"""The Meta client against the fake Meta: the one-time state, the code exchange, reading ad
accounts in two calls (list + batch), money in cents, a refused balance, one account without
numbers, a revoked token, failures remembered, and never leaking the secret."""

import http.client
import json
import logging
import os
import stat
import threading
import time
import types
from urllib.parse import parse_qs, urlparse

import pytest

from fakemeta import APP_ID, BUSINESS, CONFIG_ID, SECRET, oauth_error, secret
from pauta import meta as meta_mod
from pauta.meta import (
    NO_BALANCE,
    NO_BALANCE_ANSWER,
    NO_BUSINESS,
    NO_NUMBERS,
    NOT_CONNECTED,
    REVOKED,
    THROTTLED,
    UNAVAILABLE,
    UNKNOWN_BUSINESS,
    Meta,
    MetaError,
    cents,
)


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
        "connections": [],
        "error": "",
        "accounts_at": None,
        "accounts_stale": True,
        "accounts_error": "",
    }
    assert m.connections() == [] and not m.error
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
    token_file = meta_on.token_file(BUSINESS)
    assert token_file.name == "pauta.db.meta-token.300000000000003"
    saved = json.loads(token_file.read_text())
    assert saved["access_token"] == fake_meta.token
    assert saved["business_id"] == "300000000000003"
    assert saved["business_name"] == "Agência Exemplo" and saved["by"] == 7
    assert saved["connected_at"].endswith("Z")
    assert saved["state"] == "ok" and saved["error"] == ""
    assert stat.S_IMODE(os.stat(token_file).st_mode) == 0o600
    st = meta_on.status()
    assert st["connected"] and st["error"] == ""
    assert st["connections"] == [
        {
            "business_id": BUSINESS,
            "business_name": "Agência Exemplo",
            "connected_at": saved["connected_at"],
            "by": 7,
            "state": "ok",
            "error": "",
        }
    ]
    assert fake_meta.token not in json.dumps(st) and SECRET not in json.dumps(st)
    meta_on.disconnect(BUSINESS)
    assert not token_file.exists() and not meta_on.status()["connected"]
    meta_on.disconnect(BUSINESS)  # already gone is fine
    meta_on.disconnect()  # and so is "everything" with nothing there


def test_without_a_business_id_the_system_user_names_and_keys_it(meta_on, fake_meta):
    fake_meta.business = None
    connect(meta_on, fake_meta)
    (conn,) = meta_on.connections()
    assert conn["business_name"] == "Pauta (usuário do sistema)"
    assert conn["business_id"] == "500000000000005"  # the system user's own id
    assert meta_on.token_file("500000000000005").exists()
    assert [a["id"] for a in meta_on.accounts()] == ["111", "222"]


def test_state_is_one_time_and_expires(meta_on, fake_meta, monkeypatch):
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect("forged", back["code"])
    assert e.value.status == 400 and e.value.reason == "expirou"
    meta_on.finish_connect(back["state"], back["code"])
    # the same callback loaded again (a reload, a retry): still connected, no second exchange
    meta_on.finish_connect(back["state"], back["code"])
    meta_on.finish_connect(back["state"], "another-code")
    assert fake_meta.exchanges == 1
    # ... for ten minutes; after that the state is just expired
    later = meta_mod.time.time() + 601
    monkeypatch.setattr(meta_mod.time, "time", lambda: later)
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(back["state"], back["code"])
    assert e.value.reason == "expirou"
    monkeypatch.undo()

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
        "timezone_name": "America/Sao_Paulo",
        "business_id": BUSINESS,
        "business_name": "Agência Exemplo",
        "numbers": True,
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
    linked.accounts(stale=False)  # past ten minutes: read again (a page gets the kept list)
    assert len(fake_meta.seen) == 3 * n - 4


