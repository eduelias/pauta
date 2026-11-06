"""The Meta client's campaign tracking reads against the fake: an account's campaigns with
paging and budgets, daily insights by campaign (cents, actions as a map, Ads Manager's
Resultados in Meta's shapes and the objective fallback, the 37-month clamp, a filter on
campaign ids), the period's reach with its hour-long cache, the account's day, and the
error mapping."""

import logging
import time
from datetime import UTC, date, datetime, timedelta

import pytest
from test_meta import connect

from fakemeta import BUSINESS, CONVERSATIONS, OTHER_BUSINESS, TODAY, expected
from pauta import meta as meta_mod
from pauta.meta import (
    DEFAULT_TZ,
    REVOKED,
    THROTTLED,
    Meta,
    MetaError,
    actions_map,
    clamp_since,
    earliest,
    local_today,
    results_of,
)


@pytest.fixture()
def linked(meta_on, fake_meta):
    connect(meta_on, fake_meta)
    return meta_on


def test_helpers():
    assert meta_mod._day("2026-10-03T00:00:00-0300") == "2026-10-03"
    assert meta_mod._day("") is None and meta_mod._day("nope") is None
    assert actions_map([{"action_type": "lead", "value": "2"}, {"action_type": "lead", "value": 1}])
    assert actions_map([{"action_type": "a", "value": "x"}, "junk", {"value": "3"}]) == {"a": 0}
    assert actions_map(None) == {}
    assert earliest(date(2026, 10, 31)) == date(2023, 9, 30)  # 37 months back, day clamped
    assert earliest(date(2026, 1, 15)) == date(2022, 12, 15)
    assert clamp_since(date(2020, 1, 1), date(2026, 10, 20)) == date(2023, 9, 20)
    assert clamp_since(date(2026, 10, 1), date(2026, 10, 20)) == date(2026, 10, 1)


def test_results_of_in_metas_shapes():
    """`results` as the Graph sends it: an indicator with values is a count; one without
    values is "—" (None) under that indicator; no entry at all falls back to the campaign's
    objective and reads `actions`."""
    values = [{"value": "4", "attribution_windows": ["default"]}]
    row = {"results": [{"indicator": f"actions:{CONVERSATIONS}", "values": values}]}
    assert results_of(row, "OUTCOME_ENGAGEMENT") == (4, CONVERSATIONS)
    # several windows: the default one counts
    row = {
        "results": [
            {
                "indicator": "actions:lead",
                "values": [
                    {"value": "9", "attribution_windows": ["7d_click"]},
                    {"value": "6", "attribution_windows": ["default"]},
                ],
            }
        ]
    }
    assert results_of(row) == (6, "lead")
    row = {"results": [{"indicator": "actions:lead", "values": [{"value": "9"}]}]}
    assert results_of(row) == (9, "lead")
    # an indicator and no values (a view-content campaign without pixel events)
    row = {"results": [{"indicator": "actions:offsite_conversion.fb_pixel_view_content"}]}
    assert results_of(row, "OUTCOME_SALES") == (None, "offsite_conversion.fb_pixel_view_content")
    row = {"results": [{"indicator": "actions:lead", "values": []}]}
    assert results_of(row) == (None, "lead")
    row = {"results": [{"indicator": "actions:lead", "values": [{"value": ""}]}]}
    assert results_of(row) == (None, "lead")
    # no entry: the objective names the action type, the count comes from `actions`
    acts = [{"action_type": "link_click", "value": "12"}, {"action_type": "lead", "value": "3"}]
    assert results_of({"actions": acts}, "OUTCOME_TRAFFIC") == (12, "link_click")
    assert results_of({"actions": acts}, "LINK_CLICKS") == (12, "link_click")
    assert results_of({"actions": acts}, "OUTCOME_LEADS") == (3, "lead")
    assert results_of({"actions": acts}, "OUTCOME_SALES") == (None, "purchase")
    assert results_of({"actions": acts}, "OUTCOME_ENGAGEMENT") == (None, "post_engagement")
    assert results_of({"actions": acts}, "MESSAGES") == (None, CONVERSATIONS)
    assert results_of({"actions": acts, "results": []}, "OUTCOME_MESSAGES") == (None, CONVERSATIONS)
    # an objective not mapped, or none: no result at all
    assert results_of({"actions": acts}, "OUTCOME_AWARENESS") == (None, "")
    assert results_of({"actions": acts}) == (None, "")
    # junk never breaks the row
    assert results_of({"results": "x"}, "OUTCOME_LEADS") == (None, "lead")
    assert results_of({"results": [None, {"values": [{"value": "1"}]}, {"indicator": ""}]}) == (
        None,
        "",
    )
    assert results_of({"results": [{"indicator": "actions:x", "values": "nope"}]}) == (None, "x")


