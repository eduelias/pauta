"""Visão geral's arithmetic (docs/campaign-overview-spec.md): the windows, a window's sums
(results add up only when they count the same thing), how two windows compare (by result,
else by click), each flag with its floor, the Store's one read, and the rows' order."""

from datetime import date, timedelta

import pytest

from pauta import overview
from pauta.db import CAMPAIGN_DEFAULTS, Invalid
from pauta.overview import ACT, NOTE, WATCH

TODAY = "2026-10-20"
LAST, BEFORE = overview.flag_windows(TODAY)
LEADS = "lead"
CHATS = "onsite_conversion.messaging_conversation_started_7d"


def day(n: int) -> str:
    """`n` days before TODAY."""
    return (date.fromisoformat(TODAY) - timedelta(days=n)).isoformat()


def row(d, spend=0, clicks=0, impressions=0, results=None, kind=""):
    return {
        "meta_id": "1",
        "day": d,
        "spend_cents": spend,
        "link_clicks": clicks,
        "impressions": impressions,
        "results": results,
        "result_indicator": kind,
    }


def total(spend=0, clicks=0, results=None, kind=""):
    return overview.sums([row(TODAY, spend, clicks, 1000, results, kind)])


def client(last=None, before=None, **over):
    return {
        "id": 1,
        "name": "Clínica Bem Estar",
        "segment": "Saúde",
        "contact": "Carla Mendes",
        "whatsapp": "(11) 98888-7777",
        "currency": "BRL",
        "campaigns": 1,
        "active": 1,
        "quiet": 0,
        "last_seen": TODAY,
        "first_day": "2026-01-01",
        "days": [],
        "sums": {
            "period": last or total(),
            "previous": before or total(),
            "last": last or total(),
            "before": before or total(),
        },
        **over,
    }


def keys(marks):
    return [f["key"] for f in marks]


# ---- windows ---------------------------------------------------------------------------------


def test_the_windows_end_yesterday_and_never_overlap():
    assert LAST == ("2026-10-13", "2026-10-19")
    assert BEFORE == ("2026-10-06", "2026-10-12")
    assert overview.trend_window(TODAY) == ("2026-10-06", "2026-10-19")
    assert overview.previous("2026-10-01", "2026-10-31") == ("2026-08-31", "2026-09-30")
    assert overview.previous(TODAY, TODAY) == ("2026-10-19", "2026-10-19")


# ---- sums and comparisons --------------------------------------------------------------------


def test_sums_add_results_only_when_they_count_the_same_thing():
    same = overview.sums(
        [row(day(2), 1000, 10, 500, 4, LEADS), row(day(1), 500, 5, 300, None, LEADS)]
    )
    assert same == {
        "spend_cents": 1500,
        "link_clicks": 15,
        "impressions": 800,
        "cpl_cents": 100,
        "result_indicator": LEADS,
        "mixed": False,
        "results": 4,
        "cost_per_result_cents": 375,
    }
    mixed = overview.sums(
        [row(day(2), 1000, 10, 500, 4, LEADS), row(day(1), 500, 5, 300, 2, CHATS)]
    )
    assert mixed["mixed"] and mixed["results"] is None and mixed["result_indicator"] == ""
    assert mixed["cost_per_result_cents"] is None and mixed["cpl_cents"] == 100
    empty = overview.sums([])
    assert empty["spend_cents"] == 0 and empty["cpl_cents"] is None and empty["results"] is None


def test_pct_needs_a_before():
    assert overview.pct(150, 100) == 50
    assert overview.pct(0, 100) == -100
    assert overview.pct(100, 0) is None
    assert overview.pct(None, 100) is None
    assert overview.pct(100, None) is None


