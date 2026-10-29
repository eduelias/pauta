"""Shared fixtures: a fresh database, the passkey layer, and a running server on a free port."""

import pytest

from appserver import serve
from fakegraph import CLIENT, FakeGraph
from pauta.auth import Auth
from pauta.db import Store
from pauta.onedrive import OneDrive
from softpasskey import ORIGIN, RP_ID, SoftPasskey, call, join


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path / "pauta.db")


@pytest.fixture()
def auth(store):
    return Auth(store, enabled=True, rp_id=RP_ID, origins=[ORIGIN])


@pytest.fixture()
def drive(store):
    """Files off (no client id). Tests about files override this with one on the fake Graph."""
    return OneDrive(store.path)


@pytest.fixture()
def fake():
    """A fake Microsoft login and Graph on localhost (tests/fakegraph.py)."""
    f = FakeGraph()
    yield f
    f.close()


@pytest.fixture()
def drive_on(store, fake):
    """Files on, against the fake Graph, not connected yet."""
    return OneDrive(store.path, client_id=CLIENT, graph=fake.graph, login=fake.login)


@pytest.fixture()
def site(store, auth, drive):
    httpd = serve(store, auth, drive)
    yield f"http://127.0.0.1:{httpd.server_address[1]}", auth, store
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def team(site):
    """Renato (admin, from the CLI invite) and Piero (member, invited by Renato)."""
    base, auth, store = site
    token, _ = auth.create_invite(admin=True)
    nato_key = SoftPasskey()
    status, me, nato = join(base, token, "Renato Lima", nato_key)
    assert status == 200 and me["is_admin"] and me["name"] == "Renato Lima"
    status, inv, _ = call(f"{base}/api/invite", {}, nato)
    assert status == 200 and inv["path"].startswith("/#/entrar/")
    ptoken = inv["path"].rsplit("/", 1)[1]
    info = call(f"{base}/api/invite/{ptoken}")[1]
    assert info == {**info, "admin": False, "uses_left": 1, "invited_by": "Renato Lima"}
    status, me, piero = join(base, ptoken, "Piero", SoftPasskey())
    assert status == 200 and not me["is_admin"]
    return base, nato, piero, nato_key
