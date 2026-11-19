"""The `pauta` command: invite, users, backup, demo, onedrive, meta and --version."""

import os
import sqlite3
import time

import pytest

from pauta import __version__, cli, db, obs
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


def test_reload_changes_the_mark_a_running_server_reads(state, capsys, monkeypatch):
    server = Store(state / "pauta.db")  # the running server's own Store
    assert server.reload_mark() == f"{db.RELOAD_EPOCH}.0"
    cli.main(["reload"])  # another process: it only writes the file
    assert f"reload mark {db.RELOAD_EPOCH}.1" in capsys.readouterr().out
    assert server.reload_mark() == f"{db.RELOAD_EPOCH}.0"  # its copy, for a couple of seconds
    monkeypatch.setattr(db, "RELOAD_RECHECK_SECONDS", 0.0)
    server._reload = (0.0, "")
    assert server.reload_mark() == f"{db.RELOAD_EPOCH}.1"
    cli.main(["reload"])
    assert server.reload_mark() == f"{db.RELOAD_EPOCH}.2"
    # a release that needs every tab gone raises the epoch: a new mark with no command run
    monkeypatch.setattr(db, "RELOAD_EPOCH", db.RELOAD_EPOCH + 1)
    assert server.reload_mark() == f"{db.RELOAD_EPOCH}.2"


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


def test_onedrive(state, fake, monkeypatch, capsys):
    from fakegraph import CLIENT
    from pauta.onedrive import OneDrive

    def from_env(path):
        return OneDrive(path, client_id=CLIENT, graph=fake.graph, login=fake.login)

    with pytest.raises(SystemExit, match="PAUTA_ONEDRIVE_CLIENT_ID"):
        cli.main(["onedrive", "status"])
    monkeypatch.setattr(cli.OneDrive, "from_env", staticmethod(from_env))
    with pytest.raises(SystemExit, match="not connected"):
        cli.main(["onedrive", "status"])
    fake.approved = True
    cli.main(["onedrive", "connect", "--poll", "0"])
    out = capsys.readouterr().out
    assert "enter the code ABCD-1234" in out and "connected as Piero <piero@example.com>" in out
    assert "pauta's folder holds 0.0 MB" in out
    fake.down = True
    with pytest.raises(SystemExit, match="problem: o OneDrive não respondeu"):
        cli.main(["onedrive", "status"])
    fake.down = False
    cli.main(["onedrive", "disconnect"])
    assert "the files stay in OneDrive" in capsys.readouterr().out
    fake.deny = True
    with pytest.raises(SystemExit, match="not connected: denied"):
        cli.main(["onedrive", "connect", "--poll", "0"])
    fake.close()  # Microsoft unreachable
    with pytest.raises(SystemExit, match="onedrive: o OneDrive não respondeu"):
        cli.main(["onedrive", "connect"])


def test_meta_sync_and_status(state, fake_meta, monkeypatch, capsys):
    from test_meta import connect

    from fakemeta import APP_ID, CONFIG_ID, TODAY, secret
    from pauta import sync
    from pauta.meta import Meta

    with pytest.raises(SystemExit, match="PAUTA_META_APP_ID"):
        cli.main(["meta", "status"])
    store = Store(state / "pauta.db")
    secret(store.path)

    def from_env(path):
        return Meta(path, app_id=APP_ID, config_id=CONFIG_ID, graph=fake_meta.graph)

    monkeypatch.setattr(cli.Meta, "from_env", staticmethod(from_env))
    with pytest.raises(SystemExit, match="not connected"):
        cli.main(["meta", "status"])
    with pytest.raises(SystemExit, match="meta: a Meta não está conectada"):
        cli.main(["meta", "sync"])
    connect(from_env(store.path), fake_meta)
    clinic = store.save_client({"name": "Clínica"})
    store.sync_meta_accounts([{"id": "111", "name": "Clínica"}, {"id": "222", "name": "P"}])
    store.link_meta_account("111", clinic["id"])
    real = sync.run
    monkeypatch.setattr(sync, "run", lambda s, m, *, days: real(s, m, days=days, today=TODAY))
    cli.main(["meta", "sync", "--days", "3"])
    out = capsys.readouterr().out
    assert "1 portfolio(s), 1 account(s), 2 new campaign(s)" in out
    assert "request(s) linked" in out
    assert store.connections()[0]["last_sync"]  # the row followed the file, and the sync
    cli.main(["meta", "status"])
    out = capsys.readouterr().out
    assert "portfolio Agência Exemplo (300000000000003): ok, connected 20" in out
    assert "2 ad account(s), 1 linked" in out and "last sync 20" in out
    fake_meta.fail_campaigns.add("111")
    with pytest.raises(SystemExit) as e:
        cli.main(["meta", "sync"])
    assert e.value.code == 1 and "account 111:" in capsys.readouterr().err
    with pytest.raises(SystemExit, match="problem: a Meta não respondeu"):
        cli.main(["meta", "status"])
    # a revoked portfolio is a problem of its own
    fake_meta.fail_campaigns.clear()
    fake_meta.token_invalid = True
    with pytest.raises(SystemExit):
        cli.main(["meta", "sync"])
    with pytest.raises(SystemExit, match="problem: a conexão com a Meta foi revogada"):
        cli.main(["meta", "status"])
    assert "revoked, connected" in capsys.readouterr().out


def test_serve_starts_the_sync_scheduler_when_meta_is_on(state, monkeypatch, capsys):
    from fakemeta import APP_ID, CONFIG_ID, secret
    from pauta import sync

    class FakeServer:
        def __init__(self, addr, handler):
            pass

        def serve_forever(self):
            raise KeyboardInterrupt

    started = []

    class FakeScheduler:
        def __init__(self, store, meta):
            started.append(meta)

        def start(self):
            started.append("started")

    monkeypatch.setattr(cli, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(sync, "Scheduler", FakeScheduler)
    # the account list is read at the start too (Meta.warm), before the first page asks
    monkeypatch.setattr(cli.Meta, "warm", lambda self: started.append("warm"))
    monkeypatch.setenv("PAUTA_META_APP_ID", APP_ID)
    monkeypatch.setenv("PAUTA_META_CONFIG_ID", CONFIG_ID)
    state.mkdir(parents=True, exist_ok=True)
    secret(state / "pauta.db")
    monkeypatch.setenv("PAUTA_META_SYNC", "off")
    cli.main(["serve"])
    assert started == []
    monkeypatch.delenv("PAUTA_META_SYNC")
    cli.main(["serve"])
    assert started[0] == "warm" and started[2:] == ["started"] and started[1].enabled
    handler = obs.setup_logging()
    obs.log.removeHandler(handler)
