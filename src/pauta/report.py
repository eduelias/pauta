"""The client's report through a public link (decision 12): what the link may show.

The card on `#/relatorio` shows the campaign's name, the client's name, the period, the
campaign's state, one tile per chosen metric (the period's value and a bar per day) and the
date of Meta's numbers. A link exposes exactly that: `public_report` keeps the fields the
chosen metrics read and drops everything else (phone, contact, account and Meta ids,
budgets, notes, requests). The metric keys and the fields each reads mirror `METRICS` in
`static/app-campanhas.js`, which draws the tiles.
"""

from __future__ import annotations

import re
from datetime import date

from .db import Invalid

LINK_DAYS = 5  # a link opens for this long, then it is a 404

MAX_METRICS = 12  # the card's limit (REPORT_TILE_MAX in app-campanhas.js)

# metric key: (the period fields it reads on the campaign, the fields it reads on a day)
METRIC_FIELDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "results": (frozenset({"results", "result_indicator"}), frozenset({"results"})),
    "cpr": (
        frozenset({"results", "result_indicator", "cost_per_result_cents"}),
        frozenset({"spend_cents", "results"}),
    ),
    "spend": (frozenset({"spend_cents"}), frozenset({"spend_cents"})),
    "leads": (frozenset({"link_clicks"}), frozenset({"link_clicks"})),
    "cpl": (frozenset({"cpl_cents"}), frozenset({"spend_cents", "link_clicks"})),
    "reach": (frozenset({"reach"}), frozenset({"reach"})),
    "impressions": (frozenset({"impressions"}), frozenset({"impressions"})),
    "ctr": (
        frozenset({"impressions", "link_clicks"}),
        frozenset({"impressions", "link_clicks"}),
    ),
    "cpm": (
        frozenset({"spend_cents", "impressions"}),
        frozenset({"spend_cents", "impressions"}),
    ),
    "freq": (frozenset({"impressions", "reach"}), frozenset()),
}
ACTION = re.compile(r"^act:[a-z0-9_.]{1,80}$")  # an action type Meta reports, as a tile

# always on the card, whatever the metrics
CARD_FIELDS = ("name", "client_name", "state", "ended", "currency")

MONTHS = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def valid_metrics(keys) -> list[str]:
    """The metric keys for a link, as the card takes them: a non-empty list of known keys
    (or `act:<type>`), without repeats, at most MAX_METRICS."""
    if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
        raise Invalid("escolha ao menos uma métrica para o relatório")
    out: list[str] = []
    for k in keys:
        if k == "act:link_click":  # the card's name for that action is the leads tile
            k = "leads"
        if k not in METRIC_FIELDS and not ACTION.match(k):
            raise Invalid(f"métrica desconhecida: {k[:40]}")
        if k not in out:
            out.append(k)
    if len(out) > MAX_METRICS:
        raise Invalid(f"o relatório cabe {MAX_METRICS} métricas")
    return out


def public_report(k: dict, metrics: list[str]) -> dict:
    """The campaign (with its period sums and `days`) cut down to what the card draws for
    `metrics`: the card's own fields, the period fields and day fields those metrics read,
    and only the action types chosen."""
    period: set[str] = set()
    daily: set[str] = set()
    types: list[str] = []
    for key in metrics:
        if key in METRIC_FIELDS:
            period |= METRIC_FIELDS[key][0]
            daily |= METRIC_FIELDS[key][1]
        else:
            types.append(key[4:])
    out = {f: k.get(f) for f in CARD_FIELDS}
    out.update({f: k.get(f) for f in sorted(period)})
    if types:
        out["actions"] = {t: (k.get("actions") or {}).get(t, 0) for t in types}
    days = []
    for d in k.get("days") or []:
        row = {"day": d["day"], **{f: d.get(f) for f in sorted(daily)}}
        if types:
            row["actions"] = {t: (d.get("actions") or {}).get(t, 0) for t in types}
        days.append(row)
    out["days"] = days
    return out


def period_label(since: str, until: str, today: date | None = None) -> str:
    """The period as the card prints it, "1 nov – 4 nov" (the year only when not this one)."""
    year = (today or date.today()).year

    def one(iso: str) -> str:
        d = date.fromisoformat(iso)
        return f"{d.day} {MONTHS[d.month - 1]}" + (f" {d.year}" if d.year != year else "")

    return one(since) if since == until else f"{one(since)} – {one(until)}"
