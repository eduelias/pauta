"""One Meta connection per connected portfolio (decision 8, "Connection ownership"): the
per-business token files and the move of the old single file, the union of accounts over
connections, a revoked token marking only its own connection, a second portfolio never
overwriting the first, and the Store's side: schema v9 → v10, the `meta_connection` rows
following the files, and the `meta_log` history."""

import json
import logging
import os
import sqlite3
import stat

import pytest
from test_meta import connect

from fakemeta import APP_ID, BUSINESS, CONFIG_ID, OTHER_BUSINESS, secret
from pauta.db import SCHEMA_VERSION, Invalid, Store
from pauta.meta import (
    CACHE_SECONDS,
    LEGACY,
    NOT_CONNECTED,
    RECONNECT,
    REVOKED,
    STALE_SECONDS,
    THROTTLED,
    UNKNOWN_BUSINESS,
    Meta,
    MetaError,
)

ACC = "1000000000000016"  # acceptance's portfolio id (a client's)


def legacy_doc(**over) -> dict:
    return {
        "access_token": "EAAold",
        "business_id": ACC,
        "business_name": "Delta Corretora de Imóveis",
        "connected_at": "2026-10-30T12:00:00Z",
        "by": 1,
        **over,
    }


def build(store, fake_meta) -> Meta:
    return Meta(
        store.path,
        app_id=APP_ID,
        config_id=CONFIG_ID,
        graph=fake_meta.graph,
        dialog=fake_meta.dialog,
    )


def connect_two(meta, fake, first=7, second=8):
    """Renato connects the agency's portfolio, then the client's own one (the fake switches
    the business the next login belongs to)."""
    connect(meta, fake, account=first)
    fake.business = OTHER_BUSINESS
    connect(meta, fake, account=second)
    fake.business = BUSINESS


# ---- the single file of earlier releases ---------------------------------------------------


def test_the_old_single_file_moves_to_its_business(store, fake_meta):
    secret(store.path)
    old = store.path.with_name("pauta.db.meta-token")
    old.write_text(json.dumps(legacy_doc()))
    old.chmod(0o600)
    changes = []
    meta = build(store, fake_meta)
    meta.on_change = changes.append
    new = store.path.with_name(f"pauta.db.meta-token.{ACC}")
    assert new.exists() and not old.exists()
    assert stat.S_IMODE(os.stat(new).st_mode) == 0o600
    assert json.loads(new.read_text())["access_token"] == "EAAold"
    (conn,) = meta.connections()
    assert conn == {
        "business_id": ACC,
        "business_name": "Delta Corretora de Imóveis",
        "connected_at": "2026-10-30T12:00:00Z",
        "by": 1,
        "state": "ok",
        "error": "",
    }
    assert meta.connected and meta.token_file(ACC) == new
    # the server mirrors it into the row at startup (the person is account 1 here)
    store.sync_connections(meta.connections())
    (row,) = store.connections()
    assert row["business_id"] == ACC and row["connected_by"] is None  # no account 1 yet
    assert row["state"] == "ok" and row["last_sync"] is None
    # building again finds nothing to move
    assert build(store, fake_meta).connections() == meta.connections()


def test_the_old_file_without_a_business_waits_for_a_reconnect(store, fake_meta):
    secret(store.path)
    old = store.path.with_name("pauta.db.meta-token")
    old.write_text(json.dumps(legacy_doc(business_id="", business_name="Pauta (sistema)")))
    meta = build(store, fake_meta)
    assert not old.exists() and meta.token_file(LEGACY).exists()
    (conn,) = meta.connections()
    assert conn["business_id"] == LEGACY and conn["state"] == "error"
    assert conn["error"] == RECONNECT and conn["business_name"] == "Pauta (sistema)"
    assert meta.connected and meta.error == RECONNECT
    with pytest.raises(MetaError) as e:  # it is listed, never read
        meta.accounts()
    assert str(e.value) == NOT_CONNECTED
    # connecting for real adds a proper connection; the leftover can be dropped
    connect(meta, fake_meta)
    assert [c["business_id"] for c in meta.connections()] == [LEGACY, BUSINESS]
    assert [a["id"] for a in meta.accounts()] == ["111", "222"]
    meta.disconnect(LEGACY)
    assert [c["business_id"] for c in meta.connections()] == [BUSINESS]


