"""Campanhas in the browser (decision 8): the tab only with Meta on, the period picker that
prints its dates (Ads Manager's "Últimos 30 dias" by default), the per-client list after a
sync with Ads Manager's columns (Resultados with the objective's label, Custo por resultado,
Valor gasto, Impressões, Alcance, Orçamento) and "ativa desde", Não acompanhar / ver
ignoradas, Visto hoje, the campaign page with its cards and SVG charts, Configurações → Meta
without the monthly totals, and the client card listing campaigns.

The browsers here live in São Paulo (`timezone_id`), like Piero's phone and the fixture ad
accounts, so the dates the picker computes agree with the day the sync wrote, whatever
the hour the suite runs at on a CET machine."""

import json
import re
from datetime import date, datetime, timedelta

import pytest
from playwright.sync_api import expect

from fakemeta import EMPTY_ACCOUNT, TZ, expected
from pauta import sync
from pauta.db import cents_per
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
        brl(cents_per(want["spend_cents"], want["results"]))
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
    # the totals' costs round as the server's cents_per does: half up (5 ÷ 2 is 3, not 2)
    for a, b in [(5, 2), (7, 2), (1005, 10), (1, 3), (2, 3), (3033, 33), (0, 4)]:
        assert page.evaluate(f"centsPer({a}, {b})") == cents_per(a, b), (a, b)
    assert page.evaluate("centsPer(10, 0)") is None and cents_per(10, 0) is None

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
    # Atualizar agora: the server answers at once and syncs on its thread; the page polls
    # until it ends and says so in a toast, the "Dados da Meta" line following; a second
    # tap hits the 15-minute limit
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#toast")).to_have_text("Dados da Meta atualizados", timeout=10_000)
    expect(page.locator("#syncline")).to_have_text("Dados da Meta de agora")
    laptop.expected.add((429, "/api/meta/sync"))
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#toast")).to_contain_text("menos de 15 minutos")


def test_sync_now_lost_to_a_restart_is_not_a_success(synced):
    """The server restarting mid-pass: its lock is fresh, `last_sync` comes back from the
    database (the previous one) and `sync_error` is "", so the first poll looks exactly
    like a pass that ended. Here the POST starts nothing (the route answers 202 with the
    previous `last_sync` and the server never hears of it), so every poll answers as a
    server that restarted: the page must not toast "Dados da Meta atualizados" over
    nothing, and the button comes back for another try."""
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas")
    expect(page.locator("#syncline")).to_contain_text("Dados da Meta de")
    previous = store.sync_state()["last_sync"]
    assert previous
    body = json.dumps({"started": True, "last_sync": previous})
    page.route(
        "**/api/meta/sync",
        lambda r: r.fulfill(status=202, content_type="application/json", body=body),
    )
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#syncline")).to_contain_text("Sincronizando com a Meta")
    toast = page.locator("#toast")
    expect(toast).to_have_text("A sincronização não terminou; tente de novo", timeout=10_000)
    expect(toast).to_have_class(re.compile(r"\berr\b"))
    expect(page.locator("#syncline")).to_contain_text("Dados da Meta de")  # the line is back
    expect(page.get_by_role("button", name="Atualizar agora")).to_be_enabled()
    assert store.sync_state()["last_sync"] == previous  # nothing ran, nothing was claimed


def test_sync_now_while_a_pass_runs_waits_for_it(synced, meta, fake_meta, monkeypatch):
    """Atualizar agora while the hourly pass (or another admin's tap) is on it: the server
    answers 409 "já está sincronizando" and the page, instead of a red toast, says
    "Sincronizando com a Meta…" and waits for that pass like its own."""
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas")
    expect(page.locator("#syncline")).to_contain_text("Dados da Meta de")
    previous = store.sync_state()["last_sync"]
    # the stamp has whole seconds: the running pass gets one after the fixture's for sure
    later = datetime.strptime(previous, "%Y-%m-%dT%H:%M:%SZ") + timedelta(seconds=1)
    monkeypatch.setattr(sync, "_stamp", lambda: later.strftime("%Y-%m-%dT%H:%M:%SZ"))
    fake_meta.hold()
    thread = sync.start(store, meta, days=sync.HOURLY_DAYS)  # the hourly pass, held open
    laptop.expected.add((409, "/api/meta/sync"))
    with page.expect_response(lambda r: r.url.endswith("/api/meta/sync")) as answered:
        page.get_by_role("button", name="Atualizar agora").click()
    assert answered.value.status == 409 and answered.value.json()["reason"] == "busy"
    expect(page.locator("#syncline")).to_contain_text("Sincronizando com a Meta")
    expect(page.get_by_role("button", name="Atualizar agora")).to_be_disabled()
    expect(page.locator("#toast")).to_be_hidden()  # no "já está sincronizando" in red
    fake_meta.release()
    thread.join(timeout=30)
    expect(page.locator("#toast")).to_have_text("Dados da Meta atualizados", timeout=10_000)
    expect(page.locator("#syncline")).to_have_text("Dados da Meta de agora")


