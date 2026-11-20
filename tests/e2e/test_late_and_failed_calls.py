"""Calls that answer late, as on a phone with a bad connection: an answer for a screen the
person has left is not drawn on the one they are on."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture()
def desk(live, device):
    """An admin signed in by cookie; two clients with one request each."""
    base, auth, store = live
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Renato Lima', 'h', 1)"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
    d = device()
    d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    clinic = store.save_client({"name": "Clínica Bem Estar"})
    bakery = store.save_client({"name": "Padaria Trigo de Ouro"})
    store.create_request({"client": clinic["id"], "what": "Limpeza de pele"}, None)
    store.create_request({"client": bakery["id"], "what": "Pão de queijo"}, None)
    return base, store, d


def hold(page, url, method):
    """The next `method` call to `url` waits until the test lets it go; later ones pass."""
    held = []

    def handler(route):
        if route.request.method == method and not held:
            held.append(route)
        else:
            route.continue_()

    page.route(url, handler)
    return held


def let_go(page, held):
    with page.expect_response(lambda r: r.url == held[0].request.url):
        held[0].continue_()
    page.wait_for_timeout(200)  # the code that was waiting for the answer runs to its end


@pytest.mark.parametrize(("screen", "field"), [("pedido", "region"), ("cliente", "contact")])
def test_a_save_that_answers_late_is_not_drawn_on_the_next_screen(desk, screen, field):
    """A field saves by itself when it loses focus. The answer used to be drawn by id on
    whatever screen was up by then: the other request got this one's timeline, the other
    client this one's name, and a screen without those ids a red toast for a save that worked."""
    base, store, d = desk
    page = d.page
    api = "requests" if screen == "pedido" else "clients"
    for leave_to, there in ((f"{screen}/2", "Padaria Trigo de Ouro"), ("perfil", "Perfil")):
        held = hold(page, f"**/api/{api}/1", "PATCH")
        page.goto(f"{base}/#/{screen}/1")
        with page.expect_request(lambda r: r.method == "PATCH"):
            page.locator(f'[data-f="{field}"]').fill(f"Centro, {leave_to}")
            page.locator(f'[data-f="{field}"]').blur()
        page.goto(f"{base}/#/{leave_to}")
        expect(page.locator("#app")).to_contain_text(there)
        let_go(page, held)
        page.unroute(f"**/api/{api}/1")
        expect(page.locator("#toast")).to_be_hidden()  # nothing to say on this screen
        expect(page.locator("#app")).to_contain_text(there)
        expect(page.locator("#app")).not_to_contain_text("Clínica Bem Estar")
        expect(page.locator("#app")).not_to_contain_text("editou")  # the other's timeline
    row = store.request(1) if screen == "pedido" else store.client(1)
    assert row[field] == "Centro, perfil"  # the saves themselves were kept


def test_a_screen_that_draws_itself_again_late_does_not_cover_the_next_one(desk):
    """A screen asks for its data again by itself (the board with Cancelados ticked, a new
    period on Campanhas). Nothing told that answer the person had left: it was drawn over
    the screen they were on, under the other screen's address."""
    base, store, d = desk
    page = d.page
    page.goto(f"{base}/#/quadro")
    expect(page.get_by_role("heading", name="Quadro", exact=True)).to_be_visible()
    held = hold(page, "**/api/requests", "GET")
    with page.expect_request("**/api/requests"):
        page.locator("#showc").check()
    page.goto(f"{base}/#/clientes")
    expect(page.get_by_role("heading", name="Clientes", exact=True)).to_be_visible()
    let_go(page, held)
    expect(page.get_by_role("heading", name="Clientes", exact=True)).to_be_visible()
    expect(page.locator(".board")).to_have_count(0)
