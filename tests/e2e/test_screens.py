"""Every screen renders with real data, without JS errors or CSP violations, on both layouts."""

import re

import pytest
from playwright.sync_api import expect

from pauta import __version__, cli

pytestmark = pytest.mark.e2e

SCREENS = {
    "#/": "Renato",  # "Bom dia, Renato"
    "#/quadro": "Quadro",
    "#/pedidos": "Pedidos",
    "#/pedido/1": "Limpeza de pele",
    "#/novo": "Novo pedido",
    "#/clientes": "Clientes",
    "#/cliente/1": "Clínica Bem Estar",
    "#/cliente/novo": "Novo cliente",
    "#/financeiro": "Financeiro",
    "#/configuracoes": "Configurações",
    "#/perfil": "Perfil",
}


@pytest.fixture()
def signed_in(live, monkeypatch, device):
    """Demo data plus an admin session cookie, so each screen loads straight away."""
    base, auth, store = live
    monkeypatch.setenv("PAUTA_STATE_DIR", str(store.path.parent))
    cli.main(["demo"])
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin, email) "
            "VALUES ('Renato Lima', 'h', 1, 'nato@example.com')"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]

    def open_device(**args):
        d = device(**args)
        d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
        return d

    return base, open_device


@pytest.mark.parametrize("layout", ["desktop", "phone"])
def test_every_screen(signed_in, layout):
    base, open_device = signed_in
    args = (
        {"viewport": {"width": 390, "height": 844}, "is_mobile": True} if layout == "phone" else {}
    )
    page = open_device(**args).page
    for route, text in SCREENS.items():
        page.goto(f"{base}/{route}")
        expect(page.locator("#app")).to_contain_text(text)
        expect(page.locator("#app .spinner")).to_have_count(0)
    nav = page.locator("#tabbar" if layout == "phone" else "#nav")
    expect(nav).to_be_visible()
    brand = page.locator(".topbar .brand" if layout == "phone" else ".side .brand")
    expect(brand.locator(".ver")).to_have_text(f"v{__version__}")


def test_gravatar_shows_over_the_initials(signed_in):
    base, open_device = signed_in
    page = open_device().page
    page.goto(f"{base}/#/perfil")
    for img in (page.locator("#mechip .avatar img"), page.locator("#me .avatar img")):
        expect(img).to_have_attribute(
            "src", re.compile(r"^https://gravatar\.com/avatar/[0-9a-f]{64}\?")
        )


def test_a_screen_left_behind_does_not_take_the_address_back(signed_in):
    """The hash changes at once and the router hears of it a tick later. A list whose data
    arrived in between used to tidy its own address (`#/pedidos?f=open`) over the new one,
    and the router then went back to it: the person tapped Clientes and stayed on Pedidos."""
    base, open_device = signed_in
    page = open_device().page
    page.goto(f"{base}/#/clientes")
    expect(page.get_by_role("heading", name="Clientes", exact=True)).to_be_visible()
    # Pedidos' list answers only when the test says so (a slow connection on a phone)
    page.evaluate(
        """async () => {
          const real = window.fetch, data = await (await real("/api/requests")).json();
          window.held = new Promise((release) => { window.release = release; });
          window.fetch = (url, opts) => {
            if (url !== "/api/requests") return real(url, opts);
            window.asked = true;
            const answer = { ok: true, status: 200, json: () => Promise.resolve(data) };
            return window.held.then(() => answer);
          };
        }"""
    )
    page.evaluate("location.hash = '#/pedidos'")
    page.wait_for_function("window.asked === true")
    # the person taps Clientes, and the list arrives before the router has heard of the tap
    page.evaluate("() => { location.hash = '#/clientes'; window.release(); }")
    expect(page.get_by_role("heading", name="Clientes", exact=True)).to_be_visible()
    expect(page).to_have_url(re.compile(r"#/clientes$"))
    expect(page.get_by_role("heading", name="Pedidos", exact=True)).to_have_count(0)