def test_leaving_campanhas_mid_sync_says_nothing_elsewhere(synced):
    """The poll after Atualizar agora ends quietly when the person moves to another screen:
    no "ainda não terminou" toast over the Painel."""
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    page.goto(f"{base}/#/campanhas")
    expect(page.locator("#syncline")).to_contain_text("Dados da Meta de")
    body = json.dumps({"started": True, "last_sync": store.sync_state()["last_sync"]})
    page.route(
        "**/api/meta/sync",
        lambda r: r.fulfill(status=202, content_type="application/json", body=body),
    )
    page.get_by_role("button", name="Atualizar agora").click()
    expect(page.locator("#syncline")).to_contain_text("Sincronizando com a Meta")
    page.locator("#nav a[data-nav='#/']").click()
    expect(page.locator("#syncline")).to_have_count(0)
    page.wait_for_timeout(1500)  # past the poll's first look (1 s), which finds no screen
    expect(page.locator("#toast")).to_be_hidden()
    expect(page.locator("#syncline")).to_have_count(0)


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


def test_client_with_a_linked_account_and_no_campaigns(live, device, meta, fake_meta):
    """A client whose linked account holds no campaign (Piero's second portfolio) is on the
    list, last, saying so with the account's name and balance and without Visto hoje; the
    blocks with campaigns show the account's balance under the name."""
    base, auth, store = live
    fake_meta.accounts.append(EMPTY_ACCOUNT)
    store.save_client({"name": "Clínica Bem Estar", "ad_account": "111"})
    store.save_client({"name": "Estúdio Pilates Leve", "ad_account": "555"})
    store.save_client({"name": "Sem conta"})
    token, _ = auth.create_invite(admin=True)
    page = device(timezone_id=TZ).page
    join(page, base, token, "Renato Lima")
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Conectar Meta").click()
    expect(page.locator("#toast")).to_have_text("Meta conectada")
    expect(page.locator("#metaaccounts tbody tr")).to_have_count(3)
    out = sync.run(store, meta, days=sync.HOURLY_DAYS)
    assert out["campaigns_new"] == 2 and out["errors"] == [], out
    page.goto(f"{base}/#/campanhas?p=this_month")
    blocks = page.locator(".cblock")
    expect(blocks).to_have_count(2)  # Sem conta has no account: not here
    expect(page.locator("#app")).not_to_contain_text("Sem conta")
    expect(blocks.first).to_contain_text("Clínica Bem Estar")
    expect(page.locator("#seenline")).to_have_text("Hoje: 0 de 1 cliente visto")
    # the clinic's block: the account's balance under the name
    clinic = blocks.first
    expect(clinic.locator(".kbal")).to_have_count(1)
    expect(clinic.locator(".kbal")).to_contain_text("Saldo da conta: R$ 3.765,44")
    expect(clinic.locator(".kbal b span")).to_have_text("até o limite")
    # the studio's: the line, the account's name and balance, no rows, no Visto hoje
    studio = blocks.nth(1)
    expect(studio).to_have_class(re.compile(r"\bnocamp\b"))
    expect(studio).to_contain_text("Estúdio Pilates Leve")
    expect(studio.locator(".nocamp-line")).to_have_text(
        "sem campanhas ativas na(s) conta(s) vinculada(s): Estúdio Pilates Leve"
    )
    expect(studio.locator(".kbal")).to_contain_text("Saldo da conta: R$ 274,50")
    expect(studio.locator(".krow")).to_have_count(0)
    expect(studio.get_by_role("button", name="Visto hoje", exact=True)).to_have_count(0)
    expect(studio.locator("[data-seen]")).to_have_count(0)
    expect(studio.get_by_role("link", name="Estúdio Pilates Leve")).to_have_attribute(
        "href", re.compile(r"^#/cliente/\d+$")
    )
    # seen clients sink, but still above the ones with nothing to check
    clinic.get_by_role("button", name="Visto hoje", exact=True).click()
    expect(page.locator("#toast")).to_have_text("Clínica Bem Estar: visto hoje")
    expect(page.locator("#seenline")).to_have_text("Hoje: 1 de 1 cliente visto")
    expect(page.locator(".cblock").first).to_contain_text("Clínica Bem Estar")
    expect(page.locator(".cblock").first.locator(".seen")).to_be_visible()
    expect(page.locator(".cblock").nth(1)).to_contain_text("Estúdio Pilates Leve")
    # a balance Meta refuses says what to do, here too
    fake_meta.refuse_balance = True
    page.goto(f"{base}/#/configuracoes")
    page.locator("#meta").get_by_role("button", name="Atualizar").click()
    expect(page.locator("#metaaccounts tbody tr").first).to_contain_text("sem permissão")
    page.goto(f"{base}/#/campanhas?p=this_month")
    expect(page.locator(".cblock.nocamp .kbal span")).to_have_text(
        "sem permissão · reconecte em Adicionar contas"
    )


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
    # Cliques no link and Custo por clique no link (Ads Manager's names) stay in the picker, off
    expect(page.locator("#metrics .chip", has_text="Cliques no link")).to_have_attribute(
        "aria-pressed", "false"
    )
    expect(page.locator("#metrics .chip", has_text="Custo por clique no link")).to_have_count(1)
    # every card follows one pattern: title, value, what it counts, one explaining line, and
    # the chart with its per-day maximum named
    expect(page.locator(".mcard .mwhy")).to_have_count(3)
    expect(page.locator(".mcard[data-card='spend'] .mwhy")).to_have_text(
        "Quanto foi investido em anúncios no período."
    )
    expect(page.locator(".mcard[data-card='spend'] .chart-y")).to_contain_text("máx. por dia")
    # the actions in the data are chips too, with Ads Manager's name when known, behind
    # "Mais métricas" until one is marked
    expect(page.locator("#metrics .chip", has_text=CONVERSATIONS)).to_have_count(0)
    page.locator("#morechips").click()
    expect(page.locator("#morechips")).to_have_text("Menos métricas")
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
    page.locator("#metrics .chip", has_text="Cliques no link").click()  # on
    expect(page.locator(".mcard")).to_have_count(5)
    page.reload()
    expect(page.locator("#metrics .chip.on")).to_have_text(
        ["Resultados", "Custo por resultado", "Cliques no link", "Frequência", CONVERSATIONS]
    )
    expect(page.locator("#morechips")).to_have_count(0)  # the one action is marked: nothing hidden
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


