"""Connecting Meta over real HTTP: the round trip through Meta's login (the fake one in
tests/fakemeta.py), the cookie-less callback, one connection per portfolio (connect another,
add accounts to one, disconnect one, the history), reading ad accounts, who may do what,
/metrics."""

import json
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from fakemeta import BUSINESS, OTHER_BUSINESS, SECRET, fetch
from pauta import meta as meta_mod
from pauta.meta import NO_NUMBERS, REVOKED
from pauta.server import META_DOWN
from softpasskey import call


@pytest.fixture()
def meta(meta_on):
    return meta_on


def start(base, nato, business_id=None):
    body = {"business_id": business_id} if business_id else {}
    status, doc, _ = call(f"{base}/api/meta/connect", body, nato)
    assert status == 200, doc
    return doc["url"]


def through_meta(base, url):
    """The browser at Meta's dialog, approved: Meta's redirect, then Pauta's (no cookie)."""
    status, location, _ = fetch(url)
    assert status == 302
    back = urlparse(location)
    assert back.path == "/api/meta/callback"
    return fetch(f"{base}/api/meta/callback?{back.query}")


def test_connect_round_trip(team, fake_meta):
    base, nato, piero, _ = team
    assert call(f"{base}/api/boot", cookie=piero)[1]["meta"] == {"enabled": True}
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert doc == {
        "enabled": True,
        "connected": False,
        "connections": [],
        "error": "",
        "accounts_at": None,
    }
    url = start(base, nato)
    assert url.startswith(fake_meta.dialog)
    status, location, _ = through_meta(base, url)
    assert status == 302 and location == "/#/configuracoes?meta=conectado"

    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert doc["connected"] and doc["error"] == ""
    (conn,) = doc["connections"]
    assert conn == {
        "business_id": BUSINESS,
        "business_name": "Agência Exemplo",
        "connected_at": conn["connected_at"],
        "by": 1,
        "by_name": "Renato Lima",
        "state": "ok",
        "error": "",
        "last_sync": None,
    }
    assert [a["name"] for a in doc["accounts"]] == ["Clínica Bem Estar", "Padaria Trigo de Ouro"]
    assert doc["accounts"][0]["spend_cents"] == 123456
    assert all(a["business_id"] == BUSINESS for a in doc["accounts"])
    assert all(a["business_name"] == "Agência Exemplo" for a in doc["accounts"])
    text = json.dumps(doc)
    assert fake_meta.token not in text and SECRET not in text
    # the history: who connected what
    (line,) = call(f"{base}/api/meta/log", cookie=nato)[1]
    assert line["kind"] == "connected" and line["business_id"] == BUSINESS
    assert line["by"] == {"id": 1, "name": "Renato Lima"}
    assert line["detail"] == {"business_name": "Agência Exemplo"} and len(line["at"]) == 19

    # cached, unless asked to refresh
    seen = len(fake_meta.seen)
    call(f"{base}/api/meta", cookie=nato)
    assert len(fake_meta.seen) == seen
    call(f"{base}/api/meta?refresh=1", cookie=nato)
    assert len(fake_meta.seen) > seen

    status, doc, _ = call(f"{base}/api/meta/connections/{BUSINESS}", cookie=nato, method="DELETE")
    assert status == 200 and not doc["connected"] and doc["connections"] == []
    assert "accounts" not in call(f"{base}/api/meta", cookie=nato)[1]
    assert call(f"{base}/api/meta/connections/{BUSINESS}", cookie=nato, method="DELETE")[0] == 404
    kinds = [e["kind"] for e in call(f"{base}/api/meta/log", cookie=nato)[1]]
    assert kinds == ["disconnected", "connected"]
    assert call(f"{base}/api/export", cookie=nato)[1]["meta_connection"] == []
    exported = call(f"{base}/api/export", cookie=nato)[1]["meta_log"]
    assert [e["kind"] for e in exported] == ["connected", "disconnected"]
    assert exported[0]["detail"] == {"business_name": "Agência Exemplo"}