def test_compare_by_result_when_both_count_the_same_else_by_click():
    now, then = total(3000, 30, 10, LEADS), total(3000, 60, 20, LEADS)
    assert overview.compare(now, then) == {
        "kind": "result",
        "cost_pct": 100,
        "volume_pct": -50,
        "spend_pct": 0,
    }
    # a different thing counted, or nothing counted before: the click compares
    for other in (total(3000, 60, 20, CHATS), total(3000, 60)):
        ch = overview.compare(now, other)
        assert ch["kind"] == "click" and ch["cost_pct"] == 100 and ch["volume_pct"] == -50
    # too few results before to mean anything: the click again
    few = overview.compare(total(3000, 30, 1, LEADS), total(3000, 60, 2, LEADS), min_count=5)
    assert few["kind"] == "click"
    # and too few clicks before: no claim at all
    none = overview.compare(total(3000, 1), total(3000, 2), min_count=5)
    assert none == {"kind": "click", "cost_pct": None, "volume_pct": None, "spend_pct": 0}


def test_days_left_at_the_last_seven_days_pace():
    assert overview.days_left(10_000, total(7000)) == 10
    assert overview.days_left(999, total(7000)) == 0
    assert overview.days_left(None, total(7000)) is None
    assert overview.days_left(10_000, total(0)) is None


# ---- flags -----------------------------------------------------------------------------------


def test_a_quiet_row_has_nothing_to_say():
    assert (
        overview.flags(client(total(5000, 50, 10, LEADS), total(5000, 50, 10, LEADS)), TODAY) == []
    )


def test_cost_rising_by_result_and_by_click():
    c = client(total(6000, 40, 10, LEADS), total(3000, 40, 10, LEADS))
    assert overview.flags(c, TODAY) == [
        {"key": "cost", "level": WATCH, "text": "custo por resultado subiu 100% em 7 dias"}
    ]
    c = client(total(6000, 40), total(3000, 40))
    assert overview.flags(c, TODAY)[0]["text"] == "custo por clique subiu 100% em 7 dias"
    # under the rise: nothing
    assert overview.flags(client(total(3800, 40), total(3000, 40)), TODAY) == []


def test_volume_falling_at_the_same_spend_says_it_once():
    c = client(total(5000, 50, 6, LEADS), total(5200, 50, 10, LEADS))
    assert overview.flags(c, TODAY) == [
        {"key": "volume", "level": WATCH, "text": "resultados caíram 40% com o mesmo investimento"}
    ]
    c = client(total(5000, 30), total(5000, 60))
    assert overview.flags(c, TODAY)[0]["text"] == "cliques caíram 50% com o mesmo investimento"
    # the spend fell too: fewer results is what was paid for, and the cost didn't move
    assert overview.flags(client(total(2500, 30), total(5000, 60)), TODAY) == []


def test_the_floors_keep_small_numbers_quiet():
    # under R$ 20 in a window: no claim, whatever the percentages
    assert overview.flags(client(total(1900, 5), total(1900, 50)), TODAY) == []
    assert overview.flags(client(total(9000, 50), total(1999, 50)), TODAY) == []
    # 2 results → 1 isn't "-50%": too few to count by result, and the clicks are steady
    c = client(total(5000, 50, 1, LEADS), total(5000, 50, 2, LEADS))
    assert overview.flags(c, TODAY) == []


def test_stopped_delivering_and_no_data_never_both():
    c = client(quiet=1)
    assert overview.flags(c, TODAY) == [
        {"key": "stopped", "level": ACT, "text": "sem entrega desde ontem"}
    ]
    c = client(quiet=1, active=3)
    assert overview.flags(c, TODAY)[0]["text"] == "1 de 3 campanhas sem entrega desde ontem"
    marks = overview.flags(c, TODAY, problem="sem dados novos da Meta")
    assert marks == [{"key": "no_data", "level": ACT, "text": "sem dados novos da Meta"}]


def test_balance_running_out_only_with_a_balance_and_a_live_campaign():
    spending = client(total(7000, 70), total(7000, 70))
    assert overview.flags(spending, TODAY, remaining_cents=2500) == [
        {"key": "balance", "level": ACT, "text": "saldo para 2 dias"}
    ]
    assert overview.flags(spending, TODAY, remaining_cents=1000)[0]["text"] == "saldo para 1 dia"
    assert overview.flags(spending, TODAY, remaining_cents=500)[0]["text"] == "saldo acaba hoje"
    assert overview.flags(spending, TODAY, remaining_cents=3000) == []
    assert overview.flags(spending, TODAY, remaining_cents=None) == []
    paused = client(total(7000, 70), total(7000, 70), active=0)
    assert overview.flags(paused, TODAY, remaining_cents=500) == []