def test_an_unreadable_old_file_is_moved_aside_with_a_warning(store, fake_meta, caplog):
    """The old single file holding something that isn't a token document (half a write,
    say) used to stay put, tried again at every start: it goes to `.legacy` with a
    warning, is not a connection, and the next start is quiet."""
    caplog.set_level(logging.INFO, logger="pauta")
    secret(store.path)
    old = store.path.with_name("pauta.db.meta-token")
    old.write_text("{not json")
    meta = build(store, fake_meta)
    assert not old.exists() and meta.token_file(LEGACY).read_text() == "{not json"
    assert meta.connections() == [] and not meta.connected
    warnings = [r for r in caplog.records if '"meta_token_unreadable"' in r.getMessage()]
    assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
    assert not any('"meta_token_migrated"' in r.getMessage() for r in caplog.records)
    caplog.clear()
    build(store, fake_meta)
    assert not any("meta_token" in r.getMessage() for r in caplog.records)
    # a readable `.legacy` already there (an older leftover) is kept; the junk goes
    meta.token_file(LEGACY).write_text(json.dumps(legacy_doc(business_id="")))
    old.write_text("")
    build(store, fake_meta)
    assert not old.exists()
    assert json.loads(meta.token_file(LEGACY).read_text())["access_token"] == "EAAold"


def test_a_newer_per_business_file_wins_over_the_old_one(store, fake_meta):
    secret(store.path)
    meta = build(store, fake_meta)
    connect(meta, fake_meta)  # BUSINESS, the fake's live token
    store.path.with_name("pauta.db.meta-token").write_text(
        json.dumps(legacy_doc(business_id=BUSINESS, access_token="EAAstale"))
    )
    again = build(store, fake_meta)
    assert not store.path.with_name("pauta.db.meta-token").exists()
    assert json.loads(again.token_file(BUSINESS).read_text())["access_token"] == fake_meta.token
    assert len(again.connections()) == 1
    # odd files next to the database are not connections
    store.path.with_name("pauta.db.meta-token.abc").write_text("{}")
    store.path.with_name("pauta.db.meta-token.123.tmp").write_text("{}")
    store.path.with_name("pauta.db.meta-token.77").write_text("not json")
    assert [c["business_id"] for c in again.connections()] == [BUSINESS]


# ---- several connections -------------------------------------------------------------------


def test_two_portfolios_read_as_one_list(meta_on, fake_meta):
    changes = []
    meta_on.on_change = changes.append
    connect_two(meta_on, fake_meta)
    conns = meta_on.connections()
    assert [(c["business_id"], c["business_name"], c["by"]) for c in conns] == [
        (BUSINESS, "Agência Exemplo", 7),
        (OTHER_BUSINESS, "Delta Imóveis", 8),
    ]
    assert meta_on.token_file(BUSINESS).exists() and meta_on.token_file(OTHER_BUSINESS).exists()
    assert len(changes) == 2 and changes[-1] == conns
    accs = meta_on.accounts()
    assert [(a["id"], a["business_id"], a["business_name"]) for a in accs] == [
        ("111", BUSINESS, "Agência Exemplo"),
        ("222", BUSINESS, "Agência Exemplo"),
        ("444", OTHER_BUSINESS, "Delta Imóveis"),
    ]
    assert accs[2]["spend_cents"] == 8000 and accs[2]["balance"]["remaining_cents"] == 92000
    # two list calls and two batches, each with its own token
    assert fake_meta.calls.count("GET /me/adaccounts") == 2
    assert fake_meta.calls.count("POST /") == 2
    assert meta_on.business_of == {"111": BUSINESS, "222": BUSINESS, "444": OTHER_BUSINESS}
    # the campaign reads pick the token from the account's portfolio
    assert [c["id"] for c in meta_on.campaigns("444")] == ["23850044"]
    assert [c["id"] for c in meta_on.campaigns("444", business_id=OTHER_BUSINESS)] == ["23850044"]
    with pytest.raises(MetaError) as e:  # an account nobody read, with two connections
        meta_on.campaigns("999")
    assert str(e.value) == UNKNOWN_BUSINESS and e.value.status == 409
    with pytest.raises(MetaError):
        meta_on.campaigns("999", business_id="555")


