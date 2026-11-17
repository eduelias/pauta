"""The usage log (decision 11): the event table, cleaning, retention and the report."""

import json
from datetime import UTC, date, datetime, timedelta

from pauta import cli, usage
from pauta.db import Store

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=UTC)
REQ = "/api/requests/{id}"


def test_known_event_keeps_only_its_keys_and_cuts_long_values():
    row = usage.clean_event(
        {
            "t": NOW.timestamp() * 1000 - 5000,
            "e": "error_shown",
            "s": "pedido",
            "p": {"msg": "x" * 100, "status": 500, "name": "Renato", "nested": {"a": 1}},
        },
        NOW,
    )
    assert row is not None
    at, event, screen, props = row
    assert (at, event, screen) == ("2026-11-03 11:59:55", "error_shown", "pedido")
    assert json.loads(props) == {"msg": "x" * usage.MAX_VALUE, "status": 500}


def test_unknown_events_and_shapes_are_dropped():
    assert usage.clean_event({"e": "typed_a_name", "p": {}}, NOW) is None
    assert usage.clean_event({"e": 7}, NOW) is None
    assert usage.clean_event("screen", NOW) is None
    assert usage.clean_event(None, NOW) is None


def test_unknown_screens_and_props_shapes_fall_back():
    at, event, screen, props = usage.clean_event(
        {"e": "screen", "s": "/pedido/123", "p": ["from", "painel"]}, NOW
    )
    assert (event, screen, props) == ("screen", "", "{}")
    at, _, _, props = usage.clean_event({"e": "login", "p": {"ok": True, "method": None}}, NOW)
    assert json.loads(props) == {"ok": True}
    # the period a Campanhas draw used, next to the api_slow row it may have cost
    _, event, screen, props = usage.clean_event(
        {"e": "period", "s": "campanhas", "p": {"p": "this_month", "since": "x"}}, NOW
    )
    assert (event, screen, json.loads(props)) == ("period", "campanhas", {"p": "this_month"})
    # a Personalizado range says its shape (14 days, up to yesterday), never its dates
    _, _, _, props = usage.clean_event(
        {"e": "period", "p": {"p": "custom", "days": 14, "ago": 1, "until": "2026-11-16"}}, NOW
    )
    assert json.loads(props) == {"p": "custom", "days": 14, "ago": 1}
    # a message written for a client: the kind, never whom it was for or what it said
    _, event, _, props = usage.clean_event(
        {"e": "client_message", "p": {"kind": "balance", "to": "5511988887777", "text": "Olá"}},
        NOW,
    )
    assert (event, json.loads(props)) == ("client_message", {"kind": "balance"})


def test_client_time_is_clamped_to_the_last_day():
    ms = NOW.timestamp() * 1000
    assert usage.stamp(ms + 3_600_000, NOW) == "2026-11-03 12:00:00"  # ahead: now
    assert usage.stamp(ms - 2 * 86_400_000, NOW) == "2026-11-02 12:00:00"  # too old: a day
    assert usage.stamp("yesterday", NOW) == "2026-11-03 12:00:00"
    assert usage.stamp(True, NOW) == "2026-11-03 12:00:00"
    assert usage.stamp(1e300, NOW) == "2026-11-03 12:00:00"


def test_values_keep_numbers_and_bools_drop_the_rest():
    assert usage.clean_value(1234.5) == 1234.5
    assert usage.clean_value(False) is False
    assert usage.clean_value(float("nan")) is None
    assert usage.clean_value(1e15) is None
    assert usage.clean_value([1]) is None


