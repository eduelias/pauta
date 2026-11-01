"""The Meta card on Configurações in a real browser: the full trip to Meta's login (the fake one in
tests/fakemeta.py) and back without the session cookie, one block per connected portfolio,
the ad accounts table labelled by portfolio, and the history."""

import re

import pytest
from playwright.sync_api import expect

from fakemeta import ACCOUNTS, BUSINESS, OTHER_BUSINESS
from pauta.meta import NO_NUMBERS, REVOKED
from pauta.server import META_DOWN

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
    page.goto(f"{base}/#/configuracoes")
    card = page.locator("#meta")
    expect(card).to_contain_text("A Pauta só lê")
    # to facebook.com (the fake) and back: the callback has no cookie, the app still knows us
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page).to_have_url(re.compile(r"#/configuracoes$"))
    block = card.locator(f"[data-conn='{BUSINESS}']")
    expect(block).to_contain_text("Portfólio Agência Exemplo")
    expect(block).to_contain_text(
        re.compile(r"conectado à Pauta em \d\d/\d\d/\d{4} \(por Renato Lima\)")
    )
    expect(block).not_to_contain_text("conectado por")
    expect(card.get_by_role("button", name="Conectar outro portfólio")).to_be_visible()

    # the accounts and whose they are; the numbers live in Campanhas (decision 8)
    table = page.locator("#metaaccounts")
    expect(table.locator("thead th")).to_have_text(["Conta", "Cliente", "Saldo"])
    expect(table.locator("tbody tr")).to_have_count(2)
    clinic = table.locator("tbody tr").first
    expect(clinic).to_contain_text("Clínica Bem Estar")
    expect(clinic).to_contain_text("3.765,44")  # left before the spending limit
    expect(clinic).not_to_contain_text("1.234,56")
    expect(card).not_to_contain_text("Investido este mês")
    expect(table.locator("tbody tr").nth(1)).to_contain_text("Desativada")

    # Meta won't show the balance to this token: the rest still reads
    fake_meta.refuse_balance = True
    card.get_by_role("button", name="Atualizar").click()
    expect(clinic).to_contain_text("sem permissão")
    expect(clinic).to_contain_text("Clínica Bem Estar")

    page.once("dialog", lambda d: d.accept())
    block.get_by_role("button", name="Desconectar").click()
    expect(page.locator("#toast")).to_have_text("Portfólio desconectado")
    expect(card.get_by_role("button", name="Conectar Meta")).to_be_visible()

    # cancelled in Meta's dialog: back to Configurações with an error, nothing connected
    fake_meta.deny = True
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("A conexão foi cancelada na Meta")
    expect(page).to_have_url(re.compile(r"#/configuracoes$"))
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
    page.goto(f"{base}/#/configuracoes")
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
    page.goto(f"{base}/#/configuracoes")
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
    page.goto(f"{base}/#/configuracoes")
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

    # the client page: no campaign synced yet, the linked account's balance
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    card = page.locator("#clientmeta")
    expect(card).to_contain_text("Nenhuma campanha acompanhada nos últimos 30 dias")
    expect(card).to_contain_text("Saldo · Clínica Bem Estar")
    expect(card).to_contain_text("3.765,44")
    expect(card.locator(".row")).to_have_count(1)
    expect(card.get_by_role("link", name="Campanhas")).to_have_attribute("href", "#/campanhas")

    # unticked in Meta: the row stays, says so, and can still be unlinked
    fake_meta.accounts = fake_meta.accounts[:1]
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Atualizar").click()
    stale = page.locator("#metaaccounts tbody tr.stale")
    expect(stale).to_have_count(1)
    expect(stale).to_contain_text("Padaria Trigo de Ouro")
    expect(stale).to_contain_text("não aparece mais na Meta")
    stale.locator("select").select_option("")
    expect(page.locator("#toast")).to_have_text("Conta desvinculada")
    expect(page.locator("#metaaccounts tbody tr.stale select")).to_have_value("")
    assert store.client(bakery["id"])["ad_account"] == "act_222"

    # the bakery's page, as an admin with nothing linked: a pointer to Configurações
    page.goto(f"{base}/#/cliente/{bakery['id']}")
    expect(page.locator("#clientmeta")).to_contain_text("Nenhuma conta da Meta vinculada")
    expect(
        page.locator("#clientmeta").get_by_role("link", name="Vincule em Configurações → Meta.")
    ).to_have_attribute("href", "#/configuracoes")


