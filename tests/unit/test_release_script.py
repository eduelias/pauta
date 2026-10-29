"""scripts/release.py: notes extraction, tag checks and the version bump."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release", Path(__file__).resolve().parents[2] / "scripts" / "release.py"
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

### Added

- Something new.

## [1.0.0] - 2026-10-28

### Added

- The first one.

[Unreleased]: https://github.com/eduelias/pauta/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/eduelias/pauta/releases/tag/v1.0.0
"""
PYPROJECT = '[project]\nname = "pauta"\nversion = "1.0.0"\n'


def test_notes_are_one_section_without_link_refs():
    assert release.notes(CHANGELOG, "1.0.0") == "### Added\n\n- The first one.\n"
    with pytest.raises(release.ReleaseError):
        release.notes(CHANGELOG, "9.9.9")


def test_check_tag():
    assert release.check_tag("v1.0.0", PYPROJECT, CHANGELOG) == "1.0.0"
    for tag in ("1.0.0", "v1.0", "v1.0.0-rc1", "v1.1.0"):
        with pytest.raises(release.ReleaseError):
            release.check_tag(tag, PYPROJECT, CHANGELOG)


def test_bump_moves_unreleased_into_the_new_version():
    changelog, pyproject = release.bump(CHANGELOG, PYPROJECT, "1.1.0", "2026-11-01")
    assert 'version = "1.1.0"' in pyproject
    assert release.notes(changelog, "1.1.0") == "### Added\n\n- Something new.\n"
    assert release.sections(changelog)["Unreleased"] == ""
    assert release.notes(changelog, "1.0.0") == "### Added\n\n- The first one.\n"
    assert "## [1.1.0] - 2026-11-01" in changelog
    assert "[Unreleased]: https://github.com/eduelias/pauta/compare/v1.1.0...HEAD" in changelog
    assert "[1.1.0]: https://github.com/eduelias/pauta/compare/v1.0.0...v1.1.0" in changelog


def test_first_release_links_to_its_tag():
    first = CHANGELOG.split("## [1.0.0]")[0].replace(
        "[Unreleased]: https://github.com/eduelias/pauta/compare/v1.0.0...HEAD", ""
    )
    pyproject = PYPROJECT.replace("1.0.0", "0.1.0")
    changelog, _ = release.bump(first + "\n", pyproject, "1.0.0", "2026-10-28")
    assert "[1.0.0]: https://github.com/eduelias/pauta/releases/tag/v1.0.0" in changelog


@pytest.mark.parametrize(
    ("version", "why"),
    [("1.0", "X.Y.Z"), ("1.0.0", "not newer"), ("0.9.0", "not newer")],
)
def test_bump_refuses(version, why):
    with pytest.raises(release.ReleaseError, match=why):
        release.bump(CHANGELOG, PYPROJECT, version, "2026-11-01")


def test_bump_needs_unreleased_notes():
    empty = CHANGELOG.replace("### Added\n\n- Something new.\n\n", "", 1)
    with pytest.raises(release.ReleaseError, match="nothing under"):
        release.bump(empty, PYPROJECT, "1.1.0", "2026-11-01")


def test_the_real_changelog_is_well_formed():
    root = Path(__file__).resolve().parents[2]
    text = (root / "CHANGELOG.md").read_text()
    found = release.sections(text)
    assert next(iter(found)) == "Unreleased"
    version = release.project_version((root / "pyproject.toml").read_text())
    assert version in found or found["Unreleased"], "describe the changes under Unreleased"


def _log(*rows):
    return "\n".join("\0".join(r) for r in rows) + "\n"


def test_outside_commits_lists_what_isnt_the_owners():
    log = _log(
        ("a1", "du7@msn.com", "du7@msn.com", "Eduardo", "Release 1.2.3"),
        ("b2", "eduardo@du7.dev", "noreply@github.com", "Eduardo", "Merge #9"),
        ("c3", "nato@example.com", "nato@example.com", "Nato", "Filtro de clientes"),
        ("d4", "nato@example.com", "noreply@github.com", "Nato", "Merge pull request #12"),
        # the owner's name and e-mail, committed by someone else
        ("e5", "du7@msn.com", "nato@example.com", "Eduardo", "Rebased by Nato"),
    )
    assert release.outside_commits(log) == [
        "c3 Nato <nato@example.com>: Filtro de clientes",
        "d4 Nato <nato@example.com>: Merge pull request #12",
        "e5 Eduardo <du7@msn.com>: Rebased by Nato",
    ]
    assert release.outside_commits("") == []


def test_confirm_outside(capsys):
    release.confirm_outside([], "1.3.0", ask=lambda _: pytest.fail("asked for nothing"))
    release.confirm_outside(["c3 Nato: x"], "1.3.0", ask=lambda _: " 1.3.0\n")
    assert "c3 Nato: x" in capsys.readouterr().out
    with pytest.raises(release.ReleaseError, match="not confirmed"):
        release.confirm_outside(["c3 Nato: x"], "1.3.0", ask=lambda _: "y")
