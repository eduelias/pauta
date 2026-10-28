"""Observability: one JSON log line per request (to journald on du7) and GET /metrics.

Log lines carry the method, the route *pattern* (`/api/requests/{id}`, never the raw path),
the status, the duration and the account id. Never request bodies, IPs, cookies, names or
invite tokens: the logs must be safe to paste into an issue.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("pauta")
log.setLevel(logging.INFO)

WINDOW = 15 * 60  # seconds of recent requests /metrics reports on
RECENT_MAX = 20_000  # recent requests kept in memory, whatever the window says
# journald's priorities, for a "<N>" prefix (systemd parses it from stdout/stderr)
PRIORITY = {logging.ERROR: 3, logging.WARNING: 4, logging.INFO: 6}
GROUP = re.compile(r"\((?:[^()]|\([^()]*\))*\)")


class JournalFormatter(logging.Formatter):
    """The JSON line as is, with a journald priority prefix when systemd runs us."""

    def __init__(self, prefix: bool):
        super().__init__()
        self.prefix = prefix

    def format(self, record: logging.LogRecord) -> str:
        line = record.getMessage()
        if self.prefix:
            line = f"<{PRIORITY.get(record.levelno, 6)}>{line}"
        return line


def setup_logging(stream=None) -> logging.Handler:
    """Send the "pauta" logger to stderr, once. Under systemd (JOURNAL_STREAM is set) errors
    show up as errors in `journalctl -p err`."""
    for h in log.handlers:
        if getattr(h, "pauta", False):
            return h
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JournalFormatter(prefix=bool(os.environ.get("JOURNAL_STREAM"))))
    handler.pauta = True
    log.addHandler(handler)
    return handler


def event(name: str, level: int = logging.INFO, **fields) -> None:
    doc = {"event": name, **{k: v for k, v in fields.items() if v is not None}}
    log.log(level, json.dumps(doc, ensure_ascii=False, separators=(",", ":"), default=str))


def route_label(pattern: str) -> str:
    """`^/api/requests/(\\d{1,9})$` -> `/api/requests/{id}`: low-cardinality, no data."""
    body = pattern.removeprefix("^").removesuffix("$")
    return GROUP.sub(lambda m: "{id}" if "\\d" in m.group(0) else "{param}", body)


def newest_age(directory: str | os.PathLike | None, glob: str = "pauta-*.db") -> float | None:
    """Seconds since the newest matching file in a directory was written (None if none)."""
    if not directory:
        return None
    try:
        times = [p.stat().st_mtime for p in Path(directory).glob(glob) if p.is_file()]
    except OSError:
        return None
    return round(time.time() - max(times)) if times else None


def file_bytes(path: Path) -> int:
    """A SQLite database's size on disk, write-ahead log included."""
    total = 0
    for p in (path, Path(f"{path}-wal")):
        try:
            total += p.stat().st_size
        except OSError:
            pass
    return total


def percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))  # nearest rank
    return sorted_values[k]


class Metrics:
    """Counters since start plus the last WINDOW seconds of requests, thread-safe."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()
        self.total = 0
        self.by_class: dict[str, int] = {}
        self.recent: deque[tuple[float, int, float, str]] = deque(maxlen=RECENT_MAX)

    def record(self, route: str, status: int, ms: float) -> None:
        now = self.clock()
        with self.lock:
            self.total += 1
            key = f"{status // 100}xx"
            self.by_class[key] = self.by_class.get(key, 0) + 1
            self.recent.append((now, status, ms, route))

    def snapshot(self) -> dict:
        now = self.clock()
        with self.lock:
            while self.recent and self.recent[0][0] < now - WINDOW:
                self.recent.popleft()
            recent = list(self.recent)
            total, by_class = self.total, dict(self.by_class)
        failing: dict[str, int] = {}
        for _, status, _, route in recent:
            if status >= 500:
                failing[route] = failing.get(route, 0) + 1
        errors = sum(failing.values())
        ms = sorted(r[2] for r in recent)
        return {
            "uptime_s": round(now - self.started),
            "requests": {"total": total, **{k: by_class[k] for k in sorted(by_class)}},
            "window": {
                "seconds": WINDOW,
                "requests": len(recent),
                "errors_5xx": errors,
                "error_rate": round(errors / len(recent), 4) if recent else 0.0,
                "p50_ms": percentile(ms, 0.50),
                "p95_ms": percentile(ms, 0.95),
                "max_ms": ms[-1] if ms else None,
                "failing_routes": failing,
            },
        }
