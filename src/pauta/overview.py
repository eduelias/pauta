"""Campanhas' Visão geral (docs/campaign-overview-spec.md): every client on one row, the
ones that need a look first. Pure arithmetic over what `Store.campaign_overview` sums from
the stored daily numbers: no call to Meta, nothing written.

A row's flags are fixed rules a person can check against Ads Manager. They always compare
the last 7 full days with the 7 before (never today: its numbers are still moving, and
conversions keep arriving for days), and each has a floor so a client spending a few reais
a day doesn't cry wolf.
"""

from __future__ import annotations

from datetime import date, timedelta

from .db import CAMPAIGN_DEFAULTS, cents_per, period_results

FLAG_DAYS = 7  # the flags' two windows: the last 7 full days and the 7 before
TREND_DAYS = 14  # the small line on each row, ending yesterday
# the thresholds are the team's (Configurações → Campanhas): what each means is next to
# db.CAMPAIGN_DEFAULTS, the values a team that never opened the panel gets
DEFAULTS = CAMPAIGN_DEFAULTS

ACT, WATCH, NOTE = 2, 1, 0  # a flag's level: the row sorts by its highest

NO_DATA = "sem dados novos da Meta"


def previous(since: str, until: str) -> tuple[str, str]:
    """The period of the same length right before `since`..`until`."""
    a, b = date.fromisoformat(since), date.fromisoformat(until)
    n = (b - a).days + 1
    return (a - timedelta(days=n)).isoformat(), (a - timedelta(days=1)).isoformat()


