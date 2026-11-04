"""POST /api/usage (decision 11), against a real server: what is stored, what is dropped,
what is refused, and that the route stays out of the request log."""

import json
import logging

import pytest

from pauta import usage
from pauta.routes import usage as usage_route
from softpasskey import call


@pytest.fixture(autouse=True)
def fresh_limiter():
    usage_route.limiter.reset()
    yield
    usage_route.limiter.reset()


@pytest.fixture()
def logs(caplog):
    caplog.set_level(logging.INFO, logger="pauta")
    return lambda name="request": [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "pauta" and json.loads(r.getMessage())["event"] == name
    ]


def rows(store):
    with store.db() as db:
        return [
            dict(r)
            for r in db.execute("SELECT account, event, screen, props, dev FROM usage ORDER BY id")
        ]


def test_a_batch_is_stored_for_the_account_that_sent_it(team, site):
    base, nato, piero, _ = team
    _, _, store = site
    batch = {
        "dev": "phone/standalone/390x840/ios",
        "events": [
            {"t": 1, "e": "app_open", "s": "", "p": {"version": "1.8.0", "theme": "dark"}},
            {"t": 1, "e": "screen", "s": "quadro", "p": {"from": "painel", "extra": "dropped"}},
            {
                "t": 1,
                "e": "request_status",
                "s": "quadro",
                "p": {"from": "todo", "to": "doing", "via": "board"},
            },
        ],
    }
    status, doc, _ = call(f"{base}/api/usage", batch, piero)
    assert (status, doc) == (200, {"stored": 3})
    got = rows(store)
    assert [r["account"] for r in got] == [2, 2, 2]
    assert [r["event"] for r in got] == ["app_open", "screen", "request_status"]
    assert json.loads(got[1]["props"]) == {"from": "painel"}
    assert got[1]["screen"] == "quadro" and got[1]["dev"] == "phone/standalone/390x840/ios"
    # another account's batch is theirs, with a bad device string blanked
    status, doc, _ = call(
        f"{base}/api/usage",
        {"dev": "Mozilla/5.0", "events": [{"t": 1, "e": "login", "p": {"ok": True}}]},
        nato,
    )
    assert (status, doc) == (200, {"stored": 1})
    assert rows(store)[-1] == {
        "account": 1,
        "event": "login",
        "screen": "",
        "props": '{"ok":true}',
        "dev": "",
    }


def test_unknown_events_are_dropped_and_values_cut(team, site):
    base, nato, _, _ = team
    _, _, store = site
    batch = {
        "events": [
            {"e": "typed_name", "p": {"name": "Padaria Segredo"}},
            {"e": "error_shown", "s": "pedido", "p": {"msg": "s" * 200, "status": 500}},
            "not an event",
        ]
    }
    status, doc, _ = call(f"{base}/api/usage", batch, nato)
    assert (status, doc) == (200, {"stored": 1})
    got = rows(store)
    assert len(got) == 1 and json.loads(got[0]["props"])["msg"] == "s" * usage.MAX_VALUE
    with store.db() as db:
        everything = " ".join(str(tuple(r)) for r in db.execute("SELECT * FROM usage"))
    assert "Segredo" not in everything and "typed_name" not in everything


def test_a_foreign_origin_and_no_session_are_refused(team, site):
    base, nato, _, _ = team
    _, _, store = site
    batch = {"events": [{"e": "screen", "s": "painel"}]}
    status, doc, _ = call(
        f"{base}/api/usage", batch, nato, headers={"Origin": "https://evil.example"}
    )
    assert status == 403 and "origem" in doc["error"]
    assert call(f"{base}/api/usage", batch)[0] == 401
    assert rows(store) == []


def test_bad_shapes_and_big_batches_are_400(team):
    base, nato, _, _ = team
    assert call(f"{base}/api/usage", {"events": "screen"}, nato)[0] == 400
    assert call(f"{base}/api/usage", {}, nato)[0] == 400
    too_many = {"events": [{"e": "screen"}] * (usage.MAX_EVENTS + 1)}
    assert call(f"{base}/api/usage", too_many, nato)[0] == 400
    just_enough = {"events": [{"e": "screen"}] * usage.MAX_EVENTS}
    assert call(f"{base}/api/usage", just_enough, nato)[0] == 200


def test_a_body_over_16_kb_is_413(team):
    base, nato, _, _ = team
    # ~18 KB: over the route's cap, under the server's 256 KB one
    fat = {"events": [{"e": "screen", "p": {"from": "x" * 400}}] * 45}
    assert len(json.dumps(fat)) > usage.MAX_BODY
    assert call(f"{base}/api/usage", fat, nato)[0] == 413


def test_each_account_is_rate_limited(team, monkeypatch):
    base, nato, piero, _ = team
    monkeypatch.setitem(usage_route.limiter.limits, "usage", (2, 600))
    batch = {"events": []}
    assert call(f"{base}/api/usage", batch, nato)[0] == 200
    assert call(f"{base}/api/usage", batch, nato)[0] == 200
    status, doc, _ = call(f"{base}/api/usage", batch, nato)
    assert status == 429 and "espere" in doc["error"]
    assert call(f"{base}/api/usage", batch, piero)[0] == 200  # per account, not global


def test_a_team_can_switch_the_log_off(team, site):
    base, nato, _, _ = team
    _, _, store = site
    store.set_usage_enabled(False)
    status, doc, _ = call(f"{base}/api/usage", {"events": [{"e": "screen"}]}, nato)
    assert (status, doc) == (200, {"stored": 0})
    assert rows(store) == []


def test_the_route_is_quiet(team, logs):
    base, nato, _, _ = team
    assert call(f"{base}/api/usage", {"events": [{"e": "screen", "s": "painel"}]}, nato)[0] == 200
    call(f"{base}/api/me", cookie=nato)
    assert [e["route"] for e in logs()] == ["/api/me"]
    status, _, _ = call(f"{base}/api/usage", {"events": "x"}, nato)  # a failure is still logged
    assert status == 400
    assert [e["route"] for e in logs()][-1] == "/api/usage"
    metrics = call(f"{base}/metrics")[1]
    assert "/api/usage" not in json.dumps(metrics["window"]["failing_routes"])
