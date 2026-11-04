"""The usage log from the browser (decision 11): opening screens leaves `screen` rows, sent as
a beacon when the page goes away, with the device string and no name in them."""

import time

import pytest
from playwright.sync_api import expect

from pauta import cli

pytestmark = pytest.mark.e2e


@pytest.fixture()
def signed_in(live, monkeypatch, device):
    base, auth, store = live
    monkeypatch.setenv("PAUTA_STATE_DIR", str(store.path.parent))
    cli.main(["demo"])
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Renato Lima', 'h', 1)"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
    d = device(viewport={"width": 390, "height": 844}, is_mobile=True)
    d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    return base, store, d.page, aid


def usage_rows(store):
    with store.db() as db:
        return [
            dict(r)
            for r in db.execute("SELECT account, event, screen, props, dev FROM usage ORDER BY id")
        ]


def test_three_screens_leave_three_screen_rows(signed_in):
    base, store, page, aid = signed_in
    page.goto(f"{base}/#/")
    expect(page.locator("#app")).to_contain_text("Renato")
    page.goto(f"{base}/#/quadro")
    expect(page.locator("#app")).to_contain_text("Quadro")
    page.goto(f"{base}/#/pedidos")
    expect(page.locator("#app")).to_contain_text("Pedidos")
    assert usage_rows(store) == []  # batched: nothing has left yet
    page.goto("about:blank")  # pagehide: the batch leaves as a beacon
    for _ in range(100):
        if len([r for r in usage_rows(store) if r["event"] == "screen"]) >= 3:
            break
        time.sleep(0.05)
    rows = usage_rows(store)
    screens = [(r["screen"], r["props"]) for r in rows if r["event"] == "screen"]
    assert screens == [
        ("painel", '{"from":""}'),
        ("quadro", '{"from":"painel"}'),
        ("pedidos", '{"from":"quadro"}'),
    ]
    opens = [r for r in rows if r["event"] == "app_open"]
    assert len(opens) == 1 and '"theme":"light"' in opens[0]["props"]
    assert all(r["account"] == aid for r in rows)
    assert all(r["dev"].startswith("phone/browser/390x") for r in rows)
    assert "Renato" not in str(rows)