def flag_windows(today: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """(the last FLAG_DAYS full days, the FLAG_DAYS before them), both ending before today."""
    end = date.fromisoformat(today) - timedelta(days=1)
    start = end - timedelta(days=FLAG_DAYS - 1)
    return (start.isoformat(), end.isoformat()), previous(start.isoformat(), end.isoformat())


def trend_window(today: str) -> tuple[str, str]:
    end = date.fromisoformat(today) - timedelta(days=1)
    return (end - timedelta(days=TREND_DAYS - 1)).isoformat(), end.isoformat()


def sums(rows: list) -> dict:
    """A window's totals over daily rows (of one client's campaigns). Results add up only
    when every row that names what it counts names the same thing, the rule the client's
    total follows on the list; `mixed` says they didn't."""
    spend = sum(r["spend_cents"] for r in rows)
    clicks = sum(r["link_clicks"] for r in rows)
    kinds = {r["result_indicator"] for r in rows if r["result_indicator"]}
    counted = [r["results"] for r in rows if r["results"] is not None]
    same = len(kinds) == 1 and bool(counted)
    return {
        "spend_cents": spend,
        "link_clicks": clicks,
        "impressions": sum(r["impressions"] for r in rows),
        "cpl_cents": cents_per(spend, clicks),
        "result_indicator": next(iter(kinds)) if same else "",
        "mixed": len(kinds) > 1,
        **period_results(sum(counted) if same else None, spend),
    }


def pct(now, before) -> int | None:
    """The change from `before` to `now` in whole percent; None when there is no "before"
    to compare with, or no "now"."""
    if now is None or not before:
        return None
    return round((now - before) * 100 / before)


def compare(now: dict, before: dict, min_count: int = 1) -> dict:
    """How cost and volume moved between two windows' `sums`. By result when both windows
    count the same thing (and the earlier one at least `min_count` of it); otherwise by
    link click, the one figure that compares across objectives."""
    by_result = bool(
        now["results"]
        and (before["results"] or 0) >= min_count
        and now["result_indicator"] == before["result_indicator"]
    )
    if by_result:
        cost = pct(now["cost_per_result_cents"], before["cost_per_result_cents"])
        volume = pct(now["results"], before["results"])
    else:
        enough = before["link_clicks"] >= min_count
        cost = pct(now["cpl_cents"], before["cpl_cents"]) if enough else None
        volume = pct(now["link_clicks"], before["link_clicks"]) if enough else None
    return {
        "kind": "result" if by_result else "click",
        "cost_pct": cost,
        "volume_pct": volume,
        "spend_pct": pct(now["spend_cents"], before["spend_cents"]),
    }


NO_CHANGE = {"kind": "click", "cost_pct": None, "volume_pct": None, "spend_pct": None}


def whole(c: dict, since: str) -> bool:
    """Whether the client had numbers from `since` on: a window that starts before its
    first day isn't a whole one, and comparing with it makes a new campaign look like a
    tenfold rise."""
    return bool(c["first_day"]) and c["first_day"] <= since


def days_left(remaining_cents: int | None, last: dict) -> int | None:
    """How many days what is left on the account covers at the last FLAG_DAYS' pace; None
    when Meta gives no balance or nothing was spent."""
    if remaining_cents is None or last["spend_cents"] <= 0:
        return None
    return int(remaining_cents * FLAG_DAYS // last["spend_cents"])


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def flags(
    c: dict,
    today: str,
    remaining_cents: int | None = None,
    problem: str = "",
    reviews_used: bool = True,
    rules: dict = DEFAULTS,
) -> list[dict]:
    """What a row has to say for itself, most urgent first: [{key, level, text}]. `c` is a
    `Store.campaign_overview` row; `problem` is why Meta's numbers aren't arriving for this
    client ("" when they are); `reviews_used` is whether the team marks Visto hoje at all
    (a team that never did isn't told so on every row); `rules` are the team's thresholds
    (`Store.campaign_settings`)."""
    out: list[dict] = []
    last, before = c["sums"]["last"], c["sums"]["before"]
    # nothing left at all is its own case: it is said whatever the pace was (an account
    # empty for a week spent nothing in the last 7 days), and never as "acaba hoje"
    empty = bool(remaining_cents == 0 and c["active"] and rules["low_balance_days"])
    stopped = ""
    if c["quiet"]:
        stopped = "sem entrega desde ontem"
        if c["quiet"] < c["active"]:
            stopped = f"{c['quiet']} de {c['active']} campanhas sem entrega desde ontem"
    if problem:
        out.append({"key": "no_data", "level": ACT, "text": problem})
    elif stopped and not empty:
        # without numbers arriving, "no delivery" would only repeat `problem`
        out.append({"key": "stopped", "level": ACT, "text": stopped})
    left = days_left(remaining_cents, last) if c["active"] else None
    if empty:
        # no balance and no delivery are one event, the first the cause: one alert says both
        text = f"saldo acabou: {stopped}" if stopped and not problem else "saldo acabou"
        out.append({"key": "balance", "level": ACT, "text": text})
    elif left is not None and left < rules["low_balance_days"]:
        text = f"saldo para {_plural(left, 'dia', 'dias')}" if left else "saldo acaba hoje"
        out.append({"key": "balance", "level": ACT, "text": text})
    since = flag_windows(today)[1][0]  # where the earlier window starts
    floor = rules["min_spend"] * 100
    if whole(c, since) and min(last["spend_cents"], before["spend_cents"]) >= floor:
        ch = compare(last, before, rules["min_count"])
        what = "resultados" if ch["kind"] == "result" else "cliques"
        unit = "resultado" if ch["kind"] == "result" else "clique"
        steady = ch["spend_pct"] is not None and abs(ch["spend_pct"]) <= rules["same_spend_pct"]
        if steady and ch["volume_pct"] is not None and ch["volume_pct"] <= -rules["drop_pct"]:
            # at the same spend this is the cost rising too: one sentence says both
            text = f"{what} caíram {-ch['volume_pct']}% com o mesmo investimento"
            out.append({"key": "volume", "level": WATCH, "text": text})
        elif ch["cost_pct"] is not None and ch["cost_pct"] >= rules["rise_pct"]:
            text = f"custo por {unit} subiu {ch['cost_pct']}% em {FLAG_DAYS} dias"
            out.append({"key": "cost", "level": WATCH, "text": text})
    if c["active"] and reviews_used and rules["unseen_days"]:
        seen = c["last_seen"]
        ago = (date.fromisoformat(today) - date.fromisoformat(seen)).days if seen else None
        if ago is None:
            out.append({"key": "unseen", "level": NOTE, "text": "ainda sem análise"})
        elif ago >= rules["unseen_days"]:
            text = f"sem análise há {_plural(ago, 'dia', 'dias')}"
            out.append({"key": "unseen", "level": NOTE, "text": text})
    return sorted(out, key=lambda f: -f["level"])


def rows(
    clients: list[dict],
    today: str,
    previous_since: str,
    remaining: dict[int, int | None],
    problems: dict[int, str],
    seen: dict[int, dict],
    reviews_used: bool,
    rules: dict = DEFAULTS,
) -> list[dict]:
    """The screen's rows from `Store.campaign_overview`'s: each with the period's sums, how
    it moved against the period before (which starts on `previous_since`; `partial` and no
    percentages when the client's numbers start after that), the trend's days, the balance
    and its flags, the ones that need a look first (highest flag, then how many, then
    spend)."""
    out = []
    for c in clients:
        left = remaining.get(c["id"])
        marks = flags(c, today, left, problems.get(c["id"], ""), reviews_used, rules)
        full = whole(c, previous_since)
        change = compare(c["sums"]["period"], c["sums"]["previous"]) if full else NO_CHANGE
        out.append(
            {
                "id": c["id"],
                "name": c["name"],
                "segment": c["segment"],
                "contact": c["contact"],
                "whatsapp": c["whatsapp"],
                "currency": c["currency"],
                "campaigns": c["campaigns"],
                "active": c["active"],
                "period": c["sums"]["period"],
                "change": {**change, "partial": not full},
                "days": c["days"],
                "balance": None
                if left is None
                else {
                    "remaining_cents": left,
                    "days_left": days_left(left, c["sums"]["last"]),
                },
                "seen_today": seen.get(c["id"]),
                "last_seen": c["last_seen"],
                "flags": marks,
                "level": max((f["level"] for f in marks), default=-1),
            }
        )
    out.sort(key=lambda r: (-r["level"], -len(r["flags"]), -r["period"]["spend_cents"]))
    return out
