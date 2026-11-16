"""The client screens: the ads page link and its copy buttons, the state filter, cards or a
list in the order asked for, deleting."""

import re
import time
from datetime import UTC, datetime, timedelta

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e

ADS = "https://www.facebook.com/ads/library/?id=123"


def signed_in(live, device, **context_args):
    base, auth, store = live
    with store.db() as conn:
        aid = conn.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES ('Renato Lima', 'h', 1)"
        ).lastrowid
    value = auth.make_cookie(aid, secure=False).split(";")[0].split("=", 1)[1]
    d = device(**context_args)
    d.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    d.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    return base, store, d.page


@pytest.fixture()
def admin(live, device):
    return signed_in(live, device)


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


def test_whatsapp_is_asked_right_under_the_name_and_missing_ones_are_marked(admin):
    """The report's "Abrir conversa" needs the client's WhatsApp; almost no client had one.
    The form asks for it right under the name, with the hint, and the list marks the
    clients without one. It is still optional."""
    base, store, page = admin
    with_wa = store.save_client({"name": "Com Zap", "whatsapp": "(11) 98888-0000"})
    without = store.save_client({"name": "Sem Zap"})
    page.goto(f"{base}/#/clientes")
    cards = page.locator(".ccard")
    expect(cards).to_have_count(2)
    expect(cards.filter(has_text="Sem Zap").locator(".nowa")).to_have_text("sem WhatsApp")
    expect(cards.filter(has_text="Com Zap").locator(".nowa")).to_have_count(0)
    # the form: the WhatsApp field is the second one, right after the name, with the hint
    page.goto(f"{base}/#/cliente/{without['id']}")
    fields = page.locator("#f .field, .quiet-off .field")
    expect(fields.nth(0)).to_contain_text("Nome")
    expect(fields.nth(1)).to_contain_text("WhatsApp do cliente")
    expect(fields.nth(1).locator(".hint")).to_have_text("para abrir a conversa do relatório daqui")
    field = page.locator('input[data-f="whatsapp"]')
    expect(field).not_to_have_attribute("required", re.compile(".*"))
    field.fill("(21) 97777-1111")
    field.blur()
    expect(page.locator(".toast")).to_contain_text("Salvo")
    assert store.client(without["id"])["whatsapp"] == "(21) 97777-1111"
    assert store.client(with_wa["id"])["whatsapp"] == "(11) 98888-0000"
    # a new client saves without a number
    page.goto(f"{base}/#/cliente/novo")
    expect(page.locator("#f .field").nth(1)).to_contain_text("WhatsApp do cliente")
    page.fill("#f input[name=name]", "Novo Sem Zap")
    page.get_by_role("button", name="Salvar cliente").click()
    expect(page.locator(".toast")).to_contain_text("Cliente salvo")
    novo = next(c for c in store.clients() if c["name"] == "Novo Sem Zap")
    assert novo["whatsapp"] == ""


# ---- cards or a list, in the order asked for ----------------------------------------------

NAMES = "#grid .ccard .top b, #grid td.c-name .cl b"  # a client's name, in either view
ACADEMIA, ARMAZEM, BISTRO = "Academia Fênix", "Armazém Fechado", "Bistrô da Praça"
OFICINA, OTICA = "Oficina do Zé", "Ótica Visão"


def portfolio(store):
    """Five clients that every order tells apart. The closed one would come first or second
    in most orders (the most requests, the latest one, the oldest client), and the Ótica has
    nothing to order by but its name: no segment, no date, no request."""

    def client(name, requests=(), **fields):
        c = store.save_client({"name": name, **fields})
        for status, days in requests:
            r = store.create_request({"client": c["id"], "what": "x"}, None)
            at = datetime.now(UTC) - timedelta(days=days, minutes=5)
            with store.db() as conn:
                conn.execute(
                    "UPDATE request SET status=?, created=? WHERE id=?",
                    (status, at.strftime("%Y-%m-%d %H:%M:%S"), r["id"]),
                )
        return c

    client(OTICA)
    client(
        ARMAZEM,
        [("todo", 0)] * 4,
        state="Encerrado",
        segment="Varejo",
        since="2020-01-01",
        whatsapp="(11) 90000-0001",
    )
    client(
        BISTRO,
        [("todo", 5), ("doing", 9)],
        segment="Restaurante",
        since="2024-03-01",
        whatsapp="(11) 90000-0002",
    )
    client(
        ACADEMIA,
        [("done", 45)],
        state="Pausado",
        segment="Academia",
        since="2025-01-10",
        whatsapp="(11) 90000-0003",
    )
    return client(
        OFICINA,
        [("todo", 1), ("done", 20), ("done", 30)],
        segment="Automotivo",
        since="2022-06-15",
        whatsapp="(11) 90000-0004",
    )


