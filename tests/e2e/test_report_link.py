"""The client's link to a report in the browser (decision 12): Copiar link makes the link
and copies it, the WhatsApp message carries it, a phone with no account opens it and sees
the card (and nothing of the app), Abrir conversa before any link makes one on the way,
Revogar on the campaign page, and the plain page once the link is gone."""

import re
from datetime import UTC, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect
from test_campanhas import PHONE, synced, today  # noqa: F401  (the fixture, by import)

from fakemeta import TZ

pytestmark = pytest.mark.e2e

MONTHS_LONG = [
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
]


@pytest.fixture()
def meta(meta_on):
    return meta_on


def test_the_client_opens_the_report_without_an_account(synced, device):  # noqa: F811
    base, store, laptop, clinic, bakery = synced
    page = laptop.page
    store.save_client({"whatsapp": "(11) 98888-7777", "contact": "Carla Mendes"}, clinic["id"])
    laptop.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"{base}/#/campanhas?p=this_month")
    page.locator(".krow[data-id] a", has_text="Limpeza de pele novembro").click()
    page.get_by_role("button", name="Gerar relatório").click()
    expect(page.locator("#rep h1")).to_have_text("Limpeza de pele novembro")
    cid = page.url.split("/relatorio/")[1].split("?")[0]
    # before any link: the message has no address, no "válido até"
    assert "Veja%20o%20relat" not in page.locator("#share").get_attribute("href")
    expect(page.locator("#linkinfo")).to_be_empty()
    expect(page.locator("#links")).to_have_count(0)  # that is the campaign page's
    # Copiar link: made on the first tap, copied, and the message carries it from then on
    page.get_by_role("button", name="Copiar link").click()
    expect(page.locator("#toast")).to_contain_text("Link copiado · válido até")
    url = page.evaluate("navigator.clipboard.readText()")
    assert re.fullmatch(rf"{re.escape(base)}/r/[A-Za-z0-9_-]{{32,}}", url), url
    token = url.rsplit("/", 1)[1]
    # "válido até" is the local day (São Paulo, the browsers' zone) of the UTC stamp
    expires = store.report_link(token)["expires"]
    ends = datetime.fromisoformat(expires).replace(tzinfo=UTC).astimezone(ZoneInfo(TZ)).date()
    until = f"válido até {ends.day} de {MONTHS_LONG[ends.month - 1]}"
    expect(page.locator("#toast")).to_have_text(f"Link copiado · {until}")
    expect(page.locator("#linkinfo")).to_have_text(f"Link do relatório {until}: {url}")
    href = page.locator("#share").get_attribute("href")
    assert href.startswith("https://wa.me/5511988887777?text=Ol%C3%A1%2C%20Carla!"), href
    assert href.endswith(quote(f"\n\nVeja o relatório aqui: {url}", safe="")), href
    # a second tap copies the same link (no second row)
    page.get_by_role("button", name="Copiar link").click()
    expect(page.locator("#toast")).to_have_text(f"Link copiado · {until}")
    assert page.evaluate("navigator.clipboard.readText()") == url
    assert len(store.report_links(int(cid))) == 1
    # the same report opened again finds its link: no new one, the message ready at once
    page.reload()
    expect(page.locator("#linkinfo")).to_contain_text(url)
    assert page.locator("#share").get_attribute("href") == href
    assert len(store.report_links(int(cid))) == 1

    # the client's phone: no cookies, no passkey, never signed in
    phone = device(**PHONE, timezone_id=TZ)
    cp = phone.page
    asked: list[str] = []
    cp.on("request", lambda r: asked.append(r.url) if "/api/" in r.url else None)
    cp.goto(url)
    rep = cp.locator("#rep")
    expect(rep.locator("h1")).to_have_text("Limpeza de pele novembro")
    expect(rep.locator(".rep-kicker")).to_have_text("Relatório de campanha")
    expect(rep.locator(".rep-client")).to_contain_text("Clínica Bem Estar")
    t = today()
    expect(rep.locator(".rep-period")).to_contain_text("até hoje · campanha ativa")
    tiles = rep.locator(".rep-tile")
    expect(tiles).to_have_count(3)  # the campaign page's default metrics
    assert [tiles.nth(i).get_attribute("data-tile") for i in range(3)] == [
        "results",
        "cpr",
        "spend",
    ]
    expect(tiles.first.locator(".rep-val")).to_have_text(str(2 * t.day))
    expect(tiles.first.locator(".rep-why")).to_have_text(
        "Quantas vezes a campanha entregou o que ela busca no período."
    )
    expect(rep.locator(".rep-tile[data-tile='spend'] .rep-val")).to_contain_text("R$")
    expect(rep.locator(".rep-tile[data-tile='spend'] .rep-spark rect")).to_have_count(t.day)
    expect(rep.locator(".rep-foot")).to_contain_text("preparado por Renato")
    month = MONTHS_LONG[ends.month - 1]
    expect(cp.locator(".public-note")).to_have_text(
        f"Relatório preparado na Pauta. Este link vale até {ends.day} de {month}."
    )
    # the page is the card alone: no shell, no tools, no login, and the preview is filled in
    for sel in (".side", ".topbar", ".tabbar", "#gate", ".report-tools", "#share"):
        expect(cp.locator(sel)).to_have_count(0)
    assert cp.title().startswith(
        "Relatório da campanha Limpeza de pele novembro · Clínica Bem Estar · "
    )
    og = cp.locator('meta[property="og:title"]').get_attribute("content")
    assert og == cp.title()
    assert cp.locator('meta[property="og:url"]').get_attribute("content") == url
    assert cp.locator('meta[name="robots"]').get_attribute("content") == "noindex, nofollow"
    assert asked == [f"{base}/api/r/{token}"], asked  # nothing else of the API was touched
    # the card fits the phone
    box = rep.bounding_box()
    assert box and box["width"] <= 390 - 2 * 12, box

    # Abrir conversa before any link exists (another period): the tab opens and lands on
    # WhatsApp with the new link in the message
    laptop.context.route(
        "https://wa.me/**",
        lambda r: r.fulfill(body="<title>wa</title>", content_type="text/html"),
    )
    page.goto(f"{base}/#/relatorio/{cid}?p=today&m=results")
    expect(page.locator("#rep .rep-tile")).to_have_count(1)
    expect(page.locator("#linkinfo")).to_be_empty()
    with page.expect_popup() as pop:
        page.locator("#share").click()
    popup = pop.value
    popup.wait_for_url(re.compile(r"^https://wa\.me/5511988887777\?text="))
    links = store.report_links(int(cid))
    assert len(links) == 2 and links[0]["metrics"] == ["results"]
    newest = f"{base}/r/{links[0]['token']}"
    assert popup.url.endswith(quote(f"\n\nVeja o relatório aqui: {newest}", safe=""))
    popup.close()
    expect(page.locator("#linkinfo")).to_contain_text(newest)

    # the campaign page lists both, newest first; Revogar ends the one the client has
    page.goto(f"{base}/#/campanha/{cid}?p=this_month")
    rows = page.locator("#links .linkrow")
    expect(rows).to_have_count(2)
    expect(page.locator("#links h3")).to_have_text("Links do relatório")
    expect(rows.first).to_contain_text("1 métrica · por Renato")
    expect(rows.first).to_contain_text(until)
    expect(rows.first.locator("a")).to_have_attribute("href", newest)
    mine = page.locator(f"#links .linkrow[data-token='{token}']")
    expect(mine).to_contain_text("3 métricas")
    mine.get_by_role("button", name="Revogar").click()
    expect(page.locator("#toast")).to_have_text("Link desativado")
    expect(mine).to_have_class(re.compile(r"\boff\b"))
    expect(mine).to_contain_text("desativado em")
    expect(mine.get_by_role("button")).to_have_count(0)
    expect(rows.first.get_by_role("button", name="Revogar")).to_be_visible()
    # the client's copy is gone: the plain page, no card, no script
    phone.expected.add((404, "/r/"))
    cp.goto(url)
    expect(cp.locator("h1")).to_have_text("Este relatório não está mais disponível")
    expect(cp.locator("#rep")).to_have_count(0)
    # as is a made-up address
    cp.goto(f"{base}/r/made-up")
    expect(cp.locator("h1")).to_have_text("Este relatório não está mais disponível")
    # and the report screen makes a new one on the next Copiar link
    page.goto(f"{base}/#/relatorio/{cid}?p=this_month&m=results%2Ccpr%2Cspend")
    expect(page.locator("#linkinfo")).to_be_empty()
    page.get_by_role("button", name="Copiar link").click()
    expect(page.locator("#toast")).to_contain_text("Link copiado")
    assert page.evaluate("navigator.clipboard.readText()") != url