def test_an_account_without_numbers_and_an_odd_currency(live, device, fake_meta):
    """Meta won't return one account's insights: the account list and the balance still
    read (the numbers live in Campanhas now). A currency Intl doesn't know (Meta's data)
    falls back to "<code> <value>" instead of breaking a card."""
    base, auth, store = live
    clinic = store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    fake_meta.accounts = [ACCOUNTS[0], {**ACCOUNTS[1], "currency": "N/A"}]
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Renato Lima")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    rows = page.locator("#metaaccounts tbody tr")
    expect(rows).to_have_count(2)
    expect(rows.nth(1)).to_contain_text("—")  # no spending limit: nothing to show
    assert page.evaluate("centsMoney(1234, 'N/A')") == "N/A 12.34"  # the fallback
    assert page.evaluate("centsMoney(1234, 'BRL')") == "R$\xa012,34"
    assert page.evaluate("centsMoney(null, 'BRL')") == "—"

    fake_meta.fail_insights = {"111"}
    page.locator("#meta").get_by_role("button", name="Atualizar").click()
    clinic_row = page.locator("#metaaccounts tbody tr").first
    expect(clinic_row).to_contain_text("Clínica Bem Estar")
    expect(clinic_row).to_contain_text("3.765,44")  # the balance read still worked
    expect(clinic_row.locator("td")).to_have_count(3)
    assert NO_NUMBERS  # the reason still travels in the API, for whoever reads it

    page.goto(f"{base}/#/cliente/{clinic['id']}")
    card = page.locator("#clientmeta")
    expect(card).to_contain_text("Nenhuma campanha acompanhada")
    expect(card).to_contain_text("3.765,44")
    expect(card).not_to_contain_text("Investido")


def test_member_sees_the_card_but_no_pointer(live, device, fake_meta):
    base, auth, store = live
    clinic = store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    empty = store.save_client({"name": "Padaria"})
    # an admin connects first (the clinic's account links itself by ad_account on the read)
    token, _ = auth.create_invite(admin=True)
    nato = device()
    admin = nato.page
    admin.goto(f"{base}/#/entrar/{token}")
    admin.fill("#join input[name=name]", "Renato")
    admin.get_by_role("button", name="Criar passkey e entrar").click()
    expect(admin.locator("#mechip")).to_contain_text("Renato")
    admin.goto(f"{base}/#/configuracoes")
    admin.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(admin.locator("#toast")).to_have_text("Meta conectada")

    token, _ = auth.create_invite(admin=False)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Ana")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Ana")
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    expect(page.locator("#clientmeta")).to_contain_text("Saldo · Clínica Bem Estar")
    expect(page.locator("#clientmeta")).to_contain_text("3.765,44")
    page.goto(f"{base}/#/cliente/{empty['id']}")
    expect(page.locator("#cname")).to_contain_text("Padaria")
    expect(page.locator("#clientmeta")).to_be_empty()

    # Meta revoked the token: the admin's refresh says so on the portfolio's block, which
    # still offers Adicionar contas (the way back in); Ana's client card only says the
    # numbers are unavailable, never "conecte de novo"
    fake_meta.token_invalid = True
    admin.locator("#meta").get_by_role("button", name="Atualizar").click()
    expect(admin.locator("#meta .warnbox")).to_have_text(REVOKED)
    block = admin.locator(f"#meta [data-conn='{BUSINESS}']")
    expect(block).to_contain_text("acesso revogado na Meta; reconecte em Adicionar contas")
    expect(block.get_by_role("button", name="Adicionar contas")).to_be_visible()
    expect(admin.locator("#metaaccounts tbody tr.stale")).to_have_count(2)  # kept, no numbers
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    expect(page.locator("#clientmeta .warnbox")).to_have_text(META_DOWN)
    expect(page.locator("#clientmeta")).not_to_contain_text("Investido")
    admin.goto(f"{base}/#/cliente/{clinic['id']}")
    expect(admin.locator("#clientmeta .warnbox")).to_have_text(REVOKED)


