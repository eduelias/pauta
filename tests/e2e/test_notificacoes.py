"""Notifications in a real browser: the switch on Perfil, and the worker that shows what the
server says when a push wakes it.

Two things here are stand-ins. Chromium only gives a push subscription by asking Google's
push service, which tests never call: the page's `subscribe` is replaced by one that
answers with an address on the fake push service. And the notifications need Chromium's
newer headless mode (the default one refuses the permission), so this file starts its own.
"""

import time

import pytest
from playwright.sync_api import expect
from test_perfil import join

from appserver import serve
from fakepush import FakePush
from pauta.auth import Auth
from pauta.push import Push

pytestmark = pytest.mark.e2e

# what the browser would hand the page after asking its push service
SAID = "(go) => navigator.serviceWorker.dispatchEvent(new MessageEvent('message', {data: {go}}))"
STUB = """(endpoint) => {
  let sub = null;
  const made = { endpoint, unsubscribe: async () => { sub = null; return true; } };
  PushManager.prototype.subscribe = async function () { sub = made; return sub; };
  PushManager.prototype.getSubscription = async function () { return sub; };
}"""


@pytest.fixture(scope="module")
def browser(chromium):
    b = chromium.launch(channel="chromium")
    yield b
    b.close()


@pytest.fixture()
def fake_push():
    f = FakePush()
    yield f
    f.close()


@pytest.fixture()
def live(store, drive, meta, fake_push):
    """The shared `live`, with the push service on the fake."""
    auth = Auth(store, enabled=True, rp_id="localhost", origins=["placeholder"])
    push = Push(store, services=(fake_push.host,), scheme="http")
    httpd = serve(store, auth, drive, meta, push)
    base = f"http://localhost:{httpd.server_address[1]}"
    auth.origins = [base]
    yield base, auth, store
    httpd.shutdown()
    httpd.server_close()


def test_the_switch_on_perfil(live, device, fake_push):
    base, auth, store = live
    d = join(device, base, auth, "Piero", permissions=["notifications"])
    page = d.page
    phone = fake_push.endpoint("piero-phone")
    page.evaluate(STUB, phone)
    page.goto(f"{base}/#/perfil")
    box = page.locator("#push")
    expect(box.get_by_role("heading", name="Notificações")).to_be_visible()

    box.get_by_role("button", name="Ativar neste aparelho").click()
    expect(page.locator("#toast")).to_have_text("Notificações ativadas neste aparelho")
    expect(box).to_contain_text("Ativadas neste aparelho")
    assert store.push_targets(None) == [phone]
    assert page.evaluate("navigator.serviceWorker.getRegistration().then((r) => r.scope)") == (
        f"{base}/"
    )

    # someone else files a request: the phone is woken, with nothing in the push
    client = store.save_client({"name": "Clínica Bem Estar"})
    store.create_request({"client": client["id"], "what": "Campanha de Natal"}, None)
    assert fake_push.wait(1) == ["piero-phone"] and fake_push.pushes[0]["body"] == b""

    # signing out forgets the person's devices; the next time the Pauta opens on one that
    # still has them on, it says so again by itself
    store.push_forget(account=1)
    page.evaluate("pushResume()")
    assert store.push_targets(None) == [phone]

    box.get_by_role("button", name="Desativar").click()
    expect(page.locator("#toast")).to_have_text("Notificações desativadas neste aparelho")
    expect(box.get_by_role("button", name="Ativar neste aparelho")).to_be_visible()
    assert store.push_targets(None) == []


def test_a_browser_that_refuses_says_so(live, device):
    base, auth, _ = live
    d = join(device, base, auth, "Piero")  # the permission was never given: Chromium asks
    page = d.page
    page.evaluate("Notification.requestPermission = async () => 'denied'")  # ...and is told no
    page.goto(f"{base}/#/perfil")
    page.locator("#push").get_by_role("button", name="Ativar neste aparelho").click()
    expect(page.locator("#toast")).to_have_text(
        "as notificações não foram liberadas neste aparelho"
    )
    expect(
        page.locator("#push").get_by_role("button", name="Ativar neste aparelho")
    ).to_be_enabled()


def until(read, want, seconds=5.0):
    """`read()` once it gives what `want` accepts (the worker answers on its own time)."""
    deadline = time.monotonic() + seconds
    while not want(got := read()) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert want(got), got
    return got


def notifications(page):
    return page.evaluate(
        """async () => {
          const reg = await navigator.serviceWorker.getRegistration();
          return (await reg.getNotifications()).map((n) => [n.title, n.body, n.tag, n.data.url]);
        }"""
    )


def test_a_push_shows_what_the_server_says(live, device):
    base, auth, store = live
    d = join(device, base, auth, "Piero", permissions=["notifications"])
    page = d.page
    registrations = []
    d.cdp.on(
        "ServiceWorker.workerRegistrationUpdated",
        lambda e: registrations.extend(e["registrations"]),
    )
    d.cdp.send("ServiceWorker.enable")
    page.evaluate(
        "navigator.serviceWorker.register('/sw.js').then(() => navigator.serviceWorker.ready)"
    )
    until(lambda: registrations, bool)

    def push():
        d.cdp.send(
            "ServiceWorker.deliverPushMessage",
            {"origin": base, "registrationId": registrations[0]["registrationId"], "data": ""},
        )

    # this browser has no subscription of its own, so the worker names no device: the
    # server refuses, and the worker still shows something, as it does signed out or offline
    push()
    generic = [["Pauta", "Há novidades nos pedidos.", "pauta", "/"]]
    until(lambda: notifications(page), lambda got: got == generic)

    # with the device known to the server, it shows the request Renato just filed
    store.push_subscribe(1, "")
    client = store.save_client({"name": "Clínica Bem Estar"})
    req = store.create_request({"client": client["id"], "what": "Campanha de Natal"}, None)
    push()
    shown = until(lambda: notifications(page), lambda got: len(got) == 2)
    assert [
        "Novo pedido · Clínica Bem Estar",
        "Campanha de Natal",
        f"pedido-{req['id']}",
        f"/#/pedido/{req['id']}",
    ] in shown

    # a tap on it while the Pauta is open: the worker names the request, the page opens it
    page.evaluate(SAID, f"#/pedido/{req['id']}")
    expect(page.locator("#app")).to_contain_text("criou o pedido")
    page.evaluate(SAID, "https://example.com")
    assert page.url == f"{base}/#/pedido/{req['id']}"  # only an address inside the app
