"""The receivables engine: periods, oldest-first allocation and the statuses it derives."""

from datetime import date

import pytest

from pauta import finance
from pauta.finance import DEFAULTS, add_months, period_start, resolve_anchor, standing

D = date.fromisoformat
S = {**DEFAULTS}  # monthly, first payment anchors, 7 days' notice, no grace


def st(anchor, payments=(), today="2026-11-15", cents=10000, **over):
    return standing(
        {**S, **over},
        cents=cents,
        anchor=D(anchor) if anchor else None,
        payments=[(D(d), c) for d, c in payments],
        today=D(today),
    )


# ---- calendar maths -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "n", "expected"),
    [
        ("2026-10-29", 1, "2026-11-29"),
        ("2026-10-31", 1, "2026-11-30"),  # clamps to the month's last day
        ("2026-01-31", 1, "2026-02-28"),
        ("2026-01-31", 2, "2026-03-31"),  # and comes back after the short month
        ("2026-12-15", 1, "2027-01-15"),
        ("2026-03-31", -1, "2026-02-28"),
    ],
)
def test_add_months_keeps_the_day_when_it_can(start, n, expected):
    assert add_months(D(start), n).isoformat() == expected


def test_period_starts_by_cadence():
    a = D("2026-10-29")
    assert period_start(a, 3, "monthly") == D("2027-01-29")
    assert period_start(a, 2, "weekly") == D("2026-11-12")
    assert period_start(a, 1, "yearly") == D("2027-10-29")


# ---- anchors ----------------------------------------------------------------------------


def test_anchor_first_payment_waits_for_one():
    kw = dict(since=D("2026-01-01"), opened=D("2026-10-01"), started=None)
    assert resolve_anchor(S, first_payment=None, **kw) is None
    assert resolve_anchor(S, first_payment=D("2026-10-29"), **kw) == D("2026-10-29")


def test_anchor_client_since_falls_back_to_the_cycle_opening():
    s = {**S, "anchor": "client_since"}
    assert resolve_anchor(
        s, first_payment=None, since=D("2026-03-05"), opened=D("2026-10-01"), started=None
    ) == D("2026-03-05")
    assert resolve_anchor(
        s, first_payment=None, since=None, opened=D("2026-10-01"), started=None
    ) == D("2026-10-01")


def test_anchor_fixed_day_is_the_latest_one_on_or_before_opening():
    s = {**S, "anchor": "fixed_day", "fixed_day": 10}
    assert resolve_anchor(
        s, first_payment=None, since=None, opened=D("2026-10-15"), started=None
    ) == D("2026-10-10")
    assert resolve_anchor(
        s, first_payment=None, since=None, opened=D("2026-10-05"), started=None
    ) == D("2026-09-10")
    assert resolve_anchor(
        s, first_payment=None, since=None, opened=D("2026-10-10"), started=None
    ) == D("2026-10-10")


def test_an_explicit_start_wins():
    assert resolve_anchor(
        S,
        first_payment=D("2026-10-29"),
        since=None,
        opened=D("2026-10-01"),
        started=D("2026-10-05"),
    ) == D("2026-10-05")


# ---- standing ---------------------------------------------------------------------------


def test_waiting_for_the_first_payment():
    s = st(None)
    assert s.status == "awaiting_first" and s.months_active == 0 and s.next_due is None
    assert s.as_dict()["periods"] == []


def test_piero_paid_on_the_29th_the_month_turns_on_the_29th():
    s = st("2026-10-29", [("2026-10-29", 10000)], today="2026-11-15")
    assert s.status == "paid" and s.months_active == 1 and s.owed == 0
    assert s.next_due == D("2026-11-29")
    # a week before it turns: due soon
    assert st("2026-10-29", [("2026-10-29", 10000)], today="2026-11-22").status == "due_soon"
    assert st("2026-10-29", [("2026-10-29", 10000)], today="2026-11-21").status == "paid"
    # the day it turns, nothing paid yet: due; the day after: late (no grace)
    assert st("2026-10-29", [("2026-10-29", 10000)], today="2026-11-29").status == "due"
    late = st("2026-10-29", [("2026-10-29", 10000)], today="2026-11-30")
    assert late.status == "late" and late.owed == 10000 and late.months_active == 2
    assert late.next_due == D("2026-11-29")


def test_grace_days_delay_late():
    kw = dict(payments=[("2026-10-29", 10000)], today="2026-12-02")
    assert st("2026-10-29", **kw).status == "late"
    assert st("2026-10-29", grace_days=5, **kw).status == "due"
    assert st("2026-10-29", grace_days=2, **kw).status == "late"


def test_a_late_payment_keeps_the_day():
    # paid the second month on 5 Dec: still anchored on the 29th, third month due 29 Dec
    s = st("2026-10-29", [("2026-10-29", 10000), ("2026-12-05", 10000)], today="2026-12-10")
    assert s.status == "paid" and s.next_due == D("2026-12-29") and s.months_active == 2


def test_allocation_is_oldest_first():
    # two months owed, one and a half paid: month 1 covered, month 2 half, still late
    s = st("2026-09-01", [("2026-09-01", 10000), ("2026-10-03", 5000)], today="2026-10-20")
    assert [p.paid for p in s.periods] == [10000, 5000]
    assert s.status == "late" and s.owed == 5000 and s.next_due == D("2026-10-01")
    # paying ahead covers the following months
    s = st("2026-09-01", [("2026-09-01", 30000)], today="2026-10-20")
    assert s.status == "paid" and s.next_due == D("2026-11-01") and s.owed == 0


def test_fourth_month_active():
    pays = [(f"2026-{m:02d}-29", 10000) for m in (7, 8, 9, 10)]
    s = st("2026-07-29", pays, today="2026-11-10")
    assert s.months_active == 4 and s.status == "paid"
    assert s.as_dict()["periods"][-1] == {
        "index": 4,
        "start": "2026-10-29",
        "expected": 100.0,
        "paid": 100.0,
    }


def test_weekly_and_yearly_cadences():
    w = st("2026-11-01", [("2026-11-01", 5000)], today="2026-11-10", cents=5000, cadence="weekly")
    assert w.months_active == 2 and w.status == "late"
    y = st(
        "2025-11-01", [("2025-11-01", 120000)], today="2026-10-30", cents=120000, cadence="yearly"
    )
    assert y.months_active == 1 and y.status == "due_soon" and y.next_due == D("2026-11-01")


def test_anchor_ahead_of_today():
    # "cliente desde" next week: nothing owed yet, due soon
    s = st("2026-11-20", [], today="2026-11-15")
    assert s.status == "due_soon" and s.months_active == 0 and s.next_due == D("2026-11-20")
    assert st("2026-12-20", [], today="2026-11-15").status == "paid"


def test_the_panel_order_lists_every_status():
    assert set(finance.STATUSES) == {"late", "due", "due_soon", "awaiting_first", "paid"}
