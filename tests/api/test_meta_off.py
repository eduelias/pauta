"""Meta without its configuration: the panel stays hidden and the callback fails safely."""

from fakemeta import fetch
from softpasskey import call


def test_off_by_default(team):
    base, nato, _, _ = team
    assert call(f"{base}/api/boot", cookie=nato)[1]["meta"] == {"enabled": False}
    status, doc, _ = call(f"{base}/api/meta/connect", {}, nato)
    assert status == 400 and "Meta" in doc["error"]
    status, location, _ = fetch(f"{base}/api/meta/callback?code=x&state=y")
    assert status == 302 and location == "/#/configuracoes?meta=erro&motivo=desligado"
    assert call(f"{base}/metrics")[1]["meta"] == {
        "enabled": False,
        "connected": False,
        "connections": 0,
        "revoked": 0,
        "error": "",
        "last_sync": None,
        "sync_error": "",
    }


def test_a_clients_meta_card_is_simply_off(team):
    base, nato, piero, _ = team
    status, c, _ = call(f"{base}/api/clients", {"name": "Padaria", "ad_account": "222"}, nato)
    assert status == 200 and c["meta_accounts"] == []
    status, doc, _ = call(f"{base}/api/clients/{c['id']}/meta", cookie=piero)
    assert status == 200 and doc == {"connected": False, "accounts": []}
    # the mapping itself needs no Meta: nothing was ever read, so there is nothing to link
    body = {"client": c["id"]}
    assert call(f"{base}/api/meta/accounts/222", body, nato, method="PATCH")[0] == 404
    assert call(f"{base}/api/export", cookie=nato)[1]["meta_account"] == []