def test_callback_needs_a_live_state(team, fake_meta, monkeypatch):
    base, nato, _, _ = team
    erro = "/#/configuracoes?meta=erro&motivo="
    # nobody started it
    status, location, _ = fetch(f"{base}/api/meta/callback?code=x&state=forged")
    assert status == 302 and location == erro + "expirou"
    # started, and the callback loaded twice (Piero's browser did): connected both times
    url = start(base, nato)
    first = urlparse(fetch(url)[1]).query
    assert fetch(f"{base}/api/meta/callback?{first}")[1] == "/#/configuracoes?meta=conectado"
    assert fetch(f"{base}/api/meta/callback?{first}")[1] == "/#/configuracoes?meta=conectado"
    # started, but too long ago
    query = urlparse(fetch(start(base, nato))[1]).query
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    assert fetch(f"{base}/api/meta/callback?{query}")[1] == erro + "expirou"
    assert fake_meta.exchanges == 1


def test_callback_when_cancelled_or_meta_refuses(team, fake_meta):
    base, nato, _, _ = team
    erro = "/#/configuracoes?meta=erro&motivo="
    fake_meta.deny = True
    status, location, _ = through_meta(base, start(base, nato))
    assert location == erro + "cancelado"
    fake_meta.deny = False
    # the state from the cancelled attempt is gone too, and a bad code is Meta's refusal
    state = parse_qs(urlparse(start(base, nato)).query)["state"][0]
    query = urlencode({"code": "<script>", "state": state})
    status, location, body = fetch(f"{base}/api/meta/callback?{query}")
    assert location == erro + "meta" and b"script" not in body
    assert fetch(f"{base}/api/meta/callback")[1] == erro + "cancelado"
    assert not call(f"{base}/api/meta", cookie=nato)[1]["connected"]


def test_members_and_strangers(team):
    base, nato, piero, _ = team
    assert call(f"{base}/api/meta", cookie=piero)[0] == 403
    assert call(f"{base}/api/meta/connect", {}, piero)[0] == 403
    assert call(f"{base}/api/meta/connections/{BUSINESS}", cookie=piero, method="DELETE")[0] == 403
    assert call(f"{base}/api/meta/log", cookie=piero)[0] == 403
    assert call(f"{base}/api/meta")[0] == 401
    assert call(f"{base}/api/meta/connect", {})[0] == 401
    assert call(f"{base}/api/meta/log")[0] == 401
    assert call(f"{base}/api/meta", cookie=nato, method="DELETE")[0] == 404  # the old route
    # a write from another site is refused before anything else
    status, doc, _ = call(
        f"{base}/api/meta/connect", {}, nato, headers={"Origin": "https://evil.example"}
    )
    assert status == 403


def test_revoked_token_is_reported_on_its_connection(team, fake_meta):
    """The page never fails: the error, the connection's state and the accounts Pauta
    already knew (stale) come back together, so the admin sees what to reconnect."""
    base, nato, _, _ = team
    through_meta(base, start(base, nato))
    call(f"{base}/api/meta", cookie=nato)  # the rows exist
    fake_meta.token_invalid = True
    status, doc, _ = call(f"{base}/api/meta?refresh=1", cookie=nato)
    assert status == 200 and doc["error"] == REVOKED and doc["connected"]
    assert doc["connections"][0]["state"] == "revoked"
    assert doc["connections"][0]["error"] == REVOKED
    assert [(a["id"], a["stale"]) for a in doc["accounts"]] == [("111", True), ("222", True)]
    assert doc["accounts"][0]["business_name"] == "Agência Exemplo"
    assert call(f"{base}/metrics")[1]["meta"] == {
        "enabled": True,
        "connected": False,
        "connections": 1,
        "revoked": 1,
        "error": REVOKED,
        "last_sync": None,
        "sync_error": "",
        "syncing": False,
    }
    kinds = [e["kind"] for e in call(f"{base}/api/meta/log", cookie=nato)[1]]
    assert kinds == ["revoked", "connected"]
    # reconnecting it (Adicionar contas) clears the state
    fake_meta.token_invalid = False
    through_meta(base, start(base, nato, BUSINESS))
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert doc["error"] == "" and doc["connections"][0]["state"] == "ok"
    assert call(f"{base}/metrics")[1]["meta"]["connected"] is True


