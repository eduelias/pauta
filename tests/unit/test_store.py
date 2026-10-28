"""The Store: clients, requests, their timeline, lists, people and backups."""

import sqlite3
from datetime import date

import pytest

from pauta.db import DEFAULT_OPTIONS, SCHEMA_VERSION, Invalid, NotFound, Store


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
