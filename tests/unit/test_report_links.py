"""The client's link to a report (decision 12), no HTTP: the v14 table, tokens that are
long and random, one live link per card, expiry, revoking, and `report.public_report`
keeping only what the chosen metrics draw."""

import re
import sqlite3
from datetime import date, timedelta

import pytest

from pauta import assets, report
from pauta.db import SCHEMA_VERSION, Invalid, NotFound, Store

ACTIVE = {
    "id": "23850001",
    "name": "Limpeza de pele",
    "objective": "OUTCOME_LEADS",
    "effective_status": "ACTIVE",
    "started": "2026-10-03",
}
TODAY = "2026-10-20"


@pytest.fixture()
def campaign(store):
    """The clinic's campaign with three days of numbers; returns its row id."""
    c = store.save_client(
        {"name": "Clínica Bem Estar", "whatsapp": "(11) 98888-7777", "contact": "Carla"}
    )
    store.sync_meta_accounts([{"id": "111", "name": "Clínica"}])
    store.link_meta_account("111", c["id"])
    store.sync_campaigns("111", [ACTIVE], TODAY)
    store.store_insights(
        [
            {
                "meta_id": "23850001",
                "day": f"2026-10-{d:02d}",
                "spend_cents": 1000 + d,
                "impressions": 100 * d,
                "reach": 80 * d,
                "link_clicks": d,
                "actions": {"link_click": d, "lead": 2, "comment": 1},
                "results": 2,
                "result_indicator": "lead",
            }
            for d in (10, 11, 12)
        ],
        fetched="2026-10-20T10:00:00Z",
    )
    with store.db() as db:
        return db.execute("SELECT id FROM campaign").fetchone()[0]


def test_schema_v14_gains_the_report_link_table(tmp_path):
    """A v13 database (the previous release) gets the table on open, nothing else changes."""
    Store(tmp_path / "old.db")
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript("DROP TABLE report_link; UPDATE meta SET value='13' WHERE key='schema';")
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    with store.db() as db:
        assert db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == str(
            SCHEMA_VERSION
        )
        cols = {r[1] for r in db.execute("PRAGMA table_info(report_link)")}
    assert cols == {
        "token",
        "campaign",
        "since",
        "until",
        "metrics",
        "reach",
        "created",
        "created_by",
        "expires",
        "revoked",
    }


def test_a_link_is_long_random_and_live_for_5_days(store, campaign):
    link = store.create_report_link(
        campaign, "2026-10-10", "2026-10-12", ["results", "spend"], by=None, reach=240
    )
    assert len(link["token"]) >= 32 and link["token"].replace("-", "").replace("_", "").isalnum()
    assert link["campaign"] == campaign and link["metrics"] == ["results", "spend"]
    assert link["since"] == "2026-10-10" and link["until"] == "2026-10-12"
    assert link["reach"] == 240 and link["live"] and link["revoked"] is None
    assert link["created_by"] is None and link["by_name"] is None
    assert len(link["created"]) == 19 and len(link["expires"]) == 19
    created, expires = link["created"][:10], link["expires"][:10]
    assert date.fromisoformat(expires) - date.fromisoformat(created) == timedelta(days=5)
    assert store.report_link(link["token"]) == link
    assert store.report_link("nobody-made-this-one-at-all-0123456789") is None
    # two links are two tokens
    other = store.create_report_link(campaign, "2026-10-10", "2026-10-11", ["results"], by=None)
    assert other["token"] != link["token"]
    with pytest.raises(NotFound):
        store.create_report_link(999, "2026-10-10", "2026-10-12", ["results"], by=None)


def test_the_same_card_gets_the_same_link_while_it_lives(store, campaign):
    first = store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)
    again = store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)
    assert again["token"] == first["token"]
    # another period, or other metrics, is another card
    assert (
        store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["spend"], by=None)["token"]
        != first["token"]
    )
    # revoked: the next ask makes a new one
    store.revoke_report_link(campaign, first["token"])
    fresh = store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)
    assert fresh["token"] != first["token"] and fresh["live"]
    assert [link["token"] for link in store.report_links(campaign)][-1] == first["token"]
    assert len(store.report_links(campaign)) == 3
    assert store.report_links(999) == []


def test_expired_and_revoked_links_are_not_live(store, campaign):
    link = store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)
    with store.db() as db:
        db.execute(
            "UPDATE report_link SET expires='2020-01-01 00:00:00' WHERE token=?", (link["token"],)
        )
    gone = store.report_link(link["token"])
    assert gone["live"] is False and gone["revoked"] is None
    # expired: a new ask is a new link
    assert (
        store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)[
            "token"
        ]
        != link["token"]
    )
    live = store.report_links(campaign)[0]
    revoked = store.revoke_report_link(campaign, live["token"])
    assert revoked["live"] is False and len(revoked["revoked"]) == 19
    # twice is fine, and keeps the first stamp
    assert store.revoke_report_link(campaign, live["token"])["revoked"] == revoked["revoked"]
    assert store.report_link(live["token"])["live"] is False
    # only the campaign's own links
    with pytest.raises(NotFound):
        store.revoke_report_link(campaign + 1, live["token"])
    with pytest.raises(NotFound):
        store.revoke_report_link(campaign, "nobody-made-this-one-at-all-0123456789")


