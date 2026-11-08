"""GitHub REST client with pagination, retries, exponential backoff and rate-limit waits."""
from __future__ import annotations

import time
from typing import Any, Callable, Iterator, Optional

import requests

from src.utils.log import get_logger

log = get_logger(__name__)

RETRYABLE_STATUSES = frozenset({500, 502, 503, 504})
MAX_RATE_LIMIT_WAIT = 900
MAX_BACKOFF = 60


class GitHubAPIError(Exception):
    def __init__(self, status_code: Optional[int], message: str, url: str = ""):
        super().__init__(f"GitHub API error {status_code}: {message} ({url})")
        self.status_code = status_code
        self.message = message
        self.url = url

    @property
    def kind(self) -> str:
        if self.status_code is None:
            return "network"
        if self.status_code == 404:
            return "not_found"
        if self.status_code in (401, 403):
            return "permission"
        if self.status_code == 429:
            return "rate_limited"
        if self.status_code >= 500:
            return "server"
        return "other"

    @property
    def is_unavailable(self) -> bool:
        return self.kind in ("not_found", "permission")


class GitHubClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://api.github.com",
        timeout: int = 30,
        max_retries: int = 4,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
    ):
        if not token:
            raise ValueError("a GitHub token is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self.request_count = 0
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "DevOps-Control-Center",
        }

    # ------------------------------------------------------------------ public
    def request(self, method: str, path: str, *, params=None, json_body=None) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        attempt = 0
        while True:
            self.request_count += 1
            try:
                response = self.session.request(
                    method, url, params=params, json=json_body, headers=self.headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise GitHubAPIError(None, f"network failure: {type(exc).__name__}", url) from exc
                self._backoff(attempt, url)
                attempt += 1
                continue
            if self._is_rate_limited(response) and attempt < self.max_retries:
                self._wait_for_rate_limit(response, attempt, url)
                attempt += 1
                continue
            if response.status_code in RETRYABLE_STATUSES and attempt < self.max_retries:
                self._backoff(attempt, url)
                attempt += 1
                continue
            return response

    def get_json(self, path: str, params=None) -> Any:
        response = self.request("GET", path, params=params)
        self._raise_for_status(response, path)
        return response.json()

    def post_json(self, path: str, body: dict) -> Any:
        response = self.request("POST", path, json_body=body)
        self._raise_for_status(response, path)
        return response.json() if response.content else {}

    def paginate(self, path: str, params=None, item_key: Optional[str] = None) -> Iterator[Any]:
        query = dict(params or {})
        query.setdefault("per_page", 100)
        url, current = path, query
        while url:
            response = self.request("GET", url, params=current)
            self._raise_for_status(response, url)
            payload = response.json()
            items = payload.get(item_key, []) if item_key else payload
            yield from items or []
            url = response.links.get("next", {}).get("url")
            current = None

    # ----------------------------------------------------------------- private
    @staticmethod
    def _is_rate_limited(response) -> bool:
        if response.status_code == 429:
            return True
        return response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"

    def _wait_for_rate_limit(self, response, attempt: int, url: str) -> None:
        wait = None
        retry_after = response.headers.get("retry-after", "")
        reset = response.headers.get("x-ratelimit-reset", "")
        if retry_after.isdigit():
            wait = int(retry_after)
        elif reset.isdigit():
            wait = max(int(reset) - int(self._clock()), 1)
        if wait is None:
            wait = min(2**attempt, MAX_BACKOFF)
        if wait > MAX_RATE_LIMIT_WAIT:
            raise GitHubAPIError(429, "rate limit resets too far in the future", url)
        log.warning("rate limited; waiting %ss before retry", wait)
        self._sleep(wait)

    def _backoff(self, attempt: int, url: str) -> None:
        wait = min(2**attempt, MAX_BACKOFF)
        log.warning("transient failure for %s; retry in %ss", url, wait)
        self._sleep(wait)

    @staticmethod
    def _raise_for_status(response, url: str) -> None:
        if response.status_code < 400:
            return
        message = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("message", ""))
        except ValueError:
            message = ""
        raise GitHubAPIError(response.status_code, message or "request failed", url)