def test_local_today_is_the_accounts_day(monkeypatch):
    """2026-11-01 01:30 CET is still 2026-10-31 in São Paulo. An empty or unknown zone falls
    back to PAUTA_TZ, then DEFAULT_TZ, then UTC."""
    at = datetime(2026, 11, 1, 0, 30, tzinfo=UTC)  # 01:30 CET
    assert local_today("America/Sao_Paulo", at) == date(2026, 10, 31)
    assert local_today("Europe/Amsterdam", at) == date(2026, 11, 1)
    assert DEFAULT_TZ == "America/Sao_Paulo"
    monkeypatch.delenv("PAUTA_TZ", raising=False)
    assert local_today("", at) == date(2026, 10, 31)
    assert local_today("Mars/Olympus", at) == date(2026, 10, 31)
    monkeypatch.setenv("PAUTA_TZ", "Europe/Amsterdam")
    assert local_today("", at) == date(2026, 11, 1)
    assert local_today("America/Sao_Paulo", at) == date(2026, 10, 31)  # the account still wins
    monkeypatch.setenv("PAUTA_TZ", "Nowhere/AtAll")
    monkeypatch.setattr(meta_mod, "DEFAULT_TZ", "Also/Unknown")
    assert local_today("", at) == date(2026, 11, 1)  # UTC
    # the clock is the module's, so tests can freeze it
    monkeypatch.setattr(meta_mod, "_now", lambda: at)
    assert local_today("America/Sao_Paulo") == date(2026, 10, 31)
    monkeypatch.setattr(meta_mod, "DEFAULT_TZ", DEFAULT_TZ)
    assert isinstance(local_today(""), date)


def test_campaigns_with_paging(linked, fake_meta, monkeypatch):
    out = linked.campaigns("act_111")
    assert [c["id"] for c in out] == ["23850001", "23850002", "23850003"]
    assert out[0] == {
        "id": "23850001",
        "name": "Limpeza de pele novembro",
        "objective": "OUTCOME_ENGAGEMENT",
        "effective_status": "ACTIVE",
        "status": "ACTIVE",
        "started": "2026-10-03",
        "stopped": None,
        "daily_budget_cents": 1500,
        "lifetime_budget_cents": None,
    }
    assert out[1]["daily_budget_cents"] is None and out[1]["lifetime_budget_cents"] == 45000
    assert out[2]["daily_budget_cents"] is None and out[2]["lifetime_budget_cents"] is None
    assert out[2]["effective_status"] == "PAUSED" and out[2]["stopped"] == "2026-09-30"
    # no start_time: the creation date
    assert linked.campaigns("222")[0]["started"] == "2026-10-15"
    # one page so far; with limit=1 the fake pages, and Pauta follows the cursors
    assert fake_meta.calls.count("GET /act_111/campaigns") == 1
    fake_meta.calls.clear()
    orig = linked._graph

    def small_pages(path, params, step, business_id):
        return orig(path, {**params, "limit": "1"}, step, business_id)

    monkeypatch.setattr(linked, "_graph", small_pages)
    assert [c["id"] for c in linked.campaigns("111")] == ["23850001", "23850002", "23850003"]
    assert fake_meta.calls.count("GET /act_111/campaigns") == 3
    # odd entries (no id) are dropped
    fake_meta.campaigns["111"].append({"name": "sem id"})
    assert len(linked.campaigns("111")) == 3


def test_paging_never_loops_forever(linked, monkeypatch):
    monkeypatch.setattr(meta_mod, "MAX_PAGES", 3)
    doc = {"data": [{"id": "1"}], "paging": {"cursors": {"after": "x"}, "next": "u"}}
    monkeypatch.setattr(linked, "_graph", lambda *a: doc)
    assert len(linked._pages("/p", {}, "s", "1")) == 2  # the same cursor again: stop
    n = {"i": 0}

    def fresh(path, params, step, business_id):
        n["i"] += 1
        return {
            "data": [{"id": str(n["i"])}],
            "paging": {"cursors": {"after": str(n["i"])}, "next": "u"},
        }

    monkeypatch.setattr(linked, "_graph", fresh)
    assert len(linked._pages("/p", {}, "s", "1")) == 3


