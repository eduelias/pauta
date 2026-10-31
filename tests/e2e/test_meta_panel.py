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


def test_linking_accounts_to_clients(live, device, fake_meta):
    """The Cliente column: a suggestion by name (not saved until picked), an account linked
    on its own by the client's ad_account, the toast, and the Meta card on the client page;
    an account unticked in Meta stays, greyed, and can still be re-pointed."""
    base, auth, store = live
    clinic = store.save_client({"name": "Clínica Bem Estar"})
    bakery = store.save_client({"name": "Padaria", "ad_account": "act_222"})
    store.save_client({"name": "Antigo", "state": "Encerrado"})
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Piero Sales")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Piero")
    page.goto(f"{base}/#/equipe")
    page.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")

    rows = page.locator("#metaaccounts tbody tr")
    expect(rows).to_have_count(2)
    first, second = rows.nth(0), rows.nth(1)
    # the clinic's account: unlinked, with the suggestion shown but not saved
    pick = first.locator("select[data-link='111']")
    expect(pick).to_have_value("")
    expect(first).to_contain_text("Sugestão: Clínica Bem Estar")
    expect(pick.locator("option", has_text="Clínica Bem Estar (sugestão)")).to_have_count(1)
    texts = pick.locator("option").all_inner_texts()
    assert texts[0] == "— sem cliente —" and texts[-1] == "Antigo"  # Ativo first, Encerrado last
    assert texts[1:3] == ["Clínica Bem Estar (sugestão)", "Padaria"]
    assert store.meta_accounts()[0]["client"] is None
    # the bakery's account came linked by its ad_account
    expect(second.locator("select[data-link='222']")).to_have_value(str(bakery["id"]))

    pick.select_option(str(clinic["id"]))
    expect(page.locator("#toast")).to_have_text("Conta vinculada a Clínica Bem Estar")
    expect(page.locator("#metaaccounts select[data-link='111']")).to_have_value(str(clinic["id"]))
    expect(page.locator("#metaaccounts tbody tr").first).not_to_contain_text("Sugestão")
    assert store.client(clinic["id"])["ad_account"] == "111"

    # the client page: this month's numbers of the linked account
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    card = page.locator("#clientmeta")
    expect(card).to_contain_text("Clínica Bem Estar")
    expect(card).to_contain_text("1.234,56")
    expect(card).to_contain_text("20.118")
    expect(card).to_contain_text("903")
    expect(card).to_contain_text("1,37")
    expect(card).to_contain_text("3.765,44")
    expect(card.locator(".row")).to_have_count(6)

    # unticked in Meta: the row stays, says so, and can still be unlinked
    fake_meta.accounts = fake_meta.accounts[:1]
    page.goto(f"{base}/#/equipe")
    page.locator("#meta").get_by_role("button", name="Atualizar").click()
    stale = page.locator("#metaaccounts tbody tr.stale")
    expect(stale).to_have_count(1)
    expect(stale).to_contain_text("Padaria Trigo de Ouro")
    expect(stale).to_contain_text("não aparece mais na Meta")
    stale.locator("select").select_option("")
    expect(page.locator("#toast")).to_have_text("Conta desvinculada")
    expect(page.locator("#metaaccounts tbody tr.stale select")).to_have_value("")
    assert store.client(bakery["id"])["ad_account"] == "act_222"

    # the bakery's page, as an admin with nothing linked: a pointer to Equipe
    page.goto(f"{base}/#/cliente/{bakery['id']}")
    expect(page.locator("#clientmeta")).to_contain_text("Nenhuma conta da Meta vinculada")
    expect(page.locator("#clientmeta").get_by_role("link")).to_have_attribute("href", "#/equipe")


def test_member_sees_the_card_but_no_pointer(live, device, fake_meta):
    base, auth, store = live
    clinic = store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    empty = store.save_client({"name": "Padaria"})
    # an admin connects first (the clinic's account links itself by ad_account on the read)
    token, _ = auth.create_invite(admin=True)
    admin = device().page
    admin.goto(f"{base}/#/entrar/{token}")
    admin.fill("#join input[name=name]", "Renato")
    admin.get_by_role("button", name="Criar passkey e entrar").click()
    expect(admin.locator("#mechip")).to_contain_text("Renato")
    admin.goto(f"{base}/#/equipe")
    admin.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(admin.locator("#toast")).to_have_text("Meta conectada")

    token, _ = auth.create_invite(admin=False)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Ana")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Ana")
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    expect(page.locator("#clientmeta")).to_contain_text("Investido este mês")
    expect(page.locator("#clientmeta")).to_contain_text("1.234,56")
    page.goto(f"{base}/#/cliente/{empty['id']}")
    expect(page.locator("#cname")).to_contain_text("Padaria")
    expect(page.locator("#clientmeta")).to_be_empty()