def test_two_portfolios_each_with_its_block(live, device, fake_meta):
    """Piero connects the agency's portfolio, then the client's own one (in Meta he picks a
    different business): one block per portfolio, the accounts labelled by theirs, the
    balance's "reconecte" hint, disconnecting one, and the history naming who did what."""
    base, auth, store = live
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Piero Sales")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Piero")
    page.goto(f"{base}/#/configuracoes")
    card = page.locator("#meta")
    card.get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    blocks = card.locator("[data-conn]")
    expect(blocks).to_have_count(1)
    # the toast hides itself after ~2 s; wait for that, or the second "Meta conectada" below
    # is satisfied by this one while the second connection is still on its way
    expect(page.locator("#toast")).to_be_hidden(timeout=5_000)

    fake_meta.business = OTHER_BUSINESS  # in Meta's dialog he picks the client's portfolio
    card.get_by_role("button", name="Conectar outro portfólio").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada", timeout=15_000)
    expect(blocks).to_have_count(2, timeout=15_000)  # a round trip through the fake Meta
    expect(blocks.nth(0)).to_contain_text("Portfólio Agência Exemplo")
    expect(blocks.nth(1)).to_contain_text("Portfólio Delta Imóveis")
    for i in range(2):
        expect(blocks.nth(i)).to_contain_text(
            re.compile(r"conectado à Pauta em \d\d/\d\d/\d{4} \(por Piero Sales\)")
        )
        expect(blocks.nth(i).get_by_role("button", name="Adicionar contas")).to_be_visible()
        expect(blocks.nth(i).get_by_role("button", name="Desconectar")).to_be_visible()
    rows = page.locator("#metaaccounts tbody tr")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("Portfólio Agência Exemplo")
    expect(rows.nth(2)).to_contain_text("Delta Imóveis")
    expect(rows.nth(2)).to_contain_text("Portfólio Delta Imóveis")
    expect(rows.nth(2)).to_contain_text("920,00")  # left before the client's limit

    # Meta refuses the balance: the hint still points at Adicionar contas
    fake_meta.refuse_balance = True
    card.get_by_role("button", name="Atualizar").click()
    expect(rows.nth(0)).to_contain_text("sem permissão · reconecte em Adicionar contas")
    fake_meta.refuse_balance = False

    # the client's account gets its client: the history will say so
    delta = store.save_client({"name": "Delta Imóveis"})
    page.reload()
    page.locator("#metaaccounts select[data-link='444']").select_option(str(delta["id"]))
    expect(page.locator("#toast")).to_have_text("Conta vinculada a Delta Imóveis")

    # disconnect the client's portfolio: one block left, its account stays greyed
    page.once("dialog", lambda d: d.accept())
    card.locator(f"[data-conn='{OTHER_BUSINESS}']").get_by_role(
        "button", name="Desconectar"
    ).click()
    expect(page.locator("#toast")).to_have_text("Portfólio desconectado")
    expect(card.locator("[data-conn]")).to_have_count(1)
    expect(card.locator("[data-conn]")).to_contain_text("Portfólio Agência Exemplo")
    stale = page.locator("#metaaccounts tbody tr.stale")
    expect(stale).to_have_count(1)
    expect(stale).to_contain_text("Delta Imóveis")
    expect(stale).to_contain_text("não aparece mais na Meta")

    # the history, newest first, with the actor
    hist = page.locator("#metalog")
    hist.locator("summary").click()
    lines = hist.locator("li")
    expect(lines).to_have_count(4)
    expect(lines.nth(0)).to_contain_text("Piero Sales desconectou o portfólio Delta Imóveis")
    expect(lines.nth(1)).to_contain_text(
        "Piero Sales vinculou a conta Delta Imóveis a Delta Imóveis"
    )
    expect(lines.nth(2)).to_contain_text("Piero Sales conectou o portfólio Delta Imóveis")
    expect(lines.nth(3)).to_contain_text("Piero Sales conectou o portfólio Agência Exemplo")
    expect(lines.nth(3)).to_contain_text(re.compile(r"· \d\d/\d\d \d\d:\d\d$"))
    assert [e["kind"] for e in store.meta_log_rows()] == [
        "disconnected",
        "linked",
        "connected",
        "connected",
    ]
