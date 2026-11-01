"""What the team actually does, in a real browser: join, file a request, work it, sign back in."""

import re

import pytest
from playwright.sync_api import expect

from pauta.db import STATUSES

pytestmark = pytest.mark.e2e


def join(page, base, token, name):
    page.goto(f"{base}/#/entrar/{token}")
    expect(page.get_by_role("heading", name="Bem-vindo à pauta")).to_be_visible()
    page.fill("#join input[name=name]", name)
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text(name)


def test_admin_files_and_works_a_request(live, device):
    base, auth, store = live
    token, _ = auth.create_invite(admin=True)
    laptop = device()
    page = laptop.page
    join(page, base, token, "Renato Lima")
    assert len(laptop.passkeys()) == 1 and laptop.passkeys()[0]["isResidentCredential"]
    expect(page.locator("#mechip")).to_contain_text("Administrador")

    # a new request, with a client made on the spot
    page.get_by_role("link", name="Novo pedido").first.click()
    page.click("#newclient")
    page.fill("#qc input[name=name]", "Clínica Bem Estar")
    page.get_by_role("button", name="Criar cliente").click()
    expect(page.locator("select[name=client] option:checked")).to_have_text("Clínica Bem Estar")
    page.fill("textarea[name=what]", "Limpeza de pele com 20% de desconto")
    page.fill("input[name=budget]", "1500")
    page.click("#quickdue >> text=Amanhã")
    page.click('[data-seg=priority] [data-v="Alta"]')
    page.get_by_role("button", name="Enviar pedido").click()
    expect(page).to_have_url(re.compile(r"#/pedido/1$"))
    expect(page.locator(".toast")).to_contain_text("Pedido #1 enviado")

    # Piero's half: status, what's missing, a comment
    # (each step waits for its autosave to land, so the timeline order is the click order)
    page.click('[data-seg=status] [data-v="waiting"]')
    expect(page.locator("#missingbox")).to_be_visible()
    expect(page.locator("#tl")).to_contain_text(STATUSES["waiting"])
    page.fill('[data-f="missing"]', "Liberar a conta de anúncios")
    page.locator('[data-f="missing"]').blur()
    expect(page.locator("#tl")).to_contain_text("editou o que falta")
    page.fill("#comment", "Liberei agora!")
    page.click("#send")
    expect(page.locator("#tl .bubble").first).to_have_text("Liberei agora!")

    r = store.request(1)
    assert r["status"] == "waiting" and r["missing"] == "Liberar a conta de anúncios"
    assert r["budget"] == 1500 and r["priority"] == "Alta" and r["due"]
    assert [e["kind"] for e in r["events"]] == ["created", "status", "edited", "comment"]

    # it shows up on the list and the board
    page.goto(f"{base}/#/pedidos")
    expect(page.locator("#rows")).to_contain_text("Clínica Bem Estar")
    page.goto(f"{base}/#/quadro")
    expect(page.locator('[data-status="waiting"]')).to_contain_text("Limpeza de pele")


def test_sign_out_and_back_in_with_the_passkey(live, device):
    base, auth, _ = live
    token, _ = auth.create_invite(admin=True)
    page = device().page
    join(page, base, token, "Renato Lima")
    page.goto(f"{base}/#/perfil")
    page.click("#logout")
    expect(page.locator("#login")).to_be_visible()
    expect(page.locator("#shell")).to_be_hidden()
    page.goto(f"{base}/#/pedidos")  # signed out: still the gate, and no data
    expect(page.locator("#login")).to_be_visible()
    page.click("#login")
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")


