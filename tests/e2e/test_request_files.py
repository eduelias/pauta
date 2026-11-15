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
    # the page polls the fake Graph for the approval: longer waits, a loaded machine is slow.
    # The toast means the app refreshed its own state too, which the request page reads
    # from (a hash navigation keeps the document, so it would otherwise see the old one)
    expect(page.locator("#toast")).to_have_text("OneDrive conectado", timeout=20_000)
    expect(page.locator("#drive")).to_contain_text("piero@example.com", timeout=10_000)
    expect(page.locator("#drive")).to_contain_text("A Pauta ocupa", timeout=10_000)

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
    expect(page.locator("#filelist .file")).to_have_count(2, timeout=20_000)  # two uploads
    expect(page.locator("#tl")).to_contain_text("anexou criativo.png", timeout=10_000)
    expect(page.locator("#tl")).to_contain_text("anexou briefing.pdf", timeout=10_000)
    expect(page.locator("#filelist img")).to_have_count(1)  # a thumbnail for the image only
    expect(page.locator("#filelist img")).to_have_js_property("naturalWidth", 1, timeout=10_000)

    # a view-only link for the client
    page.get_by_role("button", name="Link para o cliente").click()
    expect(page.locator("#sharebox")).to_contain_text("https://1drv.ms/", timeout=10_000)
    expect(page.locator("#sharebox")).to_contain_text("Enviar no WhatsApp")

    # remove one (it goes to OneDrive's recycle bin)
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Remover briefing.pdf").click()
    expect(page.locator("#filelist .file")).to_have_count(1, timeout=10_000)
    expect(page.locator("#tl")).to_contain_text("removeu o arquivo briefing.pdf", timeout=10_000)
    assert len(fake.deleted) == 1

    # disconnect: the request page says how to turn files back on
    page.goto(f"{base}/#/configuracoes")
    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Desconectar").click()
    expect(page.locator("#toast")).to_have_text("OneDrive desconectado", timeout=10_000)  # same
    expect(page.get_by_role("button", name="Conectar OneDrive")).to_be_visible()
    # the toast comes after the app has refreshed /api/boot: before it, a request page
    # could still render the upload box (the one flaky test of the suite)
    expect(page.locator("#toast")).to_contain_text("OneDrive desconectado")
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator(".panel", has_text="Arquivos")).to_contain_text("Conecte o OneDrive")


def test_a_batch_goes_up_three_at_a_time(live, device, fake, drive):
    base, auth, store = live
    drive.start_connect()  # the OneDrive is connected already: this is about the batch
    fake.approved = True
    assert drive.poll() == "connected"
    token, _ = auth.create_invite(admin=True)
    page = device().page
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", "Piero Sales")
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#mechip")).to_contain_text("Piero Sales")
    c = store.save_client({"name": "Clínica Bem Estar"})
    store.create_request({"client": c["id"], "what": "Fotos da campanha"}, None)
    page.goto(f"{base}/#/pedido/1")
    expect(page.locator("#filelist")).to_contain_text("Nenhum arquivo ainda")

    fake.upload_delay = 0.4  # OneDrive takes its time with each, whatever the size
    names = [f"foto {n}.png" for n in range(1, 8)]
    page.set_input_files(
        "#pick", files=[{"name": n, "mimeType": "image/png", "buffer": PNG} for n in names]
    )
    expect(page.locator("#uploads .upl")).to_have_count(7)  # the whole queue shows at once
    expect(page.locator("#filelist .file")).to_have_count(7, timeout=20_000)
    expect(page.locator("#toast")).to_have_text("7 arquivos enviados")
    expect(page.locator("#uploads .upl")).to_have_count(0)
    for n in names:  # none lost to a response that arrived late
        expect(page.locator("#filelist")).to_contain_text(n)
    expect(page.locator("#filelist img")).to_have_count(7)
    # the first alone (it makes the folder), then never more than three together
    assert fake.together[0] == 1 and fake.together[1] == 1
    assert max(fake.together) == 3 and len(fake.together) == 7
    # the page stays as it is after a reload: what it showed is what was kept
    page.reload()
    expect(page.locator("#filelist .file")).to_have_count(7)

    # more files for a request that has its folder: nothing to wait for, three go at once
    page.set_input_files(
        "#pick",
        files=[{"name": f"extra {n}.png", "mimeType": "image/png", "buffer": PNG} for n in "abc"],
    )
    expect(page.locator("#filelist .file")).to_have_count(10, timeout=20_000)
    expect(page.locator("#toast")).to_have_text("3 arquivos enviados")
    assert sorted(fake.together[7:]) == [1, 2, 3]

    # one file says its name; an empty one is refused without stopping the rest
    page.set_input_files(
        "#pick",
        files=[
            {"name": "vazio.png", "mimeType": "image/png", "buffer": b""},
            {"name": "capa.png", "mimeType": "image/png", "buffer": PNG},
        ],
    )
    expect(page.locator("#filelist .file")).to_have_count(11, timeout=20_000)
    expect(page.locator("#toast")).to_have_text("capa.png enviado")
