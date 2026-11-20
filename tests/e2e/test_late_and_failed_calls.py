"""Calls that answer late, twice or not at all, as on a phone with a bad connection: an
answer for a screen the person has left is not drawn on the one they are on, a second tap
while the first call is on its way sends nothing, and a call that fails says so and leaves
the screen as the server has it."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

OFFLINE = "a conexão caiu; tente de novo"


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


def test_a_second_tap_sends_nothing(desk):
    """Two taps on a slow connection posted the comment twice (a comment cannot be deleted)
    and made two invites, one of them never shown."""
    base, store, d = desk
    page = d.page
    posts = []
    page.on("request", lambda r: posts.append(r.url) if r.method == "POST" else None)
    page.goto(f"{base}/#/pedido/1")
    held = hold(page, "**/api/requests/1/comments", "POST")
    page.fill("#comment", "Pode subir a campanha")
    with page.expect_request("**/api/requests/1/comments"):
        page.press("#comment", "Control+Enter")
    expect(page.locator("#send")).to_be_disabled()
    page.press("#comment", "Control+Enter")  # the keyboard's way to the same button
    page.evaluate("() => document.querySelector('#send').click()")
    let_go(page, held)
    expect(page.locator("#tl .bubble")).to_have_text(["Pode subir a campanha"])
    expect(page.locator("#send")).to_be_enabled()
    assert len([u for u in posts if u.endswith("/comments")]) == 1

    page.goto(f"{base}/#/configuracoes")
    held = hold(page, "**/api/invite", "POST")
    with page.expect_request("**/api/invite"):
        page.get_by_role("button", name="Gerar convite").click()
    expect(page.get_by_role("button", name="Gerar convite")).to_be_disabled()
    page.evaluate("() => document.querySelector('#invite').click()")
    let_go(page, held)
    expect(page.locator("#qrbox .invlink")).to_be_visible()
    expect(page.get_by_role("button", name="Gerar convite")).to_be_enabled()
    with store.db() as conn:
        assert conn.execute("SELECT count(*) FROM invite").fetchone()[0] == 1

    # the two forms that make a client: the one on its own screen and the quick one
    page.goto(f"{base}/#/cliente/novo")
    held = hold(page, "**/api/clients", "POST")
    page.fill("#f input[name=name]", "Ótica Boa Vista")
    with page.expect_request(lambda r: r.method == "POST"):
        page.get_by_role("button", name="Salvar cliente").click()
    page.evaluate("() => document.querySelector('#f button.primary').click()")
    let_go(page, held)
    expect(page.locator("#cname")).to_contain_text("Ótica Boa Vista")
    page.unroute("**/api/clients")
    page.goto(f"{base}/#/novo")
    page.get_by_role("button", name="Novo", exact=True).click()
    held = hold(page, "**/api/clients", "POST")
    page.fill("#qc input[name=name]", "Açougue Bom de Corte")
    with page.expect_request(lambda r: r.method == "POST"):
        page.get_by_role("button", name="Criar cliente").click()
    page.evaluate("() => document.querySelector('#qc button.primary').click()")
    let_go(page, held)
    expect(page.locator("#modal")).to_be_hidden()
    assert [c["name"] for c in store.clients()].count("Ótica Boa Vista") == 1
    assert [c["name"] for c in store.clients()].count("Açougue Bom de Corte") == 1


def test_a_choice_that_did_not_save_goes_back(desk):
    """Concluído used to say "Status: Concluído" before the save and stay lit when the save
    failed, and a second tap on it did nothing. Now the buttons and the lists go back to
    what the server has, the toast says why, and the same tap works once the call does."""
    base, store, d = desk
    page = d.page
    d.expected.add((500, "/api/requests/1"))
    d.expected.add((500, "/api/clients/1"))
    broken = '{"error": "erro interno; tente de novo"}'

    def fail(route):
        if route.request.method == "PATCH":
            route.fulfill(status=500, content_type="application/json", body=broken)
        else:
            route.continue_()

    toast = page.locator("#toast")
    page.goto(f"{base}/#/pedido/1")
    statuses = page.locator(".statuses")
    expect(statuses.locator("button.on")).to_have_text("A fazer")
    page.route("**/api/requests/1", fail)
    statuses.get_by_role("button", name="Concluído").click()
    expect(toast).to_have_text("erro interno; tente de novo")
    expect(toast).to_have_class("toast err")
    expect(statuses.locator("button.on")).to_have_text("A fazer")
    statuses.get_by_role("button", name="Aguardando").click()
    expect(statuses.locator("button.on")).to_have_text("A fazer")
    expect(page.locator("#missingbox")).to_be_hidden()  # nothing is waiting, after all
    page.locator('[data-f="goal"]').select_option(index=1)
    expect(page.locator('[data-f="goal"]')).to_have_value("")
    typed = page.locator('[data-f="region"]')
    typed.fill("Zona sul")
    typed.blur()
    expect(toast).to_have_class("toast err")
    expect(typed).to_have_value("Zona sul")  # typed text stays, to try again
    page.unroute("**/api/requests/1")
    statuses.get_by_role("button", name="Concluído").click()
    expect(toast).to_have_text("Status: Concluído")
    expect(statuses.locator("button.on")).to_have_text("Concluído")
    assert store.request(1)["status"] == "done"

    page.goto(f"{base}/#/cliente/1")
    state = page.locator('[data-seg="state"]')
    expect(state.locator("button.on")).to_have_text("Ativo")
    page.route("**/api/clients/1", fail)
    state.get_by_role("button", name="Encerrado").click()
    expect(toast).to_have_class("toast err")
    expect(state.locator("button.on")).to_have_text("Ativo")
    page.unroute("**/api/clients/1")
    state.get_by_role("button", name="Encerrado").click()
    expect(toast).to_have_text("Salvo")
    expect(state.locator("button.on")).to_have_text("Encerrado")


def test_offline_the_buttons_say_so_and_the_error_screen_tries_again(desk):
    """Without a connection Excluir, Exportar and Sair did nothing and said nothing, and a
    screen that could not load showed the browser's English text with no way to ask again
    (the menu item of the screen you are on does not navigate)."""
    base, store, d = desk
    page = d.page
    toast = page.locator("#toast")
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator(".req-title")).to_have_value("Limpeza de pele")
    d.context.set_offline(True)
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Excluir pedido").click()
    expect(toast).to_have_text(OFFLINE)
    expect(toast).to_have_class("toast err")
    expect(page.locator(".req-title")).to_have_value("Limpeza de pele")  # still on the request

    page.goto(f"{base}/#/configuracoes")
    expect(page.locator("#app .empty")).to_contain_text(OFFLINE)
    d.context.set_offline(False)
    page.get_by_role("button", name="Tentar de novo").click()
    expect(page.get_by_role("heading", name="Configurações")).to_be_visible()

    d.context.set_offline(True)
    toast.evaluate("t => { t.hidden = true; }")
    page.get_by_role("button", name="Exportar dados").click()
    expect(toast).to_have_text(OFFLINE)
    toast.evaluate("t => { t.hidden = true; }")
    page.locator("#mechip").click()
    page.get_by_role("button", name="Sair").click()
    expect(toast).to_have_text(OFFLINE)
    expect(page.locator("#shell")).to_be_visible()  # still in
    d.context.set_offline(False)
    assert store.request(1)["what"] == "Limpeza de pele"
