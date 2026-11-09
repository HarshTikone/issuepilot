import json
import os
import sqlite3
import time
from pathlib import Path

MINUTE = 60
DAY = 86400


class ProcessLock:
    """One supervisor per data directory. OS releases lock even after a crash."""
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError("A worker already owns this data directory") from None
        return self

    def __exit__(self, *args):
        self.file.close()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The evaluation runner shares this ledger with the service, so wait briefly for the writer.
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        # Rollback journal is sufficient for the single writer and avoids old WAL versions.
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
          repo TEXT NOT NULL, number INTEGER NOT NULL, issue TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
          next_at REAL NOT NULL DEFAULT 0, report TEXT, comment_url TEXT,
          error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
          PRIMARY KEY (repo, number));
        CREATE TABLE IF NOT EXISTS starts (at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS usage (
          provider TEXT NOT NULL, model TEXT NOT NULL, at REAL NOT NULL,
          requests INTEGER NOT NULL, tokens INTEGER NOT NULL, purpose TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS usage_by_provider ON usage(provider, at);
        CREATE TABLE IF NOT EXISTS cooldowns (
          provider TEXT PRIMARY KEY, until REAL NOT NULL, reason TEXT NOT NULL);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(jobs)")}
        with self.db:
            for name in ("provider", "model", "context", "attempt_log"):
                if name not in columns:
                    self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")

    def close(self):
        self.db.close()

    def recover(self):
        with self.db:
            self.db.execute("UPDATE jobs SET state='queued' WHERE state IN ('running','reporting')")

    def enqueue(self, repo, issue):
        now = time.time()
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO jobs(repo,number,issue,created_at,updated_at) VALUES(?,?,?,?,?)",
                            (repo, issue["number"], json.dumps(issue), now, now))

    def next_job(self):
        row = self.db.execute("SELECT * FROM jobs WHERE state='queued' AND next_at<=? ORDER BY created_at,number LIMIT 1",
                              (time.time(),)).fetchone()
        return dict(row) if row else None

    def update(self, repo, number, **values):
        allowed = {"state", "attempts", "next_at", "report", "comment_url", "error", "issue",
                   "provider", "model", "context", "attempt_log"}
        if not values or set(values) - allowed:
            raise ValueError("Invalid job fields")
        values["updated_at"] = time.time()
        with self.db:
            self.db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE repo=? AND number=?",
                            (*values.values(), repo, number))

    def reserve_start(self, limit):
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM starts WHERE at<?", (now - DAY,))
            count = self.db.execute("SELECT count(*) FROM starts").fetchone()[0]
            if count >= limit:
                return False
            self.db.execute("INSERT INTO starts VALUES(?)", (now,))
        return True

    def reserve_usage(self, spec, requests, tokens, purpose="serve"):
        """Reserve a worst-case budget before a run. Returns 0, or seconds until the budget frees up."""
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM usage WHERE at<?", (now - DAY,))
            wait = 0
            for window, req_limit, tok_limit in ((MINUTE, spec.rpm, 0), (DAY, spec.rpd, spec.tpd)):
                rows = self.db.execute("SELECT at, requests, tokens FROM usage WHERE provider=? AND at>=? ORDER BY at",
                                       (spec.name, now - window)).fetchall()
                used_req = sum(r["requests"] for r in rows)
                used_tok = sum(r["tokens"] for r in rows)
                if (req_limit and requests > req_limit) or (tok_limit and tokens > tok_limit):
                    raise ValueError(f"One run on {spec.name} needs more than its whole {window}s allowance")
                over_req = req_limit and used_req + requests > req_limit
                over_tok = tok_limit and used_tok + tokens > tok_limit
                if over_req or over_tok:
                    # Free the oldest reservations until this run fits.
                    free_req, free_tok = used_req + requests - req_limit, used_tok + tokens - tok_limit
                    until = now + window
                    for row in rows:
                        free_req -= row["requests"]
                        free_tok -= row["tokens"]
                        if (not over_req or free_req <= 0) and (not over_tok or free_tok <= 0):
                            until = row["at"] + window
                            break
                    wait = max(wait, int(until - now) + 1)
            if wait:
                return wait
            self.db.execute("INSERT INTO usage VALUES(?,?,?,?,?,?)",
                            (spec.name, spec.model, now, requests, tokens, purpose))
        return 0

    def usage_summary(self):
        since = time.time() - DAY
        return [dict(r) for r in self.db.execute(
            "SELECT provider, model, purpose, count(*) AS runs, sum(requests) AS requests, sum(tokens) AS tokens "
            "FROM usage WHERE at>=? GROUP BY provider, model, purpose ORDER BY provider", (since,))]

    def cooldown_until(self, provider):
        row = self.db.execute("SELECT until FROM cooldowns WHERE provider=?", (provider,)).fetchone()
        return row[0] if row else 0

    def set_cooldown(self, provider, until, reason):
        with self.db:
            self.db.execute("INSERT INTO cooldowns VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE "
                            "SET until=max(until, excluded.until), reason=excluded.reason", (provider, until, reason))

    def jobs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC")]

    def health(self):
        """Signals that a heartbeat alone hides: stuck queues and silent task failures."""
        now = time.time()
        oldest = self.db.execute("SELECT min(created_at) FROM jobs WHERE state='queued'").fetchone()[0]
        success = self.db.execute("SELECT max(updated_at) FROM jobs WHERE state='succeeded'").fetchone()[0]
        failed = self.db.execute("SELECT count(*) FROM jobs WHERE state='failed'").fetchone()[0]
        return {"oldest_queued_seconds": int(now - oldest) if oldest else 0,
                "last_success_at": success or 0, "failed_jobs": failed}

    def retry(self, repo, number):
        row = self.db.execute("SELECT state FROM jobs WHERE repo=? AND number=?", (repo, number)).fetchone()
        if row is None or row[0] not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled jobs can be retried")
        self.update(repo, number, state="queued", attempts=0, next_at=0, error=None)

    def backup(self, target):
        """Consistent online copy through SQLite's backup API, checked before it is kept."""
        target = Path(target)
        if target.exists():
            raise ValueError("Backup target already exists; choose a new file name")
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".partial")
        copy = sqlite3.connect(partial)
        try:
            self.db.backup(copy)
            if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup failed its integrity check")
            counts = {name: copy.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in ("jobs", "usage")}
        finally:
            copy.close()
        os.chmod(partial, 0o600)
        os.replace(partial, target)
        return counts


def restore(backup, target):
    """Restore into a stopped service's data directory, refusing to overwrite a live database."""
    backup, target = Path(backup), Path(target)
    if target.exists():
        raise ValueError("Move the existing database aside first; restore never overwrites it")
    source = sqlite3.connect(f"file:{backup.as_posix()}?mode=ro", uri=True)
    try:
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup failed its integrity check")
        copy = sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            copy.close()
    finally:
        source.close()
    os.chmod(target, 0o600)
