"""Perfil in a real browser (decision 10): the person's own name, WhatsApp and e-mail, their
passkeys (a label each, one more from this device, one removed while another stays, a link
for a new phone) and the way out of every device."""

import re

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def join(device, base, auth, name, admin=False, **context_args):
    d = device(**context_args)
    token, _ = auth.create_invite(admin=admin)
    d.page.goto(f"{base}/#/entrar/{token}")
    d.page.fill("#join input[name=name]", name)
    d.page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(d.page.locator(".hello h1")).to_be_visible()
    return d


def rows(page):
    return page.locator("#passkeys .member")


def test_name_whatsapp_and_email_are_the_persons(live, device):
    base, auth, store = live
    join(device, base, auth, "Piero Sales")
    nato = join(device, base, auth, "Renato Lima", admin=True)
    page = nato.page

    # from the account menu
    page.click("#mechip")
    page.locator(".menu").get_by_role("link", name="Meu perfil").click()
    expect(page.get_by_role("heading", name="Perfil", exact=True)).to_be_visible()
    expect(page.locator("#me")).to_contain_text("Renato Lima")
    expect(page.locator("#me .tag", has_text="Admin")).to_be_visible()

    # the team's rule for names still applies, with its message
    nato.expected.add((400, "/api/me"))
    page.fill("#myname", "piero sales")
    page.click("#saveme")
    expect(page.locator(".toast")).to_contain_text("já tem alguém da equipe com esse nome")
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")

    page.fill("#myname", "Nato Lima")
    page.fill("#mywa", " +55 11 90000-0000 ")
    page.fill("#myemail", "nato@example.com")
    page.click("#saveme")
    expect(page.locator(".toast")).to_have_text("Salvo")
    expect(page.locator("#mechip")).to_contain_text("Nato Lima")
    page.reload()
    expect(page.locator("#myname")).to_have_value("Nato Lima")
    expect(page.locator("#mywa")).to_have_value("+55 11 90000-0000")
    expect(page.locator("#myemail")).to_have_value("nato@example.com")
    expect(page.locator("#me .avatar img")).to_have_attribute(
        "src", re.compile(r"^https://gravatar\.com/avatar/")
    )
    with store.db() as conn:
        row = conn.execute("SELECT name, whatsapp FROM account WHERE id=2").fetchone()
    assert tuple(row) == ("Nato Lima", "+55 11 90000-0000")

    expect(page.locator("#me")).to_contain_text("Só você vê o número")
    # the team's page shows the person, never the number, not even to this admin
    page.goto(f"{base}/#/configuracoes")
    expect(page.locator(".member", has_text="Nato Lima")).to_be_visible()
    expect(page.locator("#app")).not_to_contain_text("90000-0000")


def test_passkeys_add_one_here_rename_and_remove_the_other(live, device):
    base, auth, store = live
    laptop = join(device, base, auth, "Renato Lima", admin=True)
    page = laptop.page
    page.goto(f"{base}/#/perfil")
    expect(rows(page)).to_have_count(1)
    expect(page.locator("#passkeys .panel-head")).to_contain_text("1 aparelho")
    first = rows(page).first
    assert first.locator(".who b").inner_text().strip()  # a label from the browser
    expect(first).to_contain_text("nunca usada")
    expect(first.get_by_role("button", name="Remover")).to_be_disabled()  # the only one

    # a second passkey from this device. The browser refuses a duplicate on one
    # authenticator (excludeCredentials), so the device forgets the first one first, as a
    # reinstalled OS would; the account keeps both until the person removes one.
    laptop.cdp.send("WebAuthn.clearCredentials", {"authenticatorId": laptop.authenticator})
    page.get_by_role("button", name="Adicionar passkey neste aparelho").click()
    expect(page.locator(".toast")).to_have_text("Passkey adicionada neste aparelho")
    expect(rows(page)).to_have_count(2)
    expect(page.locator("#passkeys .panel-head")).to_contain_text("2 aparelhos")
    expect(rows(page).first.get_by_role("button", name="Remover")).to_be_enabled()

    page.once("dialog", lambda d: d.accept("iPhone antigo"))
    rows(page).first.get_by_role("button", name="Renomear").click()
    expect(rows(page).first.locator(".who b")).to_have_text("iPhone antigo")
    assert [k["label"] for k in auth.passkeys(1)][0] == "iPhone antigo"

    page.once("dialog", lambda d: d.accept())
    rows(page).first.get_by_role("button", name="Remover").click()
    expect(page.locator(".toast")).to_have_text("Passkey removida")
    expect(rows(page)).to_have_count(1)
    expect(rows(page).first).not_to_contain_text("iPhone antigo")
    expect(rows(page).first.get_by_role("button", name="Remover")).to_be_disabled()
    assert store.members()[0]["passkeys"] == 1

    # out everywhere, then back in with the passkey that stayed on this device
    page.click("#logout")
    expect(page.locator("#login")).to_be_visible()
    page.click("#login")
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")
    page.goto(f"{base}/#/perfil")
    expect(rows(page).first).to_contain_text("usada agora")


