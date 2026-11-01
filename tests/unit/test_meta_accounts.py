"""The account ↔ client mapping in the Store (decision 8, phase 2): rows survive Meta's list,
auto-link by the client's `ad_account`, linking fills that field, suggestions by name, and
the v7 → v8 migration."""

import sqlite3

import pytest

from pauta.db import SCHEMA_VERSION, Invalid, NotFound, Store, digits, fold, suggest

CLINIC = {"id": "111", "name": "Clínica Bem Estar", "currency": "BRL", "status": 1}
BAKERY = {"id": "222", "name": "Padaria Trigo de Ouro", "currency": "BRL", "status": 2}


def test_digits_and_fold():
    assert digits("act_123") == "123" and digits(" 1 2 3 ") == "123" and digits(None) == ""
    assert digits(456) == "456"
    assert fold("Clínica Bem-Estar  LTDA") == "clinica bem estar ltda"
    assert fold("AÇOUGUE São João") == "acougue sao joao"
    assert fold("") == "" and fold(None) == ""


def test_sync_upserts_and_keeps_rows_no_longer_listed(store):
    store.sync_meta_accounts([CLINIC, BAKERY], now="2026-10-31 10:00:00")
    rows = store.meta_accounts()
    assert [r["id"] for r in rows] == ["111", "222"]
    assert rows[0] == {
        "id": "111",
        "name": "Clínica Bem Estar",
        "currency": "BRL",
        "status": 1,
        "client": None,
        "seen": "2026-10-31 10:00:00",
        "created": rows[0]["created"],
        "business_id": "",
        "timezone_name": "",
    }
    # the clinic was renamed and the bakery unticked in Meta: the row stays, seen is old
    store.sync_meta_accounts(
        [{**CLINIC, "name": "Clínica Bem Estar Unidade 2", "status": 2}], now="2026-11-01 10:00:00"
    )
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["111"]["name"] == "Clínica Bem Estar Unidade 2" and rows["111"]["status"] == 2
    assert rows["111"]["seen"] == "2026-11-01 10:00:00"
    assert rows["222"]["seen"] == "2026-10-31 10:00:00"
    # odd entries are skipped; Meta's own key names work too; `now` defaults to now
    store.sync_meta_accounts([{"account_id": "act_333", "name": "X"}, {"id": "", "name": "no"}])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert set(rows) == {"111", "222", "333"}
    assert rows["333"]["currency"] == "BRL" and rows["333"]["status"] == 0
    assert len(rows["333"]["seen"]) == 19 and rows["333"]["seen"] > "2026-10"


def test_sync_auto_links_by_the_clients_ad_account(store):
    bakery = store.save_client({"name": "Padaria", "ad_account": "act_222"})
    other = store.save_client({"name": "Outra", "ad_account": "222"})  # a copy-paste twin
    store.save_client({"name": "Sem conta"})
    store.sync_meta_accounts([CLINIC, BAKERY])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["222"]["client"] == {"id": bakery["id"], "name": "Padaria"}  # the first wins
    assert rows["111"]["client"] is None
    assert store.client(bakery["id"])["meta_accounts"] == [{"id": "222", "name": BAKERY["name"]}]
    assert store.client(other["id"])["meta_accounts"] == []
    # an account already linked is never moved by a later sync
    store.link_meta_account("222", other["id"])
    store.sync_meta_accounts([CLINIC, BAKERY])
    assert store.meta_accounts()[1]["client"]["id"] == other["id"]


def test_only_accounts_new_to_this_sync_link_themselves(store):
    """Linking fills the client's ad_account with the id, so a later sync would see the
    match again: an admin's unlink has to survive it. Only rows this sync inserted link."""
    clinic = store.save_client({"name": "Clínica"})
    store.sync_meta_accounts([CLINIC])
    store.link_meta_account("111", clinic["id"])
    assert store.client(clinic["id"])["ad_account"] == "111"
    store.link_meta_account("111", None)
    store.sync_meta_accounts([CLINIC])  # the next read
    assert store.meta_accounts()[0]["client"] is None
    # a row that already existed, unlinked, is never linked by a client made afterwards...
    store.save_client({"name": "Nova", "ad_account": "222"})
    store.sync_meta_accounts([CLINIC, BAKERY])  # the bakery is new now: it links
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["111"]["client"] is None and rows["222"]["client"]["name"] == "Nova"
    store.link_meta_account("222", None)
    store.save_client({"name": "Outra", "ad_account": "111"})
    store.sync_meta_accounts([CLINIC, BAKERY])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["111"]["client"] is None and rows["222"]["client"] is None
    # ...while a brand-new account whose id matches still does
    store.save_client({"name": "Terceira", "ad_account": "act_333"})
    store.sync_meta_accounts([CLINIC, BAKERY, {"id": "333", "name": "Terceira Ads"}])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["333"]["client"]["name"] == "Terceira" and rows["111"]["client"] is None