def test_unseen_only_for_a_team_that_marks_visto_hoje():
    assert overview.flags(client(last_seen=day(1)), TODAY) == []
    assert overview.flags(client(last_seen=day(3)), TODAY) == [
        {"key": "unseen", "level": NOTE, "text": "sem análise há 3 dias"}
    ]
    assert overview.flags(client(last_seen=None), TODAY)[0]["text"] == "ainda sem análise"
    assert overview.flags(client(last_seen=None), TODAY, reviews_used=False) == []
    assert overview.flags(client(last_seen=None, active=0), TODAY) == []


def test_flags_come_most_urgent_first():
    c = client(total(6000, 40), total(3000, 40), last_seen=None, quiet=1)
    assert keys(overview.flags(c, TODAY, remaining_cents=100)) == [
        "stopped",
        "balance",
        "cost",
        "unseen",
    ]


def test_a_young_campaign_is_not_compared_with_a_window_it_was_not_in():
    # the numbers start inside the earlier window: "custo subiu 100%" would be the ramp-up
    young = client(total(6000, 40), total(3000, 40), first_day=day(10))
    assert overview.flags(young, TODAY) == []
    assert overview.flags({**young, "first_day": None}, TODAY) == []
    assert keys(overview.flags({**young, "first_day": BEFORE[0]}, TODAY)) == ["cost"]
    # the same on the row: no percentages against a period the client wasn't whole in
    (row_,) = overview.rows([young], TODAY, day(20), {}, {}, {}, True)
    assert row_["change"] == {**overview.NO_CHANGE, "partial": True}
    (row_,) = overview.rows([young], TODAY, day(10), {}, {}, {}, True)
    assert row_["change"]["partial"] is False and row_["change"]["cost_pct"] == 100


# ---- rows ------------------------------------------------------------------------------------


def test_rows_put_the_ones_that_need_a_look_first():
    calm_big = client(total(90_000, 900), total(90_000, 900), id=1, name="Grande")
    calm_small = client(total(5000, 50), total(5000, 50), id=2, name="Pequena")
    rising = client(total(6000, 40), total(3000, 40), id=3, name="Subindo")
    stopped = client(id=4, name="Parada", quiet=1)
    rows = overview.rows(
        [calm_big, calm_small, rising, stopped],
        TODAY,
        "2026-09-01",
        remaining={1: 500_000},
        problems={},
        seen={2: {"by": "Piero", "at": "2026-10-20 12:00:00"}},
        reviews_used=True,
    )
    assert [r["name"] for r in rows] == ["Parada", "Subindo", "Grande", "Pequena"]
    assert [r["level"] for r in rows] == [ACT, WATCH, -1, -1]
    big = rows[2]
    assert big["balance"] == {"remaining_cents": 500_000, "days_left": 38}
    assert big["change"] == {
        "kind": "click",
        "cost_pct": 0,
        "volume_pct": 0,
        "spend_pct": 0,
        "partial": False,
    }
    assert big["period"]["spend_cents"] == 90_000 and big["flags"] == []
    assert rows[3]["seen_today"] == {"by": "Piero", "at": "2026-10-20 12:00:00"}
    assert rows[3]["balance"] is None and rows[0]["seen_today"] is None
    # whom the screen writes to (Avisar o cliente): the client's own contact and number
    assert (big["contact"], big["whatsapp"]) == ("Carla Mendes", "(11) 98888-7777")


# ---- the Store's read ------------------------------------------------------------------------

LIVE = {"objective": "OUTCOME_LEADS", "effective_status": "ACTIVE", "started": "2026-09-01"}


