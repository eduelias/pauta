"""The Meta card on Equipe in a real browser: the full trip to Meta's login (the fake one in
tests/fakemeta.py) and back without the session cookie, then the ad accounts table."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture()
def meta(meta_on):
    return meta_on


def test_connect_read_and_disconnect(live, device, fake_meta):
    base, auth, store = live
    token, _ = auth.create_invite(admin=True)
    laptop = device()
    page = laptop.page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Renato Lima")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")

    # not connected: one line and the button
    page.goto(f"{base}/#/equipe")
    card = page.locator("#meta")
    expect(card).to_contain_text("A Pauta só lê")
    # to facebook.com (the fake) and back: the callback has no cookie, the app still knows us
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page).to_have_url(re.compile(r"#/equipe$"))
    expect(card).to_contain_text("Conectado: Agência Exemplo desde")

    table = page.locator("#metaaccounts")
    expect(table.locator("tbody tr")).to_have_count(2)
    clinic = table.locator("tbody tr").first
    expect(clinic).to_contain_text("Clínica Bem Estar")
    expect(clinic).to_contain_text("1.234,56")  # investido
    expect(clinic).to_contain_text("20.118")  # alcance
    expect(clinic).to_contain_text("1,37")  # custo por clique
    expect(clinic).to_contain_text("3.765,44")  # left before the spending limit
    expect(table.locator("tbody tr").nth(1)).to_contain_text("Desativada")

    # Meta won't show the balance to this token: the rest still reads
    fake_meta.refuse_balance = True
    card.get_by_role("button", name="Atualizar").click()
    expect(clinic).to_contain_text("sem permissão")
    expect(clinic).to_contain_text("1.234,56")

    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="Desconectar").click()
    expect(page.locator("#toast")).to_have_text("Meta desconectada")
    expect(card.get_by_role("button", name="Conectar Meta")).to_be_visible()

    # cancelled in Meta's dialog: back to Equipe with an error, nothing connected
    fake_meta.deny = True
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("A conexão foi cancelada na Meta")
    expect(page).to_have_url(re.compile(r"#/equipe$"))
    expect(page.locator("#meta").get_by_role("button", name="Conectar Meta")).to_be_visible()


def test_adding_a_new_clients_account(live, device, fake_meta):
    """Piero picked one account; a new client means another trip through Meta's login, where
    he ticks the old and the new account, and the table grows."""
    base, auth, _ = live
    fake_meta.accounts = fake_meta.accounts[:1]
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Piero Sales")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Piero")
    page.goto(f"{base}/#/equipe")
    card = page.locator("#meta")
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page.locator("#metaaccounts tbody tr")).to_have_count(1)
    expect(card).to_contain_text("Cliente novo?")

    fake_meta.accounts = list(fake_meta.default_accounts)  # in Meta he ticks both
    page.once("dialog", lambda d: d.accept())
    card.get_by_role("button", name="Adicionar contas").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page.locator("#metaaccounts tbody tr")).to_have_count(2)
    assert fake_meta.exchanges == 2


def test_hidden_without_the_secret(live, device, meta):
    base, auth, _ = live
    meta.secret_file.unlink()  # no app secret on the server: Meta is off
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Renato Lima")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")
    page.goto(f"{base}/#/equipe")
    expect(page.locator("#drive")).to_be_visible()
    expect(page.locator("#meta")).to_have_count(0)
