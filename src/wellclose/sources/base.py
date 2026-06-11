"""Acquisition source interface + politeness framework (Brief §4.5, Stage A)."""
from __future__ import annotations
import time
import urllib.robotparser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol
import httpx
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential_jitter
from ..config import settings

_CFG: dict | None = None


def source_config() -> dict:
    global _CFG
    if _CFG is None:
        _CFG = yaml.safe_load((Path(__file__).parent / "sources.yaml").read_text())
    return _CFG


@dataclass
class DocumentRef:
    source: str
    url: str
    well_hint: str | None = None
    doc_hint: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class Source(Protocol):
    name: str
    def discover(self, well_selector: dict) -> Iterable[DocumentRef]: ...
    def fetch(self, ref: DocumentRef) -> tuple[bytes, dict]: ...


class PoliteClient:
    """Rate limit + backoff + circuit breaker + robots + honest UA (§4.5)."""

    def __init__(self, base: str, rps: float | None = None):
        self.base = base
        self.min_interval = 1.0 / (rps or settings().rate_limit_rps)
        self._last = 0.0
        self._failures = 0
        self._client = httpx.Client(headers={"User-Agent": settings().user_agent},
                                    timeout=60, follow_redirects=True)
        # RFC 9309 semantics: parse robots.txt only on 200; 4xx (incl. 401/403) means
        # no crawl policy is published -> allowed. urllib's read() treats 403 as
        # disallow-all, which would wrongly block hosts that just deny /robots.txt.
        self._robots: urllib.robotparser.RobotFileParser | None = None
        try:
            r = self._client.get(base.rstrip("/") + "/robots.txt")
            if r.status_code == 200:
                rp = urllib.robotparser.RobotFileParser()
                rp.parse(r.text.splitlines())
                self._robots = rp
        except Exception:
            self._robots = None

    def reset_breaker(self) -> None:
        """Clear the consecutive-failure count. The breaker guards against hammering a
        down host within one burst; a new logical unit of work (e.g. the next well in a
        corpus run) should start fresh rather than inherit a latched-open breaker."""
        self._failures = 0

    def _gate(self, url: str) -> None:
        if self._failures >= 5:
            raise RuntimeError(f"Circuit breaker open for {self.base} (5 consecutive failures)")
        if self._robots and not self._robots.can_fetch(settings().user_agent, url):
            raise PermissionError(f"robots.txt disallows {url}")
        wait = self.min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)

    @retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(initial=1, max=30))
    def get(self, url: str, **kw) -> httpx.Response:
        self._gate(url)
        self._last = time.monotonic()
        try:
            r = self._client.get(url, **kw)
            r.raise_for_status()
            self._failures = 0
            return r
        except Exception:
            self._failures += 1
            raise

    @retry(stop=stop_after_attempt(4), wait=wait_exponential_jitter(initial=1, max=30))
    def post(self, url: str, **kw) -> httpx.Response:
        self._gate(url)
        self._last = time.monotonic()
        try:
            r = self._client.post(url, **kw)
            r.raise_for_status()
            self._failures = 0
            return r
        except Exception:
            self._failures += 1
            raise

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies


def fetch_meta(resp: httpx.Response) -> dict:
    return {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": resp.status_code, "url": str(resp.url),
            "headers": {k: v for k, v in resp.headers.items()
                        if k.lower() in ("content-type", "last-modified", "etag", "content-length")}}
