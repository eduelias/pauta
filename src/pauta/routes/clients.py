"""Clients."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from ..meta import MetaError
from . import ID, META_DOWN, _stale, finance_visible


def install(route, store, auth, drive, meta):
    # ---- clients ----------------------------------------------------------------------

    @route("GET", "/api/clients")
    def list_clients(self, viewer, _body):
        return store.clients()

    @route("POST", "/api/clients")
    def new_client(self, viewer, body):
        body.pop("billed", None)
        return _client_for(self, viewer, store.save_client(body, by=viewer["account"]))

    @route("GET", f"/api/clients/{ID}")
    def get_client(self, viewer, _body, cid):
        return _client_for(self, viewer, store.client(int(cid)))

    @route("PATCH", f"/api/clients/{ID}")
    def edit_client(self, viewer, body, cid):
        body.pop("billed", None)  # that one goes through /billing, with the finance check
        return _client_for(self, viewer, store.save_client(body, int(cid), viewer["account"]))

    def _client_for(self, viewer, client: dict) -> dict:
        if not finance_visible(viewer, store.finance_settings()):
            client = {**client, "billing": None, "payments": []}
        return client

    @route("GET", f"/api/clients/{ID}/meta")
    def client_meta(self, viewer, _body, cid):
        """This client's linked ad accounts with this month's numbers (from the Meta
        cache; a cold cache reads Meta). Meta off or not connected is not an error, and
        neither is Meta failing: 200 with `error` (the reason for admins, a neutral line
        for members) so the card says so instead of the page breaking."""
        store.client(int(cid))  # 404 for an unknown client
        if not meta.connected:
            return {"connected": False, "accounts": []}
        try:
            live = {a["id"]: a for a in meta.accounts()}  # a cold cache syncs the rows
        except MetaError as e:
            if not store.client(int(cid))["meta_accounts"]:
                return {"connected": True, "accounts": []}  # nothing to show anyway
            error = str(e) if viewer["is_admin"] else META_DOWN
            return {"connected": True, "accounts": [], "error": error}
        linked = store.client(int(cid))["meta_accounts"]
        rows = {r["id"]: r for r in store.meta_accounts()}
        names = {c["business_id"]: c["business_name"] for c in meta.connections()}
        return {
            "connected": True,
            "accounts": [
                {**live[a["id"]], "stale": False}
                if a["id"] in live
                else {**_stale(rows[a["id"]], names), "stale": True}
                for a in linked
            ],
        }

    @route("DELETE", f"/api/clients/{ID}", "admin")
    def delete_client(self, viewer, _body, cid):
        query = parse_qs(urlparse(self.path).query)
        with_requests = query.get("with_requests") == ["1"]
        n = store.delete_client(int(cid), with_requests=with_requests)
        return {"ok": True, "requests_deleted": n}