def test_clients_in_the_order_asked_for(admin):
    """By name at first, accents where they belong ("Ótica" after "Oficina", not after "Z"),
    and each other order starts the way people want it: the most in the open, the latest
    request. The button beside it turns the order round. Whatever the order, a closed client
    stays at the end and one with nothing to order by comes after the ones that have it."""
    base, store, page = admin
    portfolio(store)
    page.goto(f"{base}/#/clientes")
    names = page.locator(NAMES)
    sort, turn = page.locator("#sort"), page.locator("#dir")
    expect(names).to_have_text([ACADEMIA, BISTRO, OFICINA, OTICA, ARMAZEM])
    expect(sort).to_have_value("name")
    expect(turn).to_have_text("A → Z")
    turn.click()
    expect(turn).to_have_text("Z → A")
    expect(names).to_have_text([OTICA, OFICINA, BISTRO, ACADEMIA, ARMAZEM])

    sort.select_option(label="Em aberto")
    expect(turn).to_have_text("Mais primeiro")
    expect(names).to_have_text([BISTRO, OFICINA, ACADEMIA, OTICA, ARMAZEM])  # 2, 1, 0, 0
    turn.click()
    expect(turn).to_have_text("Menos primeiro")
    expect(names).to_have_text([ACADEMIA, OTICA, OFICINA, BISTRO, ARMAZEM])

    sort.select_option(label="Pedidos")
    expect(names).to_have_text([OFICINA, BISTRO, ACADEMIA, OTICA, ARMAZEM])  # 3, 2, 1, 0

    sort.select_option(label="Último pedido")
    expect(turn).to_have_text("Mais recente primeiro")
    expect(names).to_have_text([OFICINA, BISTRO, ACADEMIA, OTICA, ARMAZEM])
    turn.click()  # the one without a request is still after the ones with
    expect(names).to_have_text([ACADEMIA, BISTRO, OFICINA, OTICA, ARMAZEM])

    sort.select_option(label="Cliente desde")
    expect(turn).to_have_text("Mais antigo primeiro")
    expect(names).to_have_text([OFICINA, BISTRO, ACADEMIA, OTICA, ARMAZEM])
    turn.click()
    expect(turn).to_have_text("Mais novo primeiro")
    expect(names).to_have_text([ACADEMIA, BISTRO, OFICINA, OTICA, ARMAZEM])

    sort.select_option(label="Segmento")
    expect(names).to_have_text([ACADEMIA, OFICINA, BISTRO, OTICA, ARMAZEM])

    sort.select_option(label="Situação")  # the one order that moves the closed client
    expect(turn).to_have_text("Ativos primeiro")
    expect(names).to_have_text([BISTRO, OFICINA, OTICA, ACADEMIA, ARMAZEM])
    turn.click()
    expect(turn).to_have_text("Encerrados primeiro")
    expect(names).to_have_text([ARMAZEM, ACADEMIA, BISTRO, OFICINA, OTICA])

    # the order is kept with the state filter and the search, and after a reload
    sort.select_option(label="Em aberto")
    page.locator("#states").get_by_role("button", name=re.compile(r"^Ativo")).click()
    expect(names).to_have_text([BISTRO, OFICINA, OTICA])
    page.fill("#q", "o")
    page.fill("#q", "ofi")
    expect(names).to_have_text([OFICINA])
    page.reload()
    expect(sort).to_have_value("open")
    expect(turn).to_have_text("Mais primeiro")
    expect(names).to_have_text([BISTRO, OFICINA, OTICA])


