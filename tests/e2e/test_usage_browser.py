"""The usage log from the browser (decision 11): opening screens leaves `screen` rows, sent as
a beacon when the page goes away, with the device string and no name in them."""

import json
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
    return base, store, d, aid


def usage_rows(store):
    with store.db() as db:
        return [
            dict(r)
            for r in db.execute("SELECT account, event, screen, props, dev FROM usage ORDER BY id")
        ]


def test_three_screens_leave_three_screen_rows(signed_in):
    base, store, d, aid = signed_in
    page = d.page
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


def test_error_toasts_say_which_call_or_form(signed_in):
    """An error toast's row carries the call that failed just before it (method, route
    pattern, status), or, when no call failed (a check in the page itself), the form it
    came from (its id, else the screen): `pauta usage` can then say which form fails
    instead of just "validation"."""
    base, store, d, aid = signed_in
    page = d.page
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator("#app")).to_contain_text("Briefing")
    d.expected.add((400, "/api/requests/1"))  # the link below is refused: that is the point
    link = page.locator('input[data-f="campaign_url"]')
    link.fill("sem link, só texto")
    link.blur()
    expect(page.locator("#toast")).to_have_class("toast err")
    page.goto(f"{base}/#/novo")
    expect(page.locator("#f")).to_be_visible()
    page.locator("#f input, #f textarea").first.focus()
    # a check in the page itself, with no call failed: the 400 above is forgotten after 3 s
    page.evaluate("USAGE.lastErr.at -= 3100")
    page.evaluate("toast('Falta algo', true)")
    expect(page.locator("#toast")).to_have_text("Falta algo")
    page.goto("about:blank")
    for _ in range(100):
        if len([r for r in usage_rows(store) if r["event"] == "error_shown"]) >= 2:
            break
        time.sleep(0.05)
    errors = [r for r in usage_rows(store) if r["event"] == "error_shown"]
    assert [(r["screen"], json.loads(r["props"])) for r in errors] == [
        (
            "pedido",
            {"msg": "validation", "status": 400, "route": "/api/requests/{id}", "method": "PATCH"},
        ),
        ("novo", {"msg": "validation", "form": "f"}),
    ]


def test_a_new_request_is_logged_with_its_kind(signed_in):
    """The kind is picked with buttons, which are not fields of the form: the log read it
    from the form's fields and so never had one."""
    base, store, d, aid = signed_in
    page = d.page
    page.goto(f"{base}/#/novo")
    page.select_option("#f select[name=client]", index=1)
    page.locator('#f [data-seg="kind"]').get_by_role("button", name="Relatório").click()
    page.fill("#f textarea[name=what]", "Números de outubro")
    page.get_by_role("button", name="Enviar pedido").click()
    expect(page.locator("#toast")).to_contain_text("enviado")
    page.goto("about:blank")
    made = []
    for _ in range(100):
        made = [r for r in usage_rows(store) if r["event"] == "request_created"]
        if made:
            break
        time.sleep(0.05)
    assert [json.loads(r["props"]) for r in made] == [{"kind": "Relatório", "has_deadline": False}]
