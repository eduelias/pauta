"""The client screens: the ads page link and its copy buttons, the state filter, deleting."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

ADS = "https://www.facebook.com/ads/library/?id=123"


@pytest.fixture()
def admin(live, device):
    base, auth, store = live
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Renato Lima', 'h', 1)"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
    d = device()
    d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    d.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    return base, store, d.page


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def test_ads_page_on_the_client_and_the_request(admin):
    base, store, page = admin
    c = store.save_client({"name": "Açougue Bom de Corte"})
    store.create_request({"client": c["id"], "what": "Promoção de churrasco"}, None)

    page.goto(f"{base}/#/cliente/{c['id']}")
    field = page.locator('input[data-f="ads_page"]')
    field.fill(ADS)
    field.blur()
    expect(page.locator(".toast")).to_contain_text("Salvo")
    shortcut = page.locator(".clientbox .ads-page")
    expect(shortcut.get_by_role("link", name="Página de anúncios")).to_have_attribute("href", ADS)
    shortcut.get_by_role("button", name="Copiar").click()
    expect(page.locator(".toast")).to_contain_text("Copiado")
    assert clipboard(page) == ADS
    assert store.client(c["id"])["ads_page"] == ADS

    page.goto(f"{base}/#/pedido/1")
    briefing = page.locator(".kv .v.ads-page")
    expect(briefing.get_by_role("link", name="Página de anúncios")).to_have_attribute("href", ADS)
    page.evaluate("navigator.clipboard.writeText('')")
    briefing.get_by_role("button", name="Copiar").click()
    assert clipboard(page) == ADS
    data = page.locator("aside .clientbox .ads-page")  # "Dados do cliente" on the request
    expect(data.get_by_role("button", name="Copiar")).to_be_visible()


def test_free_text_ads_page_is_shown_as_written(admin):
    base, store, page = admin
    c = store.save_client({"name": "Padaria", "ads_page": "pedir o link ao cliente"})
    page.goto(f"{base}/#/cliente/{c['id']}")
    row = page.locator(".clientbox .ads-page")
    expect(row).to_contain_text("pedir o link ao cliente")
    expect(row.get_by_role("link")).to_have_count(0)


def test_request_without_ads_page_points_to_the_client(admin):
    base, store, page = admin
    c = store.save_client({"name": "Ótica"})
    store.create_request({"client": c["id"], "what": "x"}, None)
    page.goto(f"{base}/#/pedido/1")
    link = page.locator(".kv .v.ads-page").get_by_role("link", name="Cadastrar no cliente")
    expect(link).to_have_attribute("href", f"#/cliente/{c['id']}")


def test_filter_clients_by_state(admin):
    base, store, page = admin
    for name, state in (
        ("A Ativo", "Ativo"),
        ("B Pausado", "Pausado"),
        ("C Encerrado", "Encerrado"),
    ):
        store.save_client({"name": name, "state": state})
    store.save_client({"name": "D Ativo"})
    page.goto(f"{base}/#/clientes")
    cards = page.locator("#grid .ccard")
    expect(cards).to_have_count(4)
    states = page.locator("#states")
    expect(states.get_by_role("button", name=re.compile(r"^Ativo"))).to_contain_text("2")
    states.get_by_role("button", name=re.compile(r"^Pausado")).click()
    expect(cards).to_have_count(1)
    expect(cards).to_contain_text("B Pausado")
    expect(page).to_have_url(re.compile(r"#/clientes\?s=Pausado$"))
    page.fill("#q", "nada")
    expect(page.locator("#grid")).to_contain_text("Nenhum cliente encontrado")
    page.fill("#q", "")
    page.reload()  # the filter survives a reload
    expect(cards).to_have_count(1)
    states.get_by_role("button", name=re.compile(r"^Todos")).click()
    expect(cards).to_have_count(4)


def test_delete_a_client_with_requests_needs_its_name(admin):
    base, store, page = admin
    c = store.save_client({"name": "Açougue Bom de Corte"})
    store.create_request({"client": c["id"], "what": "teste"}, None)
    page.goto(f"{base}/#/cliente/{c['id']}")
    page.get_by_role("button", name="Excluir cliente").click()
    dialog = page.locator("#delc")
    expect(dialog).to_contain_text("e o pedido")
    go = dialog.get_by_role("button", name="Excluir", exact=True)
    expect(go).to_be_disabled()
    dialog.locator("input[name=confirm]").fill("açougue")
    expect(go).to_be_disabled()
    dialog.locator("input[name=confirm]").fill(" açougue bom  de corte ")  # case and spaces ok
    expect(go).to_be_enabled()
    go.click()
    expect(page).to_have_url(re.compile(r"#/clientes$"))
    expect(page.locator(".toast")).to_contain_text("excluídos")
    assert store.clients() == [] and store.requests() == []


def test_cancel_keeps_the_client(admin):
    base, store, page = admin
    c = store.save_client({"name": "Fica"})
    page.goto(f"{base}/#/cliente/{c['id']}")
    page.get_by_role("button", name="Excluir cliente").click()
    page.locator("#delc").get_by_role("button", name="Cancelar").click()
    expect(page.locator("#modal")).to_be_hidden()
    assert len(store.clients()) == 1