def test_metrics(team, fake_meta):
    base, nato, _, _ = team
    assert call(f"{base}/metrics")[1]["meta"] == {
        "enabled": True,
        "connected": False,
        "connections": 0,
        "revoked": 0,
        "error": "",
        "last_sync": None,
        "sync_error": "",
        "syncing": False,
    }
    through_meta(base, start(base, nato))
    fake_meta.business = OTHER_BUSINESS
    through_meta(base, start(base, nato))
    doc = call(f"{base}/metrics")[1]["meta"]
    assert doc["connected"] is True and doc["connections"] == 2 and doc["revoked"] == 0
    fake_meta.revoke(OTHER_BUSINESS)
    call(f"{base}/api/meta?refresh=1", cookie=nato)
    doc = call(f"{base}/metrics")[1]["meta"]
    assert doc["connected"] is True and doc["connections"] == 2 and doc["revoked"] == 1
    assert doc["error"] == REVOKED


def test_two_portfolios(team, fake_meta):
    """Piero connects the agency's portfolio, then a client's own one: two connections, the
    accounts of both (each saying whose), "Adicionar contas" on one, and disconnecting one
    leaves the other and keeps the disconnected one's accounts as rows."""
    base, nato, piero, _ = team
    through_meta(base, start(base, nato))
    fake_meta.business = OTHER_BUSINESS
    through_meta(base, start(base, nato))
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert [(c["business_id"], c["business_name"]) for c in doc["connections"]] == [
        (BUSINESS, "Agência Exemplo"),
        (OTHER_BUSINESS, "Delta Imóveis"),
    ]
    assert [(a["id"], a["business_name"]) for a in doc["accounts"]] == [
        ("111", "Agência Exemplo"),
        ("222", "Agência Exemplo"),
        ("444", "Delta Imóveis"),
    ]
    rows = call(f"{base}/api/export", cookie=nato)[1]["meta_account"]
    assert {r["id"]: r["business_id"] for r in rows} == {
        "111": BUSINESS,
        "222": BUSINESS,
        "444": OTHER_BUSINESS,
    }
    # "Adicionar contas" on the client's portfolio: a re-login on it, the agency untouched
    exchanges = fake_meta.exchanges
    status, location, _ = through_meta(base, start(base, nato, OTHER_BUSINESS))
    assert location == "/#/configuracoes?meta=conectado" and fake_meta.exchanges == exchanges + 1
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert len(doc["connections"]) == 2
    # ...and on a portfolio that isn't connected, or with a bad id
    status, out, _ = call(f"{base}/api/meta/connect", {"business_id": "999"}, nato)
    assert status == 404
    status, out, _ = call(f"{base}/api/meta/connect", {"business_id": "../x"}, nato)
    assert status == 400
    status, out, _ = call(f"{base}/api/meta/connect", {"business_id": 5}, nato)
    assert status == 400
    # started on the agency, but Piero picked the client's portfolio in Meta's dialog: it is
    # saved under its own business, nothing overwritten (fake.business is still OTHER)
    through_meta(base, start(base, nato, BUSINESS))
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert [c["business_id"] for c in doc["connections"]] == [BUSINESS, OTHER_BUSINESS]
    assert len(fake_meta.tokens_of(BUSINESS)) == 1 and len(fake_meta.tokens_of(OTHER_BUSINESS)) == 3

    # disconnect the client's portfolio: its account stays as a row, stale
    status, doc, _ = call(
        f"{base}/api/meta/connections/{OTHER_BUSINESS}", cookie=nato, method="DELETE"
    )
    assert status == 200 and [c["business_id"] for c in doc["connections"]] == [BUSINESS]
    doc = call(f"{base}/api/meta?refresh=1", cookie=nato)[1]
    assert [(a["id"], a["stale"], a["business_name"]) for a in doc["accounts"]] == [
        ("111", False, "Agência Exemplo"),
        ("222", False, "Agência Exemplo"),
        ("444", True, ""),
    ]
    assert call(f"{base}/api/meta/connections/legacy", cookie=nato, method="DELETE")[0] == 404
    kinds = [e["kind"] for e in call(f"{base}/api/meta/log", cookie=nato)[1]]
    assert kinds == ["disconnected"] + ["connected"] * 4
    assert all(
        e["by"]["name"] == "Renato Lima" for e in call(f"{base}/api/meta/log", cookie=nato)[1]
    )


# ---- the account ↔ client mapping ---------------------------------------------------------


def connected(team, fake_meta):
    base, nato, piero, _ = team
    through_meta(base, start(base, nato))
    return base, nato, piero


def new_client(base, nato, **data):
    status, doc, _ = call(f"{base}/api/clients", data, nato)
    assert status == 200, doc
    return doc


