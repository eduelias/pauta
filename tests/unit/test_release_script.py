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


def test_an_earlier_version_without_a_link_gets_no_compare_link():
    # Versions released from the old repository have no tag here, so no link line either.
    unlinked = CHANGELOG.split("[Unreleased]:")[0]
    changelog, _ = release.bump(unlinked, PYPROJECT, "1.1.0", "2026-11-01")
    assert "[1.1.0]: https://github.com/eduelias/pauta/releases/tag/v1.1.0" in changelog
    assert "compare/v1.0.0" not in changelog


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
