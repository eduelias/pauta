"""The data: clients, requests (pedidos) and their history, in one SQLite file.

A request carries both halves of the old spreadsheet on one row: the briefing whoever asked
filled in (client, what, goal, audience, budget, due date...) and the execution whoever runs
it fills in (status, what's missing, done date, campaign link). Nothing is linked by row
position any more, so sorting, filtering and deleting are safe.

Every change to a request leaves an `event` (created, status, edited, comment): that is the
timeline on the request page.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, handle TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL DEFAULT '', is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0,
    created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS passkey (
    id TEXT PRIMARY KEY, account INTEGER NOT NULL REFERENCES account(id) ON DELETE CASCADE,
    public_key BLOB NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT,
    created TEXT NOT NULL DEFAULT (datetime('now')), last_used TEXT
);
CREATE TABLE IF NOT EXISTS invite (
    token_hash TEXT PRIMARY KEY, admin INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL,
    created_by INTEGER, created TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS client (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '', whatsapp TEXT NOT NULL DEFAULT '',
    instagram TEXT NOT NULL DEFAULT '', ad_account TEXT NOT NULL DEFAULT '',
    access TEXT NOT NULL DEFAULT 'Pendente', drive_url TEXT NOT NULL DEFAULT '',
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
CREATE TABLE IF NOT EXISTS option (
    list TEXT NOT NULL, value TEXT NOT NULL, pos INTEGER NOT NULL, PRIMARY KEY (list, value)
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


def _text(limit):
    def check(v, _db):
        return " ".join(str(v or "").split())[:limit]

    return check


def _long(limit):
    def check(v, _db):
        return str(v or "").replace("\r\n", "\n").strip()[:limit]

    return check


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
    try:
        cid = int(v)
    except (TypeError, ValueError):
        raise Invalid("escolha um cliente") from None
    if not db.execute("SELECT 1 FROM client WHERE id=?", (cid,)).fetchone():
        raise Invalid("cliente não encontrado")
    return cid


def _account(v, db):
    if v in (None, "", 0):
        return None
    try:
        aid = int(v)
    except (TypeError, ValueError):
        raise Invalid("responsável inválido") from None
    if not db.execute("SELECT 1 FROM account WHERE id=? AND NOT disabled", (aid,)).fetchone():
        raise Invalid("responsável não encontrado")
    return aid


CLIENT_FIELDS = {
    "name": _text(80),
    "segment": _text(MAX_OPTION),
    "contact": _text(80),
    "whatsapp": _text(40),
    "instagram": _text(120),
    "ad_account": _text(60),
    "access": _choice(ACCESS),
    "drive_url": _url,
    "since": _date,
    "state": _choice(CLIENT_STATES),
    "notes": _long(4000),
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
                "(SELECT MAX(last_used) FROM passkey p WHERE p.account=a.id) AS last_seen "
                "FROM account a ORDER BY a.disabled, a.id"
            ).fetchall()
        # the address itself stays private; teammates only get the Gravatar hash
        out = []
        for r in map(dict, rows):
            r["avatar"] = gravatar(r.pop("email"))
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
        return {**dict(row), "requests": reqs}

    def save_client(self, data: dict, cid: int | None = None) -> dict:
        with self.db() as db:
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
        return self.client(cid)

    def delete_client(self, cid: int) -> None:
        with self.db() as db:
            if db.execute("SELECT 1 FROM request WHERE client=?", (cid,)).fetchone():
                raise Invalid("este cliente tem pedidos; marque-o como Encerrado")
            if not db.execute("DELETE FROM client WHERE id=?", (cid,)).rowcount:
                raise NotFound("cliente não encontrado")

    # ---- requests ---------------------------------------------------------------------------

    @staticmethod
    def _requests(db, where: str = "", args: tuple = ()) -> list[dict]:
        rows = db.execute(
            "SELECT r.*, c.name AS client_name, c.state AS client_state, "
            "cb.name AS created_by_name, asg.name AS assignee_name, "
            "(SELECT COUNT(*) FROM event e WHERE e.request=r.id AND e.kind='comment') "
            "  AS comments "
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
            return {
                **reqs[0],
                "client_info": dict(client.fetchone()),
                "events": [dict(e) for e in events],
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