def _settles(meta, after: float, seconds: float = 3.0) -> None:
    """Wait for the read behind a stale answer to land (or fail), without sleeping long."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        cached, failed = meta._cache, meta._failed
        landed = (cached and cached[0] > after) or (failed and failed[0] > after)
        if landed and not meta._reading.locked():  # and the thread has let go
            return
        time.sleep(0.01)
    raise AssertionError("the read behind the stale list never finished")


def test_after_ten_minutes_the_last_list_answers_while_meta_is_read_again(
    linked, fake_meta, monkeypatch
):
    first = linked.accounts()
    n = len(fake_meta.seen)
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    fake_meta.accounts[0] = {**fake_meta.accounts[0], "name": "Clínica Renomeada"}
    fake_meta.hold()
    assert linked.accounts() == first  # at once, from memory
    assert fake_meta.held.wait(2)  # while Meta is being asked behind it...
    assert linked.accounts() == first  # ...a second visitor doesn't start another read
    fake_meta.release()
    _settles(linked, now + 600)
    assert linked.accounts()[0]["name"] == "Clínica Renomeada"
    assert len(fake_meta.seen) == 2 * n - 2  # one read: everything but /me and the business


def test_the_sync_waits_for_the_new_list(linked, fake_meta, monkeypatch):
    linked.accounts()
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    fake_meta.accounts[0] = {**fake_meta.accounts[0], "name": "Clínica Renomeada"}
    assert linked.accounts(stale=False)[0]["name"] == "Clínica Renomeada"


def test_the_server_start_reads_the_list_before_any_page_asks(linked, fake_meta):
    """`warm()`: a new process has no list in memory; the read starts at once on a thread
    of its own, and a page arriving meanwhile waits for that same read, not a second one."""
    linked._cache = None  # as after a restart
    n = fake_meta.calls.count("GET /me/adaccounts")
    fake_meta.hold()
    started = time.time()
    linked.warm()
    assert fake_meta.held.wait(2) and linked._reading.locked()  # at Meta, nobody waiting
    fake_meta.release()
    _settles(linked, started)
    assert fake_meta.calls.count("GET /me/adaccounts") == n + 1
    assert [a["id"] for a in linked.accounts()] == ["111", "222"]
    assert fake_meta.calls.count("GET /me/adaccounts") == n + 1
    # nothing connected: nothing to read, no thread
    linked.disconnect()
    linked.warm()
    assert not linked._reading.locked()


def test_a_read_failing_behind_the_list_keeps_it(linked, fake_meta, monkeypatch):
    first = linked.accounts()
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    fake_meta.down = True
    assert linked.accounts() == first
    _settles(linked, now + 600)
    assert linked._failed is not None
    calls = len(fake_meta.calls)
    assert linked.accounts() == first  # still the list, and no retry inside the minute
    assert len(fake_meta.calls) == calls
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601 + meta_mod.FAIL_SECONDS)
    fake_meta.down = False
    assert linked.accounts() == first  # the minute is up: the list, and a read behind it
    _settles(linked, now + 601)
    assert linked._failed is None
    # a day-old list is not shown any more: the reader waits, and Meta being down is an error
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 2 * meta_mod.STALE_SECONDS)
    fake_meta.down = True
    with pytest.raises(MetaError):
        linked.accounts()


def test_a_list_read_across_a_connect_or_disconnect_is_not_kept(linked, monkeypatch):
    """The read started with the connections before the change: once more, then give up
    keeping it (the next reader reads again)."""
    reads = []

    def read_bumping(times):
        def _read():
            reads.append(1)
            if len(reads) <= times:
                linked._gen += 1  # a disconnect while Meta answered
            return [{"id": "111"}]

        return _read

    monkeypatch.setattr(linked, "_read", read_bumping(1))
    assert linked.accounts(stale=False) == [{"id": "111"}]
    assert len(reads) == 2 and linked._cache is not None  # the second read was clean
    linked._cache = None
    reads.clear()
    monkeypatch.setattr(linked, "_read", read_bumping(9))
    assert linked.accounts(stale=False) == [{"id": "111"}]
    assert len(reads) == 2 and linked._cache is None  # answered, not kept
    assert not linked._reading.locked()


def test_no_thread_to_read_behind_the_list_keeps_the_list_and_the_lock_free(linked, monkeypatch):
    first = linked.accounts()
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)

    class NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    # only the module's view of threading: the fake Graph server keeps its own threads
    monkeypatch.setattr(meta_mod, "threading", types.SimpleNamespace(Thread=NoThread))
    assert linked.accounts() == first
    assert not linked._reading.locked()
    monkeypatch.setattr(meta_mod, "threading", threading)
    assert linked.accounts(stale=False) == first  # a waiting reader isn't stuck behind it


def test_status_says_when_the_list_was_read(linked, monkeypatch):
    assert linked.status()["accounts_at"] is None and linked.status()["accounts_stale"]
    linked.accounts()
    assert linked.status()["accounts_at"].endswith("+00:00")
    assert not linked.status()["accounts_stale"] and linked.status()["accounts_error"] == ""
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    assert linked.status()["accounts_stale"]


def test_the_page_hears_stale_with_the_list_it_gets(linked, fake_meta):
    """The flag travels with the list: `status()` read a moment later can already say
    "fresh" (the read behind lands in milliseconds on a fast Meta), and a page told that
    about an old list never asks again."""
    first, stale = linked.accounts_served()
    assert first and stale is False
    fake_meta.hold()
    with linked._lock:
        linked._age_list()
    kept, stale = linked.accounts_served()
    assert kept == first and stale is True
    fake_meta.release()
    _settles(linked, meta_mod.time.time() - meta_mod.CACHE_SECONDS)
    assert linked.accounts_served() == (first, False)
    assert linked.accounts_served(stale=False)[1] is False  # a waiting read is fresh


def test_a_connect_or_disconnect_keeps_the_list_aged_instead_of_dropping_it(
    linked, fake_meta, monkeypatch
):
    """After a connect (or a disconnect, or a revocation) the next page used to wait for
    a full read of every portfolio: the kept list now answers at once, past its ten
    minutes, and Meta is read again behind it. A disconnected portfolio's accounts leave
    the kept list at once."""
    first = linked.accounts()
    assert first and not linked.status()["accounts_stale"]
    n = len(fake_meta.seen)
    fake_meta.hold()
    with linked._lock:
        linked._age_list()  # what finish_connect does
    assert linked.status()["accounts_stale"]
    assert linked.accounts() == first  # at once, and a read starts behind it
    assert fake_meta.held.wait(2)
    fake_meta.release()
    _settles(linked, meta_mod.time.time() - meta_mod.CACHE_SECONDS)
    assert not linked.status()["accounts_stale"]
    assert len(fake_meta.seen) == 2 * n - 2  # one read behind
    # a disconnect: that portfolio's accounts leave the kept list at once
    (business,) = {a["business_id"] for a in first}
    linked.disconnect(business)
    assert linked._cache is not None and linked._cache[1] == []
    assert not linked.connected


def test_balance_refused_is_not_an_error(linked, fake_meta, caplog):
    caplog.set_level(logging.INFO, logger="pauta")
    fake_meta.refuse_balance = True
    accs = linked.accounts()
    assert all(
        a["balance"] == {"available": False, "refused": True, "reason": NO_BALANCE} for a in accs
    )
    assert accs[0]["spend_cents"] == 123456 and not linked.error


def test_revoked_token_says_connect_again(linked, fake_meta):
    fake_meta.token_invalid = True
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 409 and str(e.value) == REVOKED
    st = linked.status()
    assert st["error"] == REVOKED and st["connected"]  # still there, to be reconnected
    assert st["connections"][0]["state"] == "revoked" and linked.error == REVOKED
    # the mark lives in the file: a restart still knows
    assert (
        Meta(linked.secret_file.with_suffix(""), APP_ID, CONFIG_ID).connections()[0]["state"]
        == "revoked"
    )
    fake_meta.token_invalid = False
    connect(linked, fake_meta)  # connecting again clears it
    assert linked.status()["error"] == "" and len(linked.accounts()) == 2
    assert linked.connections()[0]["state"] == "ok"


def test_revoked_while_reading_the_balance(linked, monkeypatch):
    """A 190 inside one batch item (the token died between the two calls) is still the
    whole list's problem, like a throttle in one item."""
    real = linked._batch

    def revoke_in_balance(reads, business_id):
        answers = real(reads, business_id)
        answers[1] = (400, oauth_error(190))
        return answers

    monkeypatch.setattr(linked, "_batch", revoke_in_balance)
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 409 and linked.error == REVOKED

    def throttle_in_insights(reads, business_id):
        answers = real(reads, business_id)
        answers[0] = (400, oauth_error(4))
        return answers

    linked._mark(BUSINESS, "ok", "")
    assert not linked.error
    monkeypatch.setattr(linked, "_batch", throttle_in_insights)
    with pytest.raises(MetaError) as e:
        linked.accounts(refresh=True)
    assert e.value.status == 503 and str(e.value) == THROTTLED


