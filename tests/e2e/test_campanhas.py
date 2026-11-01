"""Campanhas in the browser (decision 8): the tab only with Meta on, the period picker that
prints its dates (Ads Manager's "Últimos 30 dias" by default), the per-client list after a
sync with Ads Manager's columns (Resultados with the objective's label, Custo por resultado,
Valor gasto, Impressões, Alcance, Orçamento) and "ativa desde", Não acompanhar / ver
ignoradas, Visto hoje, the campaign page with its cards and SVG charts, Configurações → Meta
without the monthly totals, and the client card listing campaigns.

The browsers here live in São Paulo (`timezone_id`), like Piero's phone and the fixture ad
accounts, so the dates the picker computes agree with the day the sync wrote, whatever
the hour the suite runs at on a CET machine."""

import re
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect

from fakemeta import TZ, expected
from pauta import sync
from pauta.meta import local_today

pytestmark = pytest.mark.e2e

PHONE = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
CONVERSATIONS = "Conversas por mensagem iniciadas"


@pytest.fixture()
def meta(meta_on):
    return meta_on


def today() -> date:
    """The day in São Paulo: the browser's, the ad accounts' and the sync's."""
    return local_today(TZ)


def label(since: date, until: date) -> str:
    """What the picker prints: "1 nov – 1 nov" (the year only when it isn't this one)."""
    year = today().year

    def one(d):
        return f"{d.day} {MONTHS[d.month - 1]}" + (f" {d.year}" if d.year != year else "")

    return f"{one(since)} – {one(until)}"


def brl(cents: int) -> str:
    whole, frac = divmod(cents, 100)
    return f"{whole:,}".replace(",", ".") + f",{frac:02d}"


def join(page, base, token, name):
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", name)
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text(name.split()[0])


@pytest.fixture()
def synced(live, device, meta):
    """Renato (admin) signed in, Meta connected through its login, both accounts linked to
    their clients by ad_account, one sync done with the real date."""
    base, auth, store = live
    clinic = store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    bakery = store.save_client({"name": "Padaria Trigo de Ouro", "ad_account": "222"})
    token, _ = auth.create_invite(admin=True)
    laptop = device(timezone_id=TZ)
    page = laptop.page
    join(page, base, token, "Renato Lima")
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page.locator("#metaaccounts tbody tr")).to_have_count(2)  # the read linked them
    out = sync.run(store, meta, days=sync.HOURLY_DAYS)  # "today" is the accounts' own day
    assert out["accounts"] == 2 and out["campaigns_new"] == 3, out
    return base, store, laptop, clinic, bakery


def test_tab_only_with_meta_enabled(live, device, meta):
    base, auth, _ = live
    meta.secret_file.unlink()  # no app secret on the server: Meta is off
    token, _ = auth.create_invite(admin=True)
    page = device().page
    join(page, base, token, "Renato Lima")
    expect(page.locator("#nav a[data-nav='#/campanhas']")).to_have_count(0)
    expect(page.locator("#tabbar a[data-nav='#/campanhas']")).to_have_count(0)
    expect(page.locator("#tabbar a")).to_have_count(5)  # the slot stays Financeiro's/Quadro's
    page.goto(f"{base}/#/campanhas")
    expect(page).to_have_url(re.compile(r"/#/$"))


