#!/usr/bin/env python3
"""Release helper: cut a version, and pull its notes out of CHANGELOG.md.

    scripts/release.py cut 1.2.0 [--push]   # move Unreleased to 1.2.0, bump, commit, tag
    scripts/release.py notes 1.2.0           # that version's section, for the GitHub release
    scripts/release.py check-tag v1.2.0      # the tag, pyproject and CHANGELOG agree (CI)

The CHANGELOG follows Keep a Changelog: `## [Unreleased]` on top, then `## [X.Y.Z] - date`.
Pushing the tag is what publishes: the release workflow tests, builds, writes the GitHub
release from these notes and deploys it to du7.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
HEADING = re.compile(r"^## \[(?P<v>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$", re.M)
REPO_URL = "https://github.com/eduelias/pauta"
LOCK = ROOT / "uv.lock"
# Commits by anyone else are listed before a release, for the owner to confirm: a release
# deploys to du7. Git identities are not authentication; this is a reminder to look, not a
# gate (the gates are the rulesets and the du7 job guard, decision 2). The owner's
# addresses: their GitHub noreply one, `git config user.email`, and any `git config --add
# pauta.ownerEmail ...` (kept in the owner's git config, not in this public file).
OWNER_NOREPLY = "12836540+eduelias@users.noreply.github.com"
GITHUB_COMMITTER = "noreply@github.com"  # merges and edits made on github.com


class ReleaseError(Exception):
    pass


def sections(text: str) -> dict[str, str]:
    """{version: body} for every `## [...]` heading, in file order."""
    marks = list(HEADING.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end() : end]
        body = re.split(r"^\[[^\]]+\]: ", body, maxsplit=1, flags=re.M)[0]  # link refs
        out[m["v"]] = body.strip()
    return out


def notes(text: str, version: str) -> str:
    body = sections(text).get(version)
    if not body:
        raise ReleaseError(f"CHANGELOG.md has no notes for {version}")
    return body + "\n"


def project_version(pyproject: str) -> str:
    m = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    if not m:
        raise ReleaseError("no version in pyproject.toml")
    return m[1]


def check_tag(tag: str, pyproject: str, changelog: str) -> str:
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ReleaseError(f"tag {tag!r} is not vX.Y.Z")
    version = tag[1:]
    if project_version(pyproject) != version:
        raise ReleaseError(f"tag {tag} but pyproject.toml says {project_version(pyproject)}")
    notes(changelog, version)
    return version


def bump(changelog: str, pyproject: str, version: str, today: str) -> tuple[str, str]:
    """The new CHANGELOG and pyproject texts for `version`."""
    if not VERSION_RE.match(version):
        raise ReleaseError(f"{version!r} is not X.Y.Z")
    current = project_version(pyproject)
    as_tuple = lambda v: tuple(int(x) for x in v.split("."))  # noqa: E731
    if as_tuple(version) <= as_tuple(current):
        raise ReleaseError(f"{version} is not newer than {current}")
    found = sections(changelog)
    if version in found:
        raise ReleaseError(f"CHANGELOG.md already has {version}")
    if not found.get("Unreleased"):
        raise ReleaseError("nothing under ## [Unreleased] to release")
    changelog = changelog.replace(
        "## [Unreleased]", f"## [Unreleased]\n\n## [{version}] - {today}", 1
    )
    prev = next((v for v in found if v != "Unreleased"), None)
    link = f"[{version}]: {REPO_URL}/" + (
        f"compare/v{prev}...v{version}" if prev else f"releases/tag/v{version}"
    )
    unreleased = f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD"
    changelog = re.sub(r"^\[Unreleased\]: .*$", unreleased, changelog, count=1, flags=re.M)
    if unreleased not in changelog:
        changelog = changelog.rstrip("\n") + f"\n\n{unreleased}\n"
    changelog = changelog.replace(unreleased, f"{unreleased}\n{link}", 1)
    pyproject = re.sub(
        r'^version = "[^"]+"', f'version = "{version}"', pyproject, count=1, flags=re.M
    )
    return changelog, pyproject


def bump_lock(lock: str, version: str) -> str:
    """uv.lock with pauta's own version set to `version`, edited in place: running uv here
    would read uv.toml and indexes from the checkout, which may not be the owner's."""
    new, n = re.subn(
        r'(\[\[package\]\]\nname = "pauta"\nversion = ")[^"]+(")', rf"\g<1>{version}\2", lock
    )
    if n != 1:
        raise ReleaseError("uv.lock has no single pauta package entry")
    return new


