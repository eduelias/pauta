"""Notifications over HTTP: a device switches them on, the others' changes wake it through
the (fake) push service with an empty push, and it reads what to show as its person."""

import json
import logging

import pytest

from appserver import serve
from fakepush import FakePush
from pauta.push import Push
from softpasskey import call


@pytest.fixture()
def fake_push():
    f = FakePush()
    yield f
    f.close()


@pytest.fixture()
def site(store, auth, drive, meta, fake_push):
    """The shared `site`, with the push service on the fake (so `team` signs in here)."""
    push = Push(store, contact="https://app.pauta.cc", services=(fake_push.host,), scheme="http")
    httpd = serve(store, auth, drive, meta, push)
    yield f"http://127.0.0.1:{httpd.server_address[1]}", auth, store
    httpd.shutdown()
    httpd.server_close()


def on(base, cookie, endpoint):
    status, doc, _ = call(f"{base}/api/push", {"endpoint": endpoint}, cookie)
    assert (status, doc) == (200, {"ok": True})


def news(base, cookie, endpoint):
    status, doc, _ = call(f"{base}/api/push/news", {"endpoint": endpoint}, cookie)
    assert status == 200, doc
    return doc["news"]


def a_request(base, cookie, **extra):
    client = call(f"{base}/api/clients", {"name": "Clínica Bem Estar"}, cookie)[1]
    body = {"client": client["id"], "what": "Campanha de Natal", **extra}
    status, doc, _ = call(f"{base}/api/requests", body, cookie)
    assert status == 200, doc
    return doc


def test_a_new_request_wakes_the_other_persons_device_and_only_that(team, fake_push):
    base, nato, piero, _ = team
    phone, laptop = fake_push.endpoint("piero-phone"), fake_push.endpoint("nato-laptop")
    on(base, piero, phone)
    on(base, nato, laptop)
    req = a_request(base, nato, kind="Criar campanha")
    assert fake_push.wait(1) == ["piero-phone"]
    sent = fake_push.pushes[0]
    # nothing of the team's data leaves: no body at all, a signature and how long to keep it
    assert sent["body"] == b"" and sent["ttl"] == "86400"
    assert sent["authorization"].startswith("vapid t=") and ", k=" in sent["authorization"]
    assert news(base, piero, phone) == [
        {
            "title": "Novo pedido · Clínica Bem Estar",
            "body": "Criar campanha: Campanha de Natal",
            "url": f"/#/pedido/{req['id']}",
            "tag": f"pedido-{req['id']}",
        }
    ]
    # Piero answers: now it is Renato's laptop that hears, twice
    patch = {"status": "waiting", "missing": "o vídeo"}
    assert call(f"{base}/api/requests/{req['id']}", patch, piero, "PATCH")[0] == 200
    comment = {"text": "sem o vídeo não sobe"}
    assert call(f"{base}/api/requests/{req['id']}/comments", comment, piero)[0] == 200
    assert fake_push.wait(3) == ["piero-phone", "nato-laptop", "nato-laptop"]
    assert [(n["title"], n["body"]) for n in news(base, nato, laptop)] == [
        ("Aguardando · Clínica Bem Estar", "Falta: o vídeo"),
        ("Piero comentou · Clínica Bem Estar", "sem o vídeo não sobe"),
    ]
    # an edit that changes no status tells nobody
    assert call(f"{base}/api/requests/{req['id']}", {"notes": "x"}, piero, "PATCH")[0] == 200
    same = {"status": "waiting"}
    assert call(f"{base}/api/requests/{req['id']}", same, piero, "PATCH")[0] == 200
    assert fake_push.wait(4, seconds=0.3) == ["piero-phone", "nato-laptop", "nato-laptop"]


def test_the_key_a_browser_subscribes_with(team, store):
    base, nato, piero, _ = team
    status, doc, _ = call(f"{base}/api/push", cookie=piero)
    assert status == 200 and doc == {"key": Push(store).public_key}
    assert call(f"{base}/api/push", cookie=nato)[1] == doc  # one key for the whole team