def test_link_fills_an_empty_ad_account_and_unlink_keeps_it(store):
    clinic = store.save_client({"name": "Clínica Bem Estar"})
    store.sync_meta_accounts([CLINIC, BAKERY])
    row = store.link_meta_account("act_111", clinic["id"], by=7)
    assert row["id"] == "111" and row["client"] == {"id": clinic["id"], "name": "Clínica Bem Estar"}
    assert store.client(clinic["id"])["ad_account"] == "111"
    # a second account for the same client: the field already says something, so it stays
    store.link_meta_account("222", clinic["id"])
    assert store.client(clinic["id"])["ad_account"] == "111"
    assert [a["id"] for a in store.client(clinic["id"])["meta_accounts"]] == ["111", "222"]
    # unlinking never clears the field
    row = store.link_meta_account("111", None)
    assert row["client"] is None
    assert store.client(clinic["id"])["ad_account"] == "111"
    assert [a["id"] for a in store.client(clinic["id"])["meta_accounts"]] == ["222"]
    # a client id as a string (JSON from a <select>) is fine
    assert store.link_meta_account("111", str(clinic["id"]))["client"]["id"] == clinic["id"]


def test_link_checks_the_account_and_the_client(store):
    store.sync_meta_accounts([CLINIC])
    with pytest.raises(NotFound):
        store.link_meta_account("999", None)
    for bad in (999, "x", 0, -1):
        with pytest.raises(Invalid):
            store.link_meta_account("111", bad)
    assert store.meta_accounts()[0]["client"] is None


def test_deleting_a_client_unlinks_its_accounts(store):
    clinic = store.save_client({"name": "Clínica Bem Estar"})
    store.sync_meta_accounts([CLINIC])
    store.link_meta_account("111", clinic["id"])
    store.delete_client(clinic["id"])
    rows = store.meta_accounts()
    assert len(rows) == 1 and rows[0]["client"] is None  # ON DELETE SET NULL


def test_suggestion_rules():
    clients = [(1, "Clínica Bem Estar"), (2, "Padaria Trigo de Ouro"), (3, "Zé"), (4, "Casa")]
    assert suggest("Clinica Bem-Estar", clients) == 1  # accents and punctuation don't matter
    assert suggest("CLÍNICA BEM ESTAR - Unidade 2", clients) == 1  # contains the client
    assert suggest("Bem Estar", clients) == 1  # the client contains it
    assert suggest("Trigo de Ouro Padaria", clients) == 2  # two shared words of 4+ letters
    assert suggest("Ouro Preto Imóveis", clients) is None  # one shared word is not enough
    assert suggest("Zé Lanches", clients) is None  # a 2-letter client name never matches
    assert suggest("Casa", clients) == 4
    assert suggest("Loja do Zé", clients) is None
    assert suggest("", clients) is None and suggest("abc", clients) is None
    assert suggest("Clínica Bem Estar", []) is None


def test_suggest_client_prefers_open_clients_and_is_never_saved(store):
    gone = store.save_client({"name": "Clínica Bem Estar", "state": "Encerrado"})
    live = store.save_client({"name": "Clínica Bem Estar Odonto"})
    store.sync_meta_accounts([CLINIC])
    assert store.suggest_client("Clínica Bem Estar") == live["id"]
    assert store.meta_accounts()[0]["client"] is None
    store.delete_client(live["id"])
    assert store.suggest_client("Clínica Bem Estar") == gone["id"]
    assert store.suggest_client("Nada a ver") is None


def test_schema_v7_gains_the_meta_account_table(tmp_path):
    Store(tmp_path / "old.db")  # a complete database...
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.executescript(  # ...as the previous release left it: no meta_account, version 7
        "DROP INDEX meta_account_client; DROP TABLE meta_account;"
        "UPDATE meta SET value='7' WHERE key='schema';"
        "INSERT INTO client(name, ad_account) VALUES ('Antigo', 'act_111');"
    )
    conn.commit()
    conn.close()
    store = Store(tmp_path / "old.db")
    with store.db() as db:
        version = db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0]
        assert version == str(SCHEMA_VERSION)
    assert store.meta_accounts() == []
    store.sync_meta_accounts([CLINIC])
    assert store.meta_accounts()[0]["client"]["name"] == "Antigo"
    assert store.clients()[0]["ad_account"] == "act_111"  # the field is never rewritten


def test_sync_keeps_the_time_zone_meta_reported(store):
    """The account's `timezone_name` ("today" is its day) is written when Meta sends it and
    kept when a later entry (an older caller) doesn't."""
    store.sync_meta_accounts([{**CLINIC, "timezone_name": "America/Sao_Paulo"}, BAKERY])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["111"]["timezone_name"] == "America/Sao_Paulo"
    assert rows["222"]["timezone_name"] == ""
    store.sync_meta_accounts([CLINIC, {**BAKERY, "timezone_name": "Europe/Lisbon"}])
    rows = {r["id"]: r for r in store.meta_accounts()}
    assert rows["111"]["timezone_name"] == "America/Sao_Paulo"
    assert rows["222"]["timezone_name"] == "Europe/Lisbon"
    store.sync_meta_accounts([{**CLINIC, "timezone_name": "x" * 80}])
    assert len(store.meta_accounts()[0]["timezone_name"]) == 60
