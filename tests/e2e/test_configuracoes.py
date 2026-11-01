"""The Configurações tab (up to 1.6 "Equipe"): its name in the menu, the old address and its
deep links landing on the new one, the sections in order, and what a member sees of it."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture()
def people(live, device):
    """An admin (Renato) and a member (Piero), each with a session cookie on their own device."""
    base, auth, store = live

    def signed_in(name, admin):
        with store.db() as conn:
            aid = conn.execute(
                "INSERT INTO account(name, handle, is_admin) VALUES (?, ?, ?)",
                (name, f"h-{name}", int(admin)),
            ).lastrowid
        value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
        d = device()
        d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
        return d.page

    return base, signed_in("Renato Lima", True), signed_in("Piero", False)


def test_the_tab_is_called_configuracoes(people):
    base, admin, _ = people
    admin.goto(f"{base}/#/")
    tab = admin.locator("#nav a[data-nav='#/configuracoes']")
    expect(tab).to_have_text("Configurações")
    expect(admin.locator("#nav")).not_to_contain_text("Equipe")
    tab.click()
    expect(admin.get_by_role("heading", name="Configurações", exact=True)).to_be_visible()
    expect(tab).to_have_class("on")
    # the avatar in the sidebar opens the account menu: the person's page, then this one
    admin.click("#mechip")
    menu = admin.locator(".menu")
    expect(menu.get_by_role("link", name="Meu perfil")).to_have_attribute("href", "#/perfil")
    expect(menu.get_by_role("link", name="Configurações")).to_have_attribute(
        "href", "#/configuracoes"
    )
    expect(menu).not_to_contain_text("Adicionar passkey")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("#/equipe", "#/configuracoes"),
        ("#/equipe?meta=conectado", "#/configuracoes"),  # Meta's way back: query kept, then eaten
        ("#/equipe/qualquer?x=1", "#/configuracoes/qualquer?x=1"),  # a suffix survives the move
    ],
)
def test_the_old_address_redirects(people, old, new):
    base, admin, _ = people
    seen = []  # every address the page passes through, replaceState included
    admin.on("framenavigated", lambda f: seen.append(f.url) if f == admin.main_frame else None)
    admin.goto(f"{base}/{old}")
    if old == "#/equipe?meta=conectado":
        expect(admin.locator(".toast")).to_have_text("Meta conectada")
    if "qualquer" in new:  # an unknown screen: the router sends it home, as always
        expect(admin).to_have_url(f"{base}/#/")
        assert f"{base}/{new}" in seen
    else:
        expect(admin).to_have_url(f"{base}/{new}")
        expect(admin.get_by_role("heading", name="Configurações", exact=True)).to_be_visible()
    assert not [u for u in seen if "equipe" in u and u != f"{base}/{old}"]


def test_sections_in_order_for_an_admin(people):
    base, admin, _ = people
    admin.goto(f"{base}/#/configuracoes")
    expect(admin.locator("#drive")).to_be_visible()
    headings = admin.locator("#app section.panel > .panel-head h2").all_inner_texts()
    # Meta only shows with PAUTA_META_APP_ID; Acompanhamento has no settings panel yet
    assert headings == ["Time", "Financeiro", "Listas", "Arquivos"]
    # what is about the person moved to Perfil: one line points there
    expect(admin.locator("#toprofile")).to_contain_text("Seu perfil →")
    expect(admin.locator("#toprofile")).to_have_attribute("href", "#/perfil")
    expect(admin.locator("#myname")).to_have_count(0)
    time_panel = admin.locator("#time")
    expect(time_panel).to_contain_text("2 pessoas")
    expect(time_panel.get_by_role("heading", name="Convidar alguém")).to_be_visible()
    expect(time_panel.locator("#invite")).to_be_visible()
    expect(admin.get_by_role("button", name="Exportar dados")).to_be_visible()


def test_a_member_sees_the_team_and_nothing_to_administer(people):
    base, _, member = people
    member.goto(f"{base}/#/configuracoes")
    expect(member.get_by_role("heading", name="Configurações", exact=True)).to_be_visible()
    headings = member.locator("#app section.panel > .panel-head h2").all_inner_texts()
    assert headings == ["Time"]
    expect(member.locator("#toprofile")).to_be_visible()
    expect(member.locator(".member", has_text="Renato Lima")).to_be_visible()
    for missing in ("#invite", "#drive", "#finsettings", "#lists", "#export", "[data-m]"):
        expect(member.locator(missing)).to_have_count(0)