def test_batch_without_a_token_file(linked):
    with pytest.raises(MetaError) as e:  # a portfolio that isn't connected
        linked._batch(["act_111?fields=spend_cap"], "999")
    assert e.value.status == 409 and str(e.value) == UNKNOWN_BUSINESS
    linked.token_file(BUSINESS).unlink()
    with pytest.raises(MetaError) as e:
        linked._batch(["act_111?fields=spend_cap"], BUSINESS)
    assert e.value.status == 409 and str(e.value) == NOT_CONNECTED


def test_one_accounts_missing_numbers_dont_fail_the_list(linked, fake_meta, caplog):
    """Meta refusing the clinic's insights (400 #100) leaves the clinic without numbers
    and the bakery intact; the list is cached like any other."""
    caplog.set_level(logging.INFO, logger="pauta")
    fake_meta.fail_insights = {"111"}
    clinic, bakery = linked.accounts()
    assert clinic["numbers"] is False and clinic["reason"] == NO_NUMBERS
    for key in ("spend_cents", "impressions", "reach", "link_clicks", "cpc_cents"):
        assert clinic[key] is None, key
    assert clinic["balance"]["remaining_cents"] == 376544  # the balance read still worked
    assert bakery["numbers"] is True and bakery["spend_cents"] == 0
    assert not linked.error and "meta_numbers_missing" in caplog.text
    n = len(fake_meta.calls)
    assert linked.accounts()[0]["numbers"] is False and len(fake_meta.calls) == n
    # an item Meta gave up on (null in the batch answer): the same, balance included
    fake_meta.fail_insights = set()
    fake_meta.timeouts = {"222"}
    clinic, bakery = linked.accounts(refresh=True)
    assert clinic["numbers"] is True
    assert bakery["numbers"] is False and bakery["spend_cents"] is None
    assert bakery["balance"] == {"available": False, "reason": NO_BALANCE_ANSWER}


