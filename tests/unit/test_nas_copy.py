"""deploy/pauta-nas-copy: what the NAS copy may read, write and delete."""

import importlib.machinery
import importlib.util
import os
import time
from pathlib import Path

import pytest

loader = importlib.machinery.SourceFileLoader(
    "nas_copy", str(Path(__file__).resolve().parents[2] / "deploy" / "pauta-nas-copy")
)
spec = importlib.util.spec_from_loader("nas_copy", loader)
nas = importlib.util.module_from_spec(spec)
loader.exec_module(nas)

ME = os.getuid()


def backup(d: Path, stamp: str, age_days: float = 0, body: bytes = b"db") -> Path:
    f = d / f"pauta-{stamp}.db"
    f.write_bytes(body)
    t = time.time() - age_days * 86400
    os.utime(f, (t, t))
    return f


@pytest.fixture
def dirs(tmp_path):
    src, dest = tmp_path / "backups", tmp_path / "nas"
    src.mkdir()
    dest.mkdir()
    return src, dest


def test_copies_the_newest_backup(dirs):
    src, dest = dirs
    backup(src, "20261027-034000", age_days=2, body=b"old")
    backup(src, "20261029-034000", body=b"new")
    name = nas.newest(str(src), ME)
    assert name == "pauta-20261029-034000.db"
    out = nas.copy(str(src), name, str(dest), ME)
    assert Path(out).read_bytes() == b"new"
    assert [p.name for p in dest.iterdir()] == [name]  # no .part left behind


def test_links_fifos_strangers_and_other_names_are_never_picked(dirs, tmp_path):
    src, _ = dirs
    secret = tmp_path / "shadow"
    secret.write_text("root:secret")
    backup(src, "20261027-034000", age_days=3)
    (src / "pauta-20261029-034000.db").symlink_to(secret)  # newer, but a link
    os.mkfifo(src / "pauta-20261030-034000.db")  # newer, but a FIFO
    (src / "notes.db").write_text("x")  # not a backup name
    assert nas.newest(str(src), ME) == "pauta-20261027-034000.db"
    assert nas.newest(str(src), ME + 1) is None  # nothing owned by `pauta`


def test_a_link_swapped_in_after_the_check_is_refused(dirs, tmp_path):
    src, dest = dirs
    secret = tmp_path / "shadow"
    secret.write_text("root:secret")
    (src / "pauta-20261029-034000.db").symlink_to(secret)
    with pytest.raises(OSError):  # O_NOFOLLOW
        nas.copy(str(src), "pauta-20261029-034000.db", str(dest), ME)
    backup(src, "20261028-034000")
    with pytest.raises(SystemExit, match="not a regular file owned by pauta"):
        nas.copy(str(src), "pauta-20261028-034000.db", str(dest), ME + 1)
    assert list(dest.iterdir()) == []


def test_prune_only_removes_old_backup_copies(dirs, tmp_path):
    _, dest = dirs
    backup(dest, "20260901-034000", age_days=40)
    backup(dest, "20261028-034000", age_days=1)
    (dest / "keep-me.txt").write_text("not ours")
    old_link = dest / "pauta-20260801-034000.db"
    old_link.symlink_to(tmp_path / "elsewhere")
    os.utime(old_link, (0, 0), follow_symlinks=False)
    assert nas.prune(str(dest), 30, time.time()) == ["pauta-20260901-034000.db"]
    assert sorted(p.name for p in dest.iterdir()) == [
        "keep-me.txt",
        "pauta-20260801-034000.db",
        "pauta-20261028-034000.db",
    ]
