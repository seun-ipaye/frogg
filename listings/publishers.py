import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

from config import GITHUB_BRANCH, GITHUB_REPO, GITHUB_TOKEN, LISTINGS_OUTPUT_DIR

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"

# message_fn receives the previous listings.json text (None if there was none)
# and returns the commit message, so counts reflect what actually changed.
MessageFn = Callable[[str | None], str]


@dataclass
class PublishOutcome:
    changed: list[str]
    message: str | None

    @property
    def committed(self) -> bool:
        return bool(self.changed)


class PublishError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def git_blob_sha(text: str) -> str:
    """The SHA git itself assigns to a file's contents, so we can tell whether
    a file differs from the repo's copy without downloading it."""
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class LocalPublisher:
    """Preview mode: writes the files into a local folder (e.g. a clone of the
    listings repo) and never touches git or the network."""

    def __init__(self, directory: str):
        self.directory = Path(directory).expanduser()

    def read_file(self, path: str) -> str | None:
        target = self.directory / path
        return target.read_bytes().decode("utf-8") if target.is_file() else None

    def sync(self, files: dict[str, str], message_fn: MessageFn) -> PublishOutcome:
        changed = [path for path, text in files.items() if self.read_file(path) != text]
        if not changed:
            return PublishOutcome([], None)
        message = message_fn(self.read_file("listings.json") if "listings.json" in changed else None)
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in changed:
            (self.directory / path).write_bytes(files[path].encode("utf-8"))
        return PublishOutcome(changed, message)


class GitHubPublisher:
    """Commits all changed files to the listings repo in ONE commit through the
    Git Data API - no git binary, no local clone, nothing stateful on disk."""

    def __init__(self, token: str, repo: str, branch: str = "main", session: requests.Session | None = None,
                 timeout: int = 15):
        self.repo = repo
        self.branch = branch
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "frogg-listings-sync",
        })

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        response = self.session.request(method, f"{API_URL}/repos/{self.repo}{path}", timeout=self.timeout, **kwargs)
        if response.status_code >= 400:
            # Deliberately only the status and a body snippet - never headers (they hold the token).
            raise PublishError(response.status_code, f"{method} {path} -> {response.status_code}: {response.text[:200]}")
        return response

    def read_file(self, path: str) -> str | None:
        try:
            response = self._request(
                "GET", f"/contents/{quote(path)}", params={"ref": self.branch},
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        except PublishError as error:
            if error.status == 404:
                return None
            raise
        return response.content.decode("utf-8")

    def sync(self, files: dict[str, str], message_fn: MessageFn) -> PublishOutcome:
        for attempt in range(2):
            try:
                return self._sync_once(files, message_fn)
            except PublishError as error:
                # 409/422 = the branch moved while we were building the commit; retry once from scratch.
                if attempt == 0 and error.status in (409, 422):
                    logger.warning("Listings repo changed mid-sync, retrying: %s", error)
                    continue
                raise

    def _sync_once(self, files: dict[str, str], message_fn: MessageFn) -> PublishOutcome:
        head = self._request("GET", f"/git/ref/heads/{self.branch}").json()["object"]["sha"]
        base_tree = self._request("GET", f"/git/commits/{head}").json()["tree"]["sha"]
        tree = self._request("GET", f"/git/trees/{base_tree}").json()
        if tree.get("truncated"):
            raise PublishError(0, "Listings repo root is too large to diff; refusing to publish")
        existing = {entry["path"]: entry["sha"] for entry in tree["tree"] if entry["type"] == "blob"}

        changed = [path for path, text in files.items() if existing.get(path) != git_blob_sha(text)]
        if not changed:
            return PublishOutcome([], None)

        message = message_fn(self.read_file("listings.json") if "listings.json" in changed else None)
        entries = [{"path": p, "mode": "100644", "type": "blob", "content": files[p]} for p in changed]
        new_tree = self._request("POST", "/git/trees", json={"base_tree": base_tree, "tree": entries}).json()["sha"]
        commit = self._request(
            "POST", "/git/commits", json={"message": message, "tree": new_tree, "parents": [head]}
        ).json()["sha"]
        self._request("PATCH", f"/git/refs/heads/{self.branch}", json={"sha": commit})
        return PublishOutcome(changed, message)


def build_publisher():
    """Local preview wins if configured, so a dev setup can never push by accident."""
    if LISTINGS_OUTPUT_DIR:
        return LocalPublisher(LISTINGS_OUTPUT_DIR)
    if GITHUB_TOKEN and GITHUB_REPO:
        return GitHubPublisher(GITHUB_TOKEN, GITHUB_REPO, GITHUB_BRANCH)
    return None
