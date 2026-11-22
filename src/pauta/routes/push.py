"""Notifications (push.py): a device switches them on or off for the person signed in on it,
and its service worker asks what to show when a push wakes it."""

from __future__ import annotations

from ..push import describe
from . import Reply


def install(route, store, auth, push):
    def _account(viewer) -> int:
        if viewer["account"] is None:
            raise Reply(400, {"error": "sem contas no modo local"})
        return viewer["account"]

    @route("GET", "/api/push")
    def push_key(self, viewer, _body):
        _account(viewer)
        return {"key": push.public_key}

    @route("POST", "/api/push")
    def push_on(self, viewer, body):
        if not push.allowed(body.get("endpoint")):
            raise Reply(400, {"error": "este navegador não recebe notificações da Pauta"})
        store.push_subscribe(_account(viewer), body["endpoint"])
        return {"ok": True}

    @route("POST", "/api/push/off")
    def push_off(self, viewer, body):
        if endpoint := str(body.get("endpoint") or ""):  # never "all of this person's"
            store.push_forget(endpoint=endpoint, account=_account(viewer))
        return {"ok": True}

    @route("POST", "/api/push/news")
    def push_news(self, viewer, body):
        rows = store.push_news(_account(viewer), str(body.get("endpoint") or ""))
        return {"news": [describe(r) for r in rows]}
