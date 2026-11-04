"""POST /api/usage: the client's batched usage events (decision 11).

A session is required (an event is always for an account), the Origin check applies as to
every write, the body is capped at 16 KB and 50 events, and each account gets at most a
batch every few seconds on average. Unknown events and prop keys are dropped silently, so
an old client never fails. The route is quiet: server.QUIET keeps it out of the request
log and /metrics when it answers 200.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .. import usage
from ..ratelimit import RateLimiter
from . import Reply

# batches per account per ten minutes: a normal client flushes every 10 s at most
limiter = RateLimiter({"usage": (120, 600)})


def install(route, store, auth, drive, meta):
    @route("POST", "/api/usage")
    def post_usage(self, viewer, body):
        length = (self.headers.get("Content-Length") or "0").strip()
        if length.isdigit() and int(length) > usage.MAX_BODY:
            raise Reply(413, {"error": "pedido grande demais"})
        events = body.get("events")
        if not isinstance(events, list):
            raise Reply(400, {"error": "envie events"})
        if len(events) > usage.MAX_EVENTS:
            raise Reply(400, {"error": f"no máximo {usage.MAX_EVENTS} eventos por vez"})
        wait = limiter.hit("usage", f"acct:{viewer['account']}")
        if wait:
            raise Reply(429, {"error": f"muitos envios; espere {wait}s"})
        if not store.usage_enabled():
            return {"stored": 0}
        now = datetime.now(UTC)
        rows = [r for r in (usage.clean_event(e, now) for e in events) if r]
        store.add_usage(viewer["account"], rows, usage.clean_dev(body.get("dev")))
        return {"stored": len(rows)}
