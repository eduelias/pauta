"""The Meta client's campaign tracking reads against the fake: an account's campaigns with
paging, daily insights by campaign (cents, actions as a map, the 37-month clamp, a filter on
campaign ids), the period's reach with its hour-long cache, and the error mapping."""

from datetime import date, timedelta

import pytest
from test_meta import connect

from fakemeta import TODAY, expected
from pauta import meta as meta_mod
from pauta.meta import REVOKED, THROTTLED, Meta, MetaError, actions_map, clamp_since, earliest


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
    }
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
    }
    want = expected("23850001", since, until, date(2026, 10, 3))
    assert sum(r["spend_cents"] for r in by["23850001"]) == want["spend_cents"]
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
