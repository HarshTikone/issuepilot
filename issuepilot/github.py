import base64
import json
import re
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://api.github.com"


class GitHubError(RuntimeError):
    def __init__(self, status=0, retry_after=60):
        super().__init__(f"GitHub request failed (HTTP {status}); check permissions, rate limits and network")
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def call(opener, method, path, token, data=None):
    req = Request(API + path, method=method,
                  data=None if data is None else json.dumps(data).encode(),
                  headers={"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "User-Agent": "IssuePilot/0.2",
                           "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with opener.open(req, timeout=30) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("GitHub response exceeds size limit")
            return json.loads(body)
    except HTTPError as exc:
        retry = exc.headers.get("Retry-After", "60") if exc.headers else "60"
        raise GitHubError(exc.code, min(3600, max(60, int(retry) if retry.isdigit() else 60))) from None
    except (URLError, TimeoutError, OSError):
        raise GitHubError() from None


class TokenAuth:
    """A fine-grained personal token. Its owner is found through /user."""
    def __init__(self, token):
        self.value = token

    def token(self):
        return self.value

    def invalidate(self):
        pass

    def actor_id(self, github):
        return github.request("/user")["id"]


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def rs256_signer(key_file):
    """Load the App's private key. Needs the optional 'cryptography' package: pip install issuepilot[app]."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        raise RuntimeError("GitHub App auth needs the 'cryptography' package; install issuepilot[app]") from None
    with open(key_file, "rb") as stream:
        key = serialization.load_pem_private_key(stream.read(), password=None)
    return lambda data: key.sign(data, padding.PKCS1v15(), hashes.SHA256())


class AppAuth:
    """Short-lived installation tokens, scoped to one repository and refreshed before expiry."""
    def __init__(self, app_id, installation_id, repo, sign, opener=None, clock=time.time):
        self.app_id, self.installation_id, self.repo = app_id, installation_id, repo
        self.sign, self.clock = sign, clock
        self.opener = opener or build_opener(NoRedirect())
        self.current, self.expires_at, self.bot_id = None, 0, None

    def jwt(self):
        now = int(self.clock())
        header = b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        # Backdate for clock drift; GitHub accepts at most ten minutes of lifetime.
        claims = b64url(json.dumps({"iat": now - 60, "exp": now + 540, "iss": str(self.app_id)}).encode())
        signing_input = (header + "." + claims).encode()
        return header + "." + claims + "." + b64url(self.sign(signing_input))

    def token(self):
        if self.current and self.clock() < self.expires_at - 300:
            return self.current
        name = self.repo.split("/", 1)[1]
        result = call(self.opener, "POST", f"/app/installations/{int(self.installation_id)}/access_tokens",
                      self.jwt(), {"repositories": [name]})
        expires = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00")).timestamp()
        self.current, self.expires_at = result["token"], expires
        return self.current

    def invalidate(self):
        self.current, self.expires_at = None, 0

    def actor_id(self, github):
        # Installation tokens cannot call /user; the bot account is '<app slug>[bot]'.
        if self.bot_id is None:
            slug = call(self.opener, "GET", "/app", self.jwt())["slug"]
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                raise ValueError("Unexpected GitHub App slug")
            self.bot_id = github.request("/users/" + quote(slug + "[bot]"))["id"]
        return self.bot_id


class GitHub:
    def __init__(self, repo, auth, opener=None):
        self.repo = repo
        self.auth = TokenAuth(auth) if isinstance(auth, str) else auth
        self.opener = opener or build_opener(NoRedirect())
        self.actor_id = None

    def secrets(self):
        token = self.auth.current if isinstance(self.auth, AppAuth) else self.auth.token()
        return [token] if token else []

    def request(self, path, data=None):
        try:
            return call(self.opener, "GET" if data is None else "POST", path, self.auth.token(), data)
        except GitHubError as exc:
            if exc.status == 401:
                # An expired or revoked token is refreshed on the next request, never mid-write.
                self.auth.invalidate()
            raise

    def pages(self, path):
        result = []
        sep = "&" if "?" in path else "?"
        for page in range(1, 21):
            items = self.request(path + sep + urlencode({"per_page": 100, "page": page}))
            if not isinstance(items, list):
                raise ValueError("Expected a GitHub list response")
            result.extend(items)
            if len(items) < 100:
                return result
        raise ValueError("Pagination cap reached; narrow the repository queue")

    def issues(self, label):
        query = urlencode({"state": "open", "labels": label, "sort": "created", "direction": "asc"})
        return [i for i in self.pages(f"/repos/{self.repo}/issues?{query}") if "pull_request" not in i]

    def issue(self, number):
        return self.request(f"/repos/{self.repo}/issues/{int(number)}")

    def head(self, branch):
        commit = self.request(f"/repos/{self.repo}/commits/{quote(branch, safe='')}")["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Invalid source commit")
        return commit

    def context(self, branch, paths):
        commit = self.head(branch)
        files = {}
        total = 0
        for path in paths:
            item = self.request(f"/repos/{self.repo}/contents/{quote(path, safe='/')}?ref={commit}")
            if not isinstance(item, dict) or item.get("type") != "file" or item.get("encoding") != "base64":
                raise ValueError("Context must be a regular source file")
            if item.get("size", 0) > 20_000:
                raise ValueError("Context file exceeds 20KB")
            content = base64.b64decode(item["content"], validate=False)
            total += len(content)
            if len(content) > 20_000 or total > 60_000 or b"\x00" in content:
                raise ValueError("Source context exceeds text limits")
            files[path] = content.decode("utf-8")
        return commit, files

    def tree(self, commit):
        result = self.request(f"/repos/{self.repo}/git/trees/{commit}?recursive=1")
        return result.get("tree", []), bool(result.get("truncated"))

    def blob(self, sha):
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ValueError("Invalid blob id")
        item = self.request(f"/repos/{self.repo}/git/blobs/{sha}")
        if item.get("encoding") != "base64" or item.get("size", 0) > 20_000:
            raise ValueError("Blob is not small base64 text")
        return base64.b64decode(item["content"], validate=False)

    def find_report(self, number, marker):
        if self.actor_id is None:
            self.actor_id = self.auth.actor_id(self)
        for comment in self.pages(f"/repos/{self.repo}/issues/{int(number)}/comments"):
            if comment.get("user", {}).get("id") == self.actor_id and marker in (comment.get("body") or ""):
                return comment["html_url"]
        return None

    def post_report(self, number, body):
        return self.request(f"/repos/{self.repo}/issues/{int(number)}/comments", {"body": body})["html_url"]
