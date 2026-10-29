"""Files on requests over real HTTP, with the OneDrive behind them faked (tests/fakegraph.py)."""

import json
import urllib.error
import urllib.request
from urllib.parse import quote

import pytest

from softpasskey import ORIGIN, call


@pytest.fixture()
def drive(drive_on):
    return drive_on


def upload(base, rid, name, data, cookie, ctype="image/png", headers=None):
    hdrs = {"Content-Type": ctype, "Cookie": cookie, "Origin": ORIGIN}
    if name is not None:
        hdrs["X-File-Name"] = quote(name)
    req = urllib.request.Request(
        f"{base}/api/requests/{rid}/files", data=data, headers={**hdrs, **(headers or {})}
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read()), r.headers
    except urllib.error.HTTPError as e:
        with e:
            return e.code, json.loads(e.read() or b"{}"), e.headers


def get(url, cookie):
    req = urllib.request.Request(url, headers={"Cookie": cookie})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        with e:
            return e.code, e.read(), e.headers


def connect(base, nato, fake):
    status, doc, _ = call(f"{base}/api/onedrive/connect", {}, nato)
    assert status == 200 and doc["state"] == "pending"
    assert doc["pending"]["user_code"] == "ABCD-1234"
    assert call(f"{base}/api/onedrive", cookie=nato)[1]["state"] == "pending"
    fake.approved = True
    doc = call(f"{base}/api/onedrive", cookie=nato)[1]
    assert doc["state"] == "connected" and doc["account"] == "piero@example.com"
    assert doc["quota"]["total"] == 1024 * 2**30


@pytest.fixture()
def filed(team, fake):
    """A connected OneDrive and request #1 for "Clínica Bem Estar"."""
    base, nato, piero, _ = team
    connect(base, nato, fake)
    c = call(f"{base}/api/clients", {"name": "Clínica Bem Estar"}, nato)[1]
    r = call(f"{base}/api/requests", {"client": c["id"], "what": "Campanha"}, nato)[1]
    assert r["files"] == [] and r["id"] == 1
    return base, nato, piero


def test_only_admins_manage_the_connection(team, fake):
    base, nato, piero, _ = team
    boot = call(f"{base}/api/boot", cookie=piero)[1]
    assert boot["files"] == {"enabled": True, "connected": False, "max_mb": 200}
    assert call(f"{base}/api/onedrive", cookie=piero)[0] == 403
    assert call(f"{base}/api/onedrive/connect", {}, piero)[0] == 403
    assert call(f"{base}/api/onedrive", cookie=nato)[1]["state"] == "idle"
    status, doc, _ = upload(base, 1, "a.png", b"x", piero)
    assert status == 404  # no request yet
    connect(base, nato, fake)
    assert call(f"{base}/api/boot", cookie=piero)[1]["files"]["connected"] is True
    status, doc, _ = call(f"{base}/api/onedrive", cookie=nato, method="DELETE")
    assert status == 200 and not doc["connected"]
    assert call(f"{base}/api/boot", cookie=piero)[1]["files"]["connected"] is False