def test_clients_as_a_list(admin):
    """The same clients a line each, a column per thing to order by. A heading orders by its
    column and, asked again, turns it round; the line opens the client; the choice of a list
    is still there on the way back and after a reload."""
    base, store, page = admin
    oficina = portfolio(store)
    page.goto(f"{base}/#/clientes")
    cards, lines = page.locator("#grid .ccard"), page.locator("#grid .ctable tbody tr")
    as_cards = page.get_by_role("button", name="Cartões")
    as_list = page.get_by_role("button", name="Lista")
    expect(cards).to_have_count(5)
    expect(as_cards).to_have_attribute("aria-pressed", "true")
    expect(as_list).to_have_attribute("aria-pressed", "false")

    as_list.click()
    expect(lines).to_have_count(5)
    expect(cards).to_have_count(0)
    expect(as_list).to_have_attribute("aria-pressed", "true")
    heads = page.locator("#grid .ctable th")
    expect(heads).to_have_text(
        ["Nome", "Segmento", "Situação", "Em aberto", "Pedidos", "Último pedido", "Cliente desde"]
    )
    line = lines.filter(has_text=OFICINA)
    expect(line.locator("td:not(.c-name)")).to_have_text(
        ["Automotivo", "Ativo", "1 em aberto", "3", "ontem", "jun de 2022"]
    )
    expect(line.locator("td.c-open .unit")).to_be_hidden()  # the heading says it here
    expect(line.locator("td.c-name a")).to_have_attribute("href", f"#/cliente/{oficina['id']}")
    bare = lines.filter(has_text=OTICA)  # nothing to show but the name and the state
    expect(bare.locator("td:not(.c-name)")).to_have_text(["—", "Ativo", "0", "0", "—", "—"])
    expect(bare.locator("td.c-name .nowa")).to_have_text("sem WhatsApp")
    expect(lines.locator(".nowa")).to_have_count(1)
    expect(lines.filter(has_text=ARMAZEM)).to_have_class(re.compile(r"\bclosed\b"))

    # a narrower screen: the name is cut short and two columns go before the list is wider
    # than the screen
    page.set_viewport_size({"width": 920, "height": 760})
    for gone in ("c-total", "c-since"):
        expect(page.locator(f"#grid th.{gone}")).to_be_hidden()
        expect(line.locator(f"td.{gone}")).to_be_hidden()
    expect(line.locator("td.c-last")).to_be_visible()
    wide = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    table, room = (
        page.locator(sel).evaluate("e => e.getBoundingClientRect().width")
        for sel in ("#grid .ctable", "#grid")
    )
    assert not wide and table <= room, f"the list is wider than its place: {table} > {room}"
    page.set_viewport_size({"width": 1280, "height": 860})
    expect(line.locator("td.c-since")).to_be_visible()

    # a heading orders by its column, its own way first; again turns it round
    names = page.locator(NAMES)
    by_name = page.locator("#grid th.c-name")
    expect(by_name).to_have_attribute("aria-sort", "ascending")
    expect(names).to_have_text([ACADEMIA, BISTRO, OFICINA, OTICA, ARMAZEM])
    page.get_by_role("button", name="Em aberto").click()
    by_open = page.locator("#grid th.c-open")
    expect(by_open).to_have_attribute("aria-sort", "descending")
    expect(by_name).to_have_attribute("aria-sort", "none")
    expect(names).to_have_text([BISTRO, OFICINA, ACADEMIA, OTICA, ARMAZEM])
    expect(page.locator("#sort")).to_have_value("open")  # the two controls agree
    expect(page.locator("#dir")).to_have_text("Mais primeiro")
    page.get_by_role("button", name="Em aberto").click()
    expect(by_open).to_have_attribute("aria-sort", "ascending")
    expect(names).to_have_text([ACADEMIA, OTICA, OFICINA, BISTRO, ARMAZEM])
    page.locator("#dir").click()  # and so does the button
    expect(by_open).to_have_attribute("aria-sort", "descending")

    # the line opens the client; back, it is still a list in that order
    line.locator("td.c-segment").click()
    expect(page).to_have_url(re.compile(rf"#/cliente/{oficina['id']}$"))
    page.go_back()
    expect(names).to_have_text([BISTRO, OFICINA, ACADEMIA, OTICA, ARMAZEM])
    expect(lines).to_have_count(5)
    page.reload()
    expect(lines).to_have_count(5)
    page.fill("#q", "nada")
    expect(page.locator("#grid")).to_contain_text("Nenhum cliente encontrado")
    page.fill("#q", "")
    as_cards.click()
    expect(cards).to_have_count(5)
    expect(lines).to_have_count(0)
    expect(names).to_have_text([BISTRO, OFICINA, ACADEMIA, OTICA, ARMAZEM])  # the order stays

    # what was chosen goes to the usage log as a `filter`: that it happened, not the choice
    page.goto("about:blank")
    for _ in range(100):
        with store.db() as conn:
            got = [
                r[0]
                for r in conn.execute("SELECT props FROM usage WHERE event='filter' ORDER BY id")
            ]
        if len(got) >= 5:
            break
        time.sleep(0.05)
    assert got == ['{"what":"view"}', *['{"what":"sort"}'] * 3, '{"what":"view"}']


def test_the_list_on_a_phone(live, device):
    """No headings on a phone: "Ordenar por" orders, and a line says what its numbers are."""
    base, store, page = signed_in(
        live, device, viewport={"width": 390, "height": 844}, is_mobile=True
    )
    portfolio(store)
    page.goto(f"{base}/#/clientes")
    page.get_by_role("button", name="Lista").click()
    lines = page.locator("#grid .ctable tbody tr")
    expect(lines).to_have_count(5)
    expect(page.locator("#grid .ctable thead")).to_be_hidden()
    line = lines.filter(has_text=BISTRO)
    expect(line.locator("td.c-open")).to_have_text("2 em aberto")
    expect(line.locator("td.c-open .unit")).to_be_visible()
    expect(line.locator("td.c-last")).to_have_text("há 5 dias")
    for gone in ("td.c-total", "td.c-since"):
        expect(line.locator(gone)).to_be_hidden()
    expect(lines.filter(has_text=OTICA).locator("td.c-open")).to_be_hidden()  # nothing open
    page.locator("#sort").select_option(label="Último pedido")
    expect(page.locator(NAMES)).to_have_text([OFICINA, BISTRO, ACADEMIA, OTICA, ARMAZEM])
    wide = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not wide, "the clients screen scrolls sideways on a phone"
    line.click()
    expect(page).to_have_url(re.compile(r"#/cliente/\d+$"))