def test_accounts_carry_their_client_and_a_suggestion(team, fake_meta):
    base, nato, piero = connected(team, fake_meta)
    clinic = new_client(base, nato, name="Clínica Bem Estar")
    bakery = new_client(base, nato, name="Padaria", ad_account="act_222")
    doc = call(f"{base}/api/meta?refresh=1", cookie=nato)[1]
    first, second = doc["accounts"]
    # suggested by name, not saved; auto-linked by the client's ad_account
    assert first["client"] is None and not first["stale"]
    assert first["suggested"] == {"id": clinic["id"], "name": "Clínica Bem Estar"}
    assert second["client"] == {"id": bakery["id"], "name": "Padaria"}
    assert second["suggested"] is None
    assert second["spend_cents"] == 0 and second["status_label"] == "Desativada"
    assert call(f"{base}/api/clients/{bakery['id']}", cookie=piero)[1]["meta_accounts"] == [
        {"id": "222", "name": "Padaria Trigo de Ouro"}
    ]
    assert call(f"{base}/api/clients/{clinic['id']}", cookie=piero)[1]["meta_accounts"] == []

    # the export carries the table
    rows = call(f"{base}/api/export", cookie=nato)[1]["meta_account"]
    assert [(r["id"], r["client"]) for r in rows] == [
        ("111", None),
        ("222", {"id": bakery["id"], "name": "Padaria"}),
    ]
    assert all(r["business_id"] == BUSINESS for r in rows)

    # the bakery's account is unticked in Meta: its row stays, greyed, without numbers
    fake_meta.accounts = fake_meta.accounts[:1]
    doc = call(f"{base}/api/meta?refresh=1", cookie=nato)[1]
    assert [a["id"] for a in doc["accounts"]] == ["111", "222"]
    gone = doc["accounts"][1]
    assert gone["stale"] and gone["client"]["id"] == bakery["id"] and gone["suggested"] is None
    assert gone["name"] == "Padaria Trigo de Ouro" and gone["status_label"] == "Desativada"
    assert "spend_cents" not in gone and gone["seen"]


def test_linking_an_account(team, fake_meta):
    base, nato, piero = connected(team, fake_meta)
    clinic = new_client(base, nato, name="Clínica Bem Estar")
    call(f"{base}/api/meta", cookie=nato)  # the first read creates the rows
    status, row, _ = call(
        f"{base}/api/meta/accounts/111", {"client": clinic["id"]}, nato, method="PATCH"
    )
    assert status == 200
    assert row["id"] == "111" and row["client"] == {"id": clinic["id"], "name": "Clínica Bem Estar"}
    assert row["name"] == "Clínica Bem Estar" and row["currency"] == "BRL" and row["seen"]
    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert doc["accounts"][0]["client"]["id"] == clinic["id"]
    assert doc["accounts"][0]["suggested"] is None
    assert call(f"{base}/api/clients/{clinic['id']}", cookie=nato)[1]["ad_account"] == "111"

    status, row, _ = call(f"{base}/api/meta/accounts/111", {"client": None}, nato, method="PATCH")
    assert status == 200 and row["client"] is None
    assert call(f"{base}/api/clients/{clinic['id']}", cookie=nato)[1]["ad_account"] == "111"
    # the history says who linked and unlinked what
    log = call(f"{base}/api/meta/log", cookie=nato)[1]
    assert [(e["kind"], e["by"]["name"], e["business_id"]) for e in log] == [
        ("unlinked", "Renato Lima", BUSINESS),
        ("linked", "Renato Lima", BUSINESS),
        ("connected", "Renato Lima", BUSINESS),
    ]
    assert log[1]["detail"] == {
        "account_id": "111",
        "account_name": "Clínica Bem Estar",
        "client_name": "Clínica Bem Estar",
    }
    assert log[0]["detail"] == {"account_id": "111", "account_name": "Clínica Bem Estar"}
    # the next read (which syncs the rows) doesn't undo the unlink through that field
    doc = call(f"{base}/api/meta?refresh=1", cookie=nato)[1]
    assert doc["accounts"][0]["client"] is None
    assert call(f"{base}/api/clients/{clinic['id']}", cookie=nato)[1]["meta_accounts"] == []

    # who may, and what is refused
    status, doc, _ = call(f"{base}/api/meta/accounts/111", {"client": 1}, piero, method="PATCH")
    assert status == 403
    status, doc, _ = call(f"{base}/api/meta/accounts/999", {"client": 1}, nato, method="PATCH")
    assert status == 404 and "conta" in doc["error"]
    status, doc, _ = call(f"{base}/api/meta/accounts/111", {"client": 999}, nato, method="PATCH")
    assert status == 400 and "cliente" in doc["error"]
    status, doc, _ = call(f"{base}/api/meta/accounts/111", {}, nato, method="PATCH")
    assert status == 400
    assert call(f"{base}/api/meta/accounts/11", {"client": 1}, nato, method="PATCH")[0] == 404
    assert call(f"{base}/api/meta/accounts/111", {"client": 1}, method="PATCH")[0] == 401


