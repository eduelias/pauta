"""The usage log (decision 11): what the app records about how the team uses it, and the
`pauta usage` report over it.

Rows are pseudonymous (account id, never a name) and hold nothing from the team's data:
event names and prop keys come from the fixed table below, unknown ones are dropped,
string values are cut at MAX_VALUE characters, and the device string is a short fixed shape
built client-side (never the user agent). Rows older than RETENTION_DAYS are pruned by the
nightly backup run (`pauta backup`).
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from statistics import median

from . import obs

RETENTION_DAYS = 90
MAX_VALUE = 64  # characters of a prop value
MAX_EVENTS = 50  # events per POST /api/usage
MAX_BODY = 16 * 1024  # bytes per POST /api/usage
MAX_BEHIND = 24 * 3600  # a client timestamp further back than this is replaced by now

# event -> the prop keys it may carry (anything else is dropped before the row is written)
EVENTS: dict[str, tuple[str, ...]] = {
    "app_open": ("version", "theme"),
    "screen": ("from",),
    "request_created": ("kind", "has_deadline", "files"),
    "request_status": ("from", "to", "via"),
    "request_sent": (),
    "comment_added": ("screen",),
    "file_added": (),
    "file_failed": ("reason",),
    "client_saved": ("new",),
    "seen_today": ("n",),
    "period": ("p",),
    "client_message": ("kind",),
    "finance_entry": ("kind",),
    "search": ("what",),
    "filter": ("what",),
    # `route`, `method` and `status` are the failed call's (within 3 s of the toast); `form`
    # is the form id or screen the toast came from when no call failed (a client-side check)
    "error_shown": ("msg", "screen", "status", "route", "method", "form"),
    "api_slow": ("route", "ms", "status", "method"),
    "settings_changed": ("section",),
    "login": ("ok", "method"),
}
SCREENS = (
    "painel",
    "quadro",
    "pedidos",
    "pedido",
    "novo",
    "clientes",
    "cliente",
    "cliente_novo",
    "financeiro",
    "campanhas",
    "campanha",
    "publicacoes",
    "configuracoes",
    "perfil",
    "entrar",
    "mudar",
)
# phone/standalone/390x840/ios: form factor, installed or not, viewport (10 px), platform
DEV = re.compile(r"^(phone|desktop)/(standalone|browser)/\d{2,4}x\d{2,4}/[a-z]{2,8}$")
# the usage events that are "actions" in the report: not a screen, not a measurement
MEASUREMENTS = ("app_open", "screen", "error_shown", "api_slow")
REPEAT_WINDOW = 5 * 60  # seconds: the same step on 2+ requests of one client within this


def stamp(t, now: datetime) -> str:
    """The row's time from the client's epoch milliseconds, clamped to [now - a day, now]
    (phones' clocks drift and a batch can sit in a backgrounded tab), as SQLite's datetime."""
    at = now
    if isinstance(t, (int, float)) and not isinstance(t, bool):
        try:
            at = datetime.fromtimestamp(t / 1000, tz=UTC)
        except (OverflowError, OSError, ValueError):
            at = now
        at = max(now - timedelta(seconds=MAX_BEHIND), min(now, at))
    return at.strftime("%Y-%m-%d %H:%M:%S")


def clean_value(v):
    """A prop value as stored: a bool, a number, or a string cut at MAX_VALUE; None otherwise."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v == v and abs(v) < 1e12:  # not NaN, not absurd
        return v
    if isinstance(v, str):
        return v[:MAX_VALUE]
    return None


def clean_event(doc, now: datetime) -> tuple[str, str, str, str] | None:
    """One client event `{t, e, s, p}` as (at, event, screen, props_json), or None when the
    event name is not in EVENTS. Unknown prop keys and non-scalar values are dropped."""
    if not isinstance(doc, dict):
        return None
    event = doc.get("e")
    if not isinstance(event, str) or event not in EVENTS:
        return None
    screen = doc.get("s")
    screen = screen if isinstance(screen, str) and screen in SCREENS else ""
    props = doc.get("p")
    kept = {}
    if isinstance(props, dict):
        for key in EVENTS[event]:
            if key in props:
                value = clean_value(props[key])
                if value is not None:
                    kept[key] = value
    return (
        stamp(doc.get("t"), now),
        event,
        screen,
        json.dumps(kept, ensure_ascii=False, separators=(",", ":")),
    )


def clean_dev(dev) -> str:
    return dev if isinstance(dev, str) and DEV.match(dev) else ""


# ---- the report ---------------------------------------------------------------------------


def _day(at: str) -> str:
    return at[:10]


def _where(p: dict) -> str:
    """Where an error toast came from: the call that failed ("PATCH /api/requests/{id}"),
    else the form or screen of a client-side check ("form novo"), else ""."""
    if p.get("route"):
        return f"{p.get('method') or '?'} {p['route']}"
    if p.get("form"):
        return f"form {p['form']}"
    return ""


def _p95(values: list[float]):
    return obs.percentile(sorted(values), 0.95)


def _p90_days(days: list[int]) -> int | None:
    return int(obs.percentile(sorted(days), 0.90)) if days else None


def summary(store, days: int = 7, today: date | None = None) -> dict:
    """The numbers behind `pauta usage`: the last `days` days up to and including today."""
    today = today or datetime.now(UTC).date()
    since = today - timedelta(days=days - 1)
    since_at = f"{since.isoformat()} 00:00:00"
    with store.db() as db:
        names = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM account")}
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT at, account, event, screen, props, dev FROM usage WHERE at >= ? "
                "ORDER BY at, id",
                (since_at,),
            )
        ]
        done = [
            dict(r)
            for r in db.execute(
                "SELECT kind, created, done_on FROM request WHERE done_on >= ?",
                (since.isoformat(),),
            )
        ]
        live_clients = {
            r[0]
            for r in db.execute(
                "SELECT DISTINCT client FROM campaign WHERE state='active' AND client IS NOT NULL"
            )
        }
        reviews = [
            (r[0], r[1])
            for r in db.execute(
                'SELECT r."on", c.client FROM review r JOIN campaign c ON c.id = r.campaign '
                'WHERE r."on" >= ? AND c.client IS NOT NULL',
                (since.isoformat(),),
            )
        ]
        steps = [
            dict(r)
            for r in db.execute(
                "SELECT e.at, e.account, e.kind, e.text, e.request, r.client, "
                "c.name AS client_name FROM event e JOIN request r ON r.id = e.request "
                "JOIN client c ON c.id = r.client "
                "WHERE e.at >= ? AND e.kind IN ('status', 'comment') ORDER BY e.at, e.id",
                (since_at,),
            )
        ]
    for r in rows:
        r["props"] = json.loads(r["props"] or "{}")

    active: dict[str, set] = defaultdict(set)
    screens: dict[str, Counter] = defaultdict(Counter)
    actions: dict[str, Counter] = defaultdict(Counter)
    paths: Counter = Counter()
    errors: Counter = Counter()
    slow: dict[str, list] = defaultdict(list)
    slow_failed: Counter = Counter()
    devs: list[str] = []
    for r in rows:
        acc = r["account"] or 0
        active[_day(r["at"])].add(acc)
        p = r["props"]
        if r["event"] == "screen":
            screens[r["screen"] or "?"][acc] += 1
            if p.get("from"):
                paths[(p["from"], r["screen"] or "?")] += 1
        elif r["event"] == "error_shown":
            errors[
                (p.get("msg", "?"), r["screen"] or "?", str(p.get("status", "")), _where(p))
            ] += 1
        elif r["event"] == "api_slow":
            route = str(p.get("route", "?"))
            ms = p.get("ms")
            if isinstance(ms, (int, float)) and not isinstance(ms, bool):
                slow[route].append(float(ms))
            status = p.get("status")
            if isinstance(status, (int, float)) and status >= 400:
                slow_failed[route] += 1
            elif status == 0:
                slow_failed[route] += 1
        elif r["event"] == "app_open":
            devs.append(r["dev"])
        else:
            actions[r["event"]][acc] += 1
    slow_rows = sorted(
        (
            {"route": route, "n": len(ms), "p95_ms": _p95(ms), "failed": slow_failed[route]}
            for route, ms in slow.items()
        ),
        key=lambda s: -(s["p95_ms"] or 0),
    )
    for route, n in slow_failed.items():  # failed calls without a timing still count
        if route not in slow:
            slow_rows.append({"route": route, "n": n, "p95_ms": None, "failed": n})

    device = {
        "opens": len(devs),
        "phone": sum(1 for d in devs if d.startswith("phone/")),
        "standalone": sum(1 for d in devs if "/standalone/" in d),
        "viewports": Counter(d.split("/")[2] for d in devs if d.count("/") == 3),
        "platforms": Counter(d.split("/")[3] for d in devs if d.count("/") == 3),
    }

    funnel: dict[str, list[int]] = defaultdict(list)
    for r in done:
        created = date.fromisoformat(r["created"][:10])
        funnel[r["kind"] or "(sem tipo)"].append((date.fromisoformat(r["done_on"]) - created).days)
    all_days = [d for ds in funnel.values() for d in ds]
    funnel_rows = [
        {"kind": kind, "n": len(ds), "median": median(ds), "p90": _p90_days(ds)}
        for kind, ds in sorted(funnel.items(), key=lambda kv: -len(kv[1]))
    ]

    seen_by_day: dict[str, set] = defaultdict(set)
    for on, client in reviews:
        seen_by_day[on].add(client)
    seen = [
        {
            "day": (since + timedelta(days=i)).isoformat(),
            "checked": len(seen_by_day[(since + timedelta(days=i)).isoformat()] & live_clients),
            "live": len(live_clients),
        }
        for i in range(days)
    ]

    by_total = lambda kv: -sum(kv[1].values())  # noqa: E731
    return {
        "days": days,
        "since": since.isoformat(),
        "until": today.isoformat(),
        "rows": len(rows),
        "names": names,
        "active": [(day, sorted(accs)) for day, accs in sorted(active.items())],
        "screens": {s: dict(c) for s, c in sorted(screens.items(), key=by_total)},
        "actions": {e: dict(c) for e, c in sorted(actions.items(), key=by_total)},
        "paths": paths.most_common(10),
        "errors": errors.most_common(10),
        "slow": slow_rows[:10],
        "devices": device,
        "funnel": {
            "rows": funnel_rows,
            "n": len(all_days),
            "median": median(all_days) if all_days else None,
            "p90": _p90_days(all_days),
        },
        "seen": seen,
        "repeated": repeated_steps(steps),
        "dead": [e for e in EVENTS if not any(r["event"] == e for r in rows)],
    }