def test_a_cold_read_is_two_calls_and_batches_of_fifty(linked, fake_meta):
    before = len(fake_meta.calls)
    linked.accounts()
    assert fake_meta.calls[before:] == ["GET /me/adaccounts", "POST /"]
    # 26 accounts are 52 reads: the list, then two batches
    fake_meta.accounts = [
        {
            "id": f"act_{900 + i}",
            "account_id": str(900 + i),
            "name": f"Conta {i}",
            "currency": "BRL",
        }
        for i in range(26)
    ]
    before = len(fake_meta.calls)
    accs = linked.accounts(refresh=True)
    assert fake_meta.calls[before:] == ["GET /me/adaccounts", "POST /", "POST /"]
    assert len(accs) == 26 and accs[25]["id"] == "925" and accs[25]["status_label"] == ""


def test_the_account_list_is_paged(linked, fake_meta):
    """A portfolio with more than a hundred ad accounts: the list is followed page by page
    (Meta's `paging.cursors.after`), like the campaign list, so none is left out."""
    fake_meta.accounts = [
        {
            "id": f"act_{1000 + i}",
            "account_id": str(1000 + i),
            "name": f"Conta {i:03d}",
            "currency": "BRL",
            "account_status": 1,
        }
        for i in range(101)
    ]
    before = len(fake_meta.calls)
    accs = linked.accounts(refresh=True)
    assert len(accs) == 101 and [a["id"] for a in accs][::100] == ["1000", "1100"]
    assert len({a["id"] for a in accs}) == 101
    # two pages of the list, then 202 reads in five batches
    assert fake_meta.calls[before:] == ["GET /me/adaccounts"] * 2 + ["POST /"] * 5
    assert all(linked.business_of[a["id"]] == BUSINESS for a in accs)


def test_concurrent_cold_readers_share_one_read(linked, fake_meta):
    before = len(fake_meta.calls)
    results, errors = [], []
    ready = threading.Barrier(3)

    def read():
        try:
            ready.wait()
            results.append(linked.accounts())
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=read) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors and len(results) == 3
    assert fake_meta.calls[before:].count("GET /me/adaccounts") == 1
    assert fake_meta.calls[before:].count("POST /") == 1
    assert results[0] is results[1] is results[2]


