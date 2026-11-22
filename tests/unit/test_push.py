"""Notifications without HTTP: the signing key, the signature a push service checks, which
device addresses the server will call, the texts, and the store's list of devices."""

import base64
import json
import stat
import time

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from pauta.db import PUSH_DEVICES, NotFound
from pauta.push import TOKEN_SECONDS, Push, describe

APPLE = "https://web.push.apple.com/QOv3xyz"


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def test_the_key_is_made_once_and_kept_private_next_to_the_database(store):
    push = Push(store)
    assert not push.key_file.exists()  # nothing until someone asks for notifications
    key = push.public_key
    assert push.key_file.name == "pauta.db.push-key"
    assert stat.S_IMODE(push.key_file.stat().st_mode) == 0o600
    point = unb64(key)
    assert len(point) == 65 and point[0] == 4  # an uncompressed P-256 point
    assert Push(store).public_key == key  # a restart reads the same file


def test_the_signature_is_one_a_push_service_accepts(store):
    push = Push(store, contact="https://app.pauta.cc")
    scheme, _, rest = push._authorization("https://web.push.apple.com").partition(" ")
    fields = dict(part.strip().split("=", 1) for part in rest.split(","))
    assert scheme == "vapid" and fields["k"] == push.public_key
    head, claims, signature = fields["t"].split(".")
    assert json.loads(unb64(head)) == {"typ": "JWT", "alg": "ES256"}
    doc = json.loads(unb64(claims))
    assert doc["aud"] == "https://web.push.apple.com" and doc["sub"] == "https://app.pauta.cc"
    assert 0 < doc["exp"] - time.time() <= TOKEN_SECONDS  # a push service takes a day at most
    raw = unb64(signature)
    assert len(raw) == 64
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(fields["k"]))
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if not


@pytest.mark.parametrize(
    "endpoint",
    [
        APPLE,
        "https://fcm.googleapis.com/fcm/send/abc:def",
        "https://updates.push.services.mozilla.com/wpush/v2/gAAA",
        "https://wns2-am3p.notify.windows.com/w/?token=BQYAAA",
    ],
)
def test_a_device_on_a_known_push_service_is_called(store, endpoint):
    assert Push(store).allowed(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://web.push.apple.com/x",  # not https
        "https://127.0.0.1/x",
        "https://localhost:8088/metrics",
        "https://web.push.apple.com.example.com/x",
        "https://example.com/web.push.apple.com",
        "https://evil@web.push.apple.com/x",
        "https://web.push.apple.com:8443/x",
        "https://notify.windows.com.evil.net/w",
        "https://evil.net\\.web.push.apple.com/x",
        "https://evil.net:443@x.web.push.apple.com/x",
        "https://web.push.apple.com:port/x",
        "https://[::1/x",  # not an address at all
        "web.push.apple.com/x",
        "",
        "https://web.push.apple.com/" + "x" * 2000,
        None,
        7,
        ["https://web.push.apple.com/x"],
    ],
)
def test_any_other_address_is_refused(store, endpoint):
    push = Push(store)
    assert not push.allowed(endpoint)
    assert push.send(endpoint) == 0  # and never called, whatever the list of devices says


def test_the_texts(store):
    row = {
        "kind": "created",
        "text": "",
        "request": 7,
        "by_name": "Renato Lima",
        "client": "Clínica Bem Estar",
        "request_kind": "Criar campanha",
        "what": "Campanha de  Natal\ncom vídeo",
        "missing": "",
    }
    assert describe(row) == {
        "title": "Novo pedido · Clínica Bem Estar",
        "body": "Criar campanha: Campanha de Natal com vídeo",
        "url": "/#/pedido/7",
        "tag": "pedido-7",
    }
    assert describe({**row, "request_kind": ""})["body"] == "Campanha de Natal com vídeo"
    said = describe({**row, "kind": "comment", "text": "x" * 500})
    assert said["title"] == "Renato comentou · Clínica Bem Estar"
    assert len(said["body"]) == 140 and said["body"].endswith("…")
    done = describe({**row, "kind": "status", "text": "doing>done"})
    assert (done["title"], done["body"]) == (
        "Concluído · Clínica Bem Estar",
        "Campanha de Natal com vídeo",
    )
    waits = describe({**row, "kind": "status", "text": "todo>waiting", "missing": "o vídeo"})
    assert (waits["title"], waits["body"]) == ("Aguardando · Clínica Bem Estar", "Falta: o vídeo")
    # a request waiting with nothing written says what it is; nobody's event names no one
    assert describe({**row, "kind": "status", "text": "todo>waiting"})["body"].startswith("Camp")
    assert describe({**row, "kind": "comment", "by_name": None})["title"].startswith("Alguém")


