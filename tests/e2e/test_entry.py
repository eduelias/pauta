"""Every way a signed-in person arrives at the app, then every screen from there.

Regression for the 1.1.0 incident: opening an invite link while signed in showed
"Você já entrou" without loading the app's startup data (BOOT), so after "Abrir a Pauta"
every screen but the dashboard said "null is not an object (evaluating 'BOOT.options')"
until a reload. Screen errors are caught and drawn in #app (no console error), so these
tests look at what each screen draws, not only at the console.
"""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}

# (hash, what the screen shows once it has drawn)
SCREENS = [
    ("#/", lambda p: p.locator(".hello h1")),
    ("#/quadro", lambda p: p.get_by_role("heading", name="Quadro", exact=True)),
    ("#/pedidos", lambda p: p.get_by_role("heading", name="Pedidos", exact=True)),
    ("#/pedido/1", lambda p: p.locator("textarea.req-title")),
    ("#/novo", lambda p: p.get_by_role("heading", name="Novo pedido", exact=True)),
    ("#/clientes", lambda p: p.get_by_role("heading", name="Clientes", exact=True)),
    ("#/cliente/novo", lambda p: p.get_by_role("heading", name="Novo cliente", exact=True)),
    ("#/cliente/1", lambda p: p.locator("#cname")),
    ("#/financeiro", lambda p: p.get_by_role("heading", name="Financeiro", exact=True)),
    ("#/configuracoes", lambda p: p.get_by_role("heading", name="Configurações", exact=True)),
]
# what the sidebar (laptop) or tab bar (phone) links to, as Piero moves around; on the phone
# Financeiro takes Quadro's slot (decision 7)
LAPTOP_NAV = [
    "Quadro",
    "Pedidos",
    "Clientes",
    "Financeiro",
    "Configurações",
    "Novo pedido",
    "Painel",
]
PHONE_NAV = ["Financeiro", "Pedidos", "Clientes", "Novo", "Painel"]


@pytest.fixture(params=["laptop", "phone"])
def signed_in(request, live, device):
    """An admin with a session cookie, one client and one request, on a laptop or a phone."""
    base, auth, store = live
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Piero Sales', 'h', 1)"
        ).lastrowid
    store.save_client({"name": "Açougue Bom de Corte"})
    store.create_request({"client": 1, "what": "Crie uma campanha para leads"}, aid)
    d = device(**PHONE) if request.param == "phone" else device()
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
    d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    return base, auth, d.page, request.param


def drawn(page, marker, kind=None):
    """The screen finished loading and drew itself, not the 😕 error box."""
    expect(page.locator("#app .spinner")).to_have_count(0)
    expect(marker(page).first).to_be_visible()
    expect(page.locator("#app .empty", has_text="😕")).to_have_count(0)
    expect(page.locator("#app")).not_to_contain_text("is not an object")
    expect(page.locator("#app")).not_to_contain_text("Cannot read properties")
    if kind == "phone":  # the way to the other screens is still on screen
        expect(page.locator("#tabbar")).to_be_in_viewport(ratio=1)


def every_screen_works(page, base, kind):
    """Through the menu, as Piero moves around, then the screens only reached from a list."""
    nav = page.locator("#tabbar" if kind == "phone" else "#nav")
    marks = dict(SCREENS)
    for name in PHONE_NAV if kind == "phone" else LAPTOP_NAV:
        link = nav.get_by_role("link", name=re.compile(rf"^{name}"))
        link.click()
        drawn(page, marks[link.get_attribute("href")], kind)
    for hash_ in ("#/pedido/1", "#/cliente/1", "#/cliente/novo"):
        page.goto(f"{base}/{hash_}")
        drawn(page, marks[hash_], kind)


def open_invite(page, base, token):
    """Tapping an invite link in WhatsApp: a fresh page load on #/entrar/<token>."""
    page.goto(f"{base}/#/entrar/{token}")
    page.reload()
    expect(page.get_by_role("heading", name="Você já entrou")).to_be_visible()


@pytest.mark.parametrize("token", ["fresh", "used", "garbage"])
def test_invite_link_then_abrir_a_pauta(signed_in, token):
    base, auth, page, kind = signed_in
    link = {"garbage": "not-a-token"}.get(token) or auth.create_invite()[0]
    if token == "used":  # e.g. his own invite, still in the WhatsApp chat
        with auth.store.db() as conn:
            conn.execute("UPDATE invite SET uses = max_uses")
    open_invite(page, base, link)
    page.get_by_role("link", name="Abrir a Pauta").click()
    drawn(page, dict(SCREENS)["#/"], kind)
    every_screen_works(page, base, kind)


def test_invite_link_then_back(signed_in):
    """The back button from the invite to the screen the link was tapped from."""
    base, auth, page, kind = signed_in
    page.goto(f"{base}/#/quadro")
    drawn(page, dict(SCREENS)["#/quadro"], kind)
    open_invite(page, base, auth.create_invite()[0])
    page.go_back()
    drawn(page, dict(SCREENS)["#/quadro"], kind)
    every_screen_works(page, base, kind)


@pytest.mark.parametrize("hash_", [h for h, _ in SCREENS])
def test_invite_link_then_typing_another_address(signed_in, hash_):
    """No button: the address is edited (or a bookmark used) on the "Você já entrou" screen."""
    base, auth, page, kind = signed_in
    open_invite(page, base, auth.create_invite()[0])
    page.goto(f"{base}/{hash_}")
    drawn(page, dict(SCREENS)[hash_], kind)


@pytest.mark.parametrize("hash_", [h for h, _ in SCREENS])
def test_fresh_load_on_any_screen(signed_in, hash_):
    """A bookmark or a shared link straight to a screen, with the app not loaded yet."""
    base, _, page, kind = signed_in
    page.goto(f"{base}/{hash_}")
    page.reload()
    drawn(page, dict(SCREENS)[hash_], kind)