def test_device_string_has_one_shape():
    assert usage.clean_dev("phone/standalone/390x840/ios") == "phone/standalone/390x840/ios"
    assert usage.clean_dev("desktop/browser/1280x860/mac") == "desktop/browser/1280x860/mac"
    assert usage.clean_dev("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == ""
    assert usage.clean_dev("phone/standalone/390x840/ios/extra") == ""
    assert usage.clean_dev(None) == ""


def test_store_writes_prunes_and_can_be_switched_off(tmp_path):
    store = Store(tmp_path / "pauta.db")
    assert store.usage_enabled()
    old = (NOW - timedelta(days=usage.RETENTION_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
    fresh = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    store.add_usage(1, [(old, "screen", "painel", "{}"), (fresh, "screen", "quadro", "{}")], "")
    store.add_usage(1, [], "")  # a batch of only unknown events writes nothing
    assert store.prune_usage(usage.RETENTION_DAYS) == 1
    with store.db() as db:
        assert [r[0] for r in db.execute("SELECT screen FROM usage")] == ["quadro"]
    store.set_usage_enabled(False)
    assert not store.usage_enabled()
    store.set_usage_enabled(True)
    assert store.usage_enabled()


def test_backup_prunes_old_usage_rows(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PAUTA_STATE_DIR", str(tmp_path / "state"))
    store = Store(tmp_path / "state" / "pauta.db")
    store.add_usage(1, [("2020-01-01 00:00:00", "screen", "painel", "{}")], "")
    cli.main(["backup", "--dir", str(tmp_path / "bk")])
    assert "pruned 1 usage row(s)" in capsys.readouterr().out
    with store.db() as db:
        assert db.execute("SELECT count(*) FROM usage").fetchone()[0] == 0


def _at(day: date, hhmm: str) -> str:
    return f"{day.isoformat()} {hhmm}:00"


def filled_store(tmp_path) -> tuple[Store, date]:
    """Two accounts, two clients with two requests each, a week of made-up usage."""
    store = Store(tmp_path / "pauta.db")
    today = date(2026, 11, 3)
    with store.db() as db:
        db.execute("INSERT INTO account(id, name, handle) VALUES (1, 'Renato', 'h1')")
        db.execute("INSERT INTO account(id, name, handle) VALUES (2, 'Piero', 'h2')")
    clinic = store.save_client({"name": "Clínica", "state": "Ativo"})["id"]
    bakery = store.save_client({"name": "Padaria", "state": "Ativo"})["id"]
    reqs = [
        store.create_request({"client": clinic, "what": "a", "kind": "Criar campanha"}, 1)["id"],
        store.create_request({"client": clinic, "what": "b", "kind": "Criar campanha"}, 1)["id"],
        store.create_request({"client": bakery, "what": "c", "kind": "Relatório"}, 1)["id"],
        store.create_request({"client": bakery, "what": "d"}, 1)["id"],
    ]
    with store.db() as db:
        # Piero moves the clinic's two requests to doing one minute apart, twice over
        for i, rid in enumerate(reqs[:2]):
            db.execute(
                "INSERT INTO event(request, account, at, kind, text) VALUES (?,2,?,'status',?)",
                (rid, _at(today, f"10:0{i}"), "todo>doing"),
            )
            db.execute(
                "INSERT INTO event(request, account, at, kind, text) VALUES (?,2,?,'comment',?)",
                (rid, _at(today, f"10:1{i}"), "subiu"),
            )
        # the bakery's two, an hour apart: not a repeat
        for i, rid in enumerate(reqs[2:]):
            db.execute(
                "INSERT INTO event(request, account, at, kind, text) VALUES (?,2,?,'status',?)",
                (rid, _at(today, f"1{i}:30"), "todo>doing"),
            )
        # one request opened five days ago and done today, one done two days ago
        db.execute(
            "UPDATE request SET created=?, done_on=? WHERE id=?",
            (_at(today - timedelta(days=5), "09:00"), today.isoformat(), reqs[0]),
        )
        db.execute(
            "UPDATE request SET created=?, done_on=? WHERE id=?",
            (
                _at(today - timedelta(days=3), "09:00"),
                (today - timedelta(days=2)).isoformat(),
                reqs[2],
            ),
        )
        # a live campaign for the clinic, checked yesterday
        db.execute(
            "INSERT INTO campaign(id, client, meta_id, state) VALUES (1, ?, 'm1', 'active')",
            (clinic,),
        )
        db.execute(
            'INSERT INTO review(campaign, "on", account) VALUES (1, ?, 2)',
            ((today - timedelta(days=1)).isoformat(),),
        )
    p = lambda **kw: json.dumps(kw)  # noqa: E731
    yesterday = today - timedelta(days=1)
    store.add_usage(
        1,
        [
            (_at(yesterday, "08:00"), "app_open", "", p(version="1.8.0", theme="light")),
            (_at(yesterday, "08:00"), "screen", "painel", p(**{"from": ""})),
            (_at(yesterday, "08:01"), "screen", "quadro", p(**{"from": "painel"})),
            (_at(yesterday, "08:02"), "request_status", "quadro", p(via="board")),
            (
                _at(yesterday, "08:03"),
                "error_shown",
                "quadro",
                p(msg="network", status=0, route=REQ, method="PATCH"),
            ),
            (_at(yesterday, "08:06"), "error_shown", "novo", p(msg="validation", form="f")),
            (_at(yesterday, "08:03"), "api_slow", "quadro", p(route=REQ, ms=2200, status=200)),
            (_at(yesterday, "08:04"), "api_slow", "quadro", p(route=REQ, ms=100, status=400)),
            (_at(yesterday, "08:05"), "api_slow", "quadro", p(route="/api/boot", status=0)),
        ],
        "desktop/browser/1280x860/mac",
    )
    store.add_usage(
        2,
        [
            (_at(today, "10:00"), "app_open", "", p(version="1.8.0", theme="dark")),
            (_at(today, "10:00"), "screen", "painel", p(**{"from": ""})),
            (_at(today, "10:01"), "screen", "quadro", p(**{"from": "painel"})),
            (_at(today, "10:02"), "comment_added", "pedido", "{}"),
        ],
        "phone/standalone/390x840/ios",
    )
    # outside the window
    store.add_usage(1, [(_at(today - timedelta(days=30), "08:00"), "screen", "perfil", "{}")], "")
    return store, today


def test_summary_counts_the_week(tmp_path):
    store, today = filled_store(tmp_path)
    s = usage.summary(store, days=7, today=today)
    assert (s["since"], s["until"], s["rows"]) == ("2026-10-28", "2026-11-03", 13)
    assert s["active"] == [("2026-11-02", [1]), ("2026-11-03", [2])]
    assert s["screens"] == {"painel": {1: 1, 2: 1}, "quadro": {1: 1, 2: 1}}
    assert s["actions"] == {"request_status": {1: 1}, "comment_added": {2: 1}}
    assert s["paths"] == [(("painel", "quadro"), 2)]
    assert s["errors"] == [
        (("network", "quadro", "0", "PATCH /api/requests/{id}"), 1),
        (("validation", "novo", "", "form f"), 1),
    ]
    assert s["slow"] == [
        {"route": "/api/requests/{id}", "n": 2, "p95_ms": 2200.0, "failed": 1},
        {"route": "/api/boot", "n": 1, "p95_ms": None, "failed": 1},
    ]
    d = s["devices"]
    assert (d["opens"], d["phone"], d["standalone"]) == (2, 1, 1)
    assert d["viewports"] == {"1280x860": 1, "390x840": 1}
    assert d["platforms"] == {"mac": 1, "ios": 1}
    f = s["funnel"]
    assert (f["n"], f["median"], f["p90"]) == (2, 3, 5)
    assert f["rows"] == [
        {"kind": "Criar campanha", "n": 1, "median": 5, "p90": 5},
        {"kind": "Relatório", "n": 1, "median": 1, "p90": 1},
    ]
    assert s["seen"][-2] == {"day": "2026-11-02", "checked": 1, "live": 1}
    assert s["seen"][-1] == {"day": "2026-11-03", "checked": 0, "live": 1}
    assert [(r["kind"], r["text"], r["requests"], r["client_name"]) for r in s["repeated"]] == [
        ("status", "todo>doing", [1, 2], "Clínica"),
        ("comment", "", [1, 2], "Clínica"),
    ]
    assert "login" in s["dead"] and "screen" not in s["dead"]


def test_render_and_the_cli_print_every_section(tmp_path, monkeypatch, capsys):
    store, today = filled_store(tmp_path)
    text = usage.render(usage.summary(store, days=7, today=today))
    for needle in (
        "Pauta usage, 7 day(s) (2026-10-28 to 2026-11-03): 13 event row(s)",
        "2026-11-03  1  (Piero)",
        "painel             2  (Renato 1, Piero 1)",
        "painel -> quadro  2",
        "network     quadro         0    1    PATCH /api/requests/{id}",
        "validation  novo           -    1    form f",
        "/api/requests/{id}                   n=2    p95=2200 ms   failed=1",
        "2 open(s): 1 phone, 1 desktop; 50% installed (standalone)",
        "all kinds: n=2 median=3 p90=5",
        "2026-11-02  1/1",
        "Repeated steps (same change on 2+ requests of one client within 5 min): 2",
        "Piero: status todo>doing on 2 requests of Clínica (#1, #2)",
        "Piero: comment on 2 requests of Clínica (#1, #2)",
        "Dead features",
    ):
        assert needle in text, needle
    monkeypatch.setenv("PAUTA_STATE_DIR", str(tmp_path))
    cli.main(["usage", "--days", "7"])
    out = capsys.readouterr().out
    assert out.startswith("Pauta usage, 7 day(s)") and "Repeated steps" in out
    cli.main(["usage", "--disable"])
    assert "usage log disabled" in capsys.readouterr().out
    assert not store.usage_enabled()
    cli.main(["usage", "--enable"])
    assert store.usage_enabled()


def test_render_on_an_empty_database(tmp_path):
    store = Store(tmp_path / "pauta.db")
    text = usage.render(usage.summary(store, days=1))
    assert "0 event row(s)" in text
    assert "no client has a live campaign" in text
    assert text.count("  none") >= 6
    assert ", ".join(usage.EVENTS) in text  # every event is dead


def test_repeated_steps_need_two_requests_within_the_window():
    def step(at, account, request):
        return {
            "at": f"2026-11-03 {at}",
            "account": account,
            "kind": "status",
            "text": "todo>doing",
            "request": request,
            "client": 1,
            "client_name": "C",
        }

    rows = [
        step("10:00:00", 2, 1),
        step("10:04:59", 2, 2),
        step("10:20:00", 2, 1),
        step("10:21:00", 2, 1),
        step("10:22:00", 1, 2),
    ]
    out = usage.repeated_steps(rows)
    # the first pair counts; the same request twice does not; two accounts do not
    assert [(r["at"], r["requests"]) for r in out] == [("2026-11-03 10:00:00", [1, 2])]
    assert usage.repeated_steps([]) == []
