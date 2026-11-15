"""The OneDrive client against the fake Graph: signing in with a code, tokens, files."""

import io
import json
import os
import stat

import pytest

from fakegraph import CLIENT
from pauta import onedrive
from pauta.onedrive import APP_SCOPES, DRIVE_SCOPES, DriveError, OneDrive, safe_name


def make(store, fake, **kw):
    return OneDrive(store.path, client_id=CLIENT, graph=fake.graph, login=fake.login, **kw)


@pytest.fixture()
def drive(store, fake):
    d = make(store, fake, chunk=4, whole=4)  # up to 4 bytes whole, more in chunks of 4
    d.start_connect()
    fake.approved = True
    assert d.poll() == "connected"
    return d


def put(drive, data: bytes, name="foto.png", folder=("Clínica", "Pedido 1")):
    return drive.upload(list(folder), name, len(data), io.BytesIO(data).read)


def test_safe_names():
    assert safe_name('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert safe_name("  ..oi  tudo bem..  ") == "oi tudo bem"
    assert safe_name("") == safe_name("...") == "arquivo"
    assert len(safe_name("x" * 500)) == 120


def test_off_without_a_client_id(store):
    d = OneDrive(store.path)
    assert not d.enabled and not d.connected
    assert d.status() == {**d.status(), "enabled": False, "connected": False}
    with pytest.raises(DriveError) as e:
        d.start_connect()
    assert e.value.status == 400
    with pytest.raises(DriveError) as e:
        d.download_url("x")
    assert e.value.status == 409


def test_from_env(store, monkeypatch):
    monkeypatch.setenv("PAUTA_ONEDRIVE_CLIENT_ID", CLIENT)
    monkeypatch.setenv("PAUTA_ONEDRIVE_ROOT", "/Clientes//Pauta/")
    monkeypatch.setenv("PAUTA_UPLOAD_MAX_MB", "50")
    d = OneDrive.from_env(store.path)
    assert d.enabled and d.root == "Clientes/Pauta" and d.max_bytes == 50 * 2**20
    assert d.scopes == DRIVE_SCOPES and d.status()["folder"] == "/Clientes/Pauta"
    monkeypatch.setenv("PAUTA_UPLOAD_MAX_MB", "lots")
    assert OneDrive.from_env(store.path).max_bytes == 200 * 2**20


def test_device_code_flow(store, fake):
    d = make(store, fake)
    p = d.start_connect()
    assert p["user_code"] == "ABCD-1234" and p["verification_uri"] == "https://microsoft.com/link"
    assert fake.scopes == [APP_SCOPES]
    assert d.poll() == "pending" and not d.connected
    d._pending["next"] = 0
    fake.approved = True
    assert d.poll() == "connected" and d.poll() == "idle"
    assert stat.S_IMODE(os.stat(d.token_file).st_mode) == 0o600
    st = d.status(quota=True)
    assert st["connected"] and st["account"] == "piero@example.com" and st["name"] == "Piero"
    assert st["used"] == 0 and "quota" not in st and not st["error"] and st["pending"] is None
    # the token is never in the database
    with store.db() as db:
        assert "rt1" not in json.dumps([list(r) for r in db.execute("SELECT * FROM meta")])


def test_denied_and_expired_codes(store, fake):
    d = make(store, fake)
    d.start_connect()
    fake.deny = True
    assert d.poll() == "denied" and d.pending() is None
    d.start_connect()
    d._pending["expires"] = 0
    assert d.poll() == "expired"


def test_slow_down_backs_off(store, fake, monkeypatch):
    d = make(store, fake)
    d.start_connect()
    monkeypatch.setattr(d, "_token_call", lambda form: (400, {"error": "slow_down"}))
    assert d.poll() == "pending" and d._pending["interval"] == 5


def test_devicecode_refused(store, fake):
    d = OneDrive(store.path, client_id="someone-else", graph=fake.graph, login=fake.login)
    with pytest.raises(DriveError):
        d.start_connect()


def test_tokens_refresh_and_rotate(drive, fake):
    drive._access = None
    drive.download_url(put(drive, b"x")["id"])
    assert fake.refreshes == 1
    assert json.loads(drive.token_file.read_text())["refresh_token"] == f"rt{fake.token_n}"
    # a token Graph no longer takes: one refresh, one retry
    drive._access = ("stale", 9e12)
    item = put(drive, b"y", "b.png")  # the retry sends the file's bytes again
    assert fake.refreshes == 2 and fake.items[item["id"]]["data"] == b"y"
    drive.download_url(item["id"])


def test_revoked_connection_says_reconnect(drive, fake):
    drive._access = None
    fake.refresh_fails = "invalid_grant"
    with pytest.raises(DriveError) as e:
        put(drive, b"x")
    assert e.value.status == 409 and "reconecte" in str(e.value)
    assert drive.status()["error"] and drive.connected  # the file stays until reconnected
    fake.refresh_fails = "temporarily_unavailable"
    with pytest.raises(DriveError) as e:
        put(drive, b"x")
    assert e.value.status == 502
    drive.disconnect()
    assert not drive.connected and not drive.token_file.exists() and not drive.error


def test_a_small_file_goes_up_whole(drive, fake):
    item = put(drive, b"abcd")
    assert item == {
        "id": item["id"],
        "name": "foto.png",
        "size": 4,
        "mime": "image/png",
        "folder": "FOLDER-approot~Clínica~Pedido 1",
    }
    assert fake.whole == 1  # one request, no session
    assert fake.items[item["id"]]["data"] == b"abcd"
    assert fake.items[item["id"]]["path"] == "approot/Clínica/Pedido 1/foto.png"
    assert put(drive, b"ab")["name"] == "foto 2.png"  # a clash is renamed here too


def test_the_real_limits_send_a_photo_whole_and_a_video_in_chunks(store, fake):
    d = make(store, fake)
    assert d.whole == 4 * 2**20 and d.chunk % (320 * 1024) == 0 and d.chunk > d.whole


def test_upload_in_chunks(drive, fake):
    item = put(drive, b"0123456789")  # chunks of 4 bytes
    assert fake.whole == 0
    assert item == {
        "id": item["id"],
        "name": "foto.png",
        "size": 10,
        "mime": "image/png",
        "folder": "FOLDER-approot~Clínica~Pedido 1",
    }
    assert fake.items[item["id"]]["data"] == b"0123456789"
    assert fake.items[item["id"]]["path"] == "approot/Clínica/Pedido 1/foto.png"
    assert fake.sessions == {}
    again = put(drive, b"abc")
    assert again["name"] == "foto 2.png"  # a clash is renamed, never overwritten


def test_upload_to_a_custom_root(store, fake):
    d = make(store, fake, root="Clientes/Pauta")
    d.start_connect()
    fake.approved = True
    d.poll()
    assert fake.scopes == [DRIVE_SCOPES]
    assert d.status(quota=True)["quota"] == {"used": 5 * 2**30, "total": 1024 * 2**30}
    item = put(d, b"abc", "a?b.png", ("Ótica: Visão",))
    assert fake.items[item["id"]]["path"] == "root/Clientes/Pauta/Ótica_ Visão/a_b.png"


def test_upload_limits_and_failures(drive, fake):
    with pytest.raises(DriveError) as e:
        put(drive, b"")
    assert e.value.status == 400
    drive.max_bytes = 5
    with pytest.raises(DriveError) as e:
        put(drive, b"123456")
    assert e.value.status == 413
    drive.max_bytes = 100
    with pytest.raises(DriveError) as e:  # the browser went away halfway
        drive.upload(["C", "P"], "a.png", 10, io.BytesIO(b"12345").read)
    assert e.value.status == 400 and fake.sessions == {}  # the session was dropped
    with pytest.raises(DriveError) as e:  # the same, with a file small enough to go whole
        drive.upload(["C", "P"], "a.png", 3, io.BytesIO(b"12").read)
    assert e.value.status == 400 and fake.whole == 0 and fake.items == {}
    fake.fail_upload = True
    with pytest.raises(DriveError) as e:
        put(drive, b"12345")
    assert e.value.status == 502 and fake.sessions == {}
    fake.fail_upload = False
    fake.quota_full = True
    for data in (b"12345", b"123"):  # in chunks, whole
        with pytest.raises(DriveError) as e:
            put(drive, data)
        assert e.value.status == 507
    fake.quota_full = False
    fake.down = True
    with pytest.raises(DriveError) as e:
        put(drive, b"123")
    assert e.value.status == 502 and fake.items == {}


def test_downloads_thumbnails_links_deletes(drive, fake):
    img = put(drive, b"png")
    pdf = put(drive, b"pdf", "doc.pdf")
    assert drive.download_url(img["id"]).endswith(f"/download/{img['id']}")
    raw, ctype = drive.thumbnail(img["id"])
    assert ctype == "image/png" and raw.startswith(b"\x89PNG")
    with pytest.raises(DriveError) as e:
        drive.thumbnail(pdf["id"])
    assert e.value.status == 404
    assert drive.share_link(img["folder"]).startswith("https://1drv.ms/")
    drive.delete(pdf["id"])
    drive.delete(pdf["id"])  # already gone is fine
    assert fake.deleted == [pdf["id"]]
    with pytest.raises(DriveError) as e:
        drive.download_url("nope")
    assert e.value.status == 404


def test_graph_down_or_unreachable(drive, fake, store):
    fake.down = True
    with pytest.raises(DriveError) as e:
        drive.download_url("x")
    assert e.value.status == 502
    st = drive.status(quota=True)
    assert st["connected"] and "quota" not in st and st["error"]
    gone = OneDrive(store.path, client_id=CLIENT, graph="http://127.0.0.1:9", login=fake.login)
    with pytest.raises(DriveError) as e:
        gone.download_url("x")
    assert e.value.status == 502


def test_quota_is_read_once_per_visit_window(drive, fake, monkeypatch):
    """The Configurações page asks for the quota on every visit; Graph answers in a second
    or two, so one read serves the window. A file going up or away, or a disconnect, drops
    it; a read that failed is asked again, never kept."""
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 1
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 1
    item = put(drive, b"abcd")
    assert drive.status(quota=True)["used"] == 4 and fake.quota_reads == 2
    drive.delete(item["id"])
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 3
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 3
    monkeypatch.setattr(onedrive, "QUOTA_SECONDS", 0)
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 4
    monkeypatch.setattr(onedrive, "QUOTA_SECONDS", 300)
    fake.down = True
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 4  # still cached
    drive._quota = None
    assert drive.status(quota=True)["error"] and "used" not in drive.status()
    fake.down = False
    assert drive.status(quota=True)["used"] == 0 and fake.quota_reads == 5  # not kept
    drive.disconnect()
    assert drive._quota is None
