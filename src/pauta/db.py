"""The data: clients, requests (pedidos) and their history, in one SQLite file.

A request carries both halves of the old spreadsheet on one row: the briefing whoever asked
filled in (client, what, goal, audience, budget, due date...) and the execution whoever runs
it fills in (status, what's missing, done date, campaign link). Nothing is linked by row
position any more, so sorting, filtering and deleting are safe.

Every change to a request leaves an `event` (created, status, edited, comment, file,
unfile): that is the timeline on the request page. A request's files live in OneDrive
(`onedrive.py`); the `file` table only keeps their ids and names.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from . import finance

SCHEMA_VERSION = 7

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, handle TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL DEFAULT '', is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0, session_gen INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS passkey (
    id TEXT PRIMARY KEY, account INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    public_key BLOB NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT,
    created TEXT NOT NULL DEFAULT (datetime('now')), last_used TEXT,
    rp_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS invite (
    token_hash TEXT PRIMARY KEY, admin INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL,
    created_by INTEGER, created TEXT NOT NULL DEFAULT (datetime('now')),
    account INTEGER REFERENCES account(id)
);
CREATE TABLE IF NOT EXISTS client (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '', whatsapp TEXT NOT NULL DEFAULT '',
    instagram TEXT NOT NULL DEFAULT '', ad_account TEXT NOT NULL DEFAULT '',
    access TEXT NOT NULL DEFAULT 'Pendente', drive_url TEXT NOT NULL DEFAULT '',
    ads_page TEXT NOT NULL DEFAULT '',
    since TEXT, state TEXT NOT NULL DEFAULT 'Ativo', notes TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT (datetime('now')),
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS client_name ON client(name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS request (
    id INTEGER PRIMARY KEY, client INTEGER NOT NULL REFERENCES client(id),
    kind TEXT NOT NULL DEFAULT '', what TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT '', region TEXT NOT NULL DEFAULT '', budget REAL,
    balance TEXT NOT NULL DEFAULT '', creatives_url TEXT NOT NULL DEFAULT '', due TEXT,
    priority TEXT NOT NULL DEFAULT 'Média', status TEXT NOT NULL DEFAULT 'todo',
    missing TEXT NOT NULL DEFAULT '', done_on TEXT, campaign_url TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '', assignee INTEGER REFERENCES account(id),
    created_by INTEGER REFERENCES account(id),
    created TEXT NOT NULL DEFAULT (datetime('now')),
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS request_client ON request(client);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY, request INTEGER NOT NULL REFERENCES request(id) ON DELETE CASCADE,
    account INTEGER REFERENCES account(id), at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL, text TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS event_request ON event(request);
CREATE TABLE IF NOT EXISTS file (
    id INTEGER PRIMARY KEY, request INTEGER NOT NULL REFERENCES request(id) ON DELETE CASCADE,
    item TEXT NOT NULL, folder TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0, mime TEXT NOT NULL DEFAULT '',
    account INTEGER REFERENCES account(id),
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS file_request ON file(request);
CREATE TABLE IF NOT EXISTS option (
    list TEXT NOT NULL, value TEXT NOT NULL, pos INTEGER NOT NULL, PRIMARY KEY (list, value)
);
CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS billing (
    id INTEGER PRIMARY KEY, client INTEGER NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    cents INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'BRL',
    started TEXT, ended TEXT,
    created_by INTEGER REFERENCES account(id),
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS billing_client ON billing(client, ended);
CREATE TABLE IF NOT EXISTS payment (
    id INTEGER PRIMARY KEY, client INTEGER NOT NULL REFERENCES client(id) ON DELETE CASCADE,
    billing INTEGER REFERENCES billing(id) ON DELETE SET NULL,
    paid_on TEXT NOT NULL, cents INTEGER NOT NULL,
    method TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    recorded_by INTEGER REFERENCES account(id),
    created TEXT NOT NULL DEFAULT (datetime('now')),
    voided_by INTEGER REFERENCES account(id), voided_at TEXT
);
CREATE INDEX IF NOT EXISTS payment_client ON payment(client, paid_on);
"""

# Fixed choices (the app's logic depends on them). Status keys are stable; labels are UI.
STATUSES = {
    "todo": "A fazer",
    "doing": "Em andamento",
    "waiting": "Aguardando",
    "done": "Concluído",
    "cancelled": "Cancelado",
}
OPEN_STATUSES = ("todo", "doing", "waiting")
PRIORITIES = ("Alta", "Média", "Baixa")
BALANCES = ("Tem saldo", "Saldo baixo", "Sem saldo")
ACCESS = ("Liberado", "Solicitado", "Pendente")
CLIENT_STATES = ("Ativo", "Pausado", "Encerrado")