def test_a_revoked_token_marks_only_its_connection(meta_on, fake_meta):
    connect_two(meta_on, fake_meta)
    assert len(meta_on.accounts()) == 3
    fake_meta.revoke(OTHER_BUSINESS)
    accs = meta_on.accounts(refresh=True)
    assert [a["id"] for a in accs] == ["111", "222"]  # the agency still reads
    agency, client = meta_on.connections()
    assert agency["state"] == "ok" and agency["error"] == ""
    assert client["state"] == "revoked" and client["error"] == REVOKED
    assert meta_on.error == REVOKED and meta_on.status()["connected"]
    assert json.loads(meta_on.token_file(OTHER_BUSINESS).read_text())["state"] == "revoked"
    # the client's campaign reads fail with "revoked"; the agency's don't
    with pytest.raises(MetaError) as e:
        meta_on.campaigns("444")
    assert e.value.status == 409 and str(e.value) == REVOKED
    assert len(meta_on.campaigns("111")) == 3
    # both revoked: the list fails as a whole, and the failure is remembered
    fake_meta.revoke(BUSINESS)
    with pytest.raises(MetaError) as e:
        meta_on.accounts(refresh=True)
    assert e.value.status == 409
    assert all(c["state"] == "revoked" for c in meta_on.connections())
    n = len(fake_meta.calls)
    with pytest.raises(MetaError):
        meta_on.accounts()
    assert len(fake_meta.calls) == n
    # reconnecting the client's portfolio brings it back, the agency stays revoked
    fake_meta.business = OTHER_BUSINESS
    connect(meta_on, fake_meta, account=9)
    assert [c["state"] for c in meta_on.connections()] == ["revoked", "ok"]
    assert [a["id"] for a in meta_on.accounts()] == ["444"]


def test_a_connection_already_revoked_does_not_drop_the_list_again(meta_on, fake_meta):
    """Revoking in Meta is how work with a client ends, and the connection stays listed
    (and read) until an admin clicks Desconectar. Its 190 drops the kept list once, when
    the state changes; after that the other portfolio's list is kept like any other, so
    a page does not read all of Meta, twice, on every load."""
    connect_two(meta_on, fake_meta)
    fake_meta.revoke(OTHER_BUSINESS)
    assert [a["id"] for a in meta_on.accounts()] == ["111", "222"]
    assert meta_on.connections()[1]["state"] == "revoked"
    n = len(fake_meta.calls)
    assert [a["id"] for a in meta_on.accounts()] == ["111", "222"]
    assert len(fake_meta.calls) == n  # answered from memory
    # past its ten minutes the list is read once, and kept again
    meta_on._cache = (meta_on._cache[0] - CACHE_SECONDS, meta_on._cache[1])
    fake_meta.calls.clear()
    assert [a["id"] for a in meta_on.accounts(stale=False)] == ["111", "222"]
    assert fake_meta.calls.count("GET /me/adaccounts") == 2  # one per connection, once
    assert meta_on.status()["accounts_stale"] is False


def test_a_connection_meta_does_not_answer_for_keeps_its_accounts_as_last_read(meta_on, fake_meta):
    """Meta failing for one portfolio (a timeout, a 500) is passing trouble: the list kept
    for the next ten minutes still has that portfolio's accounts, with the balance last
    read, so their clients don't drop out of the balance alert and Configurações doesn't
    say the accounts are gone from Meta. Not for ever: after a day without an answer they
    go, as the whole list does when every portfolio fails."""
    connect_two(meta_on, fake_meta)
    first = {a["id"]: a for a in meta_on.accounts()}
    fake_meta.down_for.add(OTHER_BUSINESS)
    accs = meta_on.accounts(refresh=True)
    assert [a["id"] for a in accs] == ["111", "222", "444"]
    assert accs[2] == first["444"] and accs[2]["balance"]["remaining_cents"] == 92000
    assert [c["state"] for c in meta_on.connections()] == ["ok", "ok"]
    meta_on._read_at[OTHER_BUSINESS] -= STALE_SECONDS
    assert [a["id"] for a in meta_on.accounts(refresh=True)] == ["111", "222"]
    # Meta answers again: read anew
    fake_meta.down_for.clear()
    assert [a["id"] for a in meta_on.accounts(refresh=True)] == ["111", "222", "444"]


def test_a_late_190_never_brings_back_a_disconnected_file(meta_on, fake_meta, monkeypatch):
    """Desconectar unlinks the file while a read is out; Meta's 190 for that read arrives
    after. Marking "revoked" reads and writes under the lock and only a file still there,
    so the token stays gone (it used to be written back, state "revoked")."""
    connect_two(meta_on, fake_meta)
    real = Meta._saved

    def read_then_disconnected(self, business_id):
        doc = real(self, business_id)
        self.token_file(business_id).unlink()  # Desconectar, between the read and the save
        return doc

    monkeypatch.setattr(Meta, "_saved", read_then_disconnected)
    changes = []
    meta_on.on_change = changes.append
    meta_on._mark(OTHER_BUSINESS, "revoked", REVOKED)
    assert not meta_on.token_file(OTHER_BUSINESS).exists()
    assert [c["business_id"] for c in meta_on.connections()] == [BUSINESS]
    assert changes == [meta_on.connections()]
    monkeypatch.undo()
    # the plain case still writes the state
    meta_on._mark(BUSINESS, "revoked", REVOKED)
    assert json.loads(meta_on.token_file(BUSINESS).read_text())["state"] == "revoked"
    # and _save with create off never makes a file
    assert meta_on._save({"business_id": "999", "access_token": "x"}, create=False) is False
    assert not meta_on.token_file("999").exists()


