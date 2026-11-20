"""Passkey-only accounts, the same way dominion-archive does them.

There is one team. Nobody signs up: the admin makes an invite (a QR code or a link), the
person types a name and creates a passkey, done. The first account is the admin; an admin
invite makes another admin. Without `PAUTA_AUTH=passkeys` the app runs open (local dev):
one anonymous admin, no login screen.

Moving to a new domain (decision 4): a passkey only works on the domain it was made on, so
during a move both domains are configured, the new one first. Each ceremony uses the domain
its page is on, and on the old one a signed-in person gets a one-time link that lets them make
a passkey for the same account on the new one. An admin can make the same link for someone
else (Configurações → Time, or `pauta move-link`) and send it on WhatsApp: one tap, then Face ID.

Configuration (environment):
  PAUTA_AUTH=passkeys     turn accounts on (unset or `open`: off; any other word stops the app)
  PAUTA_RP_ID             passkey domain(s), comma-separated, the current home first,
                          e.g. pauta.cc,pauta.genic.dev while moving (default: localhost)
  PAUTA_ORIGIN            allowed origin(s), comma-separated, the app's own first, e.g.
                          https://app.pauta.cc. A page may sit on a subdomain of its passkey
                          domain: passkeys made for pauta.cc work on app.pauta.cc
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
from urllib.parse import urlparse

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

from .db import ACCOUNT_FIELDS, NotFound, Store, gravatar

COOKIE = "pauta_session"
SESSION_DAYS = 180
FLOW_SECONDS = 300
RP_NAME = "Pauta"
INVITE_DAYS = 7
MOVE_SECONDS = 600  # the link a signed-in person makes for themselves: tapped right away
MOVE_LINK_DAYS = 3  # the link an admin makes and sends
DEV_ORIGINS = [f"http://localhost:{p}" for p in (8088, 8089)] + ["http://localhost"]


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _host(origin: str | None) -> str:
    return (urlparse(origin or "").hostname or "").lower()


def _under(host: str, rp_id: str) -> bool:
    """WebAuthn's rule: a page may use its own domain or a parent of it as the RP ID."""
    return host == rp_id or host.endswith("." + rp_id)


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
    "whatsapp": "",
    "start": "",
    "avatar": "",
    "is_admin": True,
}
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# the kind of device a passkey was made on, from the browser's User-Agent: its first label
DEVICES = (
    ("iPhone", "iPhone"),
    ("iPad", "iPad"),
    ("Android", "Android"),
    ("Macintosh", "Mac"),
    ("Windows", "Windows"),
    ("CrOS", "Chromebook"),
    ("Linux", "Linux"),
)


def device_label(user_agent: str = "", transports: str = "") -> str:
    """A passkey's first label, for the list on Perfil: the device it was made on when the
    browser says, a phone that answered a QR code, or a security key. The person may rename
    it. "Este aparelho" when nothing better is known."""
    kinds = {t for t in str(transports or "").split(",") if t}
    if kinds and "internal" not in kinds:
        return "Celular (pelo QR)" if "hybrid" in kinds else "Chave de segurança"
    ua = str(user_agent or "")
    return next((name for needle, name in DEVICES if needle in ua), "Este aparelho")