# Editable lists (the team's own vocabulary), seeded from the spreadsheet's "Listas" tab.
DEFAULT_OPTIONS = {
    "kind": [
        "Criar campanha",
        "Novos criativos",
        "Ajustar verba",
        "Ajustar público",
        "Pausar campanha",
        "Reativar campanha",
        "Relatório",
        "Outro",
    ],
    "goal": [
        "Mensagens no WhatsApp",
        "Mensagens no Direct",
        "Cadastros (formulário)",
        "Vendas no site",
        "Tráfego para o site",
        "Visitas ao perfil",
        "Reconhecimento da marca",
        "Engajamento",
    ],
    "segment": [
        "Estética",
        "Saúde",
        "Alimentação",
        "Varejo",
        "Serviços",
        "Educação",
        "Imobiliário",
        "Outro",
    ],
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_OPTION = 60


class Invalid(ValueError):
    """A field the user should fix; the message says which and why (in Portuguese)."""


class NotFound(LookupError):
    pass


# ---- field checks ------------------------------------------------------------------------

# control characters, and the bidi overrides/isolates that make text display out of order;
# _long keeps tabs and newlines
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
# links that run code if anything ever renders them as a link
DANGEROUS_SCHEME = re.compile(r"^(javascript|vbscript|data|file):", re.I)
MAX_ID = 2**31 - 1


def _text(limit):
    def check(v, _db):
        return " ".join(CONTROL.sub("", str(v or "")).split())[:limit]

    return check


def _long(limit):
    def check(v, _db):
        return CONTROL.sub("", str(v or "").replace("\r\n", "\n")).strip()[:limit]

    return check


def _not_a_script(limit):
    """Free text that is usually a link: anything goes except a link that would run code."""
    text = _text(limit)

    def check(v, db):
        v = text(v, db)
        if DANGEROUS_SCHEME.match(re.sub(r"\s", "", v)):
            raise Invalid("esse link não é aceito; use um link https://")
        return v

    return check


def _id(v) -> int | None:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n <= MAX_ID else None


def _url(v, _db):
    v = str(v or "").strip()[:500]
    if v and not re.match(r"^https?://", v, re.I):
        if "." in v and " " not in v:
            v = "https://" + v
        else:
            raise Invalid("o link precisa começar com https://")
    return v


def _date(v, _db):
    v = str(v or "").strip()
    if not v:
        return None
    if not DATE_RE.match(v):
        raise Invalid(f"data inválida: {v}")
    try:
        date.fromisoformat(v)
    except ValueError:
        raise Invalid(f"data inválida: {v}") from None
    return v


def _money(v, _db):
    if v in (None, ""):
        return None
    if isinstance(v, str):
        v = v.replace("R$", "").strip()
        if "," in v:  # 1.500,50 -> 1500.50
            v = v.replace(".", "").replace(",", ".")
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError):
        raise Invalid("verba precisa ser um número") from None
    if n < 0 or n > 100_000_000:
        raise Invalid("verba fora do intervalo")
    return n


def _cents(v, db):
    """Money for the ledger: the same input as `_money`, stored as integer cents."""
    n = _money(v, db)
    if n is None:
        raise Invalid("informe o valor")
    return round(n * 100)


def _int_range(lo, hi, label):
    def check(v, _db):
        try:
            n = int(v)
        except (TypeError, ValueError):
            raise Invalid(f"{label} precisa ser um número") from None
        if not lo <= n <= hi:
            raise Invalid(f"{label} fora do intervalo ({lo} a {hi})")
        return n

    return check


def _bool(v, _db):
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "sim", "yes", "on")
    return bool(v)


def _choice(options, blank=False):
    def check(v, _db):
        v = str(v or "").strip()
        if blank and not v:
            return ""
        if v not in options:
            raise Invalid(f"valor inválido: {v or '(vazio)'}")
        return v

    return check


def _client(v, db):
    cid = _id(v)
    if cid is None:
        raise Invalid("escolha um cliente")
    if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
        raise Invalid("cliente não encontrado")
    return cid


def _account(v, db):
    if v in (None, "", 0):
        return None
    aid = _id(v)
    if aid is None:
        raise Invalid("responsável inválido")
    if not db.execute("SELECT 1 FROM account WHERE id=? AND NOT disabled", (aid,)).fetchone():
        raise Invalid("responsável não encontrado")
    return aid


CLIENT_FIELDS = {
    "name": _text(80),
    "segment": _text(MAX_OPTION),
    "contact": _text(80),
    "whatsapp": _text(40),
    "instagram": _not_a_script(120),
    "ad_account": _text(60),
    "access": _choice(ACCESS),
    "drive_url": _url,
    "ads_page": _not_a_script(500),
    "since": _date,
    "state": _choice(CLIENT_STATES),
    "notes": _long(4000),
    "billed": _bool,
}