def test_deleting_the_client_takes_the_links(store, campaign):
    link = store.create_report_link(campaign, "2026-10-10", "2026-10-12", ["results"], by=None)
    store.delete_client(store.campaign(campaign)["client"])
    assert store.report_link(link["token"]) is None


# ---- report.py: the metrics a link may carry, and what the public data keeps ----------


def test_valid_metrics():
    assert report.valid_metrics(["results", "spend", "results"]) == ["results", "spend"]
    assert report.valid_metrics(["act:onsite_conversion.lead"]) == ["act:onsite_conversion.lead"]
    # the link_click action is the card's Cliques no link tile (metricDefs skips the chip)
    assert report.valid_metrics(["act:link_click", "leads"]) == ["leads"]
    for bad in (
        [],
        "results",
        ["results", 3],
        ["budget"],
        ["act:<b>"],
        ["act:"],
        ["act:Lead"],
        None,
    ):
        with pytest.raises(Invalid):
            report.valid_metrics(bad)
    with pytest.raises(Invalid, match="cabe 12"):
        report.valid_metrics([f"act:t{i}" for i in range(13)])


def test_public_report_keeps_only_what_the_metrics_draw(store, campaign):
    k = store.campaign(campaign, "2026-10-10", "2026-10-12")
    # the sums as the campaign route computes them
    k["spend_cents"], k["impressions"], k["link_clicks"] = 3033, 3300, 33
    k["results"], k["result_indicator"], k["cost_per_result_cents"] = 6, "lead", 506
    k["cpl_cents"], k["reach"] = 92, 240
    k["actions"] = {"link_click": 33, "lead": 6, "comment": 3}
    out = report.public_report(k, ["results"])
    assert out == {
        "name": "Limpeza de pele",
        "client_name": "Clínica Bem Estar",
        "state": "active",
        "ended": None,
        "currency": "BRL",
        "results": 6,
        "result_indicator": "lead",
        "days": [
            {"day": "2026-10-10", "results": 2},
            {"day": "2026-10-11", "results": 2},
            {"day": "2026-10-12", "results": 2},
        ],
    }
    # never, whatever the metrics
    text = str(report.public_report(k, list(report.METRIC_FIELDS) + ["act:lead"]))
    for secret in (
        "98888",
        "Carla",
        "account_id",
        "meta_id",
        "23850001",
        "budget",
        "client_contact",
        "client_whatsapp",
        "note",
        "request",
        "fetched",
        "comment",
    ):
        assert secret not in text, secret
    # an action tile carries that type alone, on the period and per day
    out = report.public_report(k, ["act:lead", "cpl"])
    assert out["actions"] == {"lead": 6} and out["cpl_cents"] == 92
    assert "spend_cents" not in out and "results" not in out
    assert out["days"][0] == {
        "day": "2026-10-10",
        "link_clicks": 10,
        "spend_cents": 1010,
        "actions": {"lead": 2},
    }
    # a day without the chosen action, and a campaign without any, count zero
    k["days"][0]["actions"] = {}
    out = report.public_report(k, ["act:lead"])
    assert out["days"][0] == {"day": "2026-10-10", "actions": {"lead": 0}}
    del k["actions"]
    assert report.public_report(k, ["act:lead"])["actions"] == {"lead": 0}
    # freq reads the period only: the days carry nothing but the date
    out = report.public_report(k, ["freq"])
    assert out["impressions"] == 3300 and out["reach"] == 240
    assert out["days"] == [{"day": "2026-10-10"}, {"day": "2026-10-11"}, {"day": "2026-10-12"}]


def test_period_label():
    today = date(2026, 11, 4)
    assert report.period_label("2026-11-01", "2026-11-04", today) == "1 nov – 4 nov"
    assert report.period_label("2025-12-20", "2026-01-03", today) == "20 dez 2025 – 3 jan"
    assert report.period_label("2026-11-04", "2026-11-04", today) == "4 nov"


def test_the_pages_metric_list_is_the_servers():
    """`METRICS` in app-campanhas.js draws the report's tiles and `report.METRIC_FIELDS`
    says what a link may carry for each: two lists kept by hand. A metric on one side
    only is a tile the link refuses, or one drawn from fields the link never sends."""
    js = (assets.STATIC / "app-campanhas.js").read_text()
    block = js.split("const METRICS = {", 1)[1].split("\n};", 1)[0]
    assert sorted(re.findall(r"^  (\w+): \{", block, re.M)) == sorted(report.METRIC_FIELDS)
