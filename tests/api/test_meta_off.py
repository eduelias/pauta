"""Meta without its configuration: the panel stays hidden and the callback fails safely."""

from fakemeta import fetch
from softpasskey import call


def test_off_by_default(team):
    base, nato, _, _ = team
    assert call(f"{base}/api/boot", cookie=nato)[1]["meta"] == {"enabled": False}
    status, doc, _ = call(f"{base}/api/meta/connect", {}, nato)
    assert status == 400 and "Meta" in doc["error"]
    status, location, _ = fetch(f"{base}/api/meta/callback?code=x&state=y")
    assert status == 302 and location == "/#/equipe?meta=erro&motivo=desligado"
    assert call(f"{base}/metrics")[1]["meta"] == {
        "enabled": False,
        "connected": False,
        "error": "",
    }
