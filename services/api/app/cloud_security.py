"""Small fail-closed guards for the single-process cloud reference API.

These guards intentionally use the ASGI peer address and never trust forwarding
headers.  A production multi-worker or multi-instance deployment must enforce a
second, distributed limit at its trusted gateway.
"""

from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Awaitable, Callable

from starlette.responses import JSONResponse


ARTIFACT_UPLOAD_PATH_RE = re.compile(r"^/v1/cases/[^/]+/artifacts/?$")
CLOUD_LIMITED_BODY_PATH_RE = re.compile(
    r"^(?:/v1/cases/[^/]+/artifacts/?|/v1/cases/import/?)$"
)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class InMemoryRateLimiter:
    """Bounded sliding-window limiter for a single API process.

    The bounded key table is important: otherwise spoofing many request paths or
    peers could turn the abuse-prevention feature itself into a memory DoS.  Once
    the table is full, new peers share an overflow bucket instead of bypassing
    the limit.
    """

    def __init__(self, *, window_seconds: int = 60, max_keys: int = 10_000) -> None:
        if window_seconds < 1 or max_keys < 1:
            raise ValueError("rate limiter window_seconds and max_keys must be positive")
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._events: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()
        self._checks = 0

    def check(
        self,
        *,
        scope: str,
        peer: str,
        limit: int,
        now: float | None = None,
    ) -> RateLimitDecision:
        if limit < 1:
            # Configuration is validated at startup too. Keep this fail-closed
            # guard so a runtime mutation cannot accidentally disable limits.
            return RateLimitDecision(False, 0, self.window_seconds)
        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self.window_seconds
        with self._lock:
            self._checks += 1
            if self._checks % 256 == 0:
                empty: list[tuple[str, str]] = []
                for existing_key, existing_events in self._events.items():
                    while existing_events and existing_events[0] <= cutoff:
                        existing_events.popleft()
                    if not existing_events:
                        empty.append(existing_key)
                for existing_key in empty:
                    del self._events[existing_key]

            key = (scope, peer)
            if key not in self._events and len(self._events) >= self.max_keys:
                key = (scope, "<overflow>")
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(events[0] + self.window_seconds - timestamp + 0.999))
                return RateLimitDecision(False, 0, retry_after)
            events.append(timestamp)
            return RateLimitDecision(True, max(0, limit - len(events)), 0)


class CloudArtifactBodyLimitMiddleware:
    """Reject oversized cloud artifact envelopes before JSON/model parsing.

    `Content-Length` is used only as an early optimization.  The actual ASGI
    stream is counted as well, so an absent or understated header cannot bypass
    the cap.
    """

    def __init__(self, app: Any, *, enabled: bool, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.enabled = enabled
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if not (
            self.enabled
            and scope.get("type") == "http"
            and scope.get("method") == "POST"
            and CLOUD_LIMITED_BODY_PATH_RE.fullmatch(str(scope.get("path", "")))
        ):
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    if int(value) > self.max_body_bytes:
                        await self._reject(scope, receive, send)
                        return
                except ValueError:
                    # Do not trust a malformed header; the stream counter below
                    # remains authoritative.
                    pass

        messages: list[dict[str, Any]] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message.get("type") == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_body_bytes:
                    await self._reject(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
            elif message.get("type") == "http.disconnect":
                break

        index = 0

        async def replay_receive() -> dict[str, Any]:
            nonlocal index
            if index < len(messages):
                message = messages[index]
                index += 1
                return message
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    async def _reject(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        response = JSONResponse(
            status_code=413,
            content={"detail": "artifact request exceeds the configured upload limit"},
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )
        await response(scope, receive, send)