class Auth:
    def __init__(
        self,
        store: Store,
        enabled: bool | None = None,
        rp_id: str | None = None,
        origins: list[str] | None = None,
    ):
        self.store = store
        if enabled is None:
            mode = os.environ.get("PAUTA_AUTH", "")
            if mode not in ("", "open", "passkeys"):  # a typo must not start the app open
                raise RuntimeError(
                    f"PAUTA_AUTH={mode!r} is not a mode: use passkeys, or leave it unset "
                    "(open, for local development)"
                )
            enabled = mode == "passkeys"
        self.enabled = enabled
        ids = rp_id or os.environ.get("PAUTA_RP_ID") or "localhost"
        self.rp_ids = [r.strip().lower() for r in ids.split(",") if r.strip()] or ["localhost"]
        self.rp_id = self.rp_ids[0]  # home: where passkeys are made from now on
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
            # as bytes: a header may carry text that is not ASCII, which str refuses
            if not hmac.compare_digest(sig.encode(), self._sign(f"{aid}|{gen}|{expires}").encode()):
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
        """Sign the account out everywhere: every cookie issued so far stops working, and so
        does any new-passkey link the person made for themselves (one an admin made for them
        is the admin's to keep: `created_by` is the admin)."""
        if account_id is None:
            return
        with self.store.db() as db:
            db.execute("UPDATE account SET session_gen = session_gen + 1 WHERE id=?", (account_id,))
            db.execute(
                "UPDATE invite SET expires=0 WHERE account=? AND created_by=?",
                (account_id, account_id),
            )

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
            "whatsapp": acc["whatsapp"] if acc else "",
            "start": acc["start"] if acc else "",
            "avatar": gravatar(acc["email"]) if acc else "",
            "is_admin": bool(acc and acc["is_admin"]),
        }

    # ---- domains (a move from one to another, decision 4) -----------------------------------

    def rp_for(self, origin: str | None) -> str:
        """The passkey domain for a page at `origin`: the configured one it sits under, else
        home. The browser and the signature check enforce the rest."""
        host = _host(origin)
        return next((r for r in self.rp_ids if _under(host, r)), self.rp_id)

    def _origins_for(self, rp_id: str) -> list[str]:
        return [o for o in self.origins if _under(_host(o), rp_id)] or self.origins

    @property
    def moving(self) -> bool:
        return self.enabled and len(self.rp_ids) > 1

    @property
    def home(self) -> str | None:
        """The app's address on the home domain, e.g. https://app.pauta.cc: the first allowed
        origin under the home passkey domain."""
        return next((o for o in self.origins if _under(_host(o), self.rp_id)), None)

    @property
    def home_host(self) -> str:
        return _host(self.home) or self.rp_id

    def move_hint(self, origin: str | None, account_id: int | None) -> dict | None:
        """What the app shows about a move: where to, whether this page is already there,
        and whether this person already has a passkey there."""
        if not self.moving or not self.home:
            return None
        done = False
        if account_id is not None:
            with self.store.db() as db:
                done = bool(
                    db.execute(
                        "SELECT 1 FROM passkey WHERE account=? AND rp_id=?",
                        (account_id, self.rp_id),
                    ).fetchone()
                )
        return {
            "to": self.home_host,
            "url": self.home,
            "here": self.rp_for(origin) == self.rp_id,
            "done": done,
        }

    def create_move(
        self, account_id: int, seconds: float = MOVE_SECONDS, created_by: int | None = None
    ) -> tuple[str, float]:
        """A one-time link to make a passkey for this account on the home domain: an invite
        bound to the account, so it survives a restart and the CLI can make one too."""
        token = secrets.token_urlsafe(24)
        expires = time.time() + seconds
        with self.store.db() as db:
            if not db.execute(
                "SELECT 1 FROM account WHERE id=? AND NOT disabled", (account_id,)
            ).fetchone():
                raise AuthError("essa pessoa não existe ou está desativada")
            db.execute(
                "INSERT INTO invite(token_hash, admin, max_uses, expires, created_by, account) "
                "VALUES (?,0,1,?,?,?)",
                (_h(token), expires, created_by, account_id),
            )
        return token, expires

    def _move_account(self, token: str) -> dict | None:
        with self.store.db() as db:
            row = db.execute(
                "SELECT a.* FROM invite i JOIN account a ON a.id = i.account "
                "WHERE i.token_hash=? AND i.uses < i.max_uses AND i.expires >= ? "
                "AND NOT a.disabled",
                (_h(str(token or "")), time.time()),
            ).fetchone()
        return dict(row) if row else None

    def move_info(self, token: str) -> dict | None:
        acc = self._move_account(token)
        return {"name": acc["name"], "to": self.home_host} if acc else None

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
        row = db.execute(
            "SELECT * FROM invite WHERE token_hash=? AND account IS NULL", (_h(token or ""),)
        ).fetchone()
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
        self,
        *,
        invite: str | None = None,
        name: str = "",
        account: dict | None = None,
        move: str | None = None,
        rp_id: str | None = None,
    ) -> dict:
        rp_id = rp_id or self.rp_id
        if move is not None:
            account = self._move_account(move)
            if not account:
                raise AuthError("este link de mudança expirou; peça um novo")
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
            rp_id=rp_id,
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
            move=move,
            rp_id=rp_id,
        )
        return {"flow": fid, "options": json.loads(options_to_json(options))}

    def register_verify(self, fid: str, credential: dict, user_agent: str = "") -> dict:
        flow = self._take_flow(fid, "register")
        _check_credential(credential)
        try:
            v = verify_registration_response(
                credential=credential,
                expected_challenge=flow["challenge"],
                expected_rp_id=flow["rp_id"],
                expected_origin=self._origins_for(flow["rp_id"]),
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
            if flow["move"] is not None:
                used = db.execute(  # the link works once
                    "UPDATE invite SET uses = uses + 1 WHERE token_hash=? AND account=? "
                    "AND uses < max_uses AND expires >= ?",
                    (_h(flow["move"]), flow["account"], time.time()),
                ).rowcount
                if used != 1:
                    raise AuthError("este link de mudança expirou; peça um novo")
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
                "INSERT INTO passkey(id, account, public_key, sign_count, transports, rp_id, "
                "label) VALUES (?,?,?,?,?,?,?)",
                (
                    cred_id,
                    account_id,
                    v.credential_public_key,
                    v.sign_count,
                    transports,
                    flow["rp_id"],
                    device_label(user_agent, transports),
                ),
            )
            row = db.execute("SELECT * FROM account WHERE id=?", (account_id,)).fetchone()
        return dict(row)

    # ---- the account's passkeys (Perfil, decision 10) -------------------------------------

    def passkeys(self, account_id: int | None) -> list[dict]:
        """This person's passkeys: label, transports, when made and last used. Never the key."""
        if account_id is None:
            return []
        with self.store.db() as db:
            rows = db.execute(
                "SELECT id, label, transports, rp_id, created, last_used FROM passkey "
                "WHERE account=? ORDER BY created, rowid",
                (account_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def relabel_passkey(self, account_id: int, cred_id: str, label) -> None:
        if not isinstance(label, str):
            raise AuthError("nome inválido")
        with self.store.db() as db:
            done = db.execute(
                "UPDATE passkey SET label=? WHERE id=? AND account=?",
                (clean_name(label), str(cred_id or ""), account_id),
            ).rowcount
        if not done:
            raise NotFound("passkey não encontrada")

    def remove_passkey(self, account_id: int, cred_id: str) -> None:
        """Take a passkey off the account, as long as another one stays: without any, the
        person could never sign in again and nobody else could make them a link. The
        account's sessions end with it (the removed device is usually the point), so the
        caller re-issues the cookie of the device doing the removing. Only a passkey that
        still signs in counts as "another one": a leftover for a domain Pauta left (decision
        4) can't be the one that stays."""
        cred_id = str(cred_id or "")
        with self.store.db() as db:
            db.execute("BEGIN IMMEDIATE")  # two removals at once can't both see "two left"
            mine = {
                r[0]: r[1]
                for r in db.execute("SELECT id, rp_id FROM passkey WHERE account=?", (account_id,))
            }
            if cred_id not in mine:
                raise NotFound("passkey não encontrada")
            usable = [k for k, rp in mine.items() if k != cred_id and (not rp or rp in self.rp_ids)]
            if not usable:
                raise AuthError("essa é a sua única passkey; adicione outra antes de tirar esta")
            db.execute("DELETE FROM passkey WHERE id=? AND account=?", (cred_id, account_id))
            db.execute("UPDATE account SET session_gen = session_gen + 1 WHERE id=?", (account_id,))
            db.execute(  # as in end_sessions: a link the person made for themselves ends too
                "UPDATE invite SET expires=0 WHERE account=? AND created_by=?",
                (account_id, account_id),
            )

    # ---- login with a discoverable passkey ------------------------------------------------

    def login_options(self, rp_id: str | None = None) -> dict:
        rp_id = rp_id or self.rp_id
        options = generate_authentication_options(
            rp_id=rp_id, user_verification=UserVerificationRequirement.REQUIRED
        )
        fid = self._new_flow(kind="login", challenge=options.challenge, rp_id=rp_id)
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
                    expected_rp_id=flow["rp_id"],
                    expected_origin=self._origins_for(flow["rp_id"]),
                    credential_public_key=pk["public_key"],
                    credential_current_sign_count=pk["sign_count"],
                    require_user_verification=True,
                )
            except Exception as e:
                raise AuthError(f"passkey não aceita: {e}") from e
            # a passkey from before 1.6 learns its domain the first time it's used
            db.execute(
                "UPDATE passkey SET sign_count=?, last_used=datetime('now'), rp_id=? WHERE id=?",
                (v.new_sign_count, flow["rp_id"], cred_id),
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
            if (disabled and not row["disabled"]) or (is_admin is False and row["is_admin"]):
                # the invites and links this account made, and the links made for it, end too
                db.execute(
                    "UPDATE invite SET expires=0 WHERE created_by=? OR account=?",
                    (account_id, account_id),
                )
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

    def set_whatsapp(self, account_id: int, number) -> None:
        """Optional, free text like a client's: only the person sees it (`GET /api/me`)."""
        with self.store.db() as db:
            db.execute(
                "UPDATE account SET whatsapp=? WHERE id=?",
                (ACCOUNT_FIELDS["whatsapp"](number, db), account_id),
            )

    def set_start(self, account_id: int, screen) -> None:
        """The screen the app opens on for this person (one of `STARTS`, '' for the Painel)."""
        with self.store.db() as db:
            db.execute(
                "UPDATE account SET start=? WHERE id=?",
                (ACCOUNT_FIELDS["start"](screen, db), account_id),
            )


def _check_credential(credential) -> None:
    if not isinstance(credential, dict):
        raise AuthError("passkey não aceita: resposta inválida")