# Equipe → Financeiro (decision 7); the defaults are in finance.DEFAULTS
FINANCE_FIELDS = {
    "enabled": _bool,
    "currency": _choice(finance.CURRENCIES),
    "amount": _money,
    "cadence": _choice(finance.CADENCES),
    "anchor": _choice(finance.ANCHORS),
    "fixed_day": _int_range(1, 28, "o dia fixo"),
    "due_soon_days": _int_range(0, 60, "o aviso de vencimento"),
    "grace_days": _int_range(0, 60, "a tolerância"),
    "visibility": _choice(finance.VISIBILITIES),
    "bill_new_clients": _bool,
}

PAYMENT_FIELDS = {
    "paid_on": _date,
    "amount": _cents,
    "method": _text(30),
    "note": _text(200),
}

REQUEST_FIELDS = {
    "client": _client,
    "kind": _text(MAX_OPTION),
    "what": _long(4000),
    "goal": _text(MAX_OPTION),
    "audience": _long(1000),
    "region": _text(200),
    "budget": _money,
    "balance": _choice(BALANCES, blank=True),
    "creatives_url": _url,
    "due": _date,
    "priority": _choice(PRIORITIES),
    "status": _choice(tuple(STATUSES)),
    "missing": _long(2000),
    "done_on": _date,
    "campaign_url": _url,
    "notes": _long(4000),
    "assignee": _account,
}

# what the timeline calls each field when it was edited
LABELS = {
    "client": "cliente",
    "kind": "tipo",
    "what": "o que fazer",
    "goal": "objetivo",
    "audience": "público",
    "region": "região",
    "budget": "verba",
    "balance": "saldo",
    "creatives_url": "criativos",
    "due": "prazo",
    "priority": "prioridade",
    "missing": "o que falta",
    "done_on": "concluído em",
    "campaign_url": "link da campanha",
    "notes": "observações",
    "assignee": "responsável",
}


def clean(spec: dict, data: dict, db: sqlite3.Connection, partial: bool) -> dict:
    if not isinstance(data, dict):
        raise Invalid("dados inválidos")
    out = {}
    for key, check in spec.items():
        if key in data:
            out[key] = check(data[key], db)
        elif not partial and key in ("client",):
            out[key] = check(None, db)
    return out


def gravatar(email: str | None) -> str:
    """Gravatar's id for an address (SHA-256 of the trimmed, lowercased email), or ''."""
    email = (email or "").strip().lower()
    return hashlib.sha256(email.encode()).hexdigest() if email else ""


# ---- the store ---------------------------------------------------------------------------