def test_a_failed_read_is_remembered(linked, fake_meta, monkeypatch):
    """After a 190, a page full of client cards doesn't ask Meta again for a minute; the
    admin's refresh does; connecting or disconnecting forgets the failure."""
    fake_meta.token_invalid = True
    with pytest.raises(MetaError):
        linked.accounts()
    n = len(fake_meta.calls)
    for _ in range(3):
        with pytest.raises(MetaError) as e:
            linked.accounts()
        assert e.value.status == 409 and str(e.value) == REVOKED
    assert len(fake_meta.calls) == n
    with pytest.raises(MetaError):
        linked.accounts(refresh=True)
    assert len(fake_meta.calls) == n + 1
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 61)
    with pytest.raises(MetaError):
        linked.accounts()
    assert len(fake_meta.calls) == n + 2
    monkeypatch.undo()
    # disconnecting forgets it: the next answer is "not connected", not the old failure
    linked.disconnect()
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert str(e.value) == NOT_CONNECTED and len(fake_meta.calls) == n + 2
    # connecting again forgets it too (the fake says 190 until told otherwise)
    fake_meta.token_invalid = False
    connect(linked, fake_meta)
    assert len(linked.accounts()) == 2


def test_a_throttle_is_remembered_longer(linked, monkeypatch):
    calls = []

    def throttled(*a, **k):
        calls.append(a)
        return 400, {"error": {"code": 17}}

    monkeypatch.setattr(linked, "_get", throttled)
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 503
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 61)
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert str(e.value) == THROTTLED and len(calls) == 1
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 121)
    with pytest.raises(MetaError):
        linked.accounts()
    assert len(calls) == 2


def test_a_short_or_malformed_answer_is_unavailable(linked, fake_meta, monkeypatch):
    def cut_off(*a, **k):
        raise http.client.IncompleteRead(b"{")

    monkeypatch.setattr(meta_mod.urllib.request, "urlopen", cut_off)
    with pytest.raises(MetaError) as e:
        linked.accounts()
    assert e.value.status == 502 and str(e.value) == UNAVAILABLE


def test_business_id_must_be_digits(meta_on, fake_meta, monkeypatch):
    """The business id goes into a Graph path and a file name: anything but digits is never
    asked for, and the system user's id keys the connection instead."""
    fake_meta.business = "../me?fields=accounts"
    connect(meta_on, fake_meta)
    (conn,) = meta_on.connections()
    assert conn["business_id"] == "500000000000005"
    assert conn["business_name"] == "Pauta (usuário do sistema)"
    assert fake_meta.seen == ["/me"]
    files = {f.name for f in meta_on.secret_file.parent.iterdir() if "token" in f.name}
    assert files == {"pauta.db.meta-token.500000000000005"}
    # neither id: nothing to key the connection by, so nothing is saved
    real = meta_on._get

    def no_ids(path, params, token=None):
        status, doc = real(path, params, token)
        return (status, {"name": "x"}) if path == "/me" else (status, doc)

    monkeypatch.setattr(meta_on, "_get", no_ids)
    back = fake_meta.approve(meta_on.start_connect(1))
    with pytest.raises(MetaError) as e:
        meta_on.finish_connect(back["state"], back["code"])
    assert str(e.value) == NO_BUSINESS and len(meta_on.connections()) == 1


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
    with pytest.raises(MetaError) as e:
        linked._balance((500, {"error": "nope"}))
    assert e.value.status == 502
    assert Meta._code({"error": "text"}) is None and Meta._code([]) is None
    # the batch answer itself is odd: not a list, too short, items without a JSON body
    monkeypatch.setattr(linked, "_post", lambda *a, **k: (200, {"data": []}))
    with pytest.raises(MetaError) as e:
        linked._batch(["act_111?fields=spend_cap"], BUSINESS)
    assert e.value.status == 502
    monkeypatch.setattr(linked, "_post", lambda *a, **k: (200, [{"code": 200, "body": "{"}]))
    assert linked._batch(["a", "b"], BUSINESS) == [(200, {}), (None, {})]
    monkeypatch.setattr(linked, "_post", lambda *a, **k: (200, [{"code": "x", "body": "[]"}]))
    assert linked._batch(["a"], BUSINESS) == [(None, {})]


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
