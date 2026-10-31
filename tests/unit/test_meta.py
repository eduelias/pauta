"""The Meta client against the fake Meta: the one-time state, the code exchange, reading ad
accounts, money in cents, a refused balance, a revoked token, and never leaking the secret."""

import json
import logging
import os
import stat
from urllib.parse import parse_qs, urlparse

import pytest

from fakemeta import APP_ID, CONFIG_ID, SECRET, secret
from pauta import meta as meta_mod
from pauta.meta import NO_BALANCE, REVOKED, Meta, MetaError, cents


def connect(meta, fake, account=7):
    back = fake.approve(meta.start_connect(account))
    meta.finish_connect(back["state"], back["code"])


@pytest.fixture()
def linked(meta_on, fake_meta):
    connect(meta_on, fake_meta)
    return meta_on


def test_cents():
    assert cents("1234.56") == 123456
    assert cents("1.367176") == 137  # rounded half up
    assert cents("0.005") == 1 and cents("0.004") == 0
    assert cents("10") == 1000 and cents(3) == 300
    assert cents(None) is None and cents("") is None and cents("n/a") is None


def test_off_without_app_config_or_secret(store):
    assert not Meta(store.path).enabled
    m = Meta(store.path, app_id=APP_ID, config_id=CONFIG_ID)
    assert not m.enabled  # no secret file yet
    m.secret_file.write_text("\n")
    assert not m.enabled  # an empty one doesn't count
    secret(store.path)
    assert m.enabled and not m.connected
    assert not Meta(store.path, app_id=APP_ID).enabled  # no config id
    assert m.status() == {
        "enabled": True,
        "connected": False,
        "business_name": "",
        "connected_at": "",
        "error": "",
    }
    with pytest.raises(MetaError) as e:
        m.accounts()
    assert e.value.status == 409
    off = Meta(store.path)
    with pytest.raises(MetaError) as e:
        off.start_connect(1)
    assert e.value.status == 400 and e.value.reason == "desligado"
    with pytest.raises(MetaError) as e:
        off.finish_connect("x", "y")
    assert e.value.reason == "desligado"


def test_from_env(store, monkeypatch):
    secret(store.path)
    monkeypatch.setenv("PAUTA_META_APP_ID", APP_ID)
    monkeypatch.setenv("PAUTA_META_CONFIG_ID", CONFIG_ID)
    monkeypatch.setenv("PAUTA_ORIGIN", " https://acc.pauta.cc/ , https://pauta.cc")
    m = Meta.from_env(store.path)
    assert m.enabled and m.redirect_uri == "https://acc.pauta.cc/api/meta/callback"
    assert m.graph == "https://graph.facebook.com/v26.0"
    assert m.dialog == "https://www.facebook.com/v26.0/dialog/oauth"
    monkeypatch.delenv("PAUTA_ORIGIN")
    assert Meta.from_env(store.path).redirect_uri == "http://localhost:8088/api/meta/callback"


def test_dialog_url(meta_on):
    url = meta_on.start_connect(7)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert url.startswith(meta_on.dialog + "?")
    assert q == {
        "client_id": APP_ID,
        "config_id": CONFIG_ID,
        "response_type": "code",
        "override_default_response_type": "true",
        "redirect_uri": "http://localhost:8088/api/meta/callback",
        "state": q["state"],
    }
    assert len(q["state"]) >= 40
    assert SECRET not in url


def test_connect_saves_the_token_privately(meta_on, fake_meta):
    connect(meta_on, fake_meta, account=7)
    saved = json.loads(meta_on.token_file.read_text())
    assert saved["access_token"] == fake_meta.token
    assert saved["business_id"] == "300000000000003"
    assert saved["business_name"] == "Agência Exemplo" and saved["by"] == 7
    assert saved["connected_at"].endswith("Z")
    assert stat.S_IMODE(os.stat(meta_on.token_file).st_mode) == 0o600
    st = meta_on.status()
    assert st["connected"] and st["business_name"] == "Agência Exemplo"
    assert fake_meta.token not in json.dumps(st) and SECRET not in json.dumps(st)
    meta_on.disconnect()
    assert not meta_on.token_file.exists() and not meta_on.status()["connected"]
    meta_on.disconnect()  # already gone is fine


def test_without_a_business_id_the_system_user_names_it(meta_on, fake_meta):
    fake_meta.business = None
    connect(meta_on, fake_meta)
    assert meta_on.status()["business_name"] == "Pauta (usuário do sistema)"


def test_state_is_one_time_and_expires(meta_on, fake_meta, monkeypatch):
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect("forged", back["code"])
    assert e.value.status == 400 and e.value.reason == "expirou"
    meta_on.finish_connect(back["state"], back["code"])
    with pytest.raises(MetaError) as e:  # the same state twice
        meta_on.finish_connect(back["state"], back["code"])
    assert e.value.reason == "expirou"
    assert fake_meta.exchanges == 1

    back = fake_meta.approve(meta_on.start_connect(1))
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(back["state"], back["code"])
    assert e.value.reason == "expirou" and fake_meta.exchanges == 1


def test_pending_states_are_capped(meta_on, monkeypatch):
    monkeypatch.setattr(meta_mod, "MAX_PENDING", 3)
    first = parse_qs(urlparse(meta_on.start_connect(1)).query)["state"][0]
    for _ in range(3):
        meta_on.start_connect(1)
    assert len(meta_on._states) == 3 and first not in meta_on._states