def test_admin_invites_a_member_who_cannot_delete(live, device):
    base, auth, store = live
    token, _ = auth.create_invite(admin=True)
    admin = device().page
    join(admin, base, token, "Renato Lima")
    store.save_client({"name": "Padaria"})
    store.create_request({"client": 1, "what": "Novos criativos"}, 1)
    admin.goto(f"{base}/#/configuracoes")
    admin.click("#invite")
    link = admin.locator(".invlink").inner_text()
    assert link.startswith(f"{base}/#/entrar/")
    expect(admin.locator("#qrbox .qr svg")).to_be_visible()

    phone = device(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    phone.page.goto(link)
    expect(phone.page.get_by_text("Renato convidou você")).to_be_visible()
    phone.page.fill("#join input[name=name]", "Piero")
    phone.page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(phone.page.locator("#tabbar")).to_be_visible()  # the phone layout
    phone.page.goto(f"{base}/#/pedido/1")
    expect(phone.page.locator("textarea.req-title")).to_have_value("Novos criativos")
    expect(phone.page.locator("#del")).to_have_count(0)  # only admins delete

    admin.reload()
    expect(admin.locator(".member", has_text="Piero")).to_be_visible()
    assert [m["name"] for m in store.members()] == ["Renato Lima", "Piero"]


def test_used_invite_is_refused(live, device):
    base, auth, _ = live
    token, _ = auth.create_invite()
    join(device().page, base, token, "Ana")
    other = device()
    other.expected.add((404, "/api/invite/"))
    other = other.page
    other.goto(f"{base}/#/entrar/{token}")
    expect(other.get_by_role("heading", name="Convite inválido")).to_be_visible()


def test_a_slow_screen_does_not_overwrite_the_next_one(live, device):
    """Regression: answers for a screen the user already left used to replace the new one."""
    base, auth, _ = live
    token, _ = auth.create_invite(admin=True)
    page = device().page
    join(page, base, token, "Renato Lima")
    held = []

    def hold_first(route):  # the list's data is held; later fetches go straight through
        held.append(route) if not held else route.continue_()

    page.route("**/api/requests", hold_first)
    page.goto(f"{base}/#/pedidos")
    # a locator, not wait_for_function: evaluating a string breaks the CSP (no unsafe-eval)
    page.locator("#app .spinner").wait_for(state="attached")
    assert held, "the list screen should be waiting on /api/requests"
    page.goto(f"{base}/#/configuracoes")
    expect(page.get_by_role("heading", name="Configurações")).to_be_visible()
    with page.expect_response("**/api/requests"):
        held[0].continue_()
    page.wait_for_timeout(200)  # let the old screen's code run to the end
    expect(page.get_by_role("heading", name="Configurações")).to_be_visible()
    expect(page.locator("#rows")).to_have_count(0)


@pytest.mark.parametrize("token", ["used", "fresh"])
def test_signed_in_opening_an_invite_link_keeps_the_app_working(live, device, token):
    """Regression (1.1.0 incident): an admin who tapped an invite link while signed in got
    "Você já entrou", and after "Abrir a Pauta" every screen said "null is not an object
    (evaluating 'BOOT.options')" until a reload."""
    base, auth, store = live
    mine, _ = auth.create_invite(admin=True)
    store.save_client({"name": "Açougue Bom de Corte"})
    laptop = device()
    page = laptop.page
    join(page, base, mine, "Piero Sales")
    link = mine if token == "used" else auth.create_invite()[0]
    page.goto(f"{base}/#/entrar/{link}")
    page.reload()  # what tapping the link in WhatsApp does: a fresh load on the invite
    expect(page.get_by_role("heading", name="Você já entrou")).to_be_visible()
    page.get_by_role("link", name="Abrir a Pauta").click()
    expect(
        page.get_by_role("heading", name=re.compile("^(Bom dia|Boa tarde|Boa noite)"))
    ).to_be_visible()
    expect(page.locator("#mechip")).to_contain_text("Piero Sales")
    for path, heading in [("quadro", "Quadro"), ("clientes", "Clientes"), ("novo", "Novo pedido")]:
        page.goto(f"{base}/#/{path}")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
    expect(page.locator("#app")).not_to_contain_text("null is not an object")
