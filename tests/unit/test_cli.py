"""The `pauta` command: invite, users, backup, demo and --version."""

import os
import sqlite3
import time

import pytest

from pauta import __version__, cli, obs
from pauta.auth import Auth
from pauta.db import Store


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("PAUTA_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "state"


def test_db_path(monkeypatch, tmp_path):
    monkeypatch.delenv("PAUTA_STATE_DIR", raising=False)
    assert str(cli.db_path()) == os.path.join("state", "pauta.db")
    monkeypatch.setenv("PAUTA_STATE_DIR", str(tmp_path))
    assert cli.db_path() == tmp_path / "pauta.db"


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"pauta {__version__}"


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main([])
    assert e.value.code == 2


def test_invite_prints_a_working_link(state, capsys):
    cli.main(["invite", "--admin", "--uses", "2", "--base-url", "https://pauta.example/"])
    out = capsys.readouterr()
    link = out.out.strip()
    assert link.startswith("https://pauta.example/#/entrar/") and "admin, 2 use(s)" in out.err
    info = Auth(Store(state / "pauta.db"), enabled=True).invite_info(link.rsplit("/", 1)[1])
    assert info["admin"] and info["uses_left"] == 2


def test_users(state, capsys):
    store = Store(state / "pauta.db")
    with store.db() as conn:
        conn.execute("INSERT INTO account(name, handle, is_admin) VALUES ('Renato', 'h', 1)")
    cli.main(["users"])
    line = capsys.readouterr().out
    assert "Renato" in line and "passkeys=0" in line and "admin" in line


def test_backup_writes_copies_and_prunes(state, tmp_path, capsys):
    Store(state / "pauta.db").save_client({"name": "Kept"})
    local, nas = tmp_path / "bk", tmp_path / "nas"
    local.mkdir()
    stale = local / "pauta-20200101-000000.db"
    stale.write_bytes(b"old")
    old = time.time() - 40 * 86400
    os.utime(stale, (old, old))
    cli.main(["backup", "--dir", str(local), "--copy-to", str(nas), "--keep-days", "30"])
    made = sorted(p.name for p in local.glob("pauta-*.db"))
    assert len(made) == 1 and not stale.exists()
    assert [p.name for p in nas.glob("pauta-*.db")] == made
    conn = sqlite3.connect(local / made[0])
    try:
        assert conn.execute("SELECT name FROM client").fetchone()[0] == "Kept"
    finally:
        conn.close()


def test_backup_survives_a_missing_nas(state, tmp_path, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    cli.main(["backup", "--dir", str(tmp_path / "bk"), "--copy-to", str(blocker / "sub")])
    assert "failed" in capsys.readouterr().err
    assert len(list((tmp_path / "bk").glob("pauta-*.db"))) == 1


def test_demo_fills_once(state, capsys):
    cli.main(["demo"])
    store = Store(state / "pauta.db")
    assert len(store.clients()) == 5 and len(store.requests()) == 6
    assert {r["status"] for r in store.requests()} == {"todo", "doing", "waiting", "done"}
    with pytest.raises(SystemExit, match="already has clients"):
        cli.main(["demo"])


def test_serve_wires_store_auth_and_server(state, monkeypatch, capsys):
    served = {}

    class FakeServer:
        def __init__(self, addr, handler):
            served["addr"], served["handler"] = addr, handler

        def serve_forever(self):
            raise KeyboardInterrupt  # what Ctrl-C does; serve exits cleanly

    monkeypatch.setattr(cli, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setenv("PAUTA_AUTH", "passkeys")
    monkeypatch.setenv("PAUTA_RP_ID", "pauta.example")
    cli.main(["serve", "--port", "9999"])
    assert served["addr"] == ("127.0.0.1", 9999)
    assert "passkeys on pauta.example" in capsys.readouterr().out
    handler = obs.setup_logging()  # serve set it up (to stderr); leave the logger clean
    obs.log.removeHandler(handler)
