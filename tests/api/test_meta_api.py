"""Connecting Meta over real HTTP: the round trip through Meta's login (the fake one in
tests/fakemeta.py), the cookie-less callback, reading ad accounts, who may do what, /metrics."""

import json
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from fakemeta import SECRET, fetch
from pauta import meta as meta_mod
from pauta.meta import REVOKED
from softpasskey import call


@pytest.fixture()
def meta(meta_on):
    return meta_on


def start(base, nato):
    status, doc, _ = call(f"{base}/api/meta/connect", {}, nato)
    assert status == 200
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
        "business_name": "",
        "connected_at": "",
        "error": "",
    }
    url = start(base, nato)
    assert url.startswith(fake_meta.dialog)
    status, location, _ = through_meta(base, url)
    assert status == 302 and location == "/#/equipe?meta=conectado"

    doc = call(f"{base}/api/meta", cookie=nato)[1]
    assert doc["connected"] and doc["business_name"] == "Agência Exemplo"
    assert [a["name"] for a in doc["accounts"]] == ["Clínica Bem Estar", "Padaria Trigo de Ouro"]
    assert doc["accounts"][0]["spend_cents"] == 123456
    text = json.dumps(doc)
    assert fake_meta.token not in text and SECRET not in text

    # cached, unless asked to refresh
    seen = len(fake_meta.seen)
    call(f"{base}/api/meta", cookie=nato)
    assert len(fake_meta.seen) == seen
    call(f"{base}/api/meta?refresh=1", cookie=nato)
    assert len(fake_meta.seen) > seen

    status, doc, _ = call(f"{base}/api/meta", cookie=nato, method="DELETE")
    assert status == 200 and not doc["connected"]
    assert "accounts" not in call(f"{base}/api/meta", cookie=nato)[1]


def test_callback_needs_a_live_state(team, fake_meta, monkeypatch):
    base, nato, _, _ = team
    erro = "/#/equipe?meta=erro&motivo="
    # nobody started it
    status, location, _ = fetch(f"{base}/api/meta/callback?code=x&state=forged")
    assert status == 302 and location == erro + "expirou"
    # started, and the callback loaded twice (Piero's browser did): connected both times
    url = start(base, nato)
    first = urlparse(fetch(url)[1]).query
    assert fetch(f"{base}/api/meta/callback?{first}")[1] == "/#/equipe?meta=conectado"
    assert fetch(f"{base}/api/meta/callback?{first}")[1] == "/#/equipe?meta=conectado"
    # started, but too long ago
    query = urlparse(fetch(start(base, nato))[1]).query
    now = meta_mod.time.time()
    monkeypatch.setattr(meta_mod.time, "time", lambda: now + 601)
    assert fetch(f"{base}/api/meta/callback?{query}")[1] == erro + "expirou"
    assert fake_meta.exchanges == 1


def test_callback_when_cancelled_or_meta_refuses(team, fake_meta):
    base, nato, _, _ = team
    erro = "/#/equipe?meta=erro&motivo="
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
    assert call(f"{base}/api/meta", cookie=piero, method="DELETE")[0] == 403
    assert call(f"{base}/api/meta")[0] == 401
    assert call(f"{base}/api/meta/connect", {})[0] == 401
    # a write from another site is refused before anything else
    status, doc, _ = call(
        f"{base}/api/meta/connect", {}, nato, headers={"Origin": "https://evil.example"}
    )
    assert status == 403


def test_revoked_token_answers_409(team, fake_meta):
    base, nato, _, _ = team
    through_meta(base, start(base, nato))
    fake_meta.token_invalid = True
    status, doc, _ = call(f"{base}/api/meta?refresh=1", cookie=nato)
    assert status == 409 and doc["error"] == REVOKED
    assert call(f"{base}/metrics")[1]["meta"] == {
        "enabled": True,
        "connected": True,
        "error": REVOKED,
    }


def test_metrics(team):
    base, nato, _, _ = team
    assert call(f"{base}/metrics")[1]["meta"] == {"enabled": True, "connected": False, "error": ""}
    through_meta(base, start(base, nato))
    assert call(f"{base}/metrics")[1]["meta"]["connected"] is True
