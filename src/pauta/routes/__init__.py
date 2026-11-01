"""The /api routes, one module per area. Each exposes install(route, store, auth, drive, meta),
which server.make_handler calls so its handlers register on the same route table; the
handlers are plain functions taking the request handler as `self`. What the areas share
(the id patterns, Reply, the Meta texts) lives here.
"""

from __future__ import annotations

from ..meta import ACCOUNT_STATUS

ID = r"(\d{1,9})"

CRED = r"([A-Za-z0-9_-]{8,1400})"  # a passkey's credential id, base64url

SENT = object()  # a route that wrote its own response (a redirect, an image)

# what a member sees when Meta fails: the real reason ("conecte de novo") is the admin's
META_DOWN = "os números da Meta estão indisponíveis no momento"

MAX_PERIOD_DAYS = 400  # /api/campaigns refuses a longer range

DEFAULT_PERIOD_DAYS = 30  # Ads Manager's own default: "Últimos 30 dias", yesterday back


def _stale(row: dict, names: dict[str, str] | None = None) -> dict:
    """A meta_account row as an account entry without numbers (not in Meta's latest list),
    labelled with its portfolio (`names`: business id -> name)."""
    return {
        "id": row["id"],
        "name": row["name"],
        "currency": row["currency"],
        "status": row["status"],
        "status_label": ACCOUNT_STATUS.get(row["status"], ""),
        "client": row["client"],
        "seen": row["seen"],
        "business_id": row.get("business_id") or "",
        "business_name": (names or {}).get(row.get("business_id") or "", ""),
    }


class Reply(Exception):
    def __init__(self, status: int, doc: dict | list):
        super().__init__(status)
        self.status, self.doc = status, doc


def finance_visible(viewer: dict, settings: dict) -> bool:
    """Who sees money: everyone, or admins only, per the team's setting; nobody when off."""
    if not settings.get("enabled"):
        return False
    return settings.get("visibility") == "all" or bool(viewer.get("is_admin"))
