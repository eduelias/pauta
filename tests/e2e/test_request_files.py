"""Files on a request in a real browser: connect OneDrive on Configurações → Arquivos, upload,
share, remove. The OneDrive is the fake Graph (tests/fakegraph.py)."""

import pytest
from playwright.sync_api import expect

from fakegraph import PNG

pytestmark = pytest.mark.e2e


@pytest.fixture()
def drive(drive_on):
    return drive_on


def test_connect_upload_share_and_remove(live, device, fake):
    base, auth, store = live
    token, _ = auth.create_invite(admin=True)
    laptop = device()
    page = laptop.page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Renato Lima")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Renato Lima")

    # connect: the page shows the code, then notices the approval by itself
    page.goto(f"{base}/#/configuracoes")
    page.get_by_role("button", name="Conectar OneDrive").click()
    expect(page.locator("#usercode")).to_have_text("ABCD-1234")
    expect(page.locator("#drive")).to_contain_text("microsoft.com/link")
    fake.approved = True
    expect(page.locator("#drive")).to_contain_text("piero@example.com", timeout=10_000)
    expect(page.locator("#drive")).to_contain_text("A Pauta ocupa")

    # upload two files to a request
    c = store.save_client({"name": "Clínica Bem Estar"})
    store.create_request({"client": c["id"], "what": "Campanha de novembro"}, None)
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator("#filelist")).to_contain_text("Nenhum arquivo ainda")
    expect(page.get_by_role("button", name="Link para o cliente")).to_be_hidden()
    page.set_input_files(
        "#pick",
        files=[
            {"name": "criativo.png", "mimeType": "image/png", "buffer": PNG},
            {"name": "briefing.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4"},
        ],
    )
    expect(page.locator("#filelist .file")).to_have_count(2)
    expect(page.locator("#tl")).to_contain_text("anexou criativo.png")
    expect(page.locator("#tl")).to_contain_text("anexou briefing.pdf")
    expect(page.locator("#filelist img")).to_have_count(1)  # a thumbnail for the image only
    expect(page.locator("#filelist img")).to_have_js_property("naturalWidth", 1)

    # a view-only link for the client
    page.get_by_role("button", name="Link para o cliente").click()
    expect(page.locator("#sharebox")).to_contain_text("https://1drv.ms/")
    expect(page.locator("#sharebox")).to_contain_text("Enviar no WhatsApp")

    # remove one (it goes to OneDrive's recycle bin)
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Remover briefing.pdf").click()
    expect(page.locator("#filelist .file")).to_have_count(1)
    expect(page.locator("#tl")).to_contain_text("removeu o arquivo briefing.pdf")
    assert len(fake.deleted) == 1

    # disconnect: the request page says how to turn files back on
    page.goto(f"{base}/#/configuracoes")
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Desconectar").click()
    expect(page.get_by_role("button", name="Conectar OneDrive")).to_be_visible()
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator(".panel", has_text="Arquivos")).to_contain_text("Conecte o OneDrive")