def test_upload_download_and_the_timeline(filed, fake):
    base, nato, piero = filed
    status, r, _ = upload(base, 1, "criativo final.png", b"\x89PNG-bytes", piero)
    assert status == 200
    f = r["files"][0]
    assert f["name"] == "criativo final.png" and f["size"] == 10 and f["mime"] == "image/png"
    assert f["account_name"] == "Piero" and r["files"] == [f]
    assert r["events"][-1]["kind"] == "file" and r["events"][-1]["text"] == "criativo final.png"
    stored = next(iter(fake.items.values()))
    assert stored["path"] == "approot/Clínica Bem Estar/Pedido 1/criativo final.png"
    assert [x["files"] for x in call(f"{base}/api/requests", cookie=nato)[1]] == [1]
    # download: a redirect to Graph's short-lived link (urllib follows it)
    status, body, _ = get(f"{base}/api/files/{f['id']}", nato)
    assert status == 200 and body == b"\x89PNG-bytes"
    req = urllib.request.Request(f"{base}/api/files/{f['id']}", headers={"Cookie": nato})
    opener = urllib.request.build_opener(NoRedirect)
    with pytest.raises(urllib.error.HTTPError) as e:
        opener.open(req)
    assert e.value.code == 302 and "/download/" in e.value.headers["Location"]
    assert e.value.headers["Cache-Control"] == "no-store"
    e.value.close()
    status, body, headers = get(f"{base}/api/files/{f['id']}/thumb", nato)
    assert status == 200 and headers["Content-Type"] == "image/png" and body.startswith(b"\x89PNG")
    assert get(f"{base}/api/files/{f['id']}", "")[0] == 401
    assert get(f"{base}/api/files/99", nato)[0] == 404
    export = call(f"{base}/api/export", cookie=nato)[1]
    assert export["requests"][0]["files"][0]["name"] == "criativo final.png"


def test_a_view_link_for_the_client(filed):
    base, nato, piero = filed
    assert call(f"{base}/api/requests/1/share", {}, piero)[0] == 400  # nothing to share yet
    upload(base, 1, "a.png", b"abc", piero)
    status, doc, _ = call(f"{base}/api/requests/1/share", {}, piero)
    assert status == 200 and doc["url"].startswith("https://1drv.ms/")


def test_removing_files(filed, fake):
    base, nato, piero = filed
    fid = upload(base, 1, "a.png", b"abc", nato)[1]["files"][0]["id"]
    assert call(f"{base}/api/files/{fid}", cookie=piero, method="DELETE")[0] == 403
    pid = upload(base, 1, "b.png", b"abc", piero)[1]["files"][0]["id"]
    status, r, _ = call(f"{base}/api/files/{pid}", cookie=piero, method="DELETE")
    assert status == 200 and [f["name"] for f in r["files"]] == ["a.png"]
    assert r["events"][-1]["kind"] == "unfile" and len(fake.deleted) == 1
    status, r, _ = call(f"{base}/api/files/{fid}", cookie=nato, method="DELETE")  # admin
    assert status == 200 and r["files"] == []
    assert call(f"{base}/api/files/{fid}", cookie=nato, method="DELETE")[0] == 404


def test_bad_uploads(filed, fake, drive):
    base, nato, piero = filed
    assert upload(base, 1, None, b"abc", piero)[0] == 400  # no name
    assert upload(base, 1, "a.png", b"", piero)[0] == 400  # empty
    hostile = {"Origin": "https://evil.example"}
    assert upload(base, 1, "a.png", b"abc", piero, headers=hostile)[0] == 403
    assert upload(base, 1, "a.png", b"abc", "")[0] == 401
    drive.max_bytes = 2
    status, doc, _ = upload(base, 1, "a.png", b"abc", piero)
    assert status == 413 and "grande demais" in doc["error"]
    drive.max_bytes = 2**20
    fake.quota_full = True
    assert upload(base, 1, "a.png", b"abc", piero)[0] == 507
    fake.quota_full = False
    fake.down = True
    status, doc, _ = upload(base, 1, "a.png", b"abc", piero)
    assert status == 502 and "OneDrive" in doc["error"]
    fake.down = False
    assert call(f"{base}/api/requests/1", cookie=piero)[1]["files"] == []


def test_not_connected(team, drive):
    base, nato, piero, _ = team
    c = call(f"{base}/api/clients", {"name": "Ótica"}, nato)[1]
    call(f"{base}/api/requests", {"client": c["id"], "what": "x"}, nato)
    status, doc, _ = upload(base, 1, "a.png", b"abc", piero)
    assert status == 409 and "Equipe" in doc["error"]


def test_metrics_report_the_connection(filed, drive):
    base, _, _ = filed
    with urllib.request.urlopen(f"{base}/metrics") as r:
        doc = json.loads(r.read())
    assert doc["onedrive"] == {"enabled": True, "connected": True, "error": ""}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
