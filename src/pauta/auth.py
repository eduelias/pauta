"""Passkey-only accounts, the same way dominion-archive does them.

There is one team. Nobody signs up: the admin makes an invite (a QR code or a link), the
person types a name and creates a passkey, done. The first account is the admin; an admin
invite makes another admin. Without `PAUTA_AUTH=passkeys` the app runs open (local dev):
one anonymous admin, no login screen.

Configuration (environment):
  PAUTA_AUTH=passkeys     turn accounts on
  PAUTA_RP_ID             passkey domain, e.g. pauta.genic.dev (default: localhost)
  PAUTA_ORIGIN            allowed origin(s), comma-separated, e.g. https://pauta.genic.dev
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from pathlib import Path

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .db import Store, gravatar

COOKIE = "pauta_session"
SESSION_DAYS = 180
FLOW_SECONDS = 300
RP_NAME = "Pauta"
INVITE_DAYS = 7
DEV_ORIGINS = [f"http://localhost:{p}" for p in (8088, 8089)] + ["http://localhost"]


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def clean_name(name) -> str:
    """A display name: no control or invisible format characters, single spaces, 40 max."""
    name = "".join(c for c in str(name or "") if unicodedata.category(c) not in ("Cc", "Cf"))
    return " ".join(name.split())[:40]


def _fold(name: str) -> str:
    """What makes two names look the same: case, accents and compatibility forms."""
    name = unicodedata.normalize("NFKD", name.casefold())
    return "".join(c for c in name if not unicodedata.combining(c))


def load_secret(store: Store) -> bytes:
    """The session-signing key lives next to the DB, never in it, so a copy of the DB (the
    nightly backups) can't be used to sign in. Delete the file to sign everyone out."""
    path = Path(f"{store.path}.session-key")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        secret = path.read_text().strip()
    else:
        secret = secrets.token_urlsafe(32)
        with os.fdopen(fd, "w") as f:
            f.write(secret + "\n")
    if len(secret) < 32:
        raise RuntimeError(f"{path} is too short to be a session key; delete it")
    with store.db() as db:  # 1.2 and older kept it in the DB, and so in every backup
        db.execute("DELETE FROM meta WHERE key='session_secret'")
    return secret.encode()


class AuthError(Exception):
    """A user-facing reason a passkey step failed (in Portuguese)."""