@pytest.fixture()
def tracked(store):
    """Two clients: the clinic with a live and a paused campaign, the bakery with one that
    started today; a third campaign of the clinic is ignored (Não acompanhar)."""
    clinic = store.save_client(
        {
            "name": "Clínica Bem Estar",
            "segment": "Saúde",
            "contact": "Carla Mendes",
            "whatsapp": "(11) 98888-7777",
        }
    )
    bakery = store.save_client({"name": "Padaria Trigo de Ouro"})
    store.sync_meta_accounts([{"id": "111", "name": "Clínica"}, {"id": "222", "name": "Pad"}])
    store.link_meta_account("111", clinic["id"])
    store.link_meta_account("222", bakery["id"])
    store.sync_campaigns(
        "111",
        [
            {**LIVE, "id": "1", "name": "Limpeza"},
            {**LIVE, "id": "2", "name": "Peeling"},
            {**LIVE, "id": "3", "name": "Antiga"},
        ],
        TODAY,
    )
    store.sync_campaigns(
        "111",
        [
            {**LIVE, "id": "1", "name": "Limpeza"},
            {**LIVE, "id": "2", "name": "Peeling", "effective_status": "PAUSED"},
            {**LIVE, "id": "3", "name": "Antiga"},
        ],
        TODAY,
    )
    store.sync_campaigns("222", [{**LIVE, "id": "9", "name": "Pães", "started": TODAY}], TODAY)
    with store.db() as db:
        ids = {r["meta_id"]: r["id"] for r in db.execute("SELECT id, meta_id FROM campaign")}
    store.set_campaign_state(ids["3"], "skipped")
    return store, clinic, bakery, ids


def overview_of(store):
    windows = {"last": LAST, "before": BEFORE}
    return store.campaign_overview(windows, overview.trend_window(TODAY), TODAY)


def test_the_store_reads_every_window_in_one_pass(tracked):
    store, clinic, bakery, ids = tracked
    store.store_insights(
        [
            {**row(day(1), 1000, 10, 500, 4, LEADS), "meta_id": "1"},
            {**row(day(1), 300, 3, 100), "meta_id": "2"},
            {**row(day(9), 700, 7, 400, 2, LEADS), "meta_id": "1"},
            {**row(day(40), 9999, 99, 999), "meta_id": "1"},  # before every window
            {**row(day(1), 5555, 55, 555), "meta_id": "3"},  # ignored: never counted
        ]
    )
    store.add_reviews(clinic["id"], day(3), None, "", [(ids["1"], {})])
    c, b = overview_of(store)
    assert (c["id"], c["name"], c["segment"], c["currency"]) == (
        clinic["id"],
        "Clínica Bem Estar",
        "Saúde",
        "BRL",
    )
    assert (c["contact"], c["whatsapp"]) == ("Carla Mendes", "(11) 98888-7777")
    assert (b["contact"], b["whatsapp"]) == ("", "")
    assert (c["campaigns"], c["active"], c["quiet"], c["last_seen"]) == (2, 1, 0, day(3))
    assert c["first_day"] == day(40) and b["first_day"] is None  # the ignored one's don't count
    assert overview.sums(c["rows"]["last"])["spend_cents"] == 1300
    assert overview.sums(c["rows"]["before"])["spend_cents"] == 700
    assert len(c["days"]) == overview.TREND_DAYS and c["days"][0]["day"] == day(14)
    assert c["days"][-1] == {
        "day": day(1),
        "spend_cents": 1300,
        "link_clicks": 13,
        "impressions": 600,
        "results": 4,
    }
    assert c["days"][0] == {
        "day": day(14),
        "spend_cents": 0,
        "link_clicks": 0,
        "impressions": 0,
        "results": None,
    }
    # the bakery's campaign started today: no numbers yet, and not "stopped" for that
    assert (b["name"], b["campaigns"], b["active"], b["quiet"], b["last_seen"]) == (
        "Padaria Trigo de Ouro",
        1,
        1,
        0,
        None,
    )
    assert store.reviews_used()


def test_a_live_campaign_without_impressions_since_yesterday_is_quiet(tracked):
    store, *_ = tracked
    assert not store.reviews_used()
    store.store_insights([{**row(day(2), 1000, 10, 500), "meta_id": "1"}])
    assert overview_of(store)[0]["quiet"] == 1
    store.store_insights([{**row(TODAY, 100, 1, 50), "meta_id": "1"}])  # delivering again
    assert overview_of(store)[0]["quiet"] == 0


