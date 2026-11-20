"""Properties of the money and billing code, each checked on a few thousand made-up cases.

The cases come from a seeded generator, so a failure repeats. The properties are the ones
named in the 2026-11 assessment (M-: money as typed and rounded, F-: periods and standing);
each test is called after its property.
"""

import calendar
import math
import random
from datetime import date, timedelta
from itertools import pairwise

from pauta import db as m
from pauta.db import Invalid, cents_per
from pauta.finance import CADENCES, DEFAULTS, add_months, period_start, resolve_anchor, standing

N = 3000
FIRST, LAST = date(1990, 1, 1).toordinal(), date(2100, 12, 31).toordinal()
RANK = {"late": 0, "due": 1, "due_soon": 2, "paid": 3}


def any_day(rng) -> date:
    return date.fromordinal(rng.randint(FIRST, LAST))


def last_day(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def a_cycle(rng) -> dict:
    """A fee, an anchor, payments and a today a few years around it; plain settings."""
    anchor = any_day(rng)
    return {
        "settings": {
            **DEFAULTS,
            "cadence": rng.choice(CADENCES),
            "grace_days": rng.randint(0, 10),
            "due_soon_days": rng.randint(0, 30),
        },
        "cents": rng.randint(1, 500_000),
        "anchor": anchor,
        "payments": [
            (anchor + timedelta(days=rng.randint(-60, 900)), rng.randint(1, 600_000))
            for _ in range(rng.randint(0, 8))
        ],
        "today": anchor + timedelta(days=rng.randint(-90, 1500)),
    }


def stand(c: dict, payments=None):
    return standing(
        c["settings"],
        cents=c["cents"],
        anchor=c["anchor"],
        payments=c["payments"] if payments is None else payments,
        today=c["today"],
    )


# ---- money: parsing and rounding -----------------------------------------------------------


def test_m_roundtrip():
    """Cents written the Brazilian way come back as the same cents: with or without R$,
    with or without thousands dots, with the decimal comma when there are cents."""
    rng = random.Random(20261120)
    edges = [0, 1, 99, 100, 150_000, 99_999, 100_000, 999_999_999, 10_000_000_000]
    for c in edges + [rng.randint(0, 10 ** rng.randint(1, 10)) for _ in range(N)]:
        units, part = divmod(c, 100)
        whole = f"{units:,}".replace(",", ".") if rng.random() < 0.5 else str(units)
        text = whole + (f",{part:02d}" if part or rng.random() < 0.3 else "")
        text = rng.choice(["", "R$", "R$ "]) + text
        assert m._cents(text, None) == c, text


def test_m_finite():
    """Whatever arrives as money is nothing, refused, or a finite number from 0 to 100
    million: never not-a-number, never infinity, never another error."""
    rng = random.Random(20261121)
    odd = [None, "", "nan", "NaN", "-nan", "inf", "-inf", "Infinity", "1e999", "R$ nan", "1_0"]
    odd += [True, False, [], {}, float("nan"), float("inf"), float("-inf"), 10**400, -0.0]
    letters = "0123456789.,-+eE R$naifNIxy_"
    for _ in range(N):
        v = rng.choice(
            [
                rng.choice(odd),
                "".join(rng.choice(letters) for _ in range(rng.randint(0, 12))),
                rng.uniform(-1e9, 1e9),
                rng.randint(-(10**12), 10**12),
                str(rng.uniform(-10, 2e8)),
                f"{rng.randint(0, 10**6)}.{rng.randint(0, 999):03d}",
            ]
        )
        try:
            n = m._money(v, None)
        except Invalid:
            continue
        assert n is None or (math.isfinite(n) and 0 <= n <= 100_000_000), repr(v)


def test_m_halfup():
    """spend ÷ n in whole cents is None exactly without units; otherwise the integer q with
    2nq <= 2·spend + n < 2n(q + 1): rounded half up."""
    rng = random.Random(20261122)
    assert cents_per(500, 0) is None and cents_per(500, None) is None
    assert cents_per(5, 2) == 3  # the half goes up, not to the even neighbour
    for _ in range(N):
        n = rng.randint(1, 10 ** rng.randint(1, 6))
        spend = rng.choice([rng.randint(0, 10**10), n * rng.randint(0, 10**4) + n // 2])
        q = cents_per(spend, n)
        assert isinstance(q, int) and 2 * n * q <= 2 * spend + n < 2 * n * (q + 1), (spend, n)


# ---- money: periods and standing ----------------------------------------------------------


def test_f_month():
    """`add_months(d, n, day)` lies in the month n after d's, on `day` (or d's own) clamped
    to that month's last day; with a fixed day, two steps are one step of their sum."""
    rng = random.Random(20261123)
    for _ in range(N):
        d, n, day = any_day(rng), rng.randint(-600, 600), rng.choice([None, rng.randint(1, 31)])
        r = add_months(d, n, day)
        assert r.year * 12 + r.month == d.year * 12 + d.month + n, (d, n, day)
        assert r.day == min(day or d.day, last_day(r)), (d, n, day)
        if day:
            a = rng.randint(-600, 600)
            assert add_months(add_months(d, a, day), n - a, day) == r, (d, a, n, day)


def test_f_start():
    """Period 0 starts on the anchor, each period starts after the one before, and monthly
    periods fall on the anchor's day clamped to the month's last day."""
    rng = random.Random(20261124)
    for _ in range(N):
        anchor, cadence = any_day(rng), rng.choice(CADENCES)
        starts = [period_start(anchor, i, cadence) for i in range(rng.randint(2, 40))]
        assert starts[0] == anchor
        assert all(a < b for a, b in pairwise(starts)), (anchor, cadence)
        if cadence == "monthly":
            assert all(s.day == min(anchor.day, last_day(s)) for s in starts), anchor


def test_f_anchor():
    """An explicit start wins; the first-payment rule waits for a payment; the fixed-day
    rule anchors on or before the opening, less than 31 days back, and every monthly or
    yearly period of that cycle falls on the fixed day clamped to the month's last day."""
    rng = random.Random(20261125)
    for _ in range(N):
        opened, first, since = any_day(rng), any_day(rng), any_day(rng)
        kw = {"first_payment": first, "since": since, "opened": opened}
        rule = rng.choice(["first_payment", "client_since", "fixed_day"])
        day = rng.randint(1, 31)
        s = {
            **DEFAULTS,
            "anchor": rule,
            "fixed_day": day,
            "cadence": rng.choice(["monthly", "yearly"]),
        }
        started = any_day(rng)
        assert resolve_anchor(s, **kw, started=started) == started
        r = resolve_anchor(s, **kw, started=None)
        if rule == "first_payment":
            assert (
                r == first
                and resolve_anchor(s, **{**kw, "first_payment": None}, started=None) is None
            )
        elif rule == "client_since":
            assert r == since and resolve_anchor(s, **{**kw, "since": None}, started=None) == opened
        else:
            assert r <= opened and (opened - r).days < 31, (opened, day)
            today = opened + timedelta(days=rng.randint(0, 2000))
            cycle = standing(s, cents=10000, anchor=r, payments=[], today=today)
            assert cycle.periods and cycle.periods[0].start == r
            for p in cycle.periods:
                assert p.start.day == min(day, last_day(p.start)), (opened, day, p.start)


def test_f_conserve():
    """No money appears or vanishes: the periods hold min(paid, fee × periods), what is owed
    is the rest, and the periods are full ones, then at most one partial, then empty ones."""
    rng = random.Random(20261126)
    for _ in range(N):
        c = a_cycle(rng)
        s = stand(c)
        total, due = sum(v for _, v in c["payments"]), c["cents"] * len(s.periods)
        assert s.paid == total
        assert sum(p.paid for p in s.periods) == min(total, due)
        assert s.owed == max(0, due - total)
        shape = [2 if p.paid == p.expected else 1 if p.paid else 0 for p in s.periods]
        assert shape == sorted(shape, reverse=True) and shape.count(1) <= 1, shape


def test_f_status():
    """Late or due exactly when something is owed; one more payment never raises what is
    owed nor moves the status toward late; the order of the payments does not matter."""
    rng = random.Random(20261127)
    for _ in range(N):
        c = a_cycle(rng)
        s = stand(c)
        assert (s.status in ("late", "due")) == (s.owed > 0), c
        more = stand(c, [*c["payments"], (any_day(rng), rng.randint(1, 600_000))])
        assert more.owed <= s.owed and RANK[more.status] >= RANK[s.status], c
        assert stand(c, rng.sample(c["payments"], len(c["payments"]))) == s, c


def test_f_next():
    """The next due date is the start of the first period the payments do not cover (paid
    ahead, the engine looks at most 1200 periods past today's: a hundred years of months)."""
    rng = random.Random(20261128)
    for _ in range(N):
        c = a_cycle(rng)
        s = stand(c)
        covered = min(sum(v for _, v in c["payments"]) // c["cents"], len(s.periods) + 1200)
        assert s.next_due == period_start(c["anchor"], covered, c["settings"]["cadence"]), c
