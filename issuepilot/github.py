import base64
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


class GitHubError(RuntimeError):
    def __init__(self, status=0, retry_after=60):
        super().__init__(f"GitHub request failed (HTTP {status}); check permissions, rate limits and network")
        self.status = status
        self.retry_after = retry_after


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHub:
    def __init__(self, repo, token, opener=None):
        self.repo = repo
        self.token = token
        self.opener = opener or build_opener(NoRedirect())
        self.actor_id = None

    def request(self, path, data=None):
        req = Request("https://api.github.com" + path,
                      data=None if data is None else json.dumps(data).encode(),
                      headers={"Authorization": "Bearer " + self.token,
                               "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json", "User-Agent": "IssuePilot/0.1",
                               "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with self.opener.open(req, timeout=30) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise ValueError("GitHub response exceeds size limit")
                return json.loads(body)
        except HTTPError as exc:
            retry = exc.headers.get("Retry-After", "60")
            raise GitHubError(exc.code, min(3600, max(60, int(retry) if retry.isdigit() else 60))) from None
        except (URLError, TimeoutError, OSError):
            raise GitHubError() from None

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

    def context(self, branch, paths):
        commit = self.request(f"/repos/{self.repo}/commits/{quote(branch, safe='')}")["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("Invalid source commit")
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

    def find_report(self, number, marker):
        if self.actor_id is None:
            self.actor_id = self.request("/user")["id"]
        for comment in self.pages(f"/repos/{self.repo}/issues/{int(number)}/comments"):
            if comment.get("user", {}).get("id") == self.actor_id and marker in (comment.get("body") or ""):
                return comment["html_url"]
        return None

    def post_report(self, number, body):
        return self.request(f"/repos/{self.repo}/issues/{int(number)}/comments", {"body": body})["html_url"]
