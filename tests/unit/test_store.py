"""The Store: clients, requests, their timeline, lists, people and backups."""

import sqlite3
from datetime import date, timedelta

import pytest

from pauta.db import DEFAULT_OPTIONS, SCHEMA_VERSION, Invalid, NotFound, Store
from pauta.finance import add_months


@pytest.fixture()
def client(store):
    return store.save_client({"name": "Clínica Bem Estar", "segment": "Estética"})


def new_request(store, client, **extra):
    return store.create_request({"client": client["id"], "what": "Campanha", **extra}, None)


# ---- schema and options ------------------------------------------------------------------


def test_fresh_database(store):
    with store.db() as conn:
        version = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert version == str(SCHEMA_VERSION)
    opts = store.options()
    for lst, values in DEFAULT_OPTIONS.items():
        assert opts[lst] == values
    assert opts["status"]["done"] == "Concluído"


def test_reopening_keeps_data_and_edited_lists(tmp_path):
    s1 = Store(tmp_path / "x.db")
    s1.save_client({"name": "Kept"})
    s1.set_options("kind", ["Só isso"])
    s2 = Store(tmp_path / "x.db")
    assert [c["name"] for c in s2.clients()] == ["Kept"]
    assert s2.options()["kind"] == ["Só isso"]  # defaults are only seeded once


def test_set_options(store):
    assert store.set_options("goal", [" Vendas ", "vendas", "", "Leads"]) == ["Vendas", "Leads"]
    assert len(store.set_options("segment", [f"s{i}" for i in range(80)])) == 50
    with pytest.raises(Invalid):
        store.set_options("status", ["x"])  # fixed lists aren't editable
    with pytest.raises(Invalid):
        store.set_options("kind", ["", "  "])
    with pytest.raises(Invalid):
        store.set_options("kind", "not a list")


# ---- clients -------------------------------------------------------------------------------


def test_client_create_update_delete(store, client):
    assert client["state"] == "Ativo" and client["access"] == "Pendente"
    with pytest.raises(Invalid, match="nome"):
        store.save_client({"segment": "x"})
    with pytest.raises(Invalid, match="já existe"):
        store.save_client({"name": "clínica bem estar"})  # case-insensitive
    updated = store.save_client({"access": "Liberado"}, client["id"])
    assert updated["access"] == "Liberado" and updated["name"] == client["name"]
    assert store.save_client({"name": "Clínica Bem Estar"}, client["id"])["id"] == client["id"]
    with pytest.raises(NotFound):
        store.save_client({"notes": "x"}, 999)
    store.delete_client(client["id"])
    with pytest.raises(NotFound):
        store.client(client["id"])
    with pytest.raises(NotFound):
        store.delete_client(client["id"])


def test_client_with_requests_cannot_be_deleted(store, client):
    new_request(store, client)
    with pytest.raises(Invalid, match="Encerrado"):
        store.delete_client(client["id"])


def test_client_counts(store, client):
    new_request(store, client)
    new_request(store, client, status="done")
    other = store.save_client({"name": "Antiga", "state": "Encerrado"})
    rows = store.clients()
    assert [r["name"] for r in rows] == ["Clínica Bem Estar", "Antiga"]  # closed ones last
    assert rows[0]["open_requests"] == 1 and rows[0]["total_requests"] == 2
    assert store.client(other["id"])["requests"] == []


# ---- requests ------------------------------------------------------------------------------


def test_create_request_defaults(store, client):
    r = new_request(store, client)
    assert r["status"] == "todo" and r["priority"] == "Média" and r["done_on"] is None
    assert r["client_info"]["name"] == "Clínica Bem Estar"
    assert [e["kind"] for e in r["events"]] == ["created"]
    with pytest.raises(Invalid, match="descreva"):
        store.create_request({"client": client["id"], "what": "  "}, None)


def test_request_created_done_gets_a_done_date(store, client):
    r = new_request(store, client, status="done")
    assert r["done_on"] == date.today().isoformat()
    r = new_request(store, client, status="done", done_on="2026-01-02")
    assert r["done_on"] == "2026-01-02"