def test_report_for_the_client_and_share_on_whatsapp(synced):
    """Gerar relatório: the campaign page's period and marked metrics become one clean screen
    (no shell) with a tile per metric, a plain line under each number, and Compartilhar com
    o cliente opening WhatsApp on the client's registered number; without a number the
    button is off and the screen says where to register it."""
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    # typed with the trunk zero, as people dial it: the link still gets Brazil's 55
    store.save_client({"whatsapp": "0 (11) 98888-7777", "contact": "Carla Mendes"}, clinic["id"])
    page.goto(f"{base}/#/campanhas?p=this_month")
    page.locator(".krow[data-id] a", has_text="Limpeza de pele novembro").click()
    expect(page.locator("#kname")).to_have_text("Limpeza de pele novembro")
    for typed, digits in [
        ("0 32 99999-9999", "5532999999999"),
        ("(32) 99999-9999", "5532999999999"),
        ("032 9999-9999", "553299999999"),
        ("+55 32 99999-9999", "5532999999999"),
        ("0055 32 99999-9999", "5532999999999"),
        ("+31 6 1234 5678", "31612345678"),
    ]:
        assert page.evaluate(f"waUrl({typed!r})") == f"https://wa.me/{digits}", typed
    # the objective reads in Portuguese, and the link-click action is not a second chip
    expect(page.locator(".head")).to_contain_text("objetivo: Engajamento")
    expect(page.get_by_role("button", name="Cliques no link", exact=True)).to_have_count(1)
    page.get_by_role("button", name="Cliques no link", exact=True).click()
    expect(page.locator("#metrics .chip.on")).to_have_count(4)
    page.get_by_role("button", name="Gerar relatório").click()
    expect(page).to_have_url(
        re.compile(r"#/relatorio/\d+\?p=this_month&m=results%2Ccpr%2Cspend%2Cleads$")
    )
    # no app chrome around the card; the card names the campaign, the client and the period
    expect(page.locator("body")).to_have_class(re.compile(r"\breport\b"))
    expect(page.locator(".side")).to_be_hidden()
    expect(page.locator(".tabbar")).to_be_hidden()
    rep = page.locator("#rep")
    expect(rep.locator("h1")).to_have_text("Limpeza de pele novembro")
    expect(rep.locator(".rep-kicker")).to_have_text("Relatório de campanha")
    expect(rep.locator(".rep-client")).to_contain_text("Clínica Bem Estar")
    t = today()
    expect(rep.locator(".rep-period")).to_have_text(
        f"{label(t.replace(day=1), t)} · até hoje · campanha ativa"
    )
    # the four marked metrics, in the page's order, the first one as the hero number
    tiles = rep.locator(".rep-tile")
    expect(tiles).to_have_count(4)
    assert [tiles.nth(i).get_attribute("data-tile") for i in range(4)] == [
        "results",
        "cpr",
        "spend",
        "leads",
    ]
    expect(tiles.first).to_have_class(re.compile(r"\bhero\b"))
    expect(tiles.first.locator(".rep-label")).to_have_text("Resultados")
    expect(tiles.first.locator(".rep-val")).to_have_text(str(2 * t.day))
    expect(tiles.first.locator(".rep-sub")).to_have_text(CONVERSATIONS)
    expect(tiles.first.locator(".rep-why")).to_have_text(
        "Quantas vezes a campanha entregou o que ela busca no período."
    )
    spend = rep.locator(".rep-tile[data-tile='spend']")
    expect(spend.locator(".rep-val")).to_contain_text("R$")
    expect(spend.locator(".rep-why")).to_have_text("Quanto foi investido em anúncios no período.")
    expect(spend.locator(".rep-spark rect")).to_have_count(t.day)  # a bar per day
    expect(rep.locator(".rep-tile[data-tile='leads'] .rep-label")).to_have_text("Cliques no link")
    expect(rep.locator(".rep-foot")).to_contain_text("preparado por Renato")
    # Compartilhar com o cliente: WhatsApp on the client's number, the message ready
    share = page.locator("#share")
    expect(share).to_have_attribute("target", "_blank")
    href = share.get_attribute("href")
    assert href.startswith("https://wa.me/5511988887777?text=Ol%C3%A1%2C%20Carla!"), href
    assert "Limpeza%20de%20pele%20novembro" in href and "relat%C3%B3rio" in href, href
    expect(page.locator("#sharehint")).to_contain_text("Tire um print")
    # the card fits a phone (the print goes to WhatsApp)
    page.set_viewport_size({"width": 390, "height": 844})
    box = rep.bounding_box()
    assert box and box["width"] <= 390 - 2 * 12, box
    expect(tiles.nth(1)).to_be_visible()
    page.set_viewport_size({"width": 1280, "height": 860})
    # Voltar: the campaign page, with its shell, and the same period
    page.get_by_role("link", name="Voltar à campanha").click()
    expect(page.locator("#kname")).to_have_text("Limpeza de pele novembro")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\breport\b"))
    expect(page.locator(".side")).to_be_visible()
    expect(page.locator("#pdates")).to_have_text(label(t.replace(day=1), t))
    # no number on the client: the button is off and the screen says where to put one
    page.goto(f"{base}/#/campanhas?p=this_month")
    page.locator(".krow[data-id] a", has_text="Panetone").click()
    page.get_by_role("button", name="Gerar relatório").click()
    expect(page.locator("#rep h1")).to_have_text("Panetone")
    expect(page.locator("#share")).to_be_disabled()
    hint = page.locator("#sharehint")
    expect(hint).to_contain_text("Padaria Trigo de Ouro não tem WhatsApp cadastrado")
    expect(hint.locator("a")).to_have_attribute("href", f"#/cliente/{bakery['id']}")
    # without `m` in the address the report takes the metrics marked on the campaign page;
    # a one-day period reads once; a wrong campaign is an error screen with its navigation
    panetone = page.url.split("/relatorio/")[1].split("?")[0]
    page.goto(f"{base}/#/relatorio/{panetone}?p=this_month")
    expect(page.locator("#rep .rep-tile")).to_have_count(4)
    page.goto(f"{base}/#/relatorio/{panetone}?p=today")
    expect(page.locator("#rep .rep-period")).to_have_text(
        f"{label(t, t).split(' – ')[0]} · hoje · campanha ativa"
    )
    laptop.expected.add((404, "/api/campaigns/999"))
    page.goto(f"{base}/#/relatorio/999?p=today")
    expect(page.locator("#app .empty")).to_contain_text("campanha não encontrada")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\breport\b"))
    expect(page.locator(".side")).to_be_visible()
