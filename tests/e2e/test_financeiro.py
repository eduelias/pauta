"""Financeiro in the browser: the panel, registering a Pix, the client card, the settings."""

from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}


@pytest.fixture()
def admin(live, device):
    base, auth, store = live
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Piero Sales', 'h', 1)"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]

    def open_device(**args):
        d = device(**args)
        d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
        return d

    return base, store, open_device


def test_register_a_payment_from_the_panel(admin):
    base, store, open_device = admin
    c = store.save_client({"name": "Açougue Bom de Corte", "segment": "Alimentação"})
    store.save_client({"name": "Parado", "state": "Pausado"})
    page = open_device().page
    page.goto(f"{base}/#/financeiro")
    expect(page.get_by_role("heading", name="Financeiro", exact=True)).to_be_visible()
    expect(page.locator(".finrow")).to_have_count(1)  # the paused one is not in the panel
    expect(page.locator(".fstatus.awaiting_first").first).to_be_visible()

    page.locator(".finrow", has_text="Açougue").get_by_role("button", name="Registrar").click()
    form = page.locator("#payf")
    expect(form.locator("input[name=amount]")).to_have_value("100")
    ago = (date.today() - timedelta(days=3)).isoformat()
    form.locator("input[name=paid_on]").fill(ago)
    form.locator("select[name=method]").select_option("Pix")
    form.get_by_role("button", name="Registrar").click()
    expect(page.locator(".toast")).to_contain_text("Pagamento registrado")
    row = page.locator(".finrow", has_text="Açougue")
    expect(row).to_contain_text("1º mês")
    expect(row).to_contain_text("R$ 100")
    expect(page.locator(".panel-head .fstatus.paid")).to_be_visible()
    assert store.client(c["id"])["billing"]["anchor"] == ago
    expect(page.locator(".stats.fin .stat").first).to_contain_text("R$ 100")


def test_the_client_card_fee_void_and_not_billed(admin):
    base, store, open_device = admin
    c = store.save_client({"name": "Padaria"})
    page = open_device().page
    page.goto(f"{base}/#/cliente/{c['id']}")
    box = page.locator("#paybox")
    expect(box).to_contain_text("Aguardando 1º pagamento")
    expect(box).to_contain_text("Nenhum pagamento registrado")

    box.locator("#payfee").fill("150")
    box.locator("#payfee").blur()
    expect(page.locator(".toast")).to_contain_text("Salvo")
    assert store.client(c["id"])["billing"]["amount"] == 150

    box.get_by_role("button", name="Registrar pagamento").click()
    expect(page.locator("#payf input[name=amount]")).to_have_value("150")
    page.locator("#payf").get_by_role("button", name="Registrar").click()
    expect(page.locator(".toast")).to_contain_text("Pagamento registrado")
    expect(box.locator(".pay")).to_have_count(1)
    expect(box).to_contain_text("1º mês")
    expect(box.locator(".fstatus.paid")).to_be_visible()

    page.once("dialog", lambda d: d.accept())
    box.get_by_role("button", name="Anular").click()
    expect(page.locator(".toast")).to_contain_text("Pagamento anulado")
    expect(box.locator(".pay.void")).to_have_count(1)  # still listed, struck through
    expect(box).to_contain_text("Aguardando 1º pagamento")

    box.locator("#paybilled").uncheck()
    expect(box).to_contain_text("não é cobrado")
    assert store.client(c["id"])["billing"] is None
    page.goto(f"{base}/#/financeiro")
    expect(page.locator(".finrow")).to_have_count(0)


def test_settings_hide_money_from_members_and_the_phone_tab(admin, live, device):
    base, store, open_device = admin
    page = open_device().page
    page.goto(f"{base}/#/equipe")
    panel = page.locator("#finsettings")
    expect(panel).to_be_visible()
    panel.locator("[data-fin=visibility]").select_option("admins")
    panel.locator("[data-fin=grace_days]").fill("3")
    panel.get_by_role("button", name="Salvar financeiro").click()
    expect(page.locator(".toast")).to_contain_text("Financeiro salvo")
    s = store.finance_settings()
    assert s["visibility"] == "admins" and s["grace_days"] == 3
    expect(page.locator("#nav a[data-nav='#/financeiro']")).to_be_visible()  # admins keep it

    # a member: no tab, no money on the client page, Quadro back on the phone
    _, auth, _ = live
    with store.db() as conn:
        mid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Renato', 'h2', 0)"
        ).lastrowid
    value = auth.make_cookie(mid, secure=False).split(";")[0].split("=", 1)[1]
    phone = device(**PHONE)
    phone.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    c = store.save_client({"name": "Padaria"})
    phone.page.goto(f"{base}/#/cliente/{c['id']}")
    expect(phone.page.locator("#cname")).to_contain_text("Padaria")
    expect(phone.page.locator("#paybox .paybox")).to_have_count(0)
    expect(phone.page.locator("#tabbar a[data-nav='#/quadro']")).to_be_visible()
    expect(phone.page.locator("#tabbar a[data-nav='#/financeiro']")).to_have_count(0)
    phone.page.goto(f"{base}/#/financeiro")  # sent home
    expect(phone.page.locator(".hello h1")).to_be_visible()


def test_phone_tab_bar_shows_financeiro_instead_of_quadro(admin):
    base, store, open_device = admin
    page = open_device(**PHONE).page
    page.goto(f"{base}/#/")
    tab = page.locator("#tabbar a[data-nav='#/financeiro']")
    expect(tab).to_be_visible()
    expect(page.locator("#tabbar a[data-nav='#/quadro']")).to_have_count(0)
    tab.click()
    expect(page.get_by_role("heading", name="Financeiro", exact=True)).to_be_visible()
    expect(page.locator("#tabbar")).to_be_in_viewport(ratio=1)