class Store:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript(SCHEMA)
            # v2: optional email per account, only used for the Gravatar picture
            cols = {r[1] for r in db.execute("PRAGMA table_info(account)")}
            if "email" not in cols:
                db.execute("ALTER TABLE account ADD COLUMN email TEXT NOT NULL DEFAULT ''")
            # v4: bumped to end every session of an account (logout, disable, enable)
            if "session_gen" not in cols:
                db.execute("ALTER TABLE account ADD COLUMN session_gen INTEGER NOT NULL DEFAULT 0")
            # v7: the domain a passkey belongs to (decision 4's move); '' until it's next used
            cols = {r[1] for r in db.execute("PRAGMA table_info(passkey)")}
            if "rp_id" not in cols:
                db.execute("ALTER TABLE passkey ADD COLUMN rp_id TEXT NOT NULL DEFAULT ''")
            # v7: an invite with an account is a move link: a passkey for that existing account
            cols = {r[1] for r in db.execute("PRAGMA table_info(invite)")}
            if "account" not in cols:
                db.execute("ALTER TABLE invite ADD COLUMN account INTEGER REFERENCES account(id)")
            # v3: the client's ads page (free text: usually a Meta Ad Library or page link)
            cols = {r[1] for r in db.execute("PRAGMA table_info(client)")}
            if "ads_page" not in cols:
                db.execute("ALTER TABLE client ADD COLUMN ads_page TEXT NOT NULL DEFAULT ''")
            # v6: the ledger (decision 7); every Ativo client starts billed, with an open cycle
            if "billed" not in cols:
                db.execute("ALTER TABLE client ADD COLUMN billed INTEGER NOT NULL DEFAULT 1")
            for row in db.execute("SELECT id FROM client WHERE state='Ativo' AND billed"):
                self._open_cycle(db, row[0], None)
            db.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema', ?)",
                (str(SCHEMA_VERSION),),
            )
            if not db.execute("SELECT 1 FROM option LIMIT 1").fetchone():
                for lst, values in DEFAULT_OPTIONS.items():
                    db.executemany(
                        "INSERT INTO option(list, value, pos) VALUES (?,?,?)",
                        [(lst, v, i) for i, v in enumerate(values)],
                    )

    @contextlib.contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        try:
            with conn:  # commit on success, roll back on error
                yield conn
        finally:
            conn.close()

    # ---- options and people ---------------------------------------------------------------

    def options(self) -> dict:
        with self.db() as db:
            rows = db.execute("SELECT list, value FROM option ORDER BY list, pos").fetchall()
        out = {k: [] for k in DEFAULT_OPTIONS}
        for r in rows:
            out.setdefault(r["list"], []).append(r["value"])
        return {
            **out,
            "status": STATUSES,
            "priority": list(PRIORITIES),
            "balance": list(BALANCES),
            "access": list(ACCESS),
            "state": list(CLIENT_STATES),
        }

    def set_options(self, lst: str, values: list) -> list[str]:
        if lst not in DEFAULT_OPTIONS:
            raise Invalid("lista desconhecida")
        if not isinstance(values, list):
            raise Invalid("valores inválidos")
        clean_values: list[str] = []
        for v in values:
            v = " ".join(str(v or "").split())[:MAX_OPTION]
            if v and v.casefold() not in {x.casefold() for x in clean_values}:
                clean_values.append(v)
        if not clean_values:
            raise Invalid("a lista precisa de pelo menos um item")
        with self.db() as db:
            db.execute("DELETE FROM option WHERE list=?", (lst,))
            db.executemany(
                "INSERT INTO option(list, value, pos) VALUES (?,?,?)",
                [(lst, v, i) for i, v in enumerate(clean_values[:50])],
            )
        return clean_values[:50]

    def members(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT a.id, a.name, a.email, a.is_admin, a.disabled, a.created, "
                "(SELECT COUNT(*) FROM passkey p WHERE p.account=a.id) AS passkeys, "
                "(SELECT MAX(last_used) FROM passkey p WHERE p.account=a.id) AS last_seen, "
                "(SELECT group_concat(DISTINCT p.rp_id) FROM passkey p "
                "WHERE p.account=a.id AND p.rp_id<>'') AS domains "
                "FROM account a ORDER BY a.disabled, a.id"
            ).fetchall()
        # the address itself stays private; teammates only get the Gravatar hash
        out = []
        for r in map(dict, rows):
            r["avatar"] = gravatar(r.pop("email"))
            r["domains"] = sorted((r["domains"] or "").split(",")) if r["domains"] else []
            out.append(r)
        return out

    # ---- clients ----------------------------------------------------------------------------

    def clients(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT c.*, "
                "(SELECT COUNT(*) FROM request r WHERE r.client=c.id "
                f" AND r.status IN {OPEN_STATUSES}) AS open_requests, "
                "(SELECT COUNT(*) FROM request r WHERE r.client=c.id) AS total_requests, "
                "(SELECT MAX(created) FROM request r WHERE r.client=c.id) AS last_request "
                "FROM client c ORDER BY c.state='Encerrado', c.name COLLATE NOCASE"
            ).fetchall()
        return [dict(r) for r in rows]

    def client(self, cid: int) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM client WHERE id=?", (cid,)).fetchone()
            if not row:
                raise NotFound("cliente não encontrado")
            reqs = self._requests(db, "WHERE r.client=?", (cid,))
            billing = self._billing(db, dict(row))
            payments = self._payments(db, cid)
        return {**dict(row), "requests": reqs, "billing": billing, "payments": payments}

    def save_client(self, data: dict, cid: int | None = None, by: int | None = None) -> dict:
        with self.db() as db:
            cid_was_new = cid is None
            vals = clean(CLIENT_FIELDS, data, db, partial=cid is not None)
            if cid is None or "name" in vals:
                if not vals.get("name"):
                    raise Invalid("o cliente precisa de um nome")
                clash = db.execute(
                    "SELECT id FROM client WHERE name=? COLLATE NOCASE AND id IS NOT ?",
                    (vals["name"], cid),
                ).fetchone()
                if clash:
                    raise Invalid("já existe um cliente com esse nome")
            if cid is None:
                vals.setdefault("billed", self._settings(db)["bill_new_clients"])
                cols = ", ".join(vals)
                marks = ", ".join("?" for _ in vals)
                cid = db.execute(
                    f"INSERT INTO client({cols}) VALUES ({marks})", tuple(vals.values())
                ).lastrowid
            else:
                if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
                    raise NotFound("cliente não encontrado")
                if vals:
                    sets = ", ".join(f"{k}=?" for k in vals)
                    db.execute(
                        f"UPDATE client SET {sets}, updated=datetime('now') WHERE id=?",
                        (*vals.values(), cid),
                    )
            if cid_was_new or "state" in vals or "billed" in vals:
                self._sync_cycle(db, cid, by)
        return self.client(cid)

    def delete_client(self, cid: int, with_requests: bool = False) -> int:
        """Delete a client. One with requests is only deleted together with them (and their
        timelines) when asked to; returns how many requests went with it."""
        with self.db() as db:
            if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
                raise NotFound("cliente não encontrado")
            n = db.execute("SELECT COUNT(*) FROM request WHERE client=?", (cid,)).fetchone()[0]
            if n and not with_requests:
                raise Invalid("este cliente tem pedidos; marque-o como Encerrado")
            db.execute("DELETE FROM request WHERE client=?", (cid,))  # events cascade
            db.execute("DELETE FROM client WHERE id=?", (cid,))
        return n

    # ---- finance (decision 7) ---------------------------------------------------------------

    @staticmethod
    def _settings(db) -> dict:
        row = db.execute("SELECT value FROM setting WHERE key='finance'").fetchone()
        saved = json.loads(row[0]) if row else {}
        return {**finance.DEFAULTS, **{k: v for k, v in saved.items() if k in finance.DEFAULTS}}

    def finance_settings(self) -> dict:
        with self.db() as db:
            return self._settings(db)

    def set_finance_settings(self, data: dict) -> dict:
        with self.db() as db:
            vals = clean(FINANCE_FIELDS, data, db, partial=True)
            if "amount" in vals and vals["amount"] is None:
                raise Invalid("informe o valor padrão")
            merged = {**self._settings(db), **vals}
            db.execute(
                "INSERT OR REPLACE INTO setting(key, value) VALUES ('finance', ?)",
                (json.dumps(merged),),
            )
            return merged

    @staticmethod
    def _open_cycle(db, cid: int, by: int | None) -> None:
        """One open cycle per client: a no-op when there is one already."""
        if db.execute("SELECT 1 FROM billing WHERE client=? AND ended IS NULL", (cid,)).fetchone():
            return
        settings = Store._settings(db)
        db.execute(
            "INSERT INTO billing(client, cents, currency, created_by) VALUES (?,?,?,?)",
            (cid, round(float(settings["amount"]) * 100), settings["currency"], by),
        )

    @staticmethod
    def _close_cycle(db, cid: int) -> None:
        db.execute("UPDATE billing SET ended=date('now') WHERE client=? AND ended IS NULL", (cid,))

    def _sync_cycle(self, db, cid: int, by: int | None) -> None:
        """Ativo and billed means an open cycle; anything else closes it. Coming back opens a
        new one, so the month count and the day restart (decision 7)."""
        row = db.execute("SELECT state, billed FROM client WHERE id=?", (cid,)).fetchone()
        if row["state"] == "Ativo" and row["billed"]:
            self._open_cycle(db, cid, by)
        else:
            self._close_cycle(db, cid)

    @staticmethod
    def _cycle_payments(db, bid: int) -> list[tuple[date, int]]:
        rows = db.execute(
            "SELECT paid_on, cents FROM payment WHERE billing=? AND voided_at IS NULL "
            "ORDER BY paid_on, id",
            (bid,),
        ).fetchall()
        return [(date.fromisoformat(r["paid_on"]), r["cents"]) for r in rows]

    def _billing(self, db, client: dict, today: date | None = None) -> dict | None:
        """The client's open cycle and where it stands, or None when not billed/not Ativo."""
        cycle = db.execute(
            "SELECT * FROM billing WHERE client=? AND ended IS NULL", (client["id"],)
        ).fetchone()
        if not cycle:
            return None
        settings = self._settings(db)
        payments = self._cycle_payments(db, cycle["id"])
        anchor = finance.resolve_anchor(
            settings,
            first_payment=payments[0][0] if payments else None,
            since=date.fromisoformat(client["since"]) if client.get("since") else None,
            opened=date.fromisoformat(cycle["created"][:10]),
            started=date.fromisoformat(cycle["started"]) if cycle["started"] else None,
        )
        st = finance.standing(
            settings,
            cents=cycle["cents"],
            anchor=anchor,
            payments=payments,
            today=today or date.today(),
        )
        return {
            "id": cycle["id"],
            "amount": cycle["cents"] / 100,
            "currency": cycle["currency"],
            "opened": cycle["created"][:10],
            **st.as_dict(),
        }

    @staticmethod
    def _payments(db, cid: int) -> list[dict]:
        rows = db.execute(
            "SELECT p.id, p.billing, p.paid_on, p.cents, p.method, p.note, p.recorded_by, "
            "p.created, p.voided_by, p.voided_at, a.name AS recorded_by_name, "
            "v.name AS voided_by_name FROM payment p "
            "LEFT JOIN account a ON a.id=p.recorded_by LEFT JOIN account v ON v.id=p.voided_by "
            "WHERE p.client=? ORDER BY p.paid_on DESC, p.id DESC",
            (cid,),
        ).fetchall()
        out = []
        for r in map(dict, rows):
            r["amount"] = r.pop("cents") / 100
            out.append(r)
        return out

    def set_billing(self, cid: int, data: dict, by: int | None) -> dict:
        """The client's fee (on its open cycle) and whether it is billed at all."""
        with self.db() as db:
            if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
                raise NotFound("cliente não encontrado")
            if "billed" in data:
                db.execute(
                    "UPDATE client SET billed=?, updated=datetime('now') WHERE id=?",
                    (_bool(data["billed"], db), cid),
                )
                self._sync_cycle(db, cid, by)
            if "amount" in data:
                cents = _cents(data["amount"], db)
                if cents <= 0:
                    raise Invalid("o valor precisa ser maior que zero")
                db.execute(
                    "UPDATE billing SET cents=? WHERE client=? AND ended IS NULL", (cents, cid)
                )
        return self.client(cid)

    def add_payment(self, cid: int, data: dict, by: int | None) -> dict:
        with self.db() as db:
            if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
                raise NotFound("cliente não encontrado")
            vals = clean(PAYMENT_FIELDS, data, db, partial=False)
            if not vals.get("paid_on"):
                raise Invalid("informe a data do pagamento")
            if "amount" not in vals:
                raise Invalid("informe o valor")
            if vals["amount"] <= 0:
                raise Invalid("o valor precisa ser maior que zero")
            if vals["paid_on"] > (date.today() + timedelta(days=1)).isoformat():
                raise Invalid("a data do pagamento não pode estar no futuro")
            cycle = db.execute(
                "SELECT id FROM billing WHERE client=? AND ended IS NULL", (cid,)
            ).fetchone()
            db.execute(
                "INSERT INTO payment(client, billing, paid_on, cents, method, note, recorded_by) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    cid,
                    cycle["id"] if cycle else None,
                    vals["paid_on"],
                    vals["amount"],
                    vals.get("method", ""),
                    vals.get("note", ""),
                    by,
                ),
            )
        return self.client(cid)

    def void_payment(self, pid: int, by: int | None, admin: bool) -> dict:
        """Payments are never deleted: whoever recorded one, or an admin, voids it."""
        with self.db() as db:
            row = db.execute("SELECT * FROM payment WHERE id=?", (pid,)).fetchone()
            if not row:
                raise NotFound("pagamento não encontrado")
            if row["voided_at"]:
                raise Invalid("esse pagamento já foi anulado")
            if not admin and (by is None or row["recorded_by"] != by):
                raise Invalid("só quem registrou o pagamento, ou um administrador, pode anular")
            db.execute(
                "UPDATE payment SET voided_by=?, voided_at=datetime('now') WHERE id=?", (by, pid)
            )
            cid = row["client"]
        return self.client(cid)

    def finance(self, today: date | None = None, month: str | None = None) -> dict:
        """The panel: every Ativo, billed client and where it stands, plus what came in each
        month and the payments of `month` (default: this one)."""
        today = today or date.today()
        if month is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise Invalid("mês inválido, use AAAA-MM")
        this_month = today.strftime("%Y-%m")
        month = month or this_month
        with self.db() as db:
            clients = db.execute(
                "SELECT * FROM client WHERE state='Ativo' AND billed ORDER BY name COLLATE NOCASE"
            ).fetchall()
            rows = []
            for c in map(dict, clients):
                b = self._billing(db, c, today)
                if not b:
                    continue
                last = db.execute(
                    "SELECT paid_on, cents FROM payment WHERE client=? AND voided_at IS NULL "
                    "ORDER BY paid_on DESC, id DESC LIMIT 1",
                    (c["id"],),
                ).fetchone()
                # the row's `id` is the client's; the cycle's goes under `billing` (1.5.1: the
                # cycle's id used to win the merge, so Registrar posted to the wrong client)
                rows.append(
                    {
                        **b,
                        "billing": b["id"],
                        "id": c["id"],
                        "name": c["name"],
                        "segment": c["segment"],
                        "since": c["since"],
                        "last_payment": (
                            {"paid_on": last["paid_on"], "amount": last["cents"] / 100}
                            if last
                            else None
                        ),
                    }
                )
            # every month with a live payment, newest first; this month and the asked one
            # are always there so the picker has something to land on
            months = {
                r["m"]: {"month": r["m"], "received": r["cents"] / 100, "payments": r["n"]}
                for r in db.execute(
                    "SELECT substr(paid_on, 1, 7) AS m, SUM(cents) AS cents, COUNT(*) AS n "
                    "FROM payment WHERE voided_at IS NULL GROUP BY m"
                ).fetchall()
            }
            for m in (this_month, month):
                months.setdefault(m, {"month": m, "received": 0, "payments": 0})
            payments = [
                {**dict(r), "amount": r["cents"] / 100}
                for r in db.execute(
                    "SELECT p.id, p.client, c.name, p.paid_on, p.cents, p.method, p.note "
                    "FROM payment p JOIN client c ON c.id=p.client "
                    "WHERE p.voided_at IS NULL AND substr(p.paid_on, 1, 7)=? "
                    "ORDER BY p.paid_on DESC, p.id DESC",
                    (month,),
                ).fetchall()
            ]
            for p in payments:
                del p["cents"]
            received_total = db.execute(
                "SELECT COALESCE(SUM(cents), 0) FROM payment WHERE voided_at IS NULL"
            ).fetchone()[0]
            settings = self._settings(db)
        order = {s: i for i, s in enumerate(finance.STATUSES)}
        rows.sort(key=lambda r: (order[r["status"]], r["next_due"] or "", r["name"].casefold()))
        return {
            "today": today.isoformat(),
            "month": month,
            "currency": settings["currency"],
            "cadence": settings["cadence"],
            "received_month": months[month]["received"],
            "received_total": received_total / 100,
            "months": sorted(months.values(), key=lambda m: m["month"], reverse=True),
            "payments": payments,
            "owed": sum(r["owed"] for r in rows),
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in finance.STATUSES},
            "clients": rows,
        }

    # ---- requests ---------------------------------------------------------------------------

    @staticmethod
    def _requests(db, where: str = "", args: tuple = ()) -> list[dict]:
        rows = db.execute(
            "SELECT r.*, c.name AS client_name, c.state AS client_state, "
            "cb.name AS created_by_name, asg.name AS assignee_name, "
            "(SELECT COUNT(*) FROM event e WHERE e.request=r.id AND e.kind='comment') "
            "  AS comments, "
            "(SELECT COUNT(*) FROM file f WHERE f.request=r.id) AS files "
            "FROM request r JOIN client c ON c.id=r.client "
            "LEFT JOIN account cb ON cb.id=r.created_by "
            "LEFT JOIN account asg ON asg.id=r.assignee "
            f"{where} ORDER BY r.id DESC",
            args,
        ).fetchall()
        return [dict(r) for r in rows]

    def requests(self) -> list[dict]:
        with self.db() as db:
            return self._requests(db)

    def request(self, rid: int) -> dict:
        with self.db() as db:
            reqs = self._requests(db, "WHERE r.id=?", (rid,))
            if not reqs:
                raise NotFound("pedido não encontrado")
            client = db.execute("SELECT * FROM client WHERE id=?", (reqs[0]["client"],))
            events = db.execute(
                "SELECT e.*, a.name AS account_name FROM event e "
                "LEFT JOIN account a ON a.id=e.account WHERE e.request=? ORDER BY e.id",
                (rid,),
            ).fetchall()
            files = db.execute(
                "SELECT f.id, f.name, f.size, f.mime, f.account, f.created, "
                "a.name AS account_name FROM file f LEFT JOIN account a ON a.id=f.account "
                "WHERE f.request=? ORDER BY f.id DESC",
                (rid,),
            ).fetchall()
            return {
                **reqs[0],
                "client_info": dict(client.fetchone()),
                "events": [dict(e) for e in events],
                "files": [dict(f) for f in files],
            }

    def create_request(self, data: dict, by: int | None) -> dict:
        with self.db() as db:
            vals = clean(REQUEST_FIELDS, data, db, partial=False)
            if not vals.get("what"):
                raise Invalid("descreva o que precisa ser feito")
            vals.setdefault("status", "todo")
            vals.setdefault("priority", "Média")
            if vals["status"] == "done" and not vals.get("done_on"):
                vals["done_on"] = date.today().isoformat()
            vals["created_by"] = by
            cols = ", ".join(vals)
            marks = ", ".join("?" for _ in vals)
            rid = db.execute(
                f"INSERT INTO request({cols}) VALUES ({marks})", tuple(vals.values())
            ).lastrowid
            db.execute(
                "INSERT INTO event(request, account, kind) VALUES (?,?,'created')", (rid, by)
            )
        return self.request(rid)

    def update_request(self, rid: int, data: dict, by: int | None) -> dict:
        with self.db() as db:
            old = db.execute("SELECT * FROM request WHERE id=?", (rid,)).fetchone()
            if not old:
                raise NotFound("pedido não encontrado")
            vals = clean(REQUEST_FIELDS, data, db, partial=True)
            if "what" in vals and not vals["what"]:
                raise Invalid("descreva o que precisa ser feito")
            changed = {k: v for k, v in vals.items() if old[k] != v}
            if changed.get("status") == "done" and not (changed.get("done_on") or old["done_on"]):
                changed["done_on"] = date.today().isoformat()
            if not changed:
                return self.request(rid)
            sets = ", ".join(f"{k}=?" for k in changed)
            db.execute(
                f"UPDATE request SET {sets}, updated=datetime('now') WHERE id=?",
                (*changed.values(), rid),
            )
            if "status" in changed:
                db.execute(
                    "INSERT INTO event(request, account, kind, text) VALUES (?,?,'status',?)",
                    (rid, by, f"{old['status']}>{changed['status']}"),
                )
            edited = [LABELS[k] for k in changed if k in LABELS and k != "done_on"]
            if edited:
                db.execute(
                    "INSERT INTO event(request, account, kind, text) VALUES (?,?,'edited',?)",
                    (rid, by, ", ".join(edited)),
                )
        return self.request(rid)

    def comment(self, rid: int, text: str, by: int | None) -> dict:
        text = str(text or "").replace("\r\n", "\n").strip()[:4000]
        if not text:
            raise Invalid("escreva algo")
        with self.db() as db:
            if not db.execute("SELECT 1 FROM request WHERE id=?", (rid,)).fetchone():
                raise NotFound("pedido não encontrado")
            db.execute(
                "INSERT INTO event(request, account, kind, text) VALUES (?,?,'comment',?)",
                (rid, by, text),
            )
            db.execute("UPDATE request SET updated=datetime('now') WHERE id=?", (rid,))
        return self.request(rid)

    # ---- files (the bytes are in OneDrive) ---------------------------------------------------

    def file_folder(self, rid: int) -> list[str]:
        """Where a request's files go: <client>/Pedido <id>."""
        with self.db() as db:
            row = db.execute(
                "SELECT c.name FROM request r JOIN client c ON c.id=r.client WHERE r.id=?", (rid,)
            ).fetchone()
        if not row:
            raise NotFound("pedido não encontrado")
        return [row["name"], f"Pedido {rid}"]

    def add_file(self, rid: int, item: dict, by: int | None) -> dict:
        name = _text(200)(item.get("name"), None) or "arquivo"
        with self.db() as db:
            if not db.execute("SELECT 1 FROM request WHERE id=?", (rid,)).fetchone():
                raise NotFound("pedido não encontrado")
            db.execute(
                "INSERT INTO file(request, item, folder, name, size, mime, account) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    rid,
                    str(item["id"]),
                    str(item.get("folder") or ""),
                    name,
                    int(item.get("size") or 0),
                    _text(100)(item.get("mime"), None),
                    by,
                ),
            )
            db.execute(
                "INSERT INTO event(request, account, kind, text) VALUES (?,?,'file',?)",
                (rid, by, name),
            )
            db.execute("UPDATE request SET updated=datetime('now') WHERE id=?", (rid,))
        return self.request(rid)

    def file(self, fid: int) -> dict:
        with self.db() as db:
            row = db.execute("SELECT * FROM file WHERE id=?", (fid,)).fetchone()
        if not row:
            raise NotFound("arquivo não encontrado")
        return dict(row)

    def request_folder(self, rid: int) -> str:
        """The OneDrive id of the request's folder (from its newest file), or ''."""
        with self.db() as db:
            if not db.execute("SELECT 1 FROM request WHERE id=?", (rid,)).fetchone():
                raise NotFound("pedido não encontrado")
            row = db.execute(
                "SELECT folder FROM file WHERE request=? AND folder != '' ORDER BY id DESC",
                (rid,),
            ).fetchone()
        return row["folder"] if row else ""

    def remove_file(self, fid: int, by: int | None) -> dict:
        with self.db() as db:
            row = db.execute("SELECT request, name FROM file WHERE id=?", (fid,)).fetchone()
            if not row:
                raise NotFound("arquivo não encontrado")
            db.execute("DELETE FROM file WHERE id=?", (fid,))
            db.execute(
                "INSERT INTO event(request, account, kind, text) VALUES (?,?,'unfile',?)",
                (row["request"], by, row["name"]),
            )
        return self.request(row["request"])

    def delete_request(self, rid: int) -> None:
        with self.db() as db:
            if not db.execute("DELETE FROM request WHERE id=?", (rid,)).rowcount:
                raise NotFound("pedido não encontrado")

    # ---- backups ----------------------------------------------------------------------------

    def backup(self, dest: Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(self.path)
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
        return dest