def test_meta_down_for_one_portfolio_is_not_a_state(meta_on, fake_meta, monkeypatch):
    """Meta not answering for one connection leaves it out this time, without marking it:
    the next read tries again. A throttle fails the list: Meta asked the whole app to wait."""
    connect_two(meta_on, fake_meta)
    real = meta_on._read_one

    def agency_down(business_id, name):
        if business_id == BUSINESS:
            raise MetaError("down")
        return real(business_id, name)

    monkeypatch.setattr(meta_on, "_read_one", agency_down)
    assert [a["id"] for a in meta_on.accounts()] == ["444"]
    assert all(c["state"] == "ok" for c in meta_on.connections())
    monkeypatch.undo()
    assert [a["id"] for a in meta_on.accounts(refresh=True)] == ["111", "222", "444"]
    fake_meta.throttle = True
    with pytest.raises(MetaError) as e:
        meta_on.accounts(refresh=True)
    # both portfolios are read at the same time: each list was read, each batch throttled
    assert str(e.value) == THROTTLED and fake_meta.calls.count("GET /me/adaccounts") == 5


def test_a_second_portfolio_keeps_the_first(meta_on, fake_meta):
    connect(meta_on, fake_meta, account=7)
    first = json.loads(meta_on.token_file(BUSINESS).read_text())
    fake_meta.business = OTHER_BUSINESS
    connect(meta_on, fake_meta, account=7)
    assert json.loads(meta_on.token_file(BUSINESS).read_text()) == first
    assert len(meta_on.connections()) == 2
    # "Adicionar contas" on the agency: a re-login on the same business replaces its token
    fake_meta.business = BUSINESS
    back = fake_meta.approve(meta_on.start_connect(7, BUSINESS))
    conn = meta_on.finish_connect(back["state"], back["code"])
    assert conn["business_id"] == BUSINESS
    assert json.loads(meta_on.token_file(BUSINESS).read_text())["access_token"] == fake_meta.token
    assert len(meta_on.connections()) == 2 and fake_meta.exchanges == 3
    # disconnecting one leaves the other
    meta_on.disconnect(OTHER_BUSINESS)
    assert [c["business_id"] for c in meta_on.connections()] == [BUSINESS]
    assert [a["id"] for a in meta_on.accounts()] == ["111", "222"]


def test_adding_accounts_to_one_portfolio_but_logging_into_another(meta_on, fake_meta, caplog):
    """Piero clicks Adicionar contas on the agency's block but picks the client's portfolio
    in Meta's dialog: that login is saved as its own connection, the agency's untouched."""
    connect(meta_on, fake_meta, account=7)
    first = json.loads(meta_on.token_file(BUSINESS).read_text())
    fake_meta.business = OTHER_BUSINESS
    back = fake_meta.approve(meta_on.start_connect(7, BUSINESS))
    conn = meta_on.finish_connect(back["state"], back["code"])
    assert conn["business_id"] == OTHER_BUSINESS and conn["by"] == 7
    assert json.loads(meta_on.token_file(BUSINESS).read_text()) == first
    assert [c["business_id"] for c in meta_on.connections()] == [BUSINESS, OTHER_BUSINESS]
    assert "meta_connected_other_business" in caplog.text
    # Adicionar contas on a portfolio that isn't connected: nothing to add to
    with pytest.raises(MetaError) as e:
        meta_on.start_connect(7, "999")
    assert e.value.status == 404 and str(e.value) == UNKNOWN_BUSINESS
    assert meta_on.start_connect(7, "").startswith(meta_on.dialog)  # "" means another one


# ---- the Store's side ----------------------------------------------------------------------


