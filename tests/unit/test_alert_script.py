"""scripts/alert.py: the WhatsApp template payload the GitHub workflows send."""

import importlib.util
import io
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "alert", Path(__file__).resolve().parents[2] / "scripts" / "alert.py"
)
alert = importlib.util.module_from_spec(spec)
spec.loader.exec_module(alert)


def test_template_variables_are_one_line():
    assert alert.param("down:\n  healthz\ttimed   out\n") == "down: · healthz timed out"
    long = alert.param("x" * 2000)
    assert len(long) == alert.MAX_PARAM and long.endswith("…")


def test_payload_shape():
    body = alert.payload("31600000000", "pauta", "a\nb", "du7_service_status", "en")
    tmpl = body["template"]
    assert body["type"] == "template" and body["to"] == "31600000000"
    assert tmpl["name"] == "du7_service_status" and tmpl["language"] == {"code": "en"}
    assert [p["text"] for p in tmpl["components"][0]["parameters"]] == ["pauta", "a · b"]


def test_dry_run_and_usage(capsys, monkeypatch):
    monkeypatch.delenv("WA_TEMPLATE", raising=False)
    assert alert.main(["pauta", "down", "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["template"]["name"] == "du7_service_status"
    assert alert.main(["only-one"]) == 2


def test_missing_secrets_are_an_error(capsys, monkeypatch):
    for k in ("WA_TOKEN", "WA_PHONE_ID", "WA_TO"):
        monkeypatch.delenv(k, raising=False)
    assert alert.main(["pauta", "down"]) == 1
    assert "WA_TOKEN, WA_PHONE_ID, WA_TO not set" in capsys.readouterr().err


def test_sends_with_the_token(capsys, monkeypatch):
    monkeypatch.setenv("WA_TOKEN", "t0k")
    monkeypatch.setenv("WA_PHONE_ID", "123")
    monkeypatch.setenv("WA_TO", "31600000000")
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"], seen["auth"] = req.full_url, req.headers["Authorization"]
        seen["body"] = json.loads(req.data)
        return io.BytesIO(b'{"messages": [{"id": "wamid.1"}]}')

    monkeypatch.setattr(alert.urllib.request, "urlopen", fake_urlopen)
    assert alert.main(["pauta", "down"]) == 0
    assert seen["url"].endswith("/123/messages") and seen["auth"] == "Bearer t0k"
    assert seen["body"]["to"] == "31600000000"
    assert "wamid.1" in capsys.readouterr().out


def test_meta_refusing_is_an_error(capsys, monkeypatch):
    monkeypatch.setenv("WA_TOKEN", "t0k")
    monkeypatch.setenv("WA_PHONE_ID", "123")
    monkeypatch.setenv("WA_TO", "31600000000")

    def refuse(req, timeout):
        raise alert.urllib.error.HTTPError(
            req.full_url, 400, "Bad Request", {}, io.BytesIO(b'{"error": "template paused"}')
        )

    monkeypatch.setattr(alert.urllib.request, "urlopen", refuse)
    assert alert.main(["pauta", "down"]) == 1
    assert "HTTP 400" in capsys.readouterr().err