def test_refused_code_or_missing_code(meta_on, fake_meta):
    url = meta_on.start_connect(1)
    state = parse_qs(urlparse(url).query)["state"][0]
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(state, "")
    assert e.value.status == 400
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(back["state"], "code-forged")
    assert e.value.status == 502 and not meta_on.connected
    assert SECRET not in str(e.value) and "code-forged" not in str(e.value)


def test_wrong_secret_is_refused(meta_on, fake_meta):
    meta_on.secret_file.write_text("not-the-secret")
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError):
        meta_on.finish_connect(back["state"], back["code"])
    assert fake_meta.exchanges == 0


def test_accounts_this_month_in_cents(linked, fake_meta):
    accs = linked.accounts()
    assert [a["id"] for a in accs] == ["111", "222"]
    clinic, bakery = accs
    assert clinic == {
        "id": "111",
        "name": "Clínica Bem Estar",
        "currency": "BRL",
        "status": 1,
        "status_label": "Ativa",
        "business": "Clínica Bem Estar Ltda",
        "spend_cents": 123456,
        "impressions": 48210,
        "reach": 20118,
        "link_clicks": 903,
        "cpc_cents": 137,
        "balance": {
            "available": True,
            "prepay": True,
            "funding": "Saldo disponível",
            "spend_cap_cents": 500000,
            "amount_spent_cents": 123456,
            "remaining_cents": 376544,
        },
    }
    # no numbers this month: zeros, no cost per click; no spending limit: nothing remaining
    assert bakery["spend_cents"] == bakery["reach"] == bakery["link_clicks"] == 0
    assert bakery["cpc_cents"] is None and bakery["status_label"] == "Desativada"
    assert bakery["balance"]["remaining_cents"] is None
    assert bakery["balance"]["spend_cap_cents"] is None and not bakery["balance"]["prepay"]


def test_accounts_are_cached_for_ten_minutes(linked, fake_meta, monkeypatch):
    linked.accounts()
    n = len(fake_meta.seen)
    linked.accounts()
    assert len(fake_meta.seen) == n
    linked.accounts(refresh=True)
    assert len(fake_meta.seen) == 2 * n - 2  # everything again but /me and the business
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    linked.accounts()
    assert len(fake_meta.seen) == 3 * n - 4


def test_balance_refused_is_not_an_error(linked, fake_meta, caplog):
    caplog.set_level(logging.INFO, logger="pauta")
    fake_meta.refuse_balance = True
    accs = linked.accounts()
    assert all(a["balance"] == {"available": False, "reason": NO_BALANCE} for a in accs)
    assert accs[0]["spend_cents"] == 123456 and not linked.error


def test_revoked_token_says_connect_again(linked, fake_meta):
    fake_meta.token_invalid = True
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 409 and str(e.value) == REVOKED
    assert linked.status()["error"] == REVOKED and linked.status()["connected"]
    fake_meta.token_invalid = False
    connect(linked, fake_meta)  # connecting again clears it
    assert linked.status()["error"] == "" and len(linked.accounts()) == 2


def test_revoked_while_reading_the_balance(linked, fake_meta, monkeypatch):
    real = linked._get

    def revoke_on_balance(path, params, token=None):
        if path == "/act_111" and token:
            fake_meta.token_invalid = True
        return real(path, params, token)

    monkeypatch.setattr(linked, "_get", revoke_on_balance)
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 409


def test_balance_without_a_token_file(linked):
    linked.token_file.unlink()
    with pytest.raises(MetaError) as e:
        linked._balance("111")
    assert e.value.status == 409


def test_meta_down_or_unreachable(linked, fake_meta, store):
    fake_meta.down = True
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 502 and not linked.error
    fake_meta.down = False
    gone = Meta(store.path, app_id=APP_ID, config_id=CONFIG_ID, graph="http://127.0.0.1:9/v26.0")
    with pytest.raises(MetaError) as e:
        gone.accounts()
    assert e.value.status == 502
    back = fake_meta.approve(gone.start_connect(1))
    with pytest.raises(MetaError) as e:
        gone.finish_connect(back["state"], back["code"])
    assert e.value.status == 502


def test_me_refused_after_exchange(meta_on, fake_meta, monkeypatch):
    real = meta_on._get

    def me_fails(path, params, token=None):
        if path == "/me":
            fake_meta.token_invalid = True
        return real(path, params, token)

    monkeypatch.setattr(meta_on, "_get", me_fails)
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(back["state"], back["code"])
    assert e.value.status == 409 and not meta_on.connected


def test_throttled(linked, monkeypatch):
    for code in (17, 80004):
        monkeypatch.setattr(linked, "_get", lambda *a, c=code, **k: (400, {"error": {"code": c}}))
        with pytest.raises(MetaError) as e:
            linked.accounts(refresh=True)
        assert e.value.status == 503


def test_odd_answers(linked, monkeypatch):
    monkeypatch.setattr(linked, "_get", lambda *a, **k: (500, {"error": "nope"}))
    with pytest.raises(MetaError) as e:
        linked._balance("111")
    assert e.value.status == 502
    assert Meta._code({"error": "text"}) is None


def test_logs_never_carry_the_token_code_or_secret(meta_on, fake_meta, caplog):
    caplog.set_level(logging.DEBUG, logger="pauta")
    back = fake_meta.approve(meta_on.start_connect(1))
    meta_on.finish_connect(back["state"], back["code"])
    meta_on.accounts()
    fake_meta.token_invalid = True
    with pytest.raises(MetaError):
        meta_on.accounts(refresh=True)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "meta_connected" in text and "meta_revoked" in text
    for secret_value in (SECRET, fake_meta.token, back["code"], back["state"]):
        assert secret_value not in text