def test_daily_insights(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    rows = linked.daily_insights("111", since, until, today=TODAY)
    by = {}
    for r in rows:
        by.setdefault(r["meta_id"], []).append(r)
    assert set(by) == {"23850001", "23850002"}  # the paused one has no rows
    assert len(by["23850001"]) == 11 and len(by["23850002"]) == 9  # the second started the 12th
    first = by["23850001"][0]
    assert first == {
        "meta_id": "23850001",
        "day": "2026-10-10",
        "spend_cents": 1010,
        "impressions": 1000,
        "reach": 800,
        "link_clicks": 10,
        "actions": {"link_click": 10, "onsite_conversion.messaging_conversation_started_7d": 2},
        "results": 2,
        "result_indicator": CONVERSATIONS,
    }
    want = expected("23850001", since, until, date(2026, 10, 3))
    assert sum(r["spend_cents"] for r in by["23850001"]) == want["spend_cents"]
    assert sum(r["results"] for r in by["23850001"]) == want["results"] == 22
    # Botox: Meta names the indicator and counts nothing (Ads Manager shows "—")
    assert all(r["results"] is None and r["result_indicator"] == "lead" for r in by["23850002"])
    # Panetone has no `results` entry: with the objective, the fallback reads `actions`
    rows = linked.daily_insights("222", since, until, today=TODAY)
    assert rows[0]["results"] is None and rows[0]["result_indicator"] == ""
    rows = linked.daily_insights(
        "222", since, until, today=TODAY, objectives={"23850004": "OUTCOME_TRAFFIC"}
    )
    assert rows[0] == {**rows[0], "day": "2026-10-15", "results": 15}
    assert rows[0]["result_indicator"] == "link_click"
    assert "results,cost_per_result" in meta_mod.DAILY_FIELDS
    # narrowed to one campaign
    rows = linked.daily_insights("111", since, until, meta_ids=["23850002"], today=TODAY)
    assert {r["meta_id"] for r in rows} == {"23850002"}
    # an empty range asks nothing; a range before Meta's memory is clamped
    fake_meta.calls.clear()
    assert linked.daily_insights("111", until, since, today=TODAY) == []
    assert fake_meta.calls == []
    old = linked.daily_insights("111", date(2020, 1, 1), date(2023, 9, 21), today=TODAY)
    assert [r["day"] for r in old] == ["2023-09-20", "2023-09-21"] or old == []


def test_reach_is_per_period_and_cached(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    pairs = [("111", "23850001"), ("111", "23850002"), ("222", "23850004"), ("111", "23850003")]
    out = linked.reach(pairs, since, until, today=TODAY)
    assert out == {"23850001": 500 * 11, "23850002": 500 * 9, "23850004": 500 * 6}
    assert "23850003" not in out  # paused: Meta says nothing, the caller shows a dash
    assert fake_meta.calls.count("POST /") == 1  # one batch for both accounts
    # cached for an hour, per (account, period)
    assert linked.reach(pairs, since, until, today=TODAY) == out
    assert fake_meta.calls.count("POST /") == 1
    linked.reach(pairs, since - timedelta(days=1), until, today=TODAY)
    assert fake_meta.calls.count("POST /") == 2
    # a new id for a cached account is asked again
    linked.reach([("111", "999")], since, until, today=TODAY)
    assert fake_meta.calls.count("POST /") == 3
    # the cache expires
    for key in list(linked._reach):
        linked._reach[key] = (linked._reach[key][0] - 3601, linked._reach[key][1])
    linked.reach(pairs, since, until, today=TODAY)
    assert fake_meta.calls.count("POST /") == 4
    assert linked.reach([], since, until) == {} and linked.reach(pairs, until, since) == {}


def test_reach_one_account_failing_is_left_out(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    fake_meta.fail_insights.add("222")  # the account-level flag; campaign level is separate
    del fake_meta.campaigns["222"]
    fake_meta.accounts[:] = []  # /act_222 still exists in BALANCE, insights answer rows
    out = linked.reach([("111", "23850001"), ("333", "1")], since, until, today=TODAY)
    assert out == {"23850001": 500 * 11}  # 333 is unknown to Meta (#100): skipped


def test_reach_skips_an_account_no_portfolio_placed(linked, fake_meta, caplog):
    """Two portfolios and an account no read has placed under one: its campaigns get no
    reach (a dash) and the others still do, instead of the whole read failing with "este
    portfólio não está conectado"."""
    caplog.set_level(logging.INFO, logger="pauta")
    fake_meta.business = OTHER_BUSINESS
    connect(linked, fake_meta, account=8)
    since, until = date(2026, 10, 10), TODAY
    linked.business_of["111"] = BUSINESS  # as a read, or the server's seed, would
    out = linked.reach([("111", "23850001"), ("999", "1")], since, until, today=TODAY)
    assert out == {"23850001": 500 * 11}
    assert sum('"meta_reach_unplaced"' in r.getMessage() for r in caplog.records) == 1
    # nothing connected at all is still the read's error
    linked.disconnect()
    with pytest.raises(MetaError) as e:
        linked.reach([("999", "1")], since, until, today=TODAY)
    assert e.value.status == 409


def test_errors_map_like_the_other_reads(linked, fake_meta):
    fake_meta.throttle = True
    with pytest.raises(MetaError) as e:
        linked.campaigns("111")
    assert e.value.status == 503 and str(e.value) == THROTTLED
    with pytest.raises(MetaError) as e:
        linked.reach([("111", "23850001")], date(2026, 10, 1), TODAY, today=TODAY)
    assert e.value.status == 503
    fake_meta.throttle = False
    fake_meta.token_invalid = True
    with pytest.raises(MetaError) as e:
        linked.daily_insights("111", date(2026, 10, 1), TODAY, today=TODAY)
    assert e.value.status == 409 and str(e.value) == REVOKED and linked.error == REVOKED
    with pytest.raises(MetaError) as e:
        linked.reach([("111", "23850001")], date(2026, 10, 2), TODAY, today=TODAY)
    assert e.value.status == 409
    fake_meta.token_invalid = False
    fake_meta.fail_campaigns.add("111")
    with pytest.raises(MetaError) as e:
        linked.campaigns("111")
    assert e.value.status == 502
    fake_meta.close()
    with pytest.raises(MetaError) as e:
        linked.campaigns("222")
    assert e.value.status == 502
    off = Meta(linked.secret_file.parent / "other.db")
    with pytest.raises(MetaError) as e:
        off.campaigns("111")
    assert e.value.status == 409


def _reach_settles(meta, seconds: float = 3.0) -> None:
    """Until the read behind a page has let go of its lock."""
    end = time.monotonic() + seconds
    while meta._reach_reading.locked() and time.monotonic() < end:
        time.sleep(0.01)
    assert not meta._reach_reading.locked()


def test_after_an_hour_the_last_reach_answers_while_meta_is_read_again(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    pairs = [("111", "23850001"), ("222", "23850004")]
    out = linked.reach(pairs, since, until, today=TODAY)
    assert fake_meta.calls.count("POST /") == 1
    for key in list(linked._reach):
        linked._reach[key] = (linked._reach[key][0] - 3601, linked._reach[key][1])
    old = {k: v[0] for k, v in linked._reach.items()}
    fake_meta.hold()
    assert linked.reach(pairs, since, until, today=TODAY) == out  # at once, from the old read
    assert linked._reach_reading.locked()  # ...and Meta is being asked behind it
    assert linked.reach(pairs, since, until, today=TODAY) == out  # a second page: no second thread
    fake_meta.held.wait(2)
    fake_meta.release()
    _reach_settles(linked)
    assert fake_meta.calls.count("POST /") == 2
    assert all(v[0] > old[k] for k, v in linked._reach.items())  # the numbers are fresh again
    assert linked.reach(pairs, since, until, today=TODAY) == out
    assert fake_meta.calls.count("POST /") == 2
    # older than a day: nothing to answer from, the page waits for Meta
    for key in list(linked._reach):
        linked._reach[key] = (
            linked._reach[key][0] - meta_mod.REACH_STALE_SECONDS,
            linked._reach[key][1],
        )
    assert linked.reach(pairs, since, until, today=TODAY) == out
    assert fake_meta.calls.count("POST /") == 3 and not linked._reach_reading.locked()


def test_the_sync_waits_for_fresh_reach(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    pairs = [("111", "23850001")]
    linked.reach(pairs, since, until, today=TODAY)
    for key in list(linked._reach):
        linked._reach[key] = (linked._reach[key][0] - 3601, linked._reach[key][1])
    assert linked.reach(pairs, since, until, today=TODAY, stale=False) == {"23850001": 500 * 11}
    assert fake_meta.calls.count("POST /") == 2 and not linked._reach_reading.locked()


def test_a_reach_read_failing_behind_the_page_keeps_the_numbers(linked, fake_meta):
    since, until = date(2026, 10, 10), TODAY
    pairs = [("111", "23850001")]
    out = linked.reach(pairs, since, until, today=TODAY)
    for key in list(linked._reach):
        linked._reach[key] = (linked._reach[key][0] - 3601, linked._reach[key][1])
    fake_meta.down = True
    assert linked.reach(pairs, since, until, today=TODAY) == out
    _reach_settles(linked)
    assert linked._reach_failed > 0
    n = fake_meta.calls.count("POST /")
    assert linked.reach(pairs, since, until, today=TODAY) == out  # not retried for a minute
    _reach_settles(linked)
    assert fake_meta.calls.count("POST /") == n
    fake_meta.down = False
    linked._reach_failed -= meta_mod.FAIL_SECONDS + 1
    assert linked.reach(pairs, since, until, today=TODAY) == out
    _reach_settles(linked)
    assert fake_meta.calls.count("POST /") == n + 1