def test_a_link_for_my_new_phone(live, device):
    base, auth, _ = live
    join(device, base, auth, "Edu Saleh", admin=True)  # the first account is the admin
    laptop = join(device, base, auth, "Piero Sales")
    page = laptop.page
    page.goto(f"{base}/#/perfil")
    page.get_by_role("button", name="Link de nova passkey").click()
    box = page.locator("#mv-me .qrbox")
    expect(box).to_contain_text("Seu link de nova passkey")
    expect(box).to_contain_text("Só para você")
    expect(box).to_contain_text("Vale uma vez, por 10 minutos")  # not an admin's 3 days
    expect(page.locator("#passkeys")).to_contain_text("por 10 minutos")
    url = box.locator("code.invlink").inner_text()
    assert url.startswith(f"{base}/#/mudar/")
    expect(box.get_by_role("button", name="Copiar link")).to_be_visible()
    wa = box.get_by_role("link", name="Enviar no WhatsApp").get_attribute("href")
    assert wa.startswith("https://wa.me/?text=") and "Meu%20link" in wa and "Oi%2C" not in wa

    phone = device(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    phone.page.goto(url)
    expect(phone.page.get_by_role("heading", name="Olá, Piero!")).to_be_visible()
    phone.page.get_by_role("button", name="Criar passkey neste aparelho").click()
    expect(phone.page.locator(".hello h1")).to_contain_text("Piero")
    # the phone's own Perfil, reached from the avatar in the top bar
    phone.page.click("#topnew")
    expect(phone.page.get_by_role("heading", name="Perfil", exact=True)).to_be_visible()
    expect(rows(phone.page)).to_have_count(2)
    expect(phone.page.locator("#me .tag", has_text="Admin")).to_have_count(0)  # a member

    page.reload()
    expect(rows(page)).to_have_count(2)
    other = device()
    other.expected.add((404, "/api/move/"))
    other.page.goto(url)  # spent
    expect(other.page.get_by_role("heading", name="Link expirado")).to_be_visible()

    # the phone is lost after all: removing its passkey from the laptop signs the phone out
    # at once, while the laptop carries on (a fresh cookie came with the answer)
    page.once("dialog", lambda d: d.accept())
    rows(page).nth(1).get_by_role("button", name="Remover").click()
    expect(page.locator(".toast")).to_have_text("Passkey removida")
    expect(rows(page)).to_have_count(1)
    phone.page.reload()
    expect(phone.page.locator("#login")).to_be_visible()
    expect(phone.page.locator("#mechip")).to_be_hidden()
    page.goto(f"{base}/#/configuracoes")
    expect(page.locator("#mechip")).to_contain_text("Piero")
    expect(page.locator(".member", has_text="Piero Sales")).to_be_visible()


def fresh(page, url):
    """Open `url` as a new page load (from the same page, a new hash is only a hashchange)."""
    page.goto("about:blank")
    page.goto(url)


def test_the_app_opens_on_the_screen_the_person_chose(live, device):
    base, auth, store = live
    laptop = join(device, base, auth, "Piero Sales", admin=True)
    page = laptop.page
    painel, quadro = page.locator(".hello h1"), page.get_by_role("heading", name="Quadro")

    # as always: the Painel, and Perfil says so; Campanhas isn't offered with Meta off
    page.goto(f"{base}/#/perfil")
    expect(page.locator("#mystart")).to_have_value("")
    offered = page.locator("#mystart option").all_inner_texts()
    assert offered[:4] == ["Painel", "Quadro", "Pedidos", "Clientes"]
    assert "Campanhas" not in offered
    page.select_option("#mystart", "quadro")
    page.click("#saveme")
    expect(page.locator(".toast")).to_have_text("Salvo")
    expect(page.locator("#mystart")).to_have_value("quadro")
    with store.db() as conn:
        assert conn.execute("SELECT start FROM account WHERE id=1").fetchone()[0] == "quadro"

    # opened by the bare address (the icon, the typed domain): the Quadro, marked in the menu
    for bare in (base, f"{base}/", f"{base}/#/"):
        fresh(page, bare)
        expect(quadro).to_be_visible()
        assert page.url == f"{base}/#/quadro"
    expect(page.locator('#nav [data-nav="#/quadro"]')).to_have_class(re.compile(r"\bon\b"))

    # the Painel stays one click away, from the menu and from the logo, and a reload of it
    # is still the Painel
    page.locator("#nav a", has_text="Painel").click()
    expect(painel).to_be_visible()
    assert page.url == f"{base}/#/painel"
    expect(page.locator("#nav a", has_text="Painel")).to_have_class(re.compile(r"\bon\b"))
    page.reload()
    expect(painel).to_be_visible()
    page.goto(f"{base}/#/pedidos")
    expect(page.get_by_role("heading", name="Pedidos")).to_be_visible()
    page.locator(".side .brand").click()
    expect(painel).to_be_visible()
    # "Cancelar" on a new request goes to "#/", inside the app: the Painel, not the Quadro
    page.goto(f"{base}/#/novo")
    page.get_by_role("link", name="Cancelar").click()
    expect(painel).to_be_visible()

    # an address of its own still opens what it names
    fresh(page, f"{base}/#/clientes")
    expect(page.get_by_role("heading", name="Clientes")).to_be_visible()

    # it is the person's, not the device's: the phone opens on the Quadro too
    value = auth.make_cookie(1, secure=False).split(";")[0].split("=", 1)[1]
    phone = device(viewport={"width": 390, "height": 844}, is_mobile=True)
    phone.context.add_cookies([{"name": "pauta_session", "value": value, "url": base}])
    phone.page.goto(base)
    expect(phone.page.get_by_role("heading", name="Quadro")).to_be_visible()
    expect(phone.page.locator("#tabbar a", has_text="Painel")).to_have_attribute("href", "#/painel")

    # out and in again with the passkey lands there as well
    page.goto(f"{base}/#/perfil")
    page.click("#logout")
    expect(page.locator("#login")).to_be_visible()
    page.click("#login")
    expect(quadro).to_be_visible()


def test_a_start_screen_out_of_sight_falls_back_to_the_painel(live, device):
    base, auth, store = live
    page = join(device, base, auth, "Renato Lima", admin=True).page
    auth.set_start(1, "campanhas")  # chosen while Meta was on; it is off here
    fresh(page, base)
    expect(page.locator(".hello h1")).to_be_visible()
    assert page.url in (base, f"{base}/")
    expect(page.locator("#nav a", has_text="Painel")).to_have_attribute("href", "#/")
    # Perfil keeps showing the choice, so saving something else doesn't drop it
    page.goto(f"{base}/#/perfil")
    expect(page.locator("#mystart")).to_have_value("campanhas")
    page.fill("#mywa", "31600000000")
    page.click("#saveme")
    expect(page.locator(".toast")).to_have_text("Salvo")
    with store.db() as conn:
        row = conn.execute("SELECT start, whatsapp FROM account WHERE id=1").fetchone()
    assert tuple(row) == ("campanhas", "31600000000")
