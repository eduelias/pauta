"""Browser fixtures: a live server on localhost and Chromium with a virtual passkey device.

Chromium's WebAuthn domain (over CDP) gives each browser context a software authenticator
that answers navigator.credentials.create/get like Face ID would, user verification and
all, so the real login and join screens run end to end.
"""

import re
from pathlib import Path

import pytest

pw = pytest.importorskip("playwright.sync_api")

TRACES = Path("test-results/traces")  # CI uploads these when a browser test fails

from appserver import serve  # noqa: E402
from pauta.auth import Auth  # noqa: E402

PNG = bytes.fromhex(  # a 1x1 transparent PNG, standing in for gravatar.com
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture()
def live(store, drive):
    """The app with passkeys on, reached as http://localhost:<port> (the passkey RP ID)."""
    auth = Auth(store, enabled=True, rp_id="localhost", origins=["placeholder"])
    httpd = serve(store, auth, drive)
    base = f"http://localhost:{httpd.server_address[1]}"
    auth.origins = [base]
    yield base, auth, store
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="session")
def browser():
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    rep = yield
    setattr(item, f"rep_{rep.when}", rep)
    return rep


class Device:
    """One phone or laptop: its own cookies and its own passkeys."""

    def __init__(self, browser, **context_args):
        self.context = browser.new_context(locale="pt-BR", **context_args)
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.context.route("https://gravatar.com/**", lambda r: r.fulfill(body=PNG))
        self.page = self.context.new_page()
        self.errors: list[str] = []
        self.page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.page.on("console", self._console)
        self.page.on("response", self._response)
        self.expected: set[tuple[int, str]] = set()  # (status, path prefix) a test expects
        cdp = self.context.new_cdp_session(self.page)
        cdp.send("WebAuthn.enable")
        self.authenticator = cdp.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                }
            },
        )["authenticatorId"]
        self.cdp = cdp

    def _console(self, msg):
        # failed loads are reported with their URL by _response instead
        if msg.type == "error" and not msg.text.startswith("Failed to load resource"):
            self.errors.append(f"console: {msg.text}")

    def _response(self, resp):
        if resp.status < 400:
            return
        path = "/" + resp.url.split("/", 3)[-1]
        if not any(resp.status == st and path.startswith(pre) for st, pre in self.expected):
            self.errors.append(f"HTTP {resp.status} {resp.request.method} {path}")

    def passkeys(self) -> list[dict]:
        return self.cdp.send("WebAuthn.getCredentials", {"authenticatorId": self.authenticator})[
            "credentials"
        ]

    def close(self, trace_to: Path | None = None):
        self.context.tracing.stop(path=trace_to)
        self.context.close()


@pytest.fixture()
def device(browser, request):
    """A desktop browser. Fails the test on any JS error, CSP violation or unexpected HTTP error."""
    made: list[Device] = []

    def make(**context_args) -> Device:
        d = Device(browser, **{"viewport": {"width": 1280, "height": 860}, **context_args})
        made.append(d)
        return d

    yield make
    errors = [e for d in made for e in d.errors]
    failed = (
        errors or getattr(request.node, "rep_call", None) is None or request.node.rep_call.failed
    )
    name = re.sub(r"[^\w.-]+", "_", request.node.name)
    for i, d in enumerate(made):
        d.close(TRACES / f"{name}-{i}.zip" if failed else None)
    assert not errors, errors