def test_list_with_the_period_picker(synced, live, device):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    t = today()
    since, until = t - timedelta(days=30), t - timedelta(days=1)
    expect(page.locator("#nav a[data-nav='#/campanhas']")).to_be_visible()
    expect(page.locator("#tabbar a[data-nav='#/campanhas']")).to_have_count(1)
    page.locator("#nav a[data-nav='#/campanhas']").click()
    expect(page.get_by_role("heading", name="Campanhas", exact=True)).to_be_visible()
    # Ads Manager's default: the last 30 days, yesterday back, today out
    expect(page).to_have_url(re.compile(r"#/campanhas\?p=last_30$"))
    expect(page.locator(".seg button.on")).to_have_text("Últimos 30 dias")
    expect(page.locator("#pdates")).to_have_text(label(since, until))
    expect(page.locator("#ptoday")).to_have_count(0)

    # two clients, three campaigns, Ads Manager's columns in its order
    blocks = page.locator(".cblock")
    expect(blocks).to_have_count(2)
    expect(blocks.first).to_contain_text("Clínica Bem Estar")
    expect(blocks.nth(1)).to_contain_text("Padaria Trigo de Ouro")
    expect(page.locator(".krow[data-id]")).to_have_count(3)
    expect(page.locator(".khead").first.locator(".km span")).to_have_text(
        ["Resultados", "Custo por resultado", "Valor gasto", "Impressões", "Alcance", "Orçamento"]
    )
    expect(page.locator("#app")).not_to_contain_text("Investido")
    expect(page.locator("#synced")).to_contain_text("Dados da Meta de")
    expect(page.locator("#seenline")).to_have_text("Hoje: 0 de 2 clientes vistos")
    want = expected("23850001", since, until, date(2026, 10, 3))
    limpeza = page.locator(".krow[data-id]", has_text="Limpeza de pele novembro")
    # Resultados as Ads Manager counts them for the objective, its label underneath
    expect(limpeza.locator(".km-results b")).to_have_text(str(want["results"]))
    expect(limpeza.locator(".km-results .ksub")).to_have_text(CONVERSATIONS)
    expect(limpeza.locator(".km-cpr b")).to_contain_text(
        brl(round(want["spend_cents"] / want["results"]))
    )
    expect(limpeza.locator(".km-cpr .ksub")).to_have_text(CONVERSATIONS)
    expect(limpeza.locator(".km-spend b")).to_have_text(
        re.compile(re.escape(brl(want["spend_cents"])))
    )
    expect(limpeza.locator(".km-reach b")).to_have_text(f"{500 * want['days']:,}".replace(",", "."))
    expect(limpeza.locator(".km-impressions b")).to_have_text(
        f"{want['impressions']:,}".replace(",", ".")
    )
    expect(limpeza.locator(".km-budget b")).to_contain_text("15,00 · diário")
    expect(limpeza.locator(".state")).to_have_text("Ativa")
    expect(limpeza.locator(".state")).to_have_attribute("title", "ACTIVE")
    expect(limpeza.locator(".ksince")).to_have_text("ativa desde 3 out")
    # Botox: Meta names the indicator (Cadastros) and counts nothing: "—", a lifetime budget
    botox = page.locator(".krow[data-id]", has_text="Botox outubro")
    expect(botox.locator(".km-results b span")).to_have_text("—")
    expect(botox.locator(".km-results b span")).to_have_attribute(
        "title", "sem resultados registrados para o objetivo da campanha"
    )
    expect(botox.locator(".km-results .ksub")).to_have_count(0)
    expect(botox.locator(".km-cpr b span")).to_have_text("—")
    expect(botox.locator(".km-budget b")).to_contain_text("450,00 · total")
    expect(botox.locator(".ksince")).to_have_text("ativa desde 12 out")
    # Panetone: no `results` from Meta, so the objective's action (link clicks); no budget
    panetone = page.locator(".krow[data-id]", has_text="Panetone")
    pan = expected("23850004", since, until, date(2026, 10, 15))
    expect(panetone.locator(".km-results b")).to_have_text(str(pan["results"]))
    expect(panetone.locator(".km-results .ksub")).to_have_text("Cliques no link")
    expect(panetone.locator(".km-budget b span")).to_have_text("—")
    # the client's totals: reach and budget don't add up; results only when they count the
    # same thing (the clinic's two don't; the bakery's one does)
    total = blocks.first.locator(".ktotal")
    expect(total.locator(".km-reach b span")).to_have_text("—")
    expect(total.locator(".km-reach b span")).to_have_attribute("title", re.compile("não soma"))
    expect(total.locator(".km-results b span")).to_have_attribute("title", re.compile("não somam"))
    expect(total.locator(".km-budget b span")).to_have_text("—")
    expect(total.locator(".km-impressions b")).not_to_have_text("0")
    bakery_total = blocks.nth(1).locator(".ktotal")
    expect(bakery_total.locator(".km-results b")).to_have_text(str(pan["results"]))
    expect(bakery_total.locator(".km-results .ksub")).to_have_text("Cliques no link")

    # Este mês includes today, and says so
    page.get_by_role("button", name="Este mês").click()
    expect(page.locator("#pdates")).to_have_text(label(t.replace(day=1), t))
    expect(page.locator("#ptoday")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#/campanhas\?p=this_month$"))
    # Últimos 7 dias: yesterday back, today out, kept in the hash and remembered
    yesterday = t - timedelta(days=1)
    page.get_by_role("button", name="Últimos 7 dias").click()
    expect(page.locator("#pdates")).to_have_text(label(t - timedelta(days=7), yesterday))
    expect(page.locator("#ptoday")).to_have_count(0)
    expect(page).to_have_url(re.compile(r"#/campanhas\?p=last_7$"))
    page.reload()
    expect(page.locator("#pdates")).to_have_text(label(t - timedelta(days=7), yesterday))
    page.goto(f"{base}/#/pedidos")
    page.goto(f"{base}/#/campanhas")  # no query: the browser remembers the last choice
    expect(page).to_have_url(re.compile(r"#/campanhas\?p=last_7$"))
    # Personalizado: two dates, kept as since/until
    page.get_by_role("button", name="Personalizado").click()
    page.locator("#psince").fill("2026-10-10")
    expect(page.locator("#pdates")).to_contain_text("10 out")  # each date redraws: one at a time
    page.locator("#puntil").fill("2026-10-12")
    expect(page.locator("#pdates")).to_have_text(label(date(2026, 10, 10), date(2026, 10, 12)))
    expect(page).to_have_url(re.compile(r"since=2026-10-10&until=2026-10-12$"))
    limpeza = page.locator(".krow[data-id]", has_text="Limpeza de pele novembro")
    expect(limpeza.locator(".km-spend b")).to_contain_text(brl(1010 + 1011 + 1012))
    expect(limpeza.locator(".km-results b")).to_have_text("6")
    expect(limpeza.locator(".km-cpr b")).to_contain_text(brl(round(3033 / 6)))
    # Botox started on the 12th, inside this range: the note says why its numbers are short
    expect(page.locator("#latenote")).to_contain_text("depois de 10 out")
    # Hoje prints the same day twice
    page.get_by_role("button", name="Hoje", exact=True).click()
    expect(page.locator("#pdates")).to_have_text(label(t, t))

    # a member sees the list and the tab, not the admin's buttons
    base_, auth, _ = live
    token, _ = auth.create_invite(admin=False)
    member = device(timezone_id=TZ).page
    join(member, base, token, "Ana")
    member.goto(f"{base}/#/campanhas")
    expect(member.locator(".cblock")).to_have_count(2)
    expect(member.locator("#nav a[data-nav='#/campanhas']")).to_be_visible()
    expect(member.locator("#syncnow")).to_have_count(0)
    expect(member.locator("[data-skip]")).to_have_count(0)
    expect(member.locator("[data-seen]").first).to_be_visible()  # the daily check is everyone's


def test_skip_follow_again_and_sync_now(synced):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas?p=this_month")
    rows = page.locator(".krow[data-id]")
    expect(rows).to_have_count(3)
    page.once("dialog", lambda d: d.accept())
    rows.filter(has_text="Botox outubro").get_by_role("button", name="Não acompanhar").click()
    expect(page.locator("#toast")).to_have_text("Campanha ignorada")
    expect(page.locator(".krow[data-id]")).to_have_count(2)
    expect(page.locator("#app")).not_to_contain_text("Botox outubro")
    # ver ignoradas lists it, greyed, with Acompanhar
    page.locator("#showskipped").check()
    expect(page.locator(".krow[data-id]")).to_have_count(3)
    skipped = page.locator(".krow.skipped")
    expect(skipped).to_have_count(1)
    expect(skipped).to_contain_text("Botox outubro")
    expect(skipped.locator(".state")).to_have_text("Ignorada")
    skipped.get_by_role("button", name="Acompanhar").click()
    expect(page.locator("#toast")).to_contain_text("de volta à lista")
    expect(page.locator(".krow.skipped")).to_have_count(0)
    expect(page.locator(".krow[data-id]")).to_have_count(3)
    # Atualizar agora: the sync's summary in a toast; a second tap hits the 15-minute limit
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#toast")).to_contain_text("2 contas lidas")
    laptop.expected.add((429, "/api/meta/sync"))
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#toast")).to_contain_text("menos de 15 minutos")


def test_visto_hoje(synced):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas?p=this_month")
    blocks = page.locator(".cblock")
    expect(blocks.first).to_contain_text("Clínica Bem Estar")
    expect(page.locator("#seenline")).to_have_text("Hoje: 0 de 2 clientes vistos")
    blocks.first.get_by_role("button", name="Visto hoje", exact=True).click()
    expect(page.locator("#toast")).to_have_text("Clínica Bem Estar: visto hoje")
    expect(page.locator("#seenline")).to_have_text("Hoje: 1 de 2 clientes vistos")
    # the seen client sinks to the bottom, marked; a reload keeps it
    expect(page.locator(".cblock").first).to_contain_text("Padaria Trigo de Ouro")
    seen = page.locator(".cblock").nth(1)
    expect(seen).to_contain_text("Clínica Bem Estar")
    expect(seen.locator(".seen")).to_have_text(re.compile(r"visto hoje por Renato"))
    expect(seen.get_by_role("button", name="Visto hoje", exact=True)).to_have_count(0)
    page.reload()
    expect(page.locator("#seenline")).to_have_text("Hoje: 1 de 2 clientes vistos")
    expect(page.locator(".cblock").first).to_contain_text("Padaria Trigo de Ouro")
    # with a note: the prompt's text lands in the review rows
    page.once("dialog", lambda d: d.accept("subi a verba"))
    page.locator(".cblock").first.locator("[data-note]").click()
    expect(page.locator("#seenline")).to_have_text("Hoje: 2 de 2 clientes vistos")
    with store.db() as db:
        notes = [r[0] for r in db.execute("SELECT note FROM review ORDER BY id")]
    assert notes == ["", "", "subi a verba"]  # the clinic's two campaigns, then the bakery's


def test_campaign_page_cards_charts_and_remembered_chips(synced):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas?p=this_month")
    page.locator(".krow[data-id] a", has_text="Limpeza de pele novembro").click()
    expect(page).to_have_url(re.compile(r"#/campanha/\d+\?p=this_month$"))
    expect(page.locator("#kname")).to_have_text("Limpeza de pele novembro")
    head = page.locator(".head")
    expect(head).to_contain_text("Clínica Bem Estar")
    expect(head.locator(".state")).to_have_text("Ativa")
    expect(head).to_contain_text("desde 03/10/2026")
    t = today()
    expect(page.locator("#pdates")).to_have_text(label(t.replace(day=1), t))

    # the default chips are Ads Manager's: Resultados, Custo por resultado, Valor gasto, each
    # a card with a chart; Resultados says what it counts under the number
    chips = page.locator("#metrics .chip.on")
    expect(chips).to_have_text(["Resultados", "Custo por resultado", "Valor gasto"])
    expect(page.locator(".mcard")).to_have_count(3)
    expect(page.locator(".mcard svg.chart")).to_have_count(3)
    results = page.locator(".mcard[data-card='results']")
    expect(results.locator(".mval")).to_have_text(str(2 * t.day))
    expect(results.locator(".msub")).to_have_text(CONVERSATIONS)
    expect(results.locator("svg rect")).to_have_count(t.day)
    expect(page.locator(".mcard[data-card='cpr'] .msub")).to_have_text(CONVERSATIONS)
    expect(page.locator(".mcard[data-card='cpr'] .mval")).to_contain_text("R$")
    expect(page.locator(".mcard[data-card='spend'] .mval")).to_contain_text("R$")
    expect(page.locator(".mcard[data-card='spend'] svg rect").first).to_be_visible()
    expect(page.locator(".mcard[data-card='spend'] .chart-y")).to_contain_text("R$")
    expect(page.locator(".mcard[data-card='spend'] .chart-x span")).to_have_count(2)
    # Leads (cliques) and Custo por lead stay in the picker, off by default
    expect(page.locator("#metrics .chip", has_text="Leads (cliques)")).to_have_attribute(
        "aria-pressed", "false"
    )
    expect(page.locator("#metrics .chip", has_text="Custo por lead")).to_have_count(1)
    # the actions in the data are chips too, with Ads Manager's name when known
    extra = page.locator("#metrics .chip", has_text=CONVERSATIONS)
    expect(extra).to_have_count(1)
    extra.click()
    card = page.locator(
        ".mcard[data-card='act:onsite_conversion.messaging_conversation_started_7d']"
    )
    expect(card.locator(".mval")).to_have_text(str(2 * t.day))
    expect(card.locator("svg.chart")).to_have_count(1)
    # frequency is period-only: a value, no chart
    page.locator("#metrics .chip", has_text="Frequência").click()
    freq = page.locator(".mcard[data-card='freq']")
    expect(freq).to_contain_text("Só no período")
    expect(freq.locator("svg")).to_have_count(0)
    page.locator("#metrics .chip", has_text="Valor gasto").click()  # off
    page.locator("#metrics .chip", has_text="Leads (cliques)").click()  # on
    expect(page.locator(".mcard")).to_have_count(5)
    page.reload()
    expect(page.locator("#metrics .chip.on")).to_have_text(
        ["Resultados", "Custo por resultado", "Leads (cliques)", "Frequência", CONVERSATIONS]
    )
    expect(page.locator(".mcard")).to_have_count(5)
    # the period picker works here too: Ontem is one bar
    page.get_by_role("button", name="Ontem").click()
    yesterday = t - timedelta(days=1)
    expect(page.locator("#pdates")).to_have_text(label(yesterday, yesterday))
    expect(page.locator(".mcard[data-card='leads'] svg rect")).to_have_count(1)
    expect(page.locator(".mcard[data-card='leads'] .mval")).to_have_text(str(yesterday.day))
    expect(page.locator(".mcard[data-card='results'] .mval")).to_have_text("2")
    # Botox: an indicator and nothing counted, "—" with the reason, no bars
    page.goto(f"{base}/#/campanhas?p=this_month")
    page.locator(".krow[data-id] a", has_text="Botox outubro").click()
    expect(page.locator("#kname")).to_have_text("Botox outubro")
    results = page.locator(".mcard[data-card='results']")
    expect(results.locator(".mval")).to_have_text("—")
    expect(results.locator(".mval")).to_have_attribute("title", re.compile("sem resultados"))
    expect(results.locator(".msub")).to_have_text("Cadastros")
    expect(results.locator("svg rect")).to_have_count(0)
    expect(page.locator(".mcard[data-card='cpr'] .mval")).to_have_text("—")


def test_configuracoes_meta_and_the_client_card(synced):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/configuracoes")
    table = page.locator("#metaaccounts")
    expect(table.locator("thead th")).to_have_text(["Conta", "Cliente", "Saldo"])
    expect(page.locator("#meta")).not_to_contain_text("Investido este mês")
    expect(page.locator("#meta")).to_contain_text("3.765,44")
    expect(page.locator("#meta").get_by_role("link", name="Campanhas")).to_be_visible()

    page.goto(f"{base}/#/cliente/{clinic['id']}")
    card = page.locator("#clientmeta")
    expect(card.locator(".kcard")).to_have_count(2)
    expect(card).to_contain_text("Limpeza de pele novembro")
    expect(card).to_contain_text("Botox outubro")
    expect(card).to_contain_text("últimos 30 dias")
    expect(card).not_to_contain_text("Investido")
    limpeza = card.locator(".kcard", has_text="Limpeza de pele novembro")
    expect(limpeza).to_contain_text("Resultados")
    expect(limpeza).to_contain_text(CONVERSATIONS)
    expect(limpeza).to_contain_text("Custo por resultado")
    expect(limpeza).to_contain_text("Valor gasto")
    botox = card.locator(".kcard", has_text="Botox outubro")
    expect(botox.locator("span[title^='sem resultados']")).to_have_count(2)  # results and cost
    expect(card.locator(".kcard").first.locator("a.row")).to_have_attribute(
        "href", re.compile(r"^#/campanha/\d+$")
    )
    expect(card).to_contain_text("Saldo · Clínica Bem Estar")
    expect(card).to_contain_text("3.765,44")
    expect(card.get_by_role("link", name="Campanhas")).to_have_attribute("href", "#/campanhas")


def test_balance_refused_says_what_to_do(synced, fake_meta):
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    fake_meta.refuse_balance = True
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Atualizar").click()
    cell = page.locator("#metaaccounts tbody tr").first.locator("td").nth(2).locator("span")
    expect(cell).to_have_text("sem permissão · reconecte em Adicionar contas")
    expect(cell).to_have_attribute("title", "sem permissão para ler o saldo")
    page.goto(f"{base}/#/cliente/{clinic['id']}")
    expect(page.locator("#clientmeta")).to_contain_text("reconecte em Adicionar contas")


def test_phone_tab_and_tiles(live, device, meta):
    base, auth, store = live
    store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    token, _ = auth.create_invite(admin=True)
    page = device(**PHONE, timezone_id=TZ).page
    join(page, base, token, "Piero Sales")
    tab = page.locator("#tabbar a[data-nav='#/campanhas']")
    expect(tab).to_be_visible()
    expect(page.locator("#tabbar a")).to_have_count(5)  # Campanhas took the fourth slot
    expect(page.locator("#tabbar a[data-nav='#/quadro']")).to_have_count(0)
    expect(page.locator("#tabbar a[data-nav='#/financeiro']")).to_have_count(0)
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page.locator("#metaaccounts tbody tr")).to_have_count(2)
    sync.run(store, meta, days=sync.HOURLY_DAYS)
    tab.click()
    expect(page.locator(".cblock")).to_have_count(1)
    expect(page.locator(".krow[data-id]")).to_have_count(2)
    # the phone layout: the labels show on the tiles (six of them), the header row doesn't
    expect(page.locator(".krow[data-id] .km-spend .kl").first).to_be_visible()
    expect(page.locator(".krow[data-id] .km-budget .kl").first).to_be_visible()
    expect(page.locator(".krow[data-id]").first.locator(".km")).to_have_count(6)
    expect(page.locator(".krow[data-id] .km-results .ksub").first).to_be_visible()
    expect(page.locator(".krow.khead").first).to_be_hidden()
    expect(page.locator("#pdates")).to_be_visible()
    expect(page.locator(".seg button.on")).to_have_text("Últimos 30 dias")
