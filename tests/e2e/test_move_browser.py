"""Moving to a new address in a real browser (decision 4): signed in on the old one, a tap
and a passkey later the same account is open on the new one. Two *.localhost names stand in
for pauta.genic.dev and pauta.cc: separate origins, separate passkey domains, one server."""

import pytest
from playwright.sync_api import expect

from appserver import serve
from pauta.auth import Auth

pytestmark = pytest.mark.e2e


@pytest.fixture()
def two_addresses(store, drive):
    auth = Auth(store, enabled=True, rp_id="new.localhost,old.localhost", origins=["placeholder"])
    httpd = serve(store, auth, drive)
    port = httpd.server_address[1]
    new, old = f"http://new.localhost:{port}", f"http://old.localhost:{port}"
    auth.origins = [new, old]
    yield new, old, auth
    httpd.shutdown()
    httpd.server_close()


def test_moving_to_the_new_address(two_addresses, device):
    new, old, auth = two_addresses
    d = device()
    page = d.page
    token, _ = auth.create_invite(admin=True)

    # joined on the old address before the move
    page.goto(f"{old}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Renato Lima")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    bar = page.locator("#movebar")
    expect(bar).to_contain_text("A Pauta mudou para new.localhost")

    # one tap: off to the new address with a one-time link, then a new passkey there
    bar.get_by_role("button", name="Mudar para new.localhost").click()
    expect(page.get_by_role("heading", name="Olá, Renato!")).to_be_visible()
    assert page.url.startswith(f"{new}/#/mudar/")
    page.get_by_role("button", name="Criar passkey em new.localhost").click()
    expect(page.locator(".hello h1")).to_be_visible()
    expect(page.locator("#movebar")).to_have_count(0)  # home: no bar
    assert sorted(c["rpId"] for c in d.passkeys()) == ["new.localhost", "old.localhost"]

    page.goto(f"{new}/#/equipe")
    expect(page.locator(".member", has_text="Renato Lima").last).to_contain_text(
        "já em new.localhost"
    )

    # back on the old address: it says so, and points to the new one
    page.goto(f"{old}/#/")
    expect(page.locator("#movebar")).to_contain_text("Você já tem passkey lá")
    expect(page.locator("#movebar a")).to_have_attribute("href", f"{new}/")

    # a spent or made-up link, opened on another phone, says so
    other = device()
    other.expected.add((404, "/api/move/"))
    other.page.goto(f"{new}/#/mudar/{'x' * 32}")
    expect(other.page.get_by_role("heading", name="Link expirado")).to_be_visible()


def test_an_admin_sends_a_link_and_it_is_one_tap(two_addresses, device):
    new, old, auth = two_addresses
    admin = device()
    token, _ = auth.create_invite(admin=True)
    admin.page.goto(f"{old}/#/entrar/{token}")
    admin.page.fill("#join input[name=name]", "Edu Saleh")
    admin.page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(admin.page.locator("#movebar")).to_be_visible()

    # Piero joined on the old address and hasn't moved
    piero = device()
    token, _ = auth.create_invite()
    piero.page.goto(f"{old}/#/entrar/{token}")
    piero.page.fill("#join input[name=name]", "Piero Sales")
    piero.page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(piero.page.locator("#movebar")).to_be_visible()

    admin.page.goto(f"{old}/#/equipe")
    row = admin.page.locator(".member", has_text="Piero Sales")
    expect(row).to_contain_text("ainda não mudou")
    row.get_by_role("button", name="Link para mudar").click()
    box = admin.page.locator(".qrbox", has_text="Link de Piero")
    expect(box).to_contain_text("Vale uma vez")
    url = box.locator("code.invlink").inner_text()
    assert url.startswith(f"{new}/#/mudar/")
    wa = box.get_by_role("link", name="Enviar no WhatsApp").get_attribute("href")
    assert wa.startswith("https://wa.me/?text=") and "Oi%2C%20Piero!" in wa

    # Piero taps it in WhatsApp: a browser with nothing for the new address, one button
    piero.page.goto(url)
    expect(piero.page.get_by_role("heading", name="Olá, Piero!")).to_be_visible()
    piero.page.get_by_role("button", name="Criar passkey em new.localhost").click()
    expect(piero.page.locator(".hello h1")).to_contain_text("Piero")
    assert sorted(c["rpId"] for c in piero.passkeys()) == ["new.localhost", "old.localhost"]

    admin.page.reload()
    expect(admin.page.locator(".member", has_text="Piero Sales")).to_contain_text(
        "já em new.localhost"
    )
    expect(admin.page.get_by_role("button", name="Link para mudar")).to_have_count(0)