OPEN_VIEWER = {
    "auth": False,
    "logged_in": True,
    "account": None,
    "name": "Você",
    "email": "",
    "avatar": "",
    "is_admin": True,
}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Auth:
    def __init__(
        self,
        store: Store,
        enabled: bool | None = None,
        rp_id: str | None = None,
        origins: list[str] | None = None,
    ):
        self.store = store
        self.enabled = (os.environ.get("PAUTA_AUTH") == "passkeys") if enabled is None else enabled
        self.rp_id = rp_id or os.environ.get("PAUTA_RP_ID") or "localhost"
        env_origins = [
            o.strip() for o in os.environ.get("PAUTA_ORIGIN", "").split(",") if o.strip()
        ]
        self.origins = origins or env_origins or DEV_ORIGINS
        self._flows: dict[str, dict] = {}
        self._lock = threading.Lock()
        self.secret = load_secret(store)

    # ---- sessions -------------------------------------------------------------------------

    def _sign(self, payload: str) -> str:
        mac = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")

    def make_cookie(self, account_id: int, secure: bool) -> str:
        expires = int(time.time()) + SESSION_DAYS * 86400
        with self.store.db() as db:
            gen = db.execute("SELECT session_gen FROM account WHERE id=?", (account_id,))
            gen = gen.fetchone()[0]
        payload = f"{account_id}|{gen}|{expires}"
        attrs = f"Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict"
        return f"{COOKIE}={payload}|{self._sign(payload)}; {attrs}{'; Secure' if secure else ''}"

    @staticmethod
    def clear_cookie(secure: bool) -> str:
        return (
            f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict{'; Secure' if secure else ''}"
        )

    def account_from_cookie(self, cookie_header: str | None) -> dict | None:
        if not cookie_header:
            return None
        for part in cookie_header.split(";"):
            name, _, value = part.strip().partition("=")
            if name != COOKIE or value.count("|") != 3:
                continue
            aid, gen, expires, sig = value.split("|")
            if not hmac.compare_digest(sig, self._sign(f"{aid}|{gen}|{expires}")):
                return None
            if not all(x.isdigit() for x in (aid, gen, expires)) or int(expires) < time.time():
                return None
            with self.store.db() as db:
                row = db.execute(
                    "SELECT * FROM account WHERE id=? AND session_gen=? AND NOT disabled",
                    (int(aid), int(gen)),
                ).fetchone()
            return dict(row) if row else None
        return None

    def end_sessions(self, account_id: int | None) -> None:
        """Sign the account out everywhere: every cookie issued so far stops working."""
        if account_id is None:
            return
        with self.store.db() as db:
            db.execute("UPDATE account SET session_gen = session_gen + 1 WHERE id=?", (account_id,))

    def viewer(self, cookie_header: str | None) -> dict:
        """Who is looking. Anonymous visitors see only the login page."""
        if not self.enabled:
            return dict(OPEN_VIEWER)
        return self.viewer_for(self.account_from_cookie(cookie_header))

    @staticmethod
    def viewer_for(acc: dict | None) -> dict:
        return {
            "auth": True,
            "logged_in": bool(acc),
            "account": acc["id"] if acc else None,
            "name": acc["name"] if acc else None,
            "email": acc["email"] if acc else "",
            "avatar": gravatar(acc["email"]) if acc else "",
            "is_admin": bool(acc and acc["is_admin"]),
        }

    # ---- invites --------------------------------------------------------------------------

    def create_invite(
        self,
        admin: bool = False,
        uses: int = 1,
        days: float = INVITE_DAYS,
        created_by: int | None = None,
    ) -> tuple[str, float]:
        token = secrets.token_urlsafe(18)
        expires = time.time() + days * 86400
        with self.store.db() as db:
            db.execute(
                "INSERT INTO invite(token_hash, admin, max_uses, expires, created_by) "
                "VALUES (?,?,?,?,?)",
                (_h(token), int(admin), max(1, min(uses, 20)), expires, created_by),
            )
        return token, expires

    @staticmethod
    def _invite_row(db, token: str):
        row = db.execute("SELECT * FROM invite WHERE token_hash=?", (_h(token or ""),)).fetchone()
        if not row or row["uses"] >= row["max_uses"] or row["expires"] < time.time():
            return None
        return row

    def invite_info(self, token: str) -> dict | None:
        with self.store.db() as db:
            row = self._invite_row(db, token)
            if not row:
                return None
            by = db.execute("SELECT name FROM account WHERE id=?", (row["created_by"],)).fetchone()
        return {
            "admin": bool(row["admin"]),
            "expires": row["expires"],
            "uses_left": row["max_uses"] - row["uses"],
            "invited_by": by[0] if by else None,
        }

    # ---- flows (the challenge stays server-side for a few minutes) --------------------------

    def _new_flow(self, **data) -> str:
        fid = secrets.token_urlsafe(16)
        with self._lock:
            now = time.time()
            self._flows = {k: v for k, v in self._flows.items() if v["expires"] > now}
            self._flows[fid] = {**data, "expires": now + FLOW_SECONDS}
        return fid

    def _take_flow(self, fid: str, kind: str) -> dict:
        with self._lock:
            flow = self._flows.pop(str(fid), None)
        if not flow or flow["kind"] != kind or flow["expires"] < time.time():
            raise AuthError("esta etapa expirou; tente de novo")
        return flow

    # ---- registration: join with an invite, or add a passkey to my account ------------------

    def register_options(
        self, *, invite: str | None = None, name: str = "", account: dict | None = None
    ) -> dict:
        if account:
            display = account["name"]
            with self.store.db() as db:
                row = db.execute("SELECT handle FROM account WHERE id=?", (account["id"],))
                handle = row.fetchone()[0]
                existing = [
                    r[0]
                    for r in db.execute("SELECT id FROM passkey WHERE account=?", (account["id"],))
                ]
        else:
            if not invite or not self.invite_info(invite):
                raise AuthError("este convite não vale mais; peça um novo")
            display = clean_name(name)
            if not display:
                raise AuthError("digite seu nome")
            with self.store.db() as db:
                self._check_name_free(db, display)
            handle, existing = bytes_to_base64url(secrets.token_bytes(16)), []
        options = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=RP_NAME,
            user_name=display,
            user_display_name=display,
            user_id=base64url_to_bytes(handle),
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in existing
            ],
        )
        fid = self._new_flow(
            kind="register",
            challenge=options.challenge,
            invite=invite,
            name=display,
            handle=handle,
            account=account["id"] if account else None,
        )
        return {"flow": fid, "options": json.loads(options_to_json(options))}

    def register_verify(self, fid: str, credential: dict) -> dict:
        flow = self._take_flow(fid, "register")
        _check_credential(credential)
        try:
            v = verify_registration_response(
                credential=credential,
                expected_challenge=flow["challenge"],
                expected_rp_id=self.rp_id,
                expected_origin=self.origins,
                require_user_verification=True,
            )
        except Exception as e:  # the library raises several types for bad responses
            raise AuthError(f"passkey não aceita: {e}") from e
        cred_id = bytes_to_base64url(v.credential_id)
        response = credential.get("response")
        transports = (response.get("transports") if isinstance(response, dict) else None) or []
        transports = ",".join(t for t in transports if isinstance(t, str))[:200]
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")  # one join at a time: an invite's uses can't race
            if flow["account"]:
                account_id = flow["account"]
            else:
                inv = self._invite_row(db, flow["invite"])
                used = db.execute(
                    "UPDATE invite SET uses = uses + 1 "
                    "WHERE token_hash=? AND uses < max_uses AND expires >= ?",
                    (_h(flow["invite"] or ""), time.time()),
                ).rowcount
                if not inv or used != 1:
                    raise AuthError("este convite não vale mais; peça um novo")
                self._check_name_free(db, flow["name"])
                first = db.execute("SELECT 1 FROM account LIMIT 1").fetchone() is None
                account_id = db.execute(
                    "INSERT INTO account(name, handle, is_admin) VALUES (?,?,?)",
                    (flow["name"], flow["handle"], int(first or inv["admin"])),
                ).lastrowid
            db.execute(
                "INSERT INTO passkey(id, account, public_key, sign_count, transports) "
                "VALUES (?,?,?,?,?)",
                (cred_id, account_id, v.credential_public_key, v.sign_count, transports),
            )
            row = db.execute("SELECT * FROM account WHERE id=?", (account_id,)).fetchone()
        return dict(row)

    # ---- login with a discoverable passkey ------------------------------------------------

    def login_options(self) -> dict:
        options = generate_authentication_options(
            rp_id=self.rp_id, user_verification=UserVerificationRequirement.REQUIRED
        )
        fid = self._new_flow(kind="login", challenge=options.challenge)
        return {"flow": fid, "options": json.loads(options_to_json(options))}

    def login_verify(self, fid: str, credential: dict) -> dict:
        flow = self._take_flow(fid, "login")
        _check_credential(credential)
        cred_id = str(credential.get("id") or credential.get("rawId") or "")
        with self.store.db() as db:
            pk = db.execute(
                "SELECT p.*, a.disabled FROM passkey p JOIN account a ON a.id=p.account "
                "WHERE p.id=?",
                (cred_id,),
            ).fetchone()
            if not pk:
                raise AuthError("esta passkey não está cadastrada aqui")
            if pk["disabled"]:
                raise AuthError("esta conta foi desativada")
            try:
                v = verify_authentication_response(
                    credential=credential,
                    expected_challenge=flow["challenge"],
                    expected_rp_id=self.rp_id,
                    expected_origin=self.origins,
                    credential_public_key=pk["public_key"],
                    credential_current_sign_count=pk["sign_count"],
                    require_user_verification=True,
                )
            except Exception as e:
                raise AuthError(f"passkey não aceita: {e}") from e
            db.execute(
                "UPDATE passkey SET sign_count=?, last_used=datetime('now') WHERE id=?",
                (v.new_sign_count, cred_id),
            )
            row = db.execute("SELECT * FROM account WHERE id=?", (pk["account"],)).fetchone()
        return dict(row)

    # ---- admin ----------------------------------------------------------------------------

    def set_member(self, account_id: int, *, disabled=None, is_admin=None, by: int | None):
        if any(v is not None and not isinstance(v, bool) for v in (disabled, is_admin)):
            raise AuthError("valor inválido")
        with self.store.db() as db:
            row = db.execute("SELECT * FROM account WHERE id=?", (account_id,)).fetchone()
            if not row:
                raise AuthError("conta não encontrada")
            if account_id == by and (disabled or is_admin is False):
                raise AuthError("você não pode desativar nem rebaixar a si mesmo")
            if disabled is not None and disabled != bool(row["disabled"]):
                # disabling ends every session, and re-enabling doesn't bring old ones back
                db.execute(
                    "UPDATE account SET disabled=?, session_gen = session_gen + 1 WHERE id=?",
                    (int(disabled), account_id),
                )
            if is_admin is not None:
                db.execute("UPDATE account SET is_admin=? WHERE id=?", (int(is_admin), account_id))
            admins = db.execute(
                "SELECT COUNT(*) FROM account WHERE is_admin AND NOT disabled"
            ).fetchone()[0]
            if not admins:  # raising rolls the change back
                raise AuthError("a equipe precisa de pelo menos um administrador ativo")

    @staticmethod
    def _check_name_free(db, name: str, account_id: int | None = None) -> None:
        """Two people can't look the same on the timeline."""
        for other, taken in db.execute("SELECT id, name FROM account"):
            if other != account_id and _fold(taken) == _fold(name):
                raise AuthError("já tem alguém da equipe com esse nome; use outro")

    def rename(self, account_id: int, name: str) -> None:
        name = clean_name(name)
        if not name:
            raise AuthError("digite seu nome")
        with self.store.db() as db:
            self._check_name_free(db, name, account_id)
            db.execute("UPDATE account SET name=? WHERE id=?", (name, account_id))

    def set_email(self, account_id: int, email: str) -> None:
        """Optional; only used to show the person's Gravatar picture."""
        email = str(email or "").strip()
        if email and (len(email) > 254 or not EMAIL.fullmatch(email)):
            raise AuthError("esse e-mail não parece válido")
        with self.store.db() as db:
            if (
                email
                and db.execute(
                    "SELECT 1 FROM account WHERE id<>? AND lower(trim(email))=?",
                    (account_id, email.lower()),
                ).fetchone()
            ):
                raise AuthError("esse e-mail já é de outra pessoa da equipe")
            db.execute("UPDATE account SET email=? WHERE id=?", (email, account_id))


def _check_credential(credential) -> None:
    if not isinstance(credential, dict):
        raise AuthError("passkey não aceita: resposta inválida")