def test_update_logs_status_and_edits(store, client):
    r = new_request(store, client)
    same = store.update_request(r["id"], {"what": "Campanha", "priority": "Média"}, None)
    assert len(same["events"]) == 1  # nothing changed, nothing logged
    r = store.update_request(r["id"], {"status": "doing", "budget": "300", "due": ""}, None)
    events = [(e["kind"], e["text"]) for e in r["events"]]
    assert events[1:] == [("status", "todo>doing"), ("edited", "verba")]
    r = store.update_request(r["id"], {"status": "done"}, None)
    assert r["done_on"] == date.today().isoformat()
    assert r["events"][-1]["text"] == "doing>done"  # done_on is not reported as an edit
    with pytest.raises(Invalid):
        store.update_request(r["id"], {"what": ""}, None)
    with pytest.raises(NotFound):
        store.update_request(999, {"status": "doing"}, None)


def test_reopening_keeps_the_first_done_date(store, client):
    r = new_request(store, client, status="done", done_on="2026-01-02")
    store.update_request(r["id"], {"status": "doing"}, None)
    r = store.update_request(r["id"], {"status": "done"}, None)
    assert r["done_on"] == "2026-01-02"


def test_comments(store, client):
    r = new_request(store, client)
    r = store.comment(r["id"], "  Liberado!\r\nObrigado ", None)
    assert r["events"][-1]["text"] == "Liberado!\nObrigado" and r["comments"] == 1
    with pytest.raises(Invalid):
        store.comment(r["id"], "   ", None)
    with pytest.raises(NotFound):
        store.comment(999, "x", None)


def test_delete_request_takes_its_timeline(store, client):
    r = store.comment(new_request(store, client)["id"], "x", None)
    store.delete_request(r["id"])
    with store.db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM event").fetchone()[0] == 0
    with pytest.raises(NotFound):
        store.delete_request(r["id"])
    with pytest.raises(NotFound):
        store.request(r["id"])


def test_requests_newest_first(store, client):
    ids = [new_request(store, client)["id"] for _ in range(3)]
    assert [r["id"] for r in store.requests()] == ids[::-1]


# ---- people and backups --------------------------------------------------------------------


def test_members_never_expose_the_email(store):
    with store.db() as conn:
        conn.execute(
            "INSERT INTO account(name, handle, email) VALUES ('Ana', 'h1', 'ana@example.com')"
        )
        conn.execute("INSERT INTO account(name, handle, disabled) VALUES ('Old', 'h2', 1)")
    ana, old = store.members()
    assert "email" not in ana and len(ana["avatar"]) == 64
    assert old["avatar"] == "" and old["disabled"] == 1 and old["passkeys"] == 0


def test_backup_is_a_working_copy(store, client, tmp_path):
    new_request(store, client)
    out = store.backup(tmp_path / "bk" / "copy.db")
    conn = sqlite3.connect(out)
    try:
        assert conn.execute("SELECT COUNT(*) FROM request").fetchone()[0] == 1
    finally:
        conn.close()


def test_ads_page_is_free_text(store, client):
    c = store.save_client({"ads_page": "  facebook.com/ads/library/?id=123  "}, client["id"])
    assert c["ads_page"] == "facebook.com/ads/library/?id=123"  # not forced into a URL
    c = store.save_client({"ads_page": "pedir ao cliente"}, client["id"])
    assert c["ads_page"] == "pedir ao cliente"
    assert len(store.save_client({"ads_page": "x" * 900}, client["id"])["ads_page"]) == 500


def test_deleting_a_client_with_its_requests(store, client):
    r = store.comment(new_request(store, client)["id"], "x", None)
    new_request(store, client)
    keep = store.save_client({"name": "Outro"})
    kept = new_request(store, keep)
    assert store.delete_client(client["id"], with_requests=True) == 2
    with pytest.raises(NotFound):
        store.request(r["id"])
    assert [x["id"] for x in store.requests()] == [kept["id"]]
    with store.db() as conn:  # timelines went too
        assert (
            conn.execute("SELECT COUNT(*) FROM event WHERE request=?", (r["id"],)).fetchone()[0]
            == 0
        )
    assert store.delete_client(keep["id"], with_requests=True) == 1
    with pytest.raises(NotFound):
        store.delete_client(999, with_requests=True)


