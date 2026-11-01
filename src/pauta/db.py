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
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from . import finance, obs

SCHEMA_VERSION = 10

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
CREATE TABLE IF NOT EXISTS meta_account (
    account_id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'BRL', status INTEGER NOT NULL DEFAULT 0,
    client INTEGER REFERENCES client(id) ON DELETE SET NULL, seen TEXT,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS meta_account_client ON meta_account(client);
CREATE TABLE IF NOT EXISTS campaign (
    id INTEGER PRIMARY KEY, client INTEGER REFERENCES client(id) ON DELETE CASCADE,
    account_id TEXT NOT NULL DEFAULT '', meta_id TEXT UNIQUE,
    name TEXT NOT NULL DEFAULT '', objective TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'active', effective_status TEXT NOT NULL DEFAULT '',
    started TEXT, ended TEXT,
    request INTEGER UNIQUE REFERENCES request(id) ON DELETE SET NULL,
    every_days INTEGER, note TEXT NOT NULL DEFAULT '', last_seen TEXT,
    created_by INTEGER REFERENCES account(id),
    created TEXT NOT NULL DEFAULT (datetime('now')),
    updated TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS campaign_client ON campaign(client);
CREATE INDEX IF NOT EXISTS campaign_account ON campaign(account_id);
CREATE TABLE IF NOT EXISTS review (
    id INTEGER PRIMARY KEY,
    campaign INTEGER NOT NULL REFERENCES campaign(id) ON DELETE CASCADE,
    "on" TEXT NOT NULL, account INTEGER REFERENCES account(id),
    note TEXT NOT NULL DEFAULT '', snapshot TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS review_campaign ON review(campaign);
CREATE TABLE IF NOT EXISTS insight (
    meta_id TEXT NOT NULL, day TEXT NOT NULL,
    spend_cents INTEGER NOT NULL DEFAULT 0, impressions INTEGER NOT NULL DEFAULT 0,
    reach INTEGER NOT NULL DEFAULT 0, link_clicks INTEGER NOT NULL DEFAULT 0,
    actions TEXT NOT NULL DEFAULT '{}', fetched TEXT NOT NULL,
    PRIMARY KEY (meta_id, day)
);
CREATE TABLE IF NOT EXISTS meta_connection (
    business_id TEXT PRIMARY KEY, business_name TEXT NOT NULL DEFAULT '',
    connected_by INTEGER REFERENCES account(id), connected_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'ok', error TEXT NOT NULL DEFAULT '', last_sync TEXT,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS meta_log (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT (datetime('now')),
    account INTEGER REFERENCES account(id), kind TEXT NOT NULL,
    business_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '{}'
);
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
# campaign tracking (decision 8): `skipped` is "Não acompanhar", never touched by the sync
CAMPAIGN_STATES = ("active", "paused", "ended", "skipped")
TRACKED_STATES = ("active", "paused", "ended")
# a done request of one of these kinds is the one a Meta campaign came from (a team setting
# in a later slice)
TRACKING_KINDS = ("Criar campanha", "Reativar campanha")
# the ways an Ads Manager link carries a campaign id
CAMPAIGN_URL_ID = (
    r"selected_campaign_ids=(\d+)",
    r"campaign_id=(\d+)",
    r"/campaigns/(\d+)",
)
EXPORT_TABLES = ("campaign", "review", "insight", "meta_connection", "meta_log")

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


def valid_date(v) -> str | None:
    """A query-string date: `YYYY-MM-DD` or None when blank; Invalid otherwise."""
    return _date(v, None)


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


def digits(value) -> str:
    """An ad account id as Meta's bare digits: "act_123", " 123 " and 123 are all "123"."""
    return "".join(c for c in str(value or "") if c.isdigit())


def campaign_id_in(url: str) -> str | None:
    """The Meta campaign id an Ads Manager link carries (`selected_campaign_ids=`,
    `campaign_id=` or `/campaigns/<id>`), or None."""
    for pat in CAMPAIGN_URL_ID:
        m = re.search(pat, str(url or ""))
        if m:
            return m.group(1)
    return None


def fold(name: str) -> str:
    """A name for loose comparison: no accents, casefolded, only letters, digits and spaces."""
    plain = unicodedata.normalize("NFKD", str(name or ""))
    plain = "".join(c for c in plain if not unicodedata.combining(c)).casefold()
    return " ".join("".join(c if c.isalnum() else " " for c in plain).split())


def suggest(name: str, clients: list) -> int | None:
    """The client an ad account called `name` probably belongs to, or None. Conservative:
    one name contains the other (both at least 4 letters), or they share two words of
    four letters or more. `clients` are (id, name) pairs in the order to prefer."""
    key = fold(name)
    if len(key) < 4:
        return None
    for cid, cname in clients:
        ck = fold(cname)
        if len(ck) >= 4 and (ck in key or key in ck):
            return cid
    words = {w for w in key.split() if len(w) >= 4}
    for cid, cname in clients:
        shared = words & {w for w in fold(cname).split() if len(w) >= 4}
        if len(shared) >= 2:
            return cid
    return None


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
            # v8: meta_account (decision 8, phase 2) is a new table: SCHEMA creates it
            # v9: campaign, review and insight (campaign tracking) are new tables too
            # v10: one Meta connection per portfolio (meta_connection, meta_log are new
            # tables); each ad account remembers which portfolio's token reads it
            cols = {r[1] for r in db.execute("PRAGMA table_info(meta_account)")}
            if "business_id" not in cols:
                db.execute(
                    "ALTER TABLE meta_account ADD COLUMN business_id TEXT NOT NULL DEFAULT ''"
                )
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
            accounts = db.execute(
                "SELECT account_id AS id, name FROM meta_account WHERE client=? "
                "ORDER BY name COLLATE NOCASE, account_id",
                (cid,),
            ).fetchall()
        return {
            **dict(row),
            "requests": reqs,
            "billing": billing,
            "payments": payments,
            "meta_accounts": [dict(a) for a in accounts],
        }

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

    # ---- Meta ad accounts (decision 8, phase 2) --------------------------------------------
    # Every ad account the connected system user reads, and the Pauta client each belongs to.
    # Rows outlive the account's presence in Meta's list, so an untick in Meta or a short
    # outage doesn't lose the mapping; the UI shows those as "não aparece mais na Meta".

    @staticmethod
    def _meta_row(r) -> dict:
        d = dict(r)
        name = d.pop("client_name")
        d["client"] = {"id": d["client"], "name": name} if d["client"] is not None else None
        return d

    def meta_accounts(self) -> list[dict]:
        with self.db() as db:
            rows = db.execute(
                "SELECT m.account_id AS id, m.name, m.currency, m.status, m.client, m.seen, "
                "m.created, m.business_id, c.name AS client_name FROM meta_account m "
                "LEFT JOIN client c ON c.id=m.client ORDER BY m.name COLLATE NOCASE, m.account_id"
            ).fetchall()
        return [self._meta_row(r) for r in rows]

    def sync_meta_accounts(self, accounts: list[dict], now: str | None = None) -> None:
        """What Meta listed just now: upsert name, currency, status, `seen` and, when the
        entry carries one, the `business_id` of the portfolio whose token read it; rows for
        accounts no longer listed stay. An account seen for the first time whose id is some
        client's `ad_account` is linked to that client (the field seeded the match, decision
        8). Only new rows: an admin's unlink stays unlinked on the next sync, even though
        linking filled the client's `ad_account` with this very id."""
        now = now or time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        with self.db() as db:
            known = {r["account_id"] for r in db.execute("SELECT account_id FROM meta_account")}
            for a in accounts:
                aid = digits(a.get("id") or a.get("account_id"))
                if not aid:
                    continue
                db.execute(
                    "INSERT INTO meta_account(account_id, name, currency, status, seen, "
                    "business_id) VALUES (?,?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET "
                    "name=excluded.name, currency=excluded.currency, status=excluded.status, "
                    "seen=excluded.seen, business_id=CASE WHEN excluded.business_id<>'' "
                    "THEN excluded.business_id ELSE meta_account.business_id END",
                    (
                        aid,
                        str(a.get("name") or ""),
                        str(a.get("currency") or "BRL"),
                        int(a.get("status") or 0),
                        now,
                        digits(a.get("business_id")),
                    ),
                )
            by_field: dict[str, int] = {}
            clients = db.execute("SELECT id, ad_account FROM client WHERE ad_account<>''")
            for c in clients:
                by_field.setdefault(digits(c["ad_account"]), c["id"])
            unlinked = db.execute("SELECT account_id FROM meta_account WHERE client IS NULL")
            for aid in [r["account_id"] for r in unlinked if r["account_id"] not in known]:
                cid = by_field.get(aid)
                if cid:
                    db.execute("UPDATE meta_account SET client=? WHERE account_id=?", (cid, aid))
                    obs.event("meta_account_autolinked", client=cid)

    def link_meta_account(self, account_id: str, client_id, by: int | None = None) -> dict:
        """Tie an ad account to a client (or to none). Linking fills the client's empty
        `ad_account` with the id, so the field stays meaningful; unlinking never clears it."""
        aid = digits(account_id)
        with self.db() as db:
            if not db.execute("SELECT 1 FROM meta_account WHERE account_id=?", (aid,)).fetchone():
                raise NotFound("conta de anúncios não encontrada")
            cid = None
            if client_id is not None:
                cid = _id(client_id)
                known = cid and db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone()
                if not known:
                    raise Invalid("cliente não encontrado")
                db.execute(
                    "UPDATE client SET ad_account=?, updated=datetime('now') "
                    "WHERE id=? AND ad_account=''",
                    (aid, cid),
                )
            db.execute("UPDATE meta_account SET client=? WHERE account_id=?", (cid, aid))
            row = db.execute(
                "SELECT m.account_id AS id, m.name, m.currency, m.status, m.client, m.seen, "
                "m.created, m.business_id, c.name AS client_name FROM meta_account m "
                "LEFT JOIN client c ON c.id=m.client WHERE m.account_id=?",
                (aid,),
            ).fetchone()
        obs.event("meta_account_linked" if cid else "meta_account_unlinked", account=by, client=cid)
        return self._meta_row(row)

    def suggest_client(self, name: str) -> int | None:
        """The client an unlinked ad account probably belongs to, by name; never saved."""
        with self.db() as db:
            rows = db.execute(
                "SELECT id, name FROM client ORDER BY state='Encerrado', name COLLATE NOCASE"
            ).fetchall()
        return suggest(name, [(r["id"], r["name"]) for r in rows])

    # ---- the connections (decision 8, "Connection ownership") -------------------------------
    # One row per connected portfolio, mirroring the token files `meta.py` owns (it knows no
    # SQLite): the server calls sync_connections with meta.connections() at startup and on
    # every change. The row adds `last_sync`, written by the sync pass. `meta_log` is the
    # short history Equipe shows: who connected, disconnected, linked or unlinked what.

    LOG_KINDS = ("connected", "disconnected", "linked", "unlinked", "revoked")

    def connections(self) -> list[dict]:
        """Every connection row, oldest first, with the connecting person's name."""
        with self.db() as db:
            rows = db.execute(
                "SELECT m.business_id, m.business_name, m.connected_by, a.name AS by_name, "
                "m.connected_at, m.state, m.error, m.last_sync FROM meta_connection m "
                "LEFT JOIN account a ON a.id=m.connected_by "
                "ORDER BY m.connected_at, m.business_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def sync_connections(self, conns: list[dict]) -> None:
        """Make the rows follow the files: upsert each connection (keeping `last_sync`),
        drop rows whose file is gone, and log a connection that just became revoked."""
        with self.db() as db:
            before = {
                r["business_id"]: r["state"]
                for r in db.execute("SELECT business_id, state FROM meta_connection")
            }
            keep = set()
            for c in conns:
                bid = str(c.get("business_id") or "")
                if not bid:
                    continue
                keep.add(bid)
                by = c.get("by")
                if (
                    by is not None
                    and not db.execute("SELECT 1 FROM account WHERE id=?", (by,)).fetchone()
                ):
                    by = None  # the person who connected is no longer an account
                state = str(c.get("state") or "ok")
                db.execute(
                    "INSERT INTO meta_connection(business_id, business_name, connected_by, "
                    "connected_at, state, error) VALUES (?,?,?,?,?,?) ON CONFLICT(business_id) "
                    "DO UPDATE SET business_name=excluded.business_name, "
                    "connected_by=excluded.connected_by, connected_at=excluded.connected_at, "
                    "state=excluded.state, error=excluded.error",
                    (
                        bid,
                        str(c.get("business_name") or ""),
                        by,
                        str(c.get("connected_at") or ""),
                        state,
                        str(c.get("error") or ""),
                    ),
                )
                if state == "revoked" and before.get(bid) not in (None, "revoked"):
                    self._log(db, "revoked", bid, None, {"business_name": c.get("business_name")})
            gone = [b for b in before if b not in keep]
            for bid in gone:
                db.execute("DELETE FROM meta_connection WHERE business_id=?", (bid,))

    def set_connection_sync(self, business_id: str, at: str, error: str = "") -> None:
        """When one connection's part of a sync pass ended and how it went."""
        with self.db() as db:
            db.execute(
                "UPDATE meta_connection SET last_sync=?, error=CASE WHEN state='ok' THEN ? "
                "ELSE error END WHERE business_id=?",
                (at, error or "", business_id),
            )

    @staticmethod
    def _log(db, kind: str, business_id: str, by: int | None, detail: dict | None) -> None:
        if kind not in Store.LOG_KINDS:
            raise Invalid("tipo de evento desconhecido")
        clean = {k: v for k, v in (detail or {}).items() if v not in (None, "")}
        db.execute(
            "INSERT INTO meta_log(account, kind, business_id, detail) VALUES (?,?,?,?)",
            (by, kind, business_id or "", json.dumps(clean, ensure_ascii=False, sort_keys=True)),
        )

    def meta_log(self, kind: str, business_id: str, by: int | None, **detail) -> None:
        """One line of the Meta history: connected, disconnected, linked, unlinked, revoked."""
        with self.db() as db:
            if (
                by is not None
                and not db.execute("SELECT 1 FROM account WHERE id=?", (by,)).fetchone()
            ):
                by = None
            self._log(db, kind, business_id, by, detail)

    def meta_log_rows(self, limit: int = 20) -> list[dict]:
        """The latest `limit` history lines, newest first, with the actor's name."""
        with self.db() as db:
            rows = db.execute(
                "SELECT l.id, l.at, l.kind, l.business_id, l.detail, l.account, "
                "a.name AS by_name FROM meta_log l LEFT JOIN account a ON a.id=l.account "
                "ORDER BY l.id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            by = {"id": d.pop("account"), "name": d.pop("by_name")}
            d["by"] = by if by["id"] is not None else None
            d["detail"] = json.loads(d["detail"] or "{}")
            out.append(d)
        return out

    # ---- campaigns and their numbers (decision 8) -------------------------------------------
    # Tracked campaigns come from Meta: each sync lists an account's campaigns and a Pauta
    # row follows each ACTIVE one, under the account's client. Numbers are kept per campaign
    # and per day in `insight`, so a period is a sum (except reach, which Meta is asked for).

    def sync_campaigns(self, account_id: str, metas: list[dict], today: str) -> dict:
        """What Meta listed for one ad account. Only a linked account is tracked: an unlinked
        one changes nothing. New rows appear only for ACTIVE campaigns (ended or archived ones
        never show up unless asked); a known one follows Meta's status: ACTIVE reopens an
        ended or paused row, anything else ends an active one. `skipped` is never touched.
        Returns the new rows' meta ids (the caller fetches their history)."""
        aid = digits(account_id)
        out: dict = {"new": [], "ended": 0, "reopened": 0}
        with self.db() as db:
            row = db.execute(
                "SELECT client FROM meta_account WHERE account_id=?", (aid,)
            ).fetchone()
            if not row or row["client"] is None:
                return out
            cid = row["client"]
            for m in metas:
                mid = digits(m.get("id"))
                if not mid:
                    continue
                active = str(m.get("effective_status") or "") == "ACTIVE"
                known = db.execute(
                    "SELECT id, state FROM campaign WHERE meta_id=?", (mid,)
                ).fetchone()
                common = (
                    str(m.get("name") or "")[:200],
                    str(m.get("objective") or "")[:60],
                    str(m.get("effective_status") or "")[:40],
                    today,
                    aid,
                    cid,
                )
                if not known:
                    if not active:
                        continue
                    db.execute(
                        "INSERT INTO campaign(name, objective, effective_status, last_seen, "
                        "account_id, client, meta_id, state, started) "
                        "VALUES (?,?,?,?,?,?,?,'active',?)",
                        (*common, mid, m.get("started") or today),
                    )
                    out["new"].append(mid)
                    continue
                db.execute(
                    "UPDATE campaign SET name=?, objective=?, effective_status=?, last_seen=?, "
                    "account_id=?, client=?, updated=datetime('now') WHERE id=?",
                    (*common, known["id"]),
                )
                if known["state"] == "skipped":
                    continue
                if active and known["state"] in ("ended", "paused"):
                    db.execute(
                        "UPDATE campaign SET state='active', ended=NULL WHERE id=?", (known["id"],)
                    )
                    out["reopened"] += 1
                elif not active and known["state"] == "active":
                    db.execute(
                        "UPDATE campaign SET state='ended', ended=? WHERE id=?",
                        (today, known["id"]),
                    )
                    out["ended"] += 1
        if out["new"] or out["ended"] or out["reopened"]:
            obs.event(
                "campaigns_synced",
                client=cid,
                new=len(out["new"]),
                ended=out["ended"],
                reopened=out["reopened"],
            )
        return out

    def store_insights(self, rows: list[dict], fetched: str | None = None) -> int:
        """Daily numbers per campaign, upserted by (meta_id, day). Returns how many rows."""
        fetched = fetched or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        n = 0
        with self.db() as db:
            for r in rows:
                mid, day = digits(r.get("meta_id")), str(r.get("day") or "")
                if not mid or not DATE_RE.match(day):
                    continue
                actions = r.get("actions") or {}
                db.execute(
                    "INSERT INTO insight(meta_id, day, spend_cents, impressions, reach, "
                    "link_clicks, actions, fetched) VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(meta_id, day) DO UPDATE SET spend_cents=excluded.spend_cents, "
                    "impressions=excluded.impressions, reach=excluded.reach, "
                    "link_clicks=excluded.link_clicks, actions=excluded.actions, "
                    "fetched=excluded.fetched",
                    (
                        mid,
                        day,
                        int(r.get("spend_cents") or 0),
                        int(r.get("impressions") or 0),
                        int(r.get("reach") or 0),
                        int(r.get("link_clicks") or 0),
                        json.dumps(actions, sort_keys=True, separators=(",", ":")),
                        fetched,
                    ),
                )
                n += 1
        return n

    def link_requests_to_campaigns(self) -> int:
        """A campaign without a request takes the done tracking-kind request whose Ads Manager
        link carries its Meta id; the request's timeline says so. Returns how many linked."""
        n = 0
        with self.db() as db:
            orphans = db.execute(
                "SELECT id, meta_id FROM campaign WHERE request IS NULL AND meta_id IS NOT NULL"
            ).fetchall()
            marks = ",".join("?" for _ in TRACKING_KINDS)
            for c in orphans:
                mid = c["meta_id"]
                candidates = db.execute(
                    "SELECT id, campaign_url FROM request WHERE status='done' "
                    f"AND kind IN ({marks}) AND campaign_url LIKE ? AND id NOT IN "
                    "(SELECT request FROM campaign WHERE request IS NOT NULL) ORDER BY id DESC",
                    (*TRACKING_KINDS, f"%{mid}%"),
                ).fetchall()
                rid = next(
                    (r["id"] for r in candidates if campaign_id_in(r["campaign_url"]) == mid), None
                )
                if rid is None:
                    continue
                db.execute(
                    "UPDATE campaign SET request=?, updated=datetime('now') WHERE id=?",
                    (rid, c["id"]),
                )
                db.execute(
                    "INSERT INTO event(request, kind, text) VALUES (?,'campaign',?)",
                    (rid, f"meta:{mid}"),
                )
                n += 1
        return n

    def campaign_rows(self, since: str, until: str, states: tuple = TRACKED_STATES) -> list[dict]:
        """Per client (by name), its campaigns (active first, then by name) with the period's
        sums from `insight`: spend, impressions, link clicks and actions by type, plus the
        account's `currency` (money is in it). `results` is the link clicks (the team's lead
        definition; a setting may change it later)."""
        marks = ",".join("?" for _ in states)
        with self.db() as db:
            rows = db.execute(
                "SELECT k.id, k.client, c.name AS client_name, k.account_id, k.meta_id, k.name, "
                "k.objective, k.state, k.effective_status, k.started, k.ended, k.request, "
                "k.every_days, k.note, k.last_seen, a.currency FROM campaign k "
                "JOIN client c ON c.id=k.client "
                "LEFT JOIN meta_account a ON a.account_id=k.account_id "
                f"WHERE k.state IN ({marks}) "
                "ORDER BY c.name COLLATE NOCASE, c.id, k.state<>'active', "
                "k.name COLLATE NOCASE, k.id",
                states,
            ).fetchall()
            sums = db.execute(
                "SELECT meta_id, SUM(spend_cents) AS spend_cents, SUM(impressions) AS impressions, "
                "SUM(link_clicks) AS link_clicks FROM insight WHERE day BETWEEN ? AND ? "
                "GROUP BY meta_id",
                (since, until),
            ).fetchall()
            acts = db.execute(
                "SELECT meta_id, actions FROM insight WHERE day BETWEEN ? AND ? AND actions<>'{}'",
                (since, until),
            ).fetchall()
        totals = {r["meta_id"]: dict(r) for r in sums}
        actions: dict[str, dict[str, int]] = {}
        for r in acts:
            bag = actions.setdefault(r["meta_id"], {})
            for k, v in json.loads(r["actions"]).items():
                bag[k] = bag.get(k, 0) + int(v)
        out: list[dict] = []
        for r in rows:
            d = dict(r)
            t = totals.get(d["meta_id"]) or {}
            d.update(
                spend_cents=int(t.get("spend_cents") or 0),
                impressions=int(t.get("impressions") or 0),
                link_clicks=int(t.get("link_clicks") or 0),
                actions=actions.get(d["meta_id"], {}),
            )
            d["results"] = d["link_clicks"]
            cname = d.pop("client_name")
            if not out or out[-1]["id"] != d["client"]:
                out.append({"id": d["client"], "name": cname, "campaigns": []})
            out[-1]["campaigns"].append(d)
        return out

    def campaign(self, cid: int, since: str | None = None, until: str | None = None) -> dict:
        """One campaign with its daily rows in the range (all of them when no range)."""
        with self.db() as db:
            row = db.execute(
                "SELECT k.*, c.name AS client_name, a.currency FROM campaign k "
                "LEFT JOIN client c ON c.id=k.client "
                "LEFT JOIN meta_account a ON a.account_id=k.account_id WHERE k.id=?",
                (cid,),
            ).fetchone()
            if not row:
                raise NotFound("campanha não encontrada")
            days = db.execute(
                "SELECT day, spend_cents, impressions, reach, link_clicks, actions, fetched "
                "FROM insight WHERE meta_id=? AND day BETWEEN ? AND ? ORDER BY day",
                (row["meta_id"], since or "0000-00-00", until or "9999-99-99"),
            ).fetchall()
        out = dict(row)
        out["days"] = [{**dict(d), "actions": json.loads(d["actions"])} for d in days]
        return out

    def set_campaign_state(self, cid: int, state, by: int | None = None) -> dict:
        """Não acompanhar (`skipped`: the sync leaves it alone from then on) or Acompanhar
        again (`active`, which the next sync corrects if Meta says otherwise)."""
        if state not in ("skipped", "active"):
            raise Invalid("estado inválido: use skipped ou active")
        with self.db() as db:
            row = db.execute("SELECT state FROM campaign WHERE id=?", (cid,)).fetchone()
            if not row:
                raise NotFound("campanha não encontrada")
            if row["state"] == state:
                raise Invalid("a campanha já está assim")
            if state == "active" and row["state"] != "skipped":
                raise Invalid(
                    "só uma campanha ignorada volta a ser acompanhada; a Meta decide o resto"
                )
            db.execute(
                "UPDATE campaign SET state=?, ended=CASE WHEN ?='active' THEN NULL ELSE ended END, "
                "updated=datetime('now') WHERE id=?",
                (state, state, cid),
            )
        obs.event("campaign_state", account=by, campaign=cid, state=state)
        return self.campaign(cid)

    def add_reviews(self, cid: int, on: str, by: int | None, note: str, snapshots: list) -> int:
        """Visto hoje (decision 8, phase 1 on the Meta rows): one `review` row per campaign
        in `snapshots` ([(campaign id, numbers)]), dated `on`, by `by`, with the note and
        the period numbers it was about. Returns how many rows were written."""
        self.client(cid)  # 404 for an unknown client
        with self.db() as db:
            for kid, snap in snapshots:
                db.execute(
                    'INSERT INTO review(campaign, "on", account, note, snapshot) '
                    "VALUES (?,?,?,?,?)",
                    (kid, on, by, note or "", json.dumps(snap, sort_keys=True)),
                )
        return len(snapshots)

    def seen_on(self, on: str) -> dict[int, dict]:
        """Per client, the latest check dated `on` over its tracked campaigns:
        {client id: {"by": name or None, "at": created}}."""
        with self.db() as db:
            rows = db.execute(
                "SELECT k.client, a.name AS by, MAX(r.created) AS at FROM review r "
                "JOIN campaign k ON k.id=r.campaign LEFT JOIN account a ON a.id=r.account "
                "WHERE r.\"on\"=? AND k.state IN ('active', 'paused', 'ended') GROUP BY k.client",
                (on,),
            ).fetchall()
        return {r["client"]: {"by": r["by"], "at": r["at"]} for r in rows}

    def table(self, name: str) -> list[dict]:
        """Every row of one of the tracking tables, for the export."""
        if name not in EXPORT_TABLES:
            raise Invalid("tabela desconhecida")
        with self.db() as db:
            rows = db.execute(f"SELECT * FROM {name} ORDER BY 1, 2").fetchall()
        out = [dict(r) for r in rows]
        if name == "insight":
            for r in out:
                r["actions"] = json.loads(r["actions"])
        if name == "meta_log":
            for r in out:
                r["detail"] = json.loads(r["detail"] or "{}")
        return out

    def sync_state(self) -> dict:
        """When the Meta sync last ran and how it went, kept across restarts."""
        with self.db() as db:
            rows = db.execute(
                "SELECT key, value FROM meta WHERE key IN ('sync_at', 'sync_error')"
            ).fetchall()
        got = {r["key"]: r["value"] for r in rows}
        return {"last_sync": got.get("sync_at") or None, "sync_error": got.get("sync_error") or ""}

    def set_sync_state(self, at: str, error: str) -> None:
        with self.db() as db:
            db.executemany(
                "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                [("sync_at", at), ("sync_error", error or "")],
            )

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