def owner_emails() -> set[str]:
    found = {OWNER_NOREPLY}
    for args in (["config", "user.email"], ["config", "--get-all", "pauta.ownerEmail"]):
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        found |= {line.strip() for line in r.stdout.splitlines() if line.strip()}
    return found


def outside_commits(log: str, owners: set[str] | None = None) -> list[str]:
    """The commits in `git log --format=%h%x00%ae%x00%ce%x00%an%x00%s` output that aren't
    entirely the owner's (authored and committed by them, or merged by them on GitHub)."""
    owners = owner_emails() if owners is None else owners
    out = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, author, committer, name, subject = line.split("\0", 4)
        if author not in owners or committer not in owners | {GITHUB_COMMITTER}:
            out.append(f"{sha} {name} <{author}>: {subject}")
    return out


def confirm_outside(outside: list[str], version: str, ask=input) -> None:
    """Show what others wrote that this release ships; go on only if the version is typed."""
    if not outside:
        return
    print(f"{version} ships {len(outside)} commit(s) not entirely yours (read them first):")
    for line in outside:
        print(f"  {line}")
    if ask(f"Type {version} to release them: ").strip() != version:
        raise ReleaseError("not confirmed; nothing changed")


def ci_passed(sha: str) -> None:
    """CI ran on this exact commit of main and passed (needs `gh`, signed in)."""
    r = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPO_URL.removeprefix("https://github.com/"),
            "--workflow",
            "CI",
            "--commit",
            sha,
            "--json",
            "conclusion",
            "--jq",
            ".[].conclusion",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise ReleaseError(f"can't ask GitHub about CI on {sha[:7]}: {r.stderr.strip()}")
    if "success" not in r.stdout.split():
        raise ReleaseError(f"CI hasn't passed on {sha[:7]} (origin/main) yet")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def cmd_cut(version: str, push: bool) -> None:
    if git("status", "--porcelain"):
        raise ReleaseError("the working tree has changes; commit or stash them first")
    if git("rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise ReleaseError("release from main")
    git("fetch", "-q", "origin", "main")
    if git("rev-parse", "HEAD") != git("rev-parse", "origin/main"):
        raise ReleaseError("main is not the same as origin/main; pull or push first")
    if (ROOT / "uv.toml").exists():
        raise ReleaseError("uv.toml exists: uv would take its indexes; remove it or review it")
    ci_passed(git("rev-parse", "origin/main"))
    git("fetch", "-q", "--tags", "origin")
    last = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0", "--match", "v*", "origin/main"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout.strip()
    span = f"{last}..origin/main" if last else "origin/main"
    confirm_outside(
        outside_commits(git("log", "--format=%h%x00%ae%x00%ce%x00%an%x00%s", span)), version
    )
    changelog, pyproject = bump(
        CHANGELOG.read_text(), PYPROJECT.read_text(), version, date.today().isoformat()
    )
    CHANGELOG.write_text(changelog)
    PYPROJECT.write_text(pyproject)
    LOCK.write_text(bump_lock(LOCK.read_text(), version))
    git("add", "CHANGELOG.md", "pyproject.toml", "uv.lock")
    git("commit", "-q", "-m", f"Release {version}")
    git("tag", "-a", f"v{version}", "-m", f"Pauta {version}\n\n{notes(changelog, version)}")
    print(f"tagged v{version}")
    if push:
        git("push", "-q", "--atomic", "origin", "main", f"v{version}")
        print(f"pushed; follow it at {REPO_URL}/actions")
    else:
        print(f"publish with: git push --atomic origin main v{version}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="release.py", description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut")
    c.add_argument("version")
    c.add_argument("--push", action="store_true")
    sub.add_parser("notes").add_argument("version")
    sub.add_parser("check-tag").add_argument("tag")
    args = p.parse_args(argv)
    try:
        if args.cmd == "cut":
            cmd_cut(args.version, args.push)
        elif args.cmd == "notes":
            sys.stdout.write(notes(CHANGELOG.read_text(), args.version))
        else:
            print(check_tag(args.tag, PYPROJECT.read_text(), CHANGELOG.read_text()))
    except (ReleaseError, subprocess.CalledProcessError) as e:
        print(f"release: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