def test_the_clients_meta_numbers(team, fake_meta):
    base, nato, piero, _ = team
    clinic = new_client(base, nato, name="Clínica Bem Estar")
    bakery = new_client(base, nato, name="Padaria", ad_account="222")
    # not connected yet: no error, just nothing
    status, doc, _ = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)
    assert status == 200 and doc == {"connected": False, "accounts": []}
    through_meta(base, start(base, nato))
    # connected, cache cold: the member's request reads Meta (and syncs the rows: the
    # bakery auto-links); the clinic has nothing linked yet
    status, doc, _ = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)
    assert status == 200 and doc == {"connected": True, "accounts": []}
    status, doc, _ = call(f"{base}/api/clients/{bakery['id']}/meta", cookie=piero)
    assert status == 200 and doc["connected"]
    assert [(a["id"], a["stale"]) for a in doc["accounts"]] == [("222", False)]
    assert doc["accounts"][0]["name"] == "Padaria Trigo de Ouro"
    call(f"{base}/api/meta/accounts/111", {"client": clinic["id"]}, nato, method="PATCH")
    seen = len(fake_meta.seen)
    doc = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)[1]
    assert len(fake_meta.seen) == seen  # from the cache
    (acc,) = doc["accounts"]
    assert acc["spend_cents"] == 123456 and acc["reach"] == 20118 and acc["cpc_cents"] == 137
    assert acc["balance"]["remaining_cents"] == 376544 and not acc["stale"]
    assert fake_meta.token not in json.dumps(doc)
    # the account left Meta's list: shown as stale, without numbers
    fake_meta.accounts = fake_meta.accounts[1:]
    call(f"{base}/api/meta?refresh=1", cookie=nato)
    (acc,) = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)[1]["accounts"]
    assert acc["stale"] and acc["name"] == "Clínica Bem Estar" and "spend_cents" not in acc
    # Meta's trouble is reported on a client with accounts, not on one without; 404 unknown.
    # A member gets a neutral line (never "conecte de novo"), an admin the reason, and the
    # failure is remembered: the client pages don't ask Meta again
    nobody = new_client(base, nato, name="Sem conta")
    fake_meta.token_invalid = True
    assert call(f"{base}/api/meta?refresh=1", cookie=nato)[1]["error"] == REVOKED
    n = len(fake_meta.calls)
    for _ in range(3):
        status, doc, _ = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)
        assert status == 200
        assert doc == {"connected": True, "accounts": [], "error": META_DOWN}
    status, doc, _ = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=nato)
    assert status == 200 and doc == {"connected": True, "accounts": [], "error": REVOKED}
    assert len(fake_meta.calls) == n
    status, doc, _ = call(f"{base}/api/clients/{nobody['id']}/meta", cookie=piero)
    assert status == 200 and doc == {"connected": True, "accounts": []}
    assert call(f"{base}/api/clients/999/meta", cookie=piero)[0] == 404
    assert call(f"{base}/api/clients/{clinic['id']}/meta")[0] == 401


def test_one_account_without_numbers(team, fake_meta):
    base, nato, piero = connected(team, fake_meta)
    clinic = new_client(base, nato, name="Clínica", ad_account="111")
    fake_meta.fail_insights = {"111"}
    doc = call(f"{base}/api/meta?refresh=1", cookie=nato)[1]
    first, second = doc["accounts"]
    assert first["numbers"] is False and first["reason"] == NO_NUMBERS
    assert first["spend_cents"] is None and first["balance"]["available"]
    assert second["numbers"] is True and second["spend_cents"] == 0
    (acc,) = call(f"{base}/api/clients/{clinic['id']}/meta", cookie=piero)[1]["accounts"]
    assert acc["numbers"] is False and acc["reason"] == NO_NUMBERS and not acc["stale"]
