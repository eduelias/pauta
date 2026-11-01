"""Moving to a new domain (decision 4): passkey domains per page, and the one-time link that
lets a signed-in person (or an admin, for them) make a passkey for the same account on the new
domain."""

import sqlite3
import time

import pytest

from pauta.auth import MOVE_LINK_DAYS, MOVE_SECONDS, Auth, AuthError
from pauta.db import Store
from softpasskey import SoftPasskey

NEW, OLD = "https://app.pauta.cc", "https://pauta.example"


@pytest.fixture()
def moving(store):
    return Auth(store, enabled=True, rp_id="pauta.cc, pauta.example", origins=[NEW, OLD])


def join_old(auth, name="Renato"):
    """Someone who joined before the move: an account and a passkey on the old domain."""
    token, _ = auth.create_invite()
    key = SoftPasskey("pauta.example", OLD)
    opts = auth.register_options(invite=token, name=name, rp_id="pauta.example")
    acc = auth.register_verify(opts["flow"], key.create(opts["options"]))
    return acc, key


def move(auth, token, key):
    opts = auth.register_options(move=token, rp_id="pauta.cc")
    return auth.register_verify(opts["flow"], key.create(opts["options"]))


def domains(store, account_id):
    with store.db() as db:
        rows = db.execute("SELECT rp_id FROM passkey WHERE account=?", (account_id,))
        return sorted(r[0] for r in rows)


def test_each_page_gets_the_domain_it_sits_under(moving):
    assert moving.rp_ids == ["pauta.cc", "pauta.example"] and moving.rp_id == "pauta.cc"
    assert moving.rp_for(NEW) == "pauta.cc"
    assert moving.rp_for(OLD) == "pauta.example"
    assert moving.rp_for("https://acc.pauta.cc") == "pauta.cc"  # a parent domain is allowed
    assert moving.rp_for("https://notpauta.cc") == "pauta.cc"  # not a lookalike: home
    assert moving.rp_for(None) == moving.rp_for("garbage") == "pauta.cc"
    assert moving.moving and moving.home == NEW


def test_one_domain_is_not_a_move(store, auth):
    assert not auth.moving
    assert auth.move_hint("http://localhost:8088", None) is None
    off = Auth(store, enabled=False, rp_id="a.example,b.example")
    assert not off.moving
    # no origin on the home domain: nowhere to send people
    lost = Auth(store, enabled=True, rp_id="a.example,b.example", origins=["https://b.example"])
    assert lost.home is None and lost.move_hint("https://b.example", None) is None


def test_moving_an_account(store, moving):
    acc, old_key = join_old(moving)
    assert domains(store, acc["id"]) == ["pauta.example"]
    hint = moving.move_hint(OLD, acc["id"])
    assert hint == {"to": "app.pauta.cc", "url": NEW, "here": False, "done": False}

    token, _ = moving.create_move(acc["id"])
    assert moving.move_info(token) == {"name": "Renato", "to": "app.pauta.cc"}
    moved = move(moving, token, SoftPasskey("pauta.cc", NEW))
    assert moved["id"] == acc["id"]  # the same account, now with a passkey on both domains
    assert domains(store, acc["id"]) == ["pauta.cc", "pauta.example"]
    assert moving.move_hint(NEW, acc["id"]) == {**hint, "here": True, "done": True}
    assert [m["domains"] for m in store.members()] == [["pauta.cc", "pauta.example"]]

    # the link works once
    assert moving.move_info(token) is None
    with pytest.raises(AuthError, match="expirou"):
        moving.register_options(move=token, rp_id="pauta.cc")

    # the old passkey still signs in on the old domain until it's closed
    opts = moving.login_options("pauta.example")
    assert moving.login_verify(opts["flow"], old_key.get(opts["options"], ""))["id"] == acc["id"]


def test_a_passkey_only_works_on_its_own_domain(moving):
    _, old_key = join_old(moving)
    opts = moving.login_options("pauta.cc")
    with pytest.raises(AuthError, match="não aceita"):
        moving.login_verify(opts["flow"], old_key.get(opts["options"], ""))
    # nor can a page on one domain register for the other
    token, _ = moving.create_move(1)
    opts = moving.register_options(move=token, rp_id="pauta.cc")
    with pytest.raises(AuthError, match="não aceita"):
        moving.register_verify(opts["flow"], SoftPasskey("pauta.cc", OLD).create(opts["options"]))


def test_move_links_expire_and_die_with_the_account(store, moving):
    acc, _ = join_old(moving)
    token, _ = moving.create_move(acc["id"])
    opts = moving.register_options(move=token, rp_id="pauta.cc")
    with store.db() as db:
        db.execute("UPDATE invite SET expires=0")
    assert moving.move_info(token) is None
    with pytest.raises(AuthError, match="expirou"):  # expired between options and verify
        moving.register_verify(opts["flow"], SoftPasskey("pauta.cc", NEW).create(opts["options"]))

    token, _ = moving.create_move(acc["id"])
    with store.db() as db:
        db.execute("UPDATE account SET disabled=1 WHERE id=?", (acc["id"],))
    assert moving.move_info(token) is None
    assert moving.move_info("not-a-token") is None
    with pytest.raises(AuthError, match="desativada"):  # nor can a new one be made
        moving.create_move(acc["id"])
    with pytest.raises(AuthError, match="não existe"):
        moving.create_move(99)


