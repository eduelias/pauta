"""Accounts: invites, passkeys, moving house, logout."""

from __future__ import annotations

import time

from .. import __version__
from ..auth import MOVE_LINK_DAYS
from ..db import EXPORT_TABLES
from . import CRED, ID, Reply, finance_visible


def install(route, store, auth, drive, meta):
    # ---- passkeys and invites ---------------------------------------------------------

    @route("POST", "/api/invite", "admin")
    def invite(self, viewer, body):
        if not auth.enabled:
            raise Reply(400, {"error": "convites precisam de passkeys (PAUTA_AUTH)"})
        uses = body.get("uses") or 1
        if not isinstance(uses, int) or isinstance(uses, bool):
            raise Reply(400, {"error": "número de usos inválido"})
        token, expires = auth.create_invite(
            admin=body.get("admin") is True, uses=uses, created_by=viewer["account"]
        )
        return {"path": f"/#/entrar/{token}", "expires": expires}

    @route("GET", "/api/invite/([A-Za-z0-9_-]{10,64})", "open")
    def invite_info(self, viewer, _body, token):
        info = auth.invite_info(token)
        if not info:
            raise Reply(404, {"error": "este convite não vale mais; peça um novo"})
        return info

    @route("POST", "/api/passkey/register/options", "open")
    def register_options(self, viewer, body):
        if not auth.enabled:
            raise Reply(400, {"error": "passkeys estão desligadas"})
        rp_id = auth.rp_for(self._page_origin())
        if body.get("move"):
            if rp_id != auth.rp_id:
                raise Reply(400, {"error": f"abra este link em {auth.home_host}"})
            return auth.register_options(move=str(body["move"]), rp_id=rp_id)
        if body.get("invite"):
            return auth.register_options(
                invite=str(body["invite"]), name=body.get("name"), rp_id=rp_id
            )
        acc = auth.account_from_cookie(self.headers.get("Cookie"))
        if not acc:
            raise Reply(401, {"error": "entre primeiro para adicionar um aparelho"})
        return auth.register_options(account=acc, rp_id=rp_id)

    @route("POST", "/api/passkey/register/verify", "open")
    def register_verify(self, viewer, body):
        acc = auth.register_verify(
            body.get("flow"),
            body.get("credential") or {},
            user_agent=self.headers.get("User-Agent", ""),
        )
        return auth.viewer_for(acc), auth.make_cookie(acc["id"], self._secure())

    @route("POST", "/api/passkey/login/options", "open")
    def login_options(self, viewer, _body):
        if not auth.enabled:
            raise Reply(400, {"error": "passkeys estão desligadas"})
        return auth.login_options(auth.rp_for(self._page_origin()))

    @route("POST", "/api/move")
    def move(self, viewer, _body):
        """From the old domain: a one-time link to make a passkey on the new one."""
        hint = auth.move_hint(self._page_origin(), viewer["account"])
        if not hint or viewer["account"] is None:
            raise Reply(400, {"error": "a Pauta não está mudando de endereço"})
        if hint["here"]:
            raise Reply(400, {"error": f"você já está em {hint['to']}"})
        token, _ = auth.create_move(viewer["account"])
        return {"url": f"{hint['url']}/#/mudar/{token}"}

    @route("POST", f"/api/members/{ID}/move", "admin")
    def move_link(self, viewer, _body, mid):
        """An admin's link for someone else: sent on WhatsApp, one tap and Face ID on the
        home domain. Also the way back in after a lost phone."""
        if not auth.enabled or not auth.home:
            raise Reply(400, {"error": "links de mudança precisam de passkeys (PAUTA_AUTH)"})
        token, expires = auth.create_move(
            int(mid), MOVE_LINK_DAYS * 86400, created_by=viewer["account"]
        )
        return {"url": f"{auth.home}/#/mudar/{token}", "expires": expires, "to": auth.home_host}

    @route("GET", "/api/move/([A-Za-z0-9_-]{20,64})", "open")
    def move_info(self, viewer, _body, token):
        info = auth.move_info(token)
        if not info:
            raise Reply(404, {"error": "este link de mudança expirou"})
        return info

    @route("POST", "/api/passkey/login/verify", "open")
    def login_verify(self, viewer, body):
        acc = auth.login_verify(body.get("flow"), body.get("credential") or {})
        return auth.viewer_for(acc), auth.make_cookie(acc["id"], self._secure())

    @route("POST", "/api/logout", "open")
    def logout(self, viewer, _body):
        if auth.enabled:  # ends this person's sessions on every device, not just this one
            auth.end_sessions(viewer["account"])
        return {"ok": True}, auth.clear_cookie(self._secure())

    # ---- the person's own passkeys (Perfil, decision 10) ------------------------------

    def _own_account(self, viewer) -> int:
        if viewer["account"] is None:
            raise Reply(400, {"error": "sem contas no modo local"})
        return viewer["account"]

    @route("GET", "/api/me/passkeys")
    def my_passkeys(self, viewer, _body):
        return auth.passkeys(viewer["account"])

    @route("PATCH", f"/api/me/passkeys/{CRED}")
    def relabel_passkey(self, viewer, body, cred):
        aid = _own_account(self, viewer)
        auth.relabel_passkey(aid, cred, body.get("label"))
        return auth.passkeys(aid)

    @route("DELETE", f"/api/me/passkeys/{CRED}")
    def remove_passkey(self, viewer, _body, cred):
        """Removing a passkey signs the account out everywhere (the device that had it
        above all); this device gets a fresh cookie and stays in."""
        aid = _own_account(self, viewer)
        auth.remove_passkey(aid, cred)
        return auth.passkeys(aid), auth.make_cookie(aid, self._secure())

    @route("POST", "/api/me/move")
    def my_move_link(self, viewer, _body):
        """The same one-time link an admin makes (move_link), for yourself: a new or
        lost phone, sent to your own WhatsApp or opened from the box on Perfil. It lasts
        minutes, not days (the person taps it on the new phone right away), and dies
        with the session (end_sessions)."""
        aid = _own_account(self, viewer)
        if not auth.enabled or not auth.home:
            raise Reply(400, {"error": "links de nova passkey precisam de passkeys (PAUTA_AUTH)"})
        token, expires = auth.create_move(aid, created_by=aid)
        return {"url": f"{auth.home}/#/mudar/{token}", "expires": expires, "to": auth.home_host}

    @route("GET", "/api/boot")
    def boot(self, viewer, _body):
        everyone = store.members()
        fin = store.finance_settings()
        members = [{"id": m["id"], "name": m["name"]} for m in everyone if not m["disabled"]]
        # Gravatar ids by account, for avatars on requests and the timeline
        avatars = {m["id"]: m["avatar"] for m in everyone if m["avatar"]}
        return {
            "me": self._me(viewer),
            "options": store.options(),
            "members": members,
            "avatars": avatars,
            "version": __version__,
            "files": {
                "enabled": drive.enabled,
                "connected": drive.connected,
                "max_mb": drive.max_bytes // (1024 * 1024),
            },
            "finance": {**fin, "visible": finance_visible(viewer, fin)},
            "meta": {"enabled": meta.enabled},
            # Configurações → Campanhas: the alert thresholds, and the request kinds the
            # "which campaign did this request create?" chooser goes by
            "campaigns": store.campaign_settings(),
        }

    @route("GET", "/api/export", "admin")
    def export(self, viewer, _body):
        return {
            "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "clients": store.clients(),
            "requests": [store.request(r["id"]) for r in store.requests()],
            "finance": store.finance_settings(),
            "campaign_settings": store.campaign_settings(),
            "payments": [p for c in store.clients() for p in store.client(c["id"])["payments"]],
            "meta_account": store.meta_accounts(),
            **{t: store.table(t) for t in EXPORT_TABLES},
        }
