"""The receivables engine: what a billed client owes, and where it stands, derived every time.

A client being Ativo and billed is a *cycle* (`billing` row). The cycle's first period starts
on its anchor (the first payment, the "cliente desde" date, or a fixed day of the month,
a team setting); the next ones follow at the cadence. Payments are allocated to the periods
oldest-first, so partial, doubled, voided and backdated payments all just work, and so will
per-month price steps later. Nothing in here touches SQLite; `db.py` feeds it rows.

Dates are ISO strings in and out, like everywhere else in Pauta. Money is integer cents.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

CADENCES = ("monthly", "weekly", "yearly")
ANCHORS = ("first_payment", "client_since", "fixed_day")
VISIBILITIES = ("all", "admins")
CURRENCIES = ("BRL", "USD", "EUR")
# the panel's order: what needs attention first
STATUSES = ("late", "due", "due_soon", "awaiting_first", "paid")

DEFAULTS = {
    "enabled": True,
    "currency": "BRL",
    "amount": 100.0,  # the fee new clients get, in currency units (the API talks units)
    "cadence": "monthly",
    "anchor": "first_payment",
    "fixed_day": 1,  # only with anchor=fixed_day
    "due_soon_days": 7,
    "grace_days": 0,
    "visibility": "all",
    "bill_new_clients": True,
}


def add_months(d: date, n: int, day: int | None = None) -> date:
    """`d` plus `n` months, keeping `day` (default: d's day) and clamping to the month's last
    day, so the 31st becomes the 28th in February and is the 31st again in March."""
    day = day or d.day
    month0 = d.year * 12 + d.month - 1 + n
    y, m = divmod(month0, 12)
    return date(y, m + 1, min(day, calendar.monthrange(y, m + 1)[1]))


def period_start(anchor: date, index: int, cadence: str) -> date:
    """The start of period `index` (0-based) of a cycle anchored on `anchor`."""
    if cadence == "weekly":
        return anchor + timedelta(days=7 * index)
    if cadence == "yearly":
        return add_months(anchor, 12 * index, anchor.day)
    return add_months(anchor, index, anchor.day)


@dataclass(frozen=True)
class Period:
    index: int  # 1-based: "4º mês"
    start: date  # also the due date
    expected: int  # cents
    paid: int  # cents allocated to it


@dataclass(frozen=True)
class Standing:
    status: str
    anchor: date | None
    periods: tuple[Period, ...]  # up to and including the one that contains `today`
    next_due: date | None  # the first period the payments do not cover
    owed: int  # cents, over the periods up to today
    paid: int  # cents, every live payment in the cycle
    months_active: int  # the current period's index (0 before the anchor)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "anchor": self.anchor.isoformat() if self.anchor else None,
            "next_due": self.next_due.isoformat() if self.next_due else None,
            "owed": self.owed / 100,
            "paid": self.paid / 100,
            "months_active": self.months_active,
            "periods": [
                {
                    "index": p.index,
                    "start": p.start.isoformat(),
                    "expected": p.expected / 100,
                    "paid": p.paid / 100,
                }
                for p in self.periods
            ],
        }


def resolve_anchor(
    settings: dict,
    *,
    first_payment: date | None,
    since: date | None,
    opened: date,
    started: date | None,
) -> date | None:
    """When the cycle's first period starts. An explicit `started` wins; otherwise the team's
    anchor setting decides. None means "nothing to count yet" (waiting for a first payment)."""
    if started:
        return started
    anchor = settings.get("anchor", "first_payment")
    if anchor == "first_payment":
        return first_payment
    if anchor == "client_since" and since:
        return since
    if anchor == "fixed_day":
        day = int(settings.get("fixed_day") or 1)
        # the most recent `day` on or before the cycle opened: that period is owed already
        candidate = add_months(opened, 0, day)
        return candidate if candidate <= opened else add_months(opened, -1, day)
    return opened  # client_since without a date: count from when the cycle opened


def standing(
    settings: dict,
    *,
    cents: int,
    anchor: date | None,
    payments: list[tuple[date, int]],
    today: date,
) -> Standing:
    """Where a cycle stands today. `payments` are the cycle's live ones: (paid_on, cents)."""
    paid_total = sum(c for _, c in payments)
    if anchor is None:
        return Standing(
            status="awaiting_first",
            anchor=None,
            periods=(),
            next_due=None,
            owed=0,
            paid=paid_total,
            months_active=0,
        )
    cadence = settings.get("cadence", "monthly")
    grace = int(settings.get("grace_days") or 0)
    soon = int(settings.get("due_soon_days") or 0)
    # every period that has started by today, oldest first
    starts: list[date] = []
    i = 0
    while True:
        s = period_start(anchor, i, cadence)
        if s > today and i > 0:
            break
        if s > today and i == 0:  # anchored in the future (a "cliente desde" ahead of today)
            break
        starts.append(s)
        i += 1
        if i > 1200:  # a hundred years of months: never spin on bad input
            break
    # allocate oldest-first
    pool = paid_total
    periods: list[Period] = []
    for n, s in enumerate(starts, start=1):
        take = min(pool, cents)
        pool -= take
        periods.append(Period(index=n, start=s, expected=cents, paid=take))
    owed = sum(p.expected - p.paid for p in periods)
    unpaid = next((p for p in periods if p.paid < p.expected), None)
    if unpaid:
        next_due = unpaid.start
        status = "late" if today > unpaid.start + timedelta(days=grace) else "due"
    else:
        # what is left over pays the following periods in advance (at most a hundred years
        # of months, like the loop above); anchored ahead of today, that starts at the anchor
        ahead = min(pool // cents, 1200) if cents > 0 else 0
        next_due = period_start(anchor, len(starts) + ahead, cadence)
        status = "due_soon" if (next_due - today).days <= soon else "paid"
    return Standing(
        status=status,
        anchor=anchor,
        periods=tuple(periods),
        next_due=next_due,
        owed=owed,
        paid=paid_total,
        months_active=len(starts),
    )
