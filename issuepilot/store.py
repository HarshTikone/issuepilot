import json
import os
import sqlite3
import time
from pathlib import Path


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
        self.db = sqlite3.connect(path)
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
        """)

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
        allowed = {"state", "attempts", "next_at", "report", "comment_url", "error", "issue"}
        if not values or set(values) - allowed:
            raise ValueError("Invalid job fields")
        values["updated_at"] = time.time()
        with self.db:
            self.db.execute("UPDATE jobs SET " + ",".join(k + "=?" for k in values) + " WHERE repo=? AND number=?",
                            (*values.values(), repo, number))

    def reserve_start(self, limit):
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM starts WHERE at<?", (now - 86400,))
            count = self.db.execute("SELECT count(*) FROM starts").fetchone()[0]
            if count >= limit:
                return False
            self.db.execute("INSERT INTO starts VALUES(?)", (now,))
        return True

    def jobs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC")]

    def retry(self, repo, number):
        row = self.db.execute("SELECT state FROM jobs WHERE repo=? AND number=?", (repo, number)).fetchone()
        if row is None or row[0] not in ("failed", "cancelled"):
            raise ValueError("Only failed or cancelled jobs can be retried")
        self.update(repo, number, state="queued", attempts=0, next_at=0, error=None)
