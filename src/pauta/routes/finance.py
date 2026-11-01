"""Finance (decision 7): the panel, billing and payments."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from . import ID, Reply, finance_visible


def install(route, store, auth, drive, meta):
    # ---- finance (decision 7) ---------------------------------------------------------

    def _finance(self, viewer):
        """Every finance route: 404 when the module is off, 403 when this person may not."""
        fin = store.finance_settings()
        if not fin["enabled"]:
            raise Reply(404, {"error": "o financeiro está desligado"})
        if not finance_visible(viewer, fin):
            raise Reply(403, {"error": "só administradores veem o financeiro"})

    @route("GET", "/api/finance")
    def finance_panel(self, viewer, _body):
        _finance(self, viewer)
        month = parse_qs(urlparse(self.path).query).get("month", [None])[0]
        return store.finance(month=month)

    @route("GET", "/api/finance/settings", "admin")
    def finance_settings(self, viewer, _body):
        return store.finance_settings()

    @route("PATCH", "/api/finance/settings", "admin")
    def edit_finance_settings(self, viewer, body):
        return store.set_finance_settings(body)

    @route("PATCH", f"/api/clients/{ID}/billing")
    def edit_billing(self, viewer, body, cid):
        _finance(self, viewer)
        return store.set_billing(int(cid), body, viewer["account"])

    @route("POST", f"/api/clients/{ID}/payments")
    def add_payment(self, viewer, body, cid):
        _finance(self, viewer)
        return store.add_payment(int(cid), body, viewer["account"])

    @route("DELETE", f"/api/payments/{ID}")
    def void_payment(self, viewer, _body, pid):
        _finance(self, viewer)
        return store.void_payment(int(pid), viewer["account"], viewer["is_admin"])
