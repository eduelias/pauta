"""Observability helpers: route labels, the metrics window, backup age, the log format."""

import io
import json
import logging
import os
import time

import pytest

from pauta import obs


def test_route_labels_hide_ids_and_tokens():
    assert obs.route_label(r"^/api/requests/(\d{1,9})$") == "/api/requests/{id}"
    assert obs.route_label(r"^/api/requests/(\d{1,9})/comments$") == "/api/requests/{id}/comments"
    assert obs.route_label(r"^/api/invite/([A-Za-z0-9_-]{10,64})$") == "/api/invite/{param}"
    assert obs.route_label(r"^/api/options/(kind|goal|segment)$") == "/api/options/{param}"
    assert obs.route_label(r"^/api/me$") == "/api/me"


def test_percentile_is_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert obs.percentile(values, 0.5) == 50.0
    assert obs.percentile(values, 0.95) == 95.0
    assert obs.percentile([7.0], 0.95) == 7.0
    assert obs.percentile([], 0.5) is None


def test_metrics_window_and_counters():
    now = [1000.0]
    m = obs.Metrics(clock=lambda: now[0])
    m.record("/api/requests", 200, 10.0)
    m.record("/api/requests/{id}", 500, 30.0)
    now[0] += obs.WINDOW + 1  # both fall out of the window, the counters keep them
    m.record("/api/requests", 200, 20.0)
    m.record("/api/me", 401, 2.0)
    m.record("/api/clients", 503, 40.0)
    snap = m.snapshot()
    assert snap["uptime_s"] == obs.WINDOW + 1
    assert snap["requests"] == {"total": 5, "2xx": 2, "4xx": 1, "5xx": 2}
    w = snap["window"]
    assert w["requests"] == 3 and w["errors_5xx"] == 1 and w["error_rate"] == 0.3333
    assert w["failing_routes"] == {"/api/clients": 1}
    assert (w["p50_ms"], w["max_ms"]) == (20.0, 40.0)


def test_an_empty_window():
    w = obs.Metrics().snapshot()["window"]
    assert w["requests"] == 0 and w["error_rate"] == 0.0 and w["p95_ms"] is None


def test_newest_backup_age(tmp_path):
    assert obs.newest_age(None) is None
    assert obs.newest_age(tmp_path) is None  # nothing there yet
    assert obs.newest_age(tmp_path / "missing") is None
    old, new = tmp_path / "pauta-1.db", tmp_path / "pauta-2.db"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    os.utime(old, (time.time() - 7200,) * 2)
    os.utime(new, (time.time() - 60,) * 2)
    (tmp_path / "pre-deploy").mkdir()  # subdirectories are other backups, not nightly ones
    assert 55 <= obs.newest_age(tmp_path) <= 65


def test_newest_backup_age_unreadable(tmp_path, monkeypatch):
    def denied(*_):
        raise PermissionError("no")

    monkeypatch.setattr(obs.Path, "glob", denied)
    assert obs.newest_age(tmp_path) is None


def test_file_bytes_counts_the_wal(tmp_path):
    db = tmp_path / "pauta.db"
    assert obs.file_bytes(db) == 0
    db.write_bytes(b"a" * 10)
    (tmp_path / "pauta.db-wal").write_bytes(b"b" * 5)
    assert obs.file_bytes(db) == 15


@pytest.fixture()
def journal(monkeypatch):
    """The "pauta" logger set up like `pauta serve` under systemd, into a buffer."""
    monkeypatch.setenv("JOURNAL_STREAM", "8:1234")
    buf = io.StringIO()
    handler = obs.setup_logging(buf)
    yield buf
    obs.log.removeHandler(handler)


def test_events_are_json_lines_with_journald_priorities(journal):
    assert obs.setup_logging() is obs.setup_logging()  # once, however often it's called
    obs.event("start", version="1.2.3", skipped=None)
    obs.event("error", logging.ERROR, route="/api/me")
    obs.event("auth_failed", logging.WARNING, route="/api/passkey/login/verify")
    lines = journal.getvalue().splitlines()
    assert [line[:3] for line in lines] == ["<6>", "<3>", "<4>"]
    assert json.loads(lines[0][3:]) == {"event": "start", "version": "1.2.3"}


def test_no_priority_prefix_outside_systemd(monkeypatch):
    monkeypatch.delenv("JOURNAL_STREAM", raising=False)
    buf = io.StringIO()
    handler = obs.setup_logging(buf)
    try:
        obs.event("start")
        assert buf.getvalue() == '{"event":"start"}\n'
    finally:
        obs.log.removeHandler(handler)