def test_a_device_must_be_on_the_push_service_and_the_persons_own(team, fake_push):
    base, nato, piero, _ = team
    for bad in ("https://example.com/x", "http://127.0.0.1:1/x", "", None, 3):
        status, err, _ = call(f"{base}/api/push", {"endpoint": bad}, piero)
        assert status == 400 and "notificações" in err["error"], bad
    phone = fake_push.endpoint("piero-phone")
    on(base, piero, phone)
    assert call(f"{base}/api/push/news", {"endpoint": phone}, nato)[0] == 404
    assert call(f"{base}/api/push/news", {}, piero)[0] == 404
    for path in ("/api/push", "/api/push/off", "/api/push/news"):  # all need a session
        assert call(f"{base}{path}", {"endpoint": phone})[0] == 401
    assert call(f"{base}/api/push")[0] == 401


def test_switching_off_and_signing_out_stop_the_pushes(team, fake_push, store):
    base, nato, piero, _ = team
    phone, tablet = fake_push.endpoint("piero-phone"), fake_push.endpoint("piero-tablet")
    on(base, piero, phone)
    on(base, piero, tablet)
    # Renato cannot switch Piero's phone off, and a missing address switches nothing off
    assert call(f"{base}/api/push/off", {"endpoint": phone}, nato)[0] == 200
    assert call(f"{base}/api/push/off", {}, piero)[0] == 200
    assert store.push_targets(None) == [phone, tablet]
    assert call(f"{base}/api/push/off", {"endpoint": phone}, piero)[0] == 200
    req = a_request(base, nato)
    assert fake_push.wait(1) == ["piero-tablet"]
    assert call(f"{base}/api/logout", {}, piero)[0] == 200  # out of every device
    assert call(f"{base}/api/requests/{req['id']}/comments", {"text": "oi"}, nato)[0] == 200
    assert fake_push.wait(2, seconds=0.3) == ["piero-tablet"]
    assert store.push_targets(None) == []


def test_a_device_its_push_service_no_longer_knows_is_forgotten(team, fake_push, store, caplog):
    base, nato, piero, _ = team
    phone, tablet = fake_push.endpoint("piero-phone"), fake_push.endpoint("piero-tablet")
    on(base, piero, phone)
    on(base, piero, tablet)
    fake_push.gone.add("piero-phone")
    with caplog.at_level(logging.INFO, logger="pauta"):
        a_request(base, nato)
        assert sorted(fake_push.wait(2)) == ["piero-phone", "piero-tablet"]
        for _ in range(300):  # the count is logged when the last one answered
            said = [r.getMessage() for r in caplog.records]
            lines = [json.loads(m) for m in said if '"push"' in m]
            if lines:
                break
            fake_push.wait(99, seconds=0.01)
    assert lines == [{"event": "push", "sent": 1, "gone": 1, "failed": 0}]
    assert store.push_targets(None) == [tablet]


def test_a_push_service_that_does_not_answer_costs_nothing(team, store, caplog):
    base, nato, piero, _ = team
    dead = FakePush()
    dead.close()  # its port answers nobody now
    push = Push(store, services=(dead.host,), scheme="http")
    assert push.send(dead.endpoint("x")) == 0
    store.push_subscribe(2, dead.endpoint("x"))
    with caplog.at_level(logging.INFO, logger="pauta"):
        push._send_all(store.push_targets(None))
    events = [json.loads(r.getMessage()) for r in caplog.records]
    assert {"event": "push_failed", "status": 0} in events
    assert {"event": "push", "sent": 0, "gone": 0, "failed": 1} in events
    assert store.push_targets(None) == [dead.endpoint("x")]  # kept: it may be back tomorrow


def test_local_mode_has_no_notifications(store, drive, meta):
    from pauta.auth import Auth

    httpd = serve(store, Auth(store, enabled=False), drive, meta)
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        assert call(f"{base}/api/push")[0] == 400
        for path in ("/api/push", "/api/push/off", "/api/push/news"):
            status, err, _ = call(f"{base}{path}", {"endpoint": "https://web.push.apple.com/x"})
            assert status == 400 and err["error"] == "sem contas no modo local", path
        client = call(f"{base}/api/clients", {"name": "X"})[1]
        assert call(f"{base}/api/requests", {"client": client["id"], "what": "y"})[0] == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert not store.path.with_name("pauta.db.push-key").exists()  # no key until it is needed