def repeated_steps(steps: list[dict]) -> list[dict]:
    """The same status change (or the same comment) applied by one account to two or more
    requests of one client within REPEAT_WINDOW: the pattern a client with two open
    requests produces when every step is done twice. `steps` are event rows (at, account,
    kind, text, request, client, client_name) in time order."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for s in steps:
        groups[(s["account"], s["client"], s["kind"], s["text"])].append(s)
    out = []
    for (account, client, kind, text), group in groups.items():
        i = 0
        while i < len(group):
            start = datetime.fromisoformat(group[i]["at"])
            j = i
            while (
                j + 1 < len(group)
                and (datetime.fromisoformat(group[j + 1]["at"]) - start).total_seconds()
                <= REPEAT_WINDOW
            ):
                j += 1
            requests = sorted({s["request"] for s in group[i : j + 1]})
            if len(requests) >= 2:
                out.append(
                    {
                        "at": group[i]["at"],
                        "account": account,
                        "client": client,
                        "client_name": group[i]["client_name"],
                        "kind": kind,
                        "text": text if kind == "status" else "",
                        "requests": requests,
                    }
                )
            i = j + 1
    return sorted(out, key=lambda r: r["at"])


def render(s: dict) -> str:
    """`summary()` as the text `pauta usage` prints."""

    def who(acc) -> str:
        return s["names"].get(acc, f"#{acc}") if acc else "(no account)"

    def by(counts: dict) -> str:
        return ", ".join(f"{who(a)} {n}" for a, n in sorted(counts.items(), key=lambda kv: -kv[1]))

    def section(title: str, body: list[str]) -> None:
        lines.extend(["", title])
        lines.extend(body or ["  none"])

    lines = [
        f"Pauta usage, {s['days']} day(s) ({s['since']} to {s['until']}): {s['rows']} event row(s)"
    ]
    section(
        "Active accounts per day",
        [f"  {day}  {len(accs)}  ({', '.join(who(a) for a in accs)})" for day, accs in s["active"]],
    )
    section(
        "Screens",
        [f"  {sc:<14} {sum(c.values()):>5}  ({by(c)})" for sc, c in s["screens"].items()],
    )
    section(
        "Actions",
        [f"  {ev:<16} {sum(c.values()):>5}  ({by(c)})" for ev, c in s["actions"].items()],
    )
    section("Paths (screen -> next screen)", [f"  {a} -> {b}  {n}" for (a, b), n in s["paths"]])
    section(
        "Error toasts (class, screen, status, the call that failed or the form)",
        [
            f"  {m:<11} {sc:<14} {st or '-':<4} {n:<4} {where or '-'}"
            for (m, sc, st, where), n in s["errors"]
        ],
    )
    slow = []
    for r in s["slow"]:
        p95 = f"{r['p95_ms']:.0f} ms" if r["p95_ms"] is not None else "-"
        slow.append(f"  {r['route']:<36} n={r['n']:<4} p95={p95:<9} failed={r['failed']}")
    section("Slow or failed calls (client-measured, network included)", slow)
    d = s["devices"]
    devices = []
    if d["opens"]:
        devices = [
            f"  {d['opens']} open(s): {d['phone']} phone, {d['opens'] - d['phone']} desktop; "
            f"{100 * d['standalone'] // d['opens']}% installed (standalone)",
            "  viewports: " + ", ".join(f"{v} {n}" for v, n in d["viewports"].most_common(6)),
            "  platforms: " + ", ".join(f"{p} {n}" for p, n in d["platforms"].most_common()),
        ]
    section("Devices (per app open)", devices)
    f = s["funnel"]
    funnel = []
    if f["n"]:
        funnel = [f"  all kinds: n={f['n']} median={f['median']:g} p90={f['p90']}"] + [
            f"  {r['kind']:<22} n={r['n']:<3} median={r['median']:g} p90={r['p90']}"
            for r in f["rows"]
        ]
    section("Open -> done (requests concluded in the window, days from creation)", funnel)
    live = s["seen"][0]["live"] if s["seen"] else 0
    section(
        "Visto hoje coverage (clients with live campaigns checked that day)",
        [f"  {r['day']}  {r['checked']}/{r['live']}" for r in s["seen"]]
        if live
        else ["  no client has a live campaign"],
    )
    rep = s["repeated"]
    section(
        f"Repeated steps (same change on 2+ requests of one client within 5 min): {len(rep)}",
        [
            f"  {r['at']}  {who(r['account'])}: {r['kind']}{' ' + r['text'] if r['text'] else ''}"
            f" on {len(r['requests'])} requests of {r['client_name']} "
            f"(#{', #'.join(map(str, r['requests']))})"
            for r in rep
        ],
    )
    section(
        "Dead features (events with no row in the window)",
        ["  " + (", ".join(s["dead"]) if s["dead"] else "none")],
    )
    return "\n".join(lines)