def test_schema_v2_gets_the_ads_page_column(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(
        "CREATE TABLE client (id INTEGER PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL "
        "DEFAULT '', contact TEXT NOT NULL DEFAULT '', whatsapp TEXT NOT NULL DEFAULT '', "
        "instagram TEXT NOT NULL DEFAULT '', ad_account TEXT NOT NULL DEFAULT '', access TEXT NOT "
        "NULL DEFAULT 'Pendente', drive_url TEXT NOT NULL DEFAULT '', since TEXT, state TEXT NOT "
        "NULL DEFAULT 'Ativo', notes TEXT NOT NULL DEFAULT '', created TEXT NOT NULL DEFAULT "
        "(datetime('now')), updated TEXT NOT NULL DEFAULT (datetime('now')));"
        "INSERT INTO client(name) VALUES ('Antigo');"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    assert store.clients()[0]["ads_page"] == ""
    assert store.save_client({"ads_page": "x"}, 1)["ads_page"] == "x"


# ---- finance: settings, cycles and the ledger (decision 7) ------------------------------


def test_finance_settings_defaults_and_validation(store):
    s = store.finance_settings()
    assert s["enabled"] and s["currency"] == "BRL" and s["amount"] == 100 and s["anchor"]
    s = store.set_finance_settings(
        {"amount": "R$ 150,00", "grace_days": "3", "visibility": "admins"}
    )
    assert s["amount"] == 150 and s["grace_days"] == 3 and s["visibility"] == "admins"
    assert store.finance_settings() == s  # persisted
    with pytest.raises(Invalid):
        store.set_finance_settings({"anchor": "lunar"})
    with pytest.raises(Invalid):
        store.set_finance_settings({"grace_days": 99})
    with pytest.raises(Invalid):
        store.set_finance_settings({"amount": ""})
    assert store.set_finance_settings({"enabled": "false"})["enabled"] is False


def test_a_new_active_client_gets_an_open_cycle(store):
    c = store.save_client({"name": "Nova"})
    assert c["billed"] == 1
    assert c["billing"]["status"] == "awaiting_first" and c["billing"]["amount"] == 100
    paused = store.save_client({"name": "Parada", "state": "Pausado"})
    assert paused["billing"] is None
    store.set_finance_settings({"bill_new_clients": False})
    assert store.save_client({"name": "Cortesia"})["billing"] is None


def test_pausing_closes_the_cycle_and_coming_back_restarts_it(store, client):
    cid = client["id"]
    first = store.add_payment(cid, {"paid_on": "2026-10-29", "amount": 100}, None)
    assert first["billing"]["anchor"] == "2026-10-29" and first["billing"]["months_active"] >= 1
    store.save_client({"state": "Pausado"}, cid)
    assert store.client(cid)["billing"] is None
    back = store.save_client({"state": "Ativo"}, cid)
    # a new cycle: the old payment stays in the ledger but no longer anchors anything
    assert back["billing"]["status"] == "awaiting_first" and len(back["payments"]) == 1
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM billing WHERE client=?", (cid,)).fetchone()[0] == 2


def test_not_billed_means_no_cycle_and_no_panel_row(store, client):
    cid = client["id"]
    off = store.set_billing(cid, {"billed": False}, None)
    assert off["billed"] == 0 and off["billing"] is None
    assert store.finance()["clients"] == []
    on = store.set_billing(cid, {"billed": True, "amount": "250"}, None)
    assert on["billing"]["amount"] == 250
    with pytest.raises(Invalid):
        store.set_billing(cid, {"amount": 0}, None)
    with pytest.raises(NotFound):
        store.set_billing(999, {"amount": 1}, None)


def test_payments_are_voided_never_deleted(store, client):
    cid = client["id"]
    with store.db() as conn:  # 7 records, 8 is someone else
        conn.execute("INSERT INTO account(id, name, handle) VALUES (7, 'Piero', 'h7')")
        conn.execute("INSERT INTO account(id, name, handle) VALUES (8, 'Renato', 'h8')")
    c = store.add_payment(cid, {"paid_on": "2026-10-29", "amount": "100", "method": "Pix"}, 7)
    pid = c["payments"][0]["id"]
    assert c["payments"][0] == {
        **c["payments"][0],
        "amount": 100,
        "method": "Pix",
        "recorded_by": 7,
    }
    with pytest.raises(Invalid):  # not the recorder, not an admin
        store.void_payment(pid, 8, admin=False)
    c = store.void_payment(pid, 8, admin=True)
    assert c["payments"][0]["voided_by"] == 8 and c["payments"][0]["voided_at"]
    assert c["billing"]["status"] == "awaiting_first"  # the anchor went with it
    with pytest.raises(Invalid):
        store.void_payment(pid, 8, admin=True)
    with pytest.raises(NotFound):
        store.void_payment(999, 8, admin=True)
    c = store.add_payment(cid, {"paid_on": "2026-10-30", "amount": 100}, 7)
    assert store.void_payment(c["payments"][0]["id"], 7, admin=False)["billing"]["anchor"] is None


def test_payment_validation(store, client):
    cid = client["id"]
    for bad in (
        {"paid_on": "", "amount": 1},
        {"paid_on": "2026-10-29"},
        {"paid_on": "2026-10-29", "amount": 0},
        {"paid_on": "2026-10-29", "amount": "abc"},
        {"paid_on": "2999-01-01", "amount": 1},
    ):
        with pytest.raises(Invalid):
            store.add_payment(cid, bad, None)
    with pytest.raises(NotFound):
        store.add_payment(999, {"paid_on": "2026-10-29", "amount": 1}, None)


def test_the_panel(store):
    # dates relative to today: the ledger refuses payments in the future
    today = date.today()
    ago = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    a = store.save_client({"name": "Em dia"})
    b = store.save_client({"name": "Atrasado"})
    c = store.save_client({"name": "Esperando"})
    store.save_client({"name": "Pausado", "state": "Pausado"})
    store.add_payment(a["id"], {"paid_on": ago(10), "amount": 100}, None)
    store.add_payment(b["id"], {"paid_on": ago(70), "amount": 100}, None)
    store.add_payment(b["id"], {"paid_on": ago(40), "amount": 100}, None)
    panel = store.finance()
    assert [r["name"] for r in panel["clients"]] == ["Atrasado", "Esperando", "Em dia"]
    assert panel["counts"] == {"late": 1, "due": 0, "due_soon": 0, "awaiting_first": 1, "paid": 1}
    assert panel["received_total"] == 300 and panel["today"] == today.isoformat()
    assert panel["owed"] == 100 and panel["currency"] == "BRL"
    late = panel["clients"][0]
    assert late["next_due"] == add_months(today - timedelta(days=70), 2).isoformat()
    assert late["months_active"] == 3
    assert late["last_payment"] == {"paid_on": ago(40), "amount": 100}
    assert panel["clients"][2]["last_payment"]["paid_on"] == ago(10)
    assert c["billing"]["status"] == "awaiting_first"


def test_deleting_a_client_takes_its_ledger(store, client):
    store.add_payment(client["id"], {"paid_on": "2026-10-29", "amount": 100}, None)
    store.delete_client(client["id"])
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM payment").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM billing").fetchone()[0] == 0


def test_schema_v6_opens_a_cycle_for_every_active_client(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(
        "CREATE TABLE client (id INTEGER PRIMARY KEY, name TEXT NOT NULL, segment TEXT NOT NULL "
        "DEFAULT '', contact TEXT NOT NULL DEFAULT '', whatsapp TEXT NOT NULL DEFAULT '', "
        "instagram TEXT NOT NULL DEFAULT '', ad_account TEXT NOT NULL DEFAULT '', access TEXT NOT "
        "NULL DEFAULT 'Pendente', drive_url TEXT NOT NULL DEFAULT '', ads_page TEXT NOT NULL "
        "DEFAULT '', since TEXT, state TEXT NOT NULL DEFAULT 'Ativo', notes TEXT NOT NULL DEFAULT "
        "'', created TEXT NOT NULL DEFAULT (datetime('now')), updated TEXT NOT NULL DEFAULT "
        "(datetime('now')));"
        "INSERT INTO client(name) VALUES ('Ativo antigo');"
        "INSERT INTO client(name, state) VALUES ('Encerrado antigo', 'Encerrado');"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    assert store.client(1)["billing"]["status"] == "awaiting_first"
    assert store.client(2)["billing"] is None
    Store(tmp_path / "old.db")  # opening again doesn't double the cycles
    with store.db() as db:
        assert db.execute("SELECT COUNT(*) FROM billing").fetchone()[0] == 1
