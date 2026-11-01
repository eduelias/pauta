"""A new or lost phone with one address (no move in progress): an admin makes a one-time
link on Configurações, the person opens it on the new phone and is in, on the same account."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


def join(device, base, auth, name, admin=False):
    d = device()
    token, _ = auth.create_invite(admin=admin)
    d.page.goto(f"{base}/#/entrar/{token}")
    d.page.fill("#join input[name=name]", name)
    d.page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(d.page.locator(".hello h1")).to_be_visible()
    return d


def test_an_admin_sends_a_new_passkey_link(live, device):
    base, auth, _ = live
    admin = join(device, base, auth, "Edu Saleh", admin=True)
    join(device, base, auth, "Piero Sales")

    admin.page.goto(f"{base}/#/configuracoes")
    row = admin.page.locator(".member", has_text="Piero Sales")
    expect(row.get_by_role("button", name="Link para mudar")).to_have_count(0)
    row.get_by_role("button", name="Link de nova passkey").click()
    box = admin.page.locator(".qrbox", has_text="Link de nova passkey de Piero")
    expect(box).to_contain_text("Vale uma vez")
    url = box.locator("code.invlink").inner_text()
    assert url.startswith(f"{base}/#/mudar/")
    wa = box.get_by_role("link", name="Enviar no WhatsApp").get_attribute("href")
    assert "passkey%20nova" in wa and "mudou" not in wa

    # Piero's new phone has nothing for this address: one button, and he's in
    phone = device()
    phone.page.goto(url)
    expect(phone.page.get_by_role("heading", name="Olá, Piero!")).to_be_visible()
    expect(phone.page.locator(".gate")).not_to_contain_text("mora em")
    phone.page.get_by_role("button", name="Criar passkey neste aparelho").click()
    expect(phone.page.locator(".hello h1")).to_contain_text("Piero")
    assert [c["rpId"] for c in phone.passkeys()] == ["localhost"]

    admin.page.reload()
    expect(admin.page.locator(".member", has_text="Piero Sales")).to_contain_text("2 passkeys")

    # the link was for one use: opened again elsewhere, it says it expired
    other = device()
    other.expected.add((404, "/api/move/"))
    other.page.goto(url)
    expect(other.page.get_by_role("heading", name="Link expirado")).to_be_visible()
    expect(other.page.locator(".gate")).not_to_contain_text("endereço antigo")


def test_no_link_for_yourself_or_disabled_people(live, device):
    base, auth, store = live
    admin = join(device, base, auth, "Edu Saleh", admin=True)
    join(device, base, auth, "Nato Lima")
    nato = next(m for m in store.members() if m["name"] == "Nato Lima")
    auth.set_member(nato["id"], disabled=True, by=None)

    admin.page.goto(f"{base}/#/configuracoes")
    me = admin.page.locator(".member", has_text="Edu Saleh").last
    expect(me.get_by_role("button", name="Link de nova passkey")).to_have_count(0)
    off = admin.page.locator(".member", has_text="Nato Lima")
    expect(off.get_by_role("button", name="Link de nova passkey")).to_have_count(0)