# ---- the store's list of devices ---------------------------------------------------------


@pytest.fixture()
def people(store):
    with store.db() as db:
        db.execute("INSERT INTO account(name, handle) VALUES ('Renato', 'renato')")
        db.execute("INSERT INTO account(name, handle) VALUES ('Piero', 'piero')")
    client = store.save_client({"name": "Clínica Bem Estar"})
    return 1, 2, client["id"]


def test_a_device_hears_what_others_did_once(store, people):
    nato, piero, client = people
    before = store.create_request({"client": client, "what": "Antigo"}, nato)
    store.push_subscribe(piero, APPLE)
    assert store.push_news(piero, APPLE)[0]["what"] == "Antigo"  # nothing new: the latest
    new = store.create_request({"client": client, "what": "Novo", "kind": "Outro"}, nato)
    store.update_request(new["id"], {"status": "doing"}, piero)  # his own: not news to him
    store.comment(new["id"], "veja o vídeo", nato)
    store.update_request(before["id"], {"notes": "só uma nota"}, nato)  # an edit is not news
    news = store.push_news(piero, APPLE)
    assert [(n["kind"], n["request"], n["by_name"]) for n in news] == [
        ("created", new["id"], "Renato"),
        ("comment", new["id"], "Renato"),
    ]
    assert news[1]["text"] == "veja o vídeo" and news[0]["client"] == "Clínica Bem Estar"
    again = store.push_news(piero, APPLE)  # a second push for the same news: the latest again
    assert [n["kind"] for n in again] == ["comment"]
    with pytest.raises(NotFound):
        store.push_news(nato, APPLE)  # another person's device
    with pytest.raises(NotFound):
        store.push_news(piero, APPLE + "x")


def test_only_the_three_newest_are_shown_and_nothing_older_than_a_day_is_repeated(store, people):
    nato, piero, client = people
    store.push_subscribe(piero, APPLE)
    for i in range(5):
        store.create_request({"client": client, "what": f"Pedido {i}"}, nato)
    shown = [n["what"] for n in store.push_news(piero, APPLE)]
    assert shown == ["Pedido 2", "Pedido 3", "Pedido 4"]
    with store.db() as db:
        db.execute("UPDATE event SET at=datetime('now','-2 days')")
    assert store.push_news(piero, APPLE) == []


def test_who_is_told(store, people):
    nato, piero, _ = people
    store.push_subscribe(nato, APPLE + "/nato")
    store.push_subscribe(piero, APPLE + "/piero")
    assert store.push_targets(nato) == [APPLE + "/piero"]
    assert store.push_targets(None) == [APPLE + "/nato", APPLE + "/piero"]  # the CLI did it
    with store.db() as db:
        db.execute("UPDATE account SET disabled=1 WHERE id=?", (piero,))
    assert store.push_targets(nato) == []
    # whoever enables a device last has it: Renato signs in on what was Piero's phone
    store.push_subscribe(nato, APPLE + "/piero")
    assert store.push_targets(None) == [APPLE + "/nato", APPLE + "/piero"]
    assert store.push_targets(nato) == []


def test_forgetting_devices(store, people):
    nato, piero, _ = people
    for i in range(PUSH_DEVICES + 2):
        store.push_subscribe(nato, f"{APPLE}/{i}")
    kept = store.push_targets(piero)
    assert kept == [f"{APPLE}/{i}" for i in range(2, PUSH_DEVICES + 2)]  # the newest ten
    store.push_forget(endpoint=kept[0], account=piero)  # not Piero's to switch off
    assert len(store.push_targets(piero)) == PUSH_DEVICES
    store.push_forget(endpoint=kept[0], account=nato)
    store.push_forget(endpoint=kept[1])  # its push service says it is gone
    assert store.push_targets(piero) == kept[2:]
    store.push_forget()  # nothing named: nothing forgotten
    assert store.push_targets(piero) == kept[2:]
    store.push_forget(account=nato)  # signed out everywhere
    assert store.push_targets(piero) == []