def test_schema_v9_gains_connections_and_the_log(tmp_path):
    Store(tmp_path / "old.db")
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(  # as v9 left it: no connection tables, no business_id on accounts
        "DROP TABLE meta_connection; DROP TABLE meta_log;"
        "ALTER TABLE meta_account DROP COLUMN business_id;"
        "UPDATE meta SET value='9' WHERE key='schema';"
        "INSERT INTO meta_account(account_id, name) VALUES ('111', 'Clínica');"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    with store.db() as db:
        version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        assert version == str(SCHEMA_VERSION)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"meta_connection", "meta_log"} <= tables
    assert store.meta_accounts()[0]["business_id"] == ""
    assert store.connections() == [] and store.meta_log_rows() == []
    # the first read after the upgrade tags the row with its portfolio
    store.sync_meta_accounts([{"id": "111", "name": "Clínica", "business_id": BUSINESS}])
    assert store.meta_accounts()[0]["business_id"] == BUSINESS
    # an entry without one (an older caller) keeps what the row has
    store.sync_meta_accounts([{"id": "111", "name": "Clínica"}])
    assert store.meta_accounts()[0]["business_id"] == BUSINESS


def test_connection_rows_follow_the_files(store):
    a = {
        "business_id": BUSINESS,
        "business_name": "Agência",
        "connected_at": "2026-11-01T10:00:00Z",
        "by": 42,  # no such account: kept as nobody
        "state": "ok",
        "error": "",
    }
    b = {**a, "business_id": OTHER_BUSINESS, "business_name": "Delta", "by": None}
    store.sync_connections([b, a, {"business_id": ""}])  # an empty id is ignored
    rows = store.connections()
    assert [(r["business_id"], r["business_name"], r["connected_by"]) for r in rows] == [
        (BUSINESS, "Agência", None),
        (OTHER_BUSINESS, "Delta", None),
    ]
    assert rows[0]["by_name"] is None and rows[0]["last_sync"] is None
    store.set_connection_sync(BUSINESS, "2026-11-01T11:00:00Z", "")
    store.set_connection_sync(OTHER_BUSINESS, "2026-11-01T11:00:01Z", "x failed")
    # a rename and a revocation arrive; last_sync survives the upsert; the log notes the
    # revocation once
    store.sync_connections([{**a, "business_name": "Agência Exemplo"}, {**b, "state": "revoked"}])
    store.sync_connections([{**a, "business_name": "Agência Exemplo"}, {**b, "state": "revoked"}])
    rows = {r["business_id"]: r for r in store.connections()}
    assert rows[BUSINESS]["business_name"] == "Agência Exemplo"
    assert rows[BUSINESS]["last_sync"] == "2026-11-01T11:00:00Z"
    assert rows[OTHER_BUSINESS]["state"] == "revoked" and rows[OTHER_BUSINESS]["error"] == ""
    log = store.meta_log_rows()
    assert [(e["kind"], e["business_id"], e["by"]) for e in log] == [
        ("revoked", OTHER_BUSINESS, None)
    ]
    assert log[0]["detail"] == {"business_name": "Delta"}
    # a sync error on a revoked connection doesn't overwrite "revoked"'s own text
    store.sync_connections([a, {**b, "state": "revoked", "error": REVOKED}])
    store.set_connection_sync(OTHER_BUSINESS, "2026-11-01T12:00:00Z", "x")
    assert store.connections()[1]["error"] == REVOKED
    # a file that is gone takes its row with it
    store.sync_connections([a])
    assert [r["business_id"] for r in store.connections()] == [BUSINESS]


def test_the_log_names_the_actor(store):
    with store.db() as db:
        db.execute("INSERT INTO account(id, name, handle) VALUES (1, 'Piero', 'piero')")
    store.meta_log("connected", BUSINESS, 1, business_name="Delta", empty="", none=None)
    store.meta_log("linked", BUSINESS, 1, account_name="Clínica", client_name="Clínica Bem Estar")
    store.meta_log("unlinked", BUSINESS, 99, account_name="Clínica")  # a gone account
    store.meta_log("disconnected", BUSINESS, None, business_name="Delta")
    rows = store.meta_log_rows()
    assert [r["kind"] for r in rows] == ["disconnected", "unlinked", "linked", "connected"]
    assert rows[3]["by"] == {"id": 1, "name": "Piero"} and rows[3]["detail"] == {
        "business_name": "Delta"
    }
    assert rows[1]["by"] is None and rows[0]["by"] is None
    assert rows[2]["detail"] == {"account_name": "Clínica", "client_name": "Clínica Bem Estar"}
    assert len(rows[0]["at"]) == 19
    assert len(store.meta_log_rows(2)) == 2 and len(store.meta_log_rows(0)) == 1
    with pytest.raises(Invalid):
        store.meta_log("deleted", BUSINESS, 1)
    # the export carries both tables, with the detail decoded
    exported = store.table("meta_log")
    assert exported[0]["kind"] == "connected" and exported[0]["detail"] == {
        "business_name": "Delta"
    }
    assert store.table("meta_connection") == []
