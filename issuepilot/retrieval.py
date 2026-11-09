import hashlib
import math
import re
from collections import Counter
from pathlib import Path, PurePosixPath

SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php",
                   ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".swift", ".scala", ".sh", ".sql", ".toml",
                   ".cfg", ".ini", ".yaml", ".yml", ".json", ".md", ".txt", ".html", ".css", ".vue"}
SKIP_DIRS = {"node_modules", "vendor", "third_party", "dist", "build", "out", "target", "coverage",
             "__pycache__", "site-packages", "venv", "env", "migrations", "fixtures", "generated"}
SKIP_NAMES = re.compile(r"(?:\.min\.\w+|_pb2\.py|\.lock|lock\.json|\.map|\.snap|\.pem|\.key|\.p12|\.pfx|"
                        r"secrets?\.\w+|credentials?\.\w+|\.env(?:\.\w+)?)$", re.I)
STOP = {"the", "and", "for", "with", "that", "this", "from", "when", "but", "not", "are", "was", "should",
        "returns", "return", "into", "have", "has", "can", "does", "it's", "its", "get", "set", "issue", "bug",
        "please", "investigate", "propose", "tests", "expected", "actual", "instead", "then", "also"}
MAX_FILE = 20_000
MAX_TOTAL = 60_000
MAX_CANDIDATES = 40


def tokens(text):
    words = []
    for word in re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text):
        parts = [p for p in re.split(r"_|(?<=[a-z0-9])(?=[A-Z])", word) if p]
        for part in [word, *parts] if len(parts) > 1 else [word]:
            part = part.lower()
            if len(part) >= 2 and part not in STOP:
                words.append(part)
    return words


def eligible_path(item):
    """Tree entries that may become context: small regular text files outside generated or secret areas."""
    path = item.get("path", "")
    if item.get("type") != "blob" or item.get("mode") not in ("100644", "100755"):
        return False
    if item.get("size", MAX_FILE + 1) > MAX_FILE or not re.fullmatch(r"[a-f0-9]{40}", item.get("sha", "")):
        return False
    parts = PurePosixPath(path).parts
    if not parts or any(p.startswith(".") for p in parts) or any(p.lower() in SKIP_DIRS for p in parts[:-1]):
        return False
    return PurePosixPath(path).suffix.lower() in SOURCE_SUFFIXES and not SKIP_NAMES.search(parts[-1])


def git_blob_sha(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


class BlobCache:
    """Content-addressed cache; every entry is re-verified against its Git blob id."""
    def __init__(self, directory):
        self.directory = Path(directory)

    def get(self, sha, fetch):
        path = self.directory / sha[:2] / sha
        if path.is_file():
            content = path.read_bytes()
            if git_blob_sha(content) == sha:
                return content
        content = fetch(sha)
        if git_blob_sha(content) != sha:
            raise ValueError("Fetched blob does not match its id")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content


def bm25(query, documents, k1=1.5, b=0.75):
    counts = {name: Counter(words) for name, words in documents.items()}
    if not counts:
        return {}
    average = sum(len(words) for words in documents.values()) / len(documents) or 1
    frequency = Counter(term for c in counts.values() for term in c)
    scores = {}
    for name, c in counts.items():
        length = len(documents[name]) or 1
        score = 0.0
        for term in set(query):
            if term not in c:
                continue
            idf = math.log(1 + (len(counts) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * c[term] * (k1 + 1) / (c[term] + k1 * (1 - b + b * length / average))
        scores[name] = score
    return scores


def imports(path, text, known):
    """Repository files a source file imports (Python modules and relative JS/TS paths)."""
    found = []
    for module in re.findall(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", text, re.M):
        name = (module[0] or module[1]).replace(".", "/")
        found += [c for c in (name + ".py", name + "/__init__.py") if c in known]
    base = PurePosixPath(path).parent
    for rel in re.findall(r"""(?:from\s+|require\()['"](\.{1,2}/[^'"]+)['"]""", text):
        parts = []
        for part in (base / rel).parts:
            if part == "..":
                if parts:
                    parts.pop()
            elif part != ".":
                parts.append(part)
        name = "/".join(parts)
        found += [c for c in (name, name + ".js", name + ".ts", name + ".tsx", name + "/index.js") if c in known]
    return found


def select_context(source, commit, issue, max_files, cache, pinned=(), token_budget=0):
    """Rank repository files for an issue. Returns {path: text} and an ordered selection record."""
    entries, truncated = source.tree(commit)
    if truncated:
        raise ValueError("Repository tree is truncated; set context_paths to limit the search")
    candidates = {item["path"]: item for item in entries if eligible_path(item)}
    query = tokens(issue.get("title", "") + " " + (issue.get("body") or ""))
    path_scores = {}
    for path in candidates:
        words = set(tokens(path.replace("/", " ").replace(".", " ")))
        path_scores[path] = sum(1 for term in set(query) if term in words)
    shortlist = sorted(candidates, key=lambda p: (-path_scores[p], candidates[p].get("size", 0), p))[:MAX_CANDIDATES]
    texts = {}
    for path in shortlist:
        content = cache.get(candidates[path]["sha"], source.blob)
        if b"\x00" in content:
            continue
        try:
            texts[path] = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
    ranks = bm25(query, {path: tokens(path + " " + text) for path, text in texts.items()})
    own = {p: ranks.get(p, 0) + 2 * path_scores[p] for p in texts}
    # A symptom often shows in a caller while the cause sits in what it imports.
    final = dict(own)
    for path, text in texts.items():
        for target in imports(path, text, texts):
            final[target] = max(final[target], own[target] + 0.6 * own[path])
    ordered = sorted(texts, key=lambda p: (-final[p], p))
    ordered = [p for p in pinned if p in texts] + [p for p in ordered if p not in pinned]
    files, record, total = {}, [], 0
    for path in ordered:
        size = len(texts[path].encode("utf-8"))
        if len(files) >= max_files or total + size > MAX_TOTAL:
            continue
        if token_budget and (total + size) // 3 > token_budget:
            continue
        files[path] = texts[path]
        total += size
        record.append({"path": path, "score": round(final[path], 3)})
    if not files:
        raise ValueError("Retrieval found no eligible source files for this issue")
    return files, record


class LocalSource:
    """The same tree/blob interface over a local directory; used by the benchmark and tests."""
    def __init__(self, root):
        self.root = Path(root)
        self.blobs = {}

    def tree(self, commit=None):
        entries = []
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                content = path.read_bytes()
                sha = git_blob_sha(content)
                self.blobs[sha] = content
                entries.append({"path": path.relative_to(self.root).as_posix(), "type": "blob", "mode": "100644",
                                "sha": sha, "size": len(content)})
        return entries, False

    def blob(self, sha):
        return self.blobs[sha]