def test_an_admin_link_lasts_days_and_survives_a_restart(store, moving):
    acc, _ = join_old(moving)
    token, expires = moving.create_move(acc["id"], MOVE_LINK_DAYS * 86400, created_by=acc["id"])
    assert expires > time.time() + 2 * 86400
    restarted = Auth(store, enabled=True, rp_id="pauta.cc,pauta.example", origins=[NEW, OLD])
    assert restarted.move_info(token) == {"name": "Renato", "to": "app.pauta.cc"}
    assert move(restarted, token, SoftPasskey("pauta.cc", NEW))["id"] == acc["id"]
    assert restarted.move_info(token) is None


def test_a_self_made_link_lasts_minutes_and_ends_with_the_sessions(store, moving):
    """The person taps their own link on the new phone right away, so it lives 10 minutes
    and dies with "Sair em todos os aparelhos"; an admin's link for them is the admin's."""
    acc, _ = join_old(moving)
    admin = add_admin(store)
    assert MOVE_SECONDS == 600
    before = time.time()
    mine, expires = moving.create_move(acc["id"], created_by=acc["id"])
    assert before + 590 < expires <= time.time() + 600
    theirs, _ = moving.create_move(acc["id"], MOVE_LINK_DAYS * 86400, created_by=admin)
    assert moving.move_info(mine) and moving.move_info(theirs)

    moving.end_sessions(acc["id"])
    assert moving.move_info(mine) is None  # expired, not deleted: the row says so
    assert moving.move_info(theirs) == {"name": "Renato", "to": "app.pauta.cc"}
    with store.db() as db:
        rows = db.execute("SELECT created_by, expires FROM invite WHERE account=?", (acc["id"],))
        assert {(r[0], r[1] == 0) for r in rows} == {(acc["id"], True), (admin, False)}
    # the admin signing out touches none of them
    moving.end_sessions(admin)
    assert moving.move_info(theirs) is not None
    moving.end_sessions(None)  # open mode: nothing to do


def add_admin(store, name="Edu"):
    with store.db() as db:
        return db.execute(
            "INSERT INTO account(name, handle, is_admin) VALUES (?, ?, 1)", (name, f"h-{name}")
        ).lastrowid


def test_a_move_link_is_not_an_invite_and_an_invite_is_not_a_move_link(store, moving):
    acc, _ = join_old(moving)
    mtoken, _ = moving.create_move(acc["id"])
    assert moving.invite_info(mtoken) is None
    with pytest.raises(AuthError, match="convite"):  # it can't make a new account
        moving.register_options(invite=mtoken, name="Intruso", rp_id="pauta.cc")
    itoken, _ = moving.create_invite()
    assert moving.move_info(itoken) is None
    with pytest.raises(AuthError, match="expirou"):  # nor take over an existing one
        moving.register_options(move=itoken, rp_id="pauta.cc")


def test_old_passkeys_learn_their_domain_when_used(store, moving):
    acc, key = join_old(moving)
    with store.db() as db:
        db.execute("UPDATE passkey SET rp_id=''")  # as created by 1.5 and older
    assert store.members()[0]["domains"] == []
    opts = moving.login_options("pauta.example")
    moving.login_verify(opts["flow"], key.get(opts["options"], ""))
    assert domains(store, acc["id"]) == ["pauta.example"]


def test_a_database_from_before_the_move_gets_the_column(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE account (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
            "handle TEXT NOT NULL UNIQUE, is_admin INTEGER NOT NULL DEFAULT 0, "
            "disabled INTEGER NOT NULL DEFAULT 0, created TEXT);"
            "CREATE TABLE passkey (id TEXT PRIMARY KEY, account INTEGER NOT NULL, "
            "public_key BLOB NOT NULL, sign_count INTEGER NOT NULL DEFAULT 0, transports TEXT, "
            "created TEXT, last_used TEXT);"
            "INSERT INTO account(id, name, handle) VALUES (1, 'Ana', 'h');"
            "INSERT INTO passkey(id, account, public_key) VALUES ('k', 1, x'00');"
            "CREATE TABLE invite (token_hash TEXT PRIMARY KEY, admin INTEGER NOT NULL DEFAULT 0, "
            "max_uses INTEGER NOT NULL, uses INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL, "
            "created_by INTEGER, created TEXT);"
        )
    db.close()
    store = Store(path)
    with store.db() as conn:
        assert conn.execute("SELECT rp_id FROM passkey").fetchone()[0] == ""
        assert "account" in {r[1] for r in conn.execute("PRAGMA table_info(invite)")}
    assert store.members()[0]["domains"] == []


def test_the_app_lives_on_a_subdomain_of_its_passkey_domain(store, moving):
    """app.pauta.cc with passkeys for pauta.cc: acceptance (acc.pauta.cc) and the public site
    (www.pauta.cc) sit under the same domain and could ask a browser for a pauta.cc passkey,
    but production only accepts its own origin."""
    assert moving.home == NEW and moving.home_host == "app.pauta.cc"
    assert moving.rp_for(NEW) == "pauta.cc"
    acc, key = join_old(moving)
    token, _ = moving.create_move(acc["id"])
    opts = moving.register_options(move=token, rp_id="pauta.cc")
    sibling = SoftPasskey("pauta.cc", "https://acc.pauta.cc")
    with pytest.raises(AuthError, match="não aceita"):
        moving.register_verify(opts["flow"], sibling.create(opts["options"]))
    moved = move(moving, token, SoftPasskey("pauta.cc", NEW))
    assert moved["id"] == acc["id"]
    # with only the apex allowed (as 1.6.0 ran), the apex is home
    apex = Auth(store, enabled=True, rp_id="pauta.cc", origins=["https://pauta.cc"])
    assert apex.home == "https://pauta.cc" and apex.home_host == "pauta.cc"