def test_no_tracked_campaign_no_row(store):
    store.save_client({"name": "Sem campanha"})
    assert overview_of(store) == []


# ---- the team's settings (Configurações → Campanhas) ------------------------------------------


def test_campaign_settings_default_then_merge_and_validate(store):
    assert store.campaign_settings() == CAMPAIGN_DEFAULTS == overview.DEFAULTS
    out = store.set_campaign_settings(
        {
            "rise_pct": "50",
            "unseen_days": 0,
            "tracking_kinds": [" Criar campanha ", "Criar campanha", "Impulsionar"],
            "nope": 1,  # not a setting: ignored
        }
    )
    want = {
        **CAMPAIGN_DEFAULTS,
        "rise_pct": 50,
        "unseen_days": 0,
        "tracking_kinds": ["Criar campanha", "Impulsionar"],
    }
    assert out == want == store.campaign_settings()
    assert store.set_campaign_settings({"drop_pct": 40}) == {**want, "drop_pct": 40}
    for bad in (
        {"rise_pct": 4},
        {"rise_pct": "muito"},
        {"min_count": 0},
        {"low_balance_days": 61},
        {"tracking_kinds": "Criar campanha"},
        {"tracking_kinds": [""]},
        {"tracking_kinds": [3]},
        {"tracking_kinds": ["x" * 200]},
        {"tracking_kinds": [f"tipo {i}" for i in range(21)]},
    ):
        with pytest.raises(Invalid):
            store.set_campaign_settings(bad)
    assert store.campaign_settings() == {**want, "drop_pct": 40}


def test_the_rules_follow_the_teams_thresholds():
    def rules(**over):
        return {**overview.DEFAULTS, **over}

    c = client(total(3800, 40), total(3000, 40))  # the cost per click rose 27%
    assert overview.flags(c, TODAY) == []
    assert keys(overview.flags(c, TODAY, rules=rules(rise_pct=25))) == ["cost"]
    assert overview.flags(c, TODAY, rules=rules(rise_pct=25, min_spend=50)) == []
    assert overview.flags(c, TODAY, rules=rules(rise_pct=25, min_count=41)) == []
    falling = client(total(5000, 40), total(5000, 50))  # 20% fewer clicks, 25% dearer
    assert overview.flags(falling, TODAY) == []
    assert keys(overview.flags(falling, TODAY, rules=rules(drop_pct=20))) == ["volume"]
    assert keys(overview.flags(falling, TODAY, rules=rules(rise_pct=25))) == ["cost"]
    spending = client(total(7000, 70), total(7000, 70))
    five = rules(low_balance_days=5)
    assert keys(overview.flags(spending, TODAY, remaining_cents=4500, rules=five)) == ["balance"]
    off = rules(low_balance_days=0, unseen_days=0)
    assert overview.flags(spending, TODAY, remaining_cents=0, rules=off) == []
    assert overview.flags(client(last_seen=day(3)), TODAY, rules=off) == []
    assert overview.flags(client(last_seen=None), TODAY, rules=off) == []
    assert overview.flags(client(last_seen=day(3)), TODAY, rules=rules(unseen_days=4)) == []
    # and through the rows
    (r,) = overview.rows([c], TODAY, "2026-09-01", {}, {}, {}, True, rules(rise_pct=25))
    assert keys(r["flags"]) == ["cost"]


def test_the_request_kinds_that_link_a_campaign_are_the_teams(tracked):
    store, clinic, _, _ = tracked
    url = "https://adsmanager.facebook.com/adsmanager/manage/campaigns?selected_campaign_ids=1"
    r = store.create_request(
        {"client": clinic["id"], "kind": "Impulsionar", "what": "x", "campaign_url": url}, None
    )
    store.update_request(r["id"], {"status": "done"}, None)
    assert store.link_requests_to_campaigns() == 0  # not one of the default kinds
    store.set_campaign_settings({"tracking_kinds": []})
    assert store.link_requests_to_campaigns() == 0  # switched off
    store.set_campaign_settings({"tracking_kinds": ["Impulsionar"]})
    assert store.link_requests_to_campaigns() == 1
