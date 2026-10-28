"""scripts/agent_guard.py: what coding-agent PRs may not change."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("agent_guard", ROOT / "scripts" / "agent_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

PYPROJECT = (ROOT / "pyproject.toml").read_text()


def pr(branch="feat/x", labels=(), number=8):
    return {
        "number": number,
        "head": {"ref": branch, "sha": "h"},
        "base": {"sha": "b"},
        "labels": [{"name": n} for n in labels],
    }


def files(*names, renamed_from=None):
    out = [{"filename": n} for n in names]
    if renamed_from:
        out[-1]["previous_filename"] = renamed_from
    return out


def test_what_makes_an_agent_pr():
    assert guard.is_agent_pr(pr("agent/pedido-12"))
    assert guard.is_agent_pr(pr("feat/x", labels=["agent"]))
    assert not guard.is_agent_pr(pr("feat/agent-ish", labels=["pedido"]))


def test_people_may_change_anything():
    assert guard.check(pr(), files(".github/workflows/ci.yml", "src/pauta/auth.py"), None) == []


def test_agent_pr_inside_its_lane_passes():
    ok = files(
        "src/pauta/db.py", "src/pauta/static/app.js", "tests/unit/test_store.py", "CHANGELOG.md"
    )
    assert guard.check(pr("agent/pedido-12"), ok, None) == []


def test_forbidden_paths():
    bad = files(
        ".github/workflows/ci.yml",
        "deploy/pauta-deploy",
        "src/pauta/auth.py",
        "src/pauta/ratelimit.py",
        "scripts/release.py",
        "uv.lock",
        "src/pauta/db.py",
    )
    assert guard.forbidden_paths(bad) == [
        ".github/workflows/ci.yml",
        "deploy/pauta-deploy",
        "scripts/release.py",
        "src/pauta/auth.py",
        "src/pauta/ratelimit.py",
        "uv.lock",
    ]
    # moving a protected file out of the way counts too
    assert guard.forbidden_paths(files("src/pauta/login.py", renamed_from="src/pauta/auth.py")) == [
        "src/pauta/auth.py"
    ]
    problems = guard.check(pr(labels=["agent"]), files("scripts/agent_guard.py"), None)
    assert problems == ["scripts/agent_guard.py: agent PRs may not change this"]


def test_pyproject_unchanged_and_harmless_edits_pass():
    assert guard.pyproject_problems(PYPROJECT, PYPROJECT) == []
    edited = PYPROJECT.replace("fail_under = 90", "fail_under = 95")
    assert guard.pyproject_problems(PYPROJECT, edited) == []


def test_pyproject_gate_and_dependencies():
    lowered = PYPROJECT.replace("fail_under = 90", "fail_under = 50")
    assert guard.pyproject_problems(PYPROJECT, lowered) == [
        "pyproject.toml: coverage fail_under lowered from 90 to 50"
    ]
    no_gate = PYPROJECT.replace("fail_under = 90\n", "")
    assert "lowered from 90 to 0" in guard.pyproject_problems(PYPROJECT, no_gate)[0]
    narrowed = PYPROJECT.replace('source = ["pauta"]', 'source = ["pauta.db"]')
    assert guard.pyproject_problems(PYPROJECT, narrowed) == [
        "pyproject.toml: tool.coverage.run changed"
    ]
    omitted = PYPROJECT.replace("skip_covered = true", 'skip_covered = true\nomit = ["*/x.py"]')
    assert guard.pyproject_problems(PYPROJECT, omitted) == [
        "pyproject.toml: tool.coverage.report.omit changed"
    ]
    dep = PYPROJECT.replace("dependencies = [", 'dependencies = [\n    "requests",', 1)
    assert guard.pyproject_problems(PYPROJECT, dep) == [
        "pyproject.toml: project.dependencies changed"
    ]


def _event(tmp_path, the_pr):
    path = tmp_path / "event.json"
    path.write_text(json.dumps({"pull_request": the_pr}))
    return str(path)


def test_main(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPOSITORY", "eduelias/pauta")
    pr_files = files("src/pauta/db.py", "pyproject.toml")
    lowered = PYPROJECT.replace("fail_under = 90", "fail_under = 80")
    seen = []

    def fake_get(url, raw=False):
        seen.append(url)
        if "/files" in url:
            return pr_files
        return PYPROJECT if url.endswith("=b") else lowered

    monkeypatch.setattr(guard, "_get", fake_get)
    assert guard.main(["x", _event(tmp_path, pr())]) == 0  # not an agent PR
    assert seen == []
    assert guard.main(["x", _event(tmp_path, pr("agent/pedido-12"))]) == 1
    out = capsys.readouterr().out
    assert "::error::pyproject.toml: coverage fail_under lowered from 90 to 80" in out
    assert seen[0].endswith("/repos/eduelias/pauta/pulls/8/files?per_page=100&page=1")
    pr_files[:] = files("src/pauta/db.py")
    assert guard.main(["x", _event(tmp_path, pr("agent/pedido-12"))]) == 0
    assert "1 file(s), all allowed" in capsys.readouterr().out
    assert guard.main(["x"]) == 2


def test_files_are_paged(monkeypatch):
    pages = {1: [{"filename": f"f{i}"} for i in range(100)], 2: [{"filename": "last"}]}
    monkeypatch.setattr(guard, "_get", lambda url, raw=False: pages[int(url.split("=")[-1])])
    assert len(guard._files("eduelias/pauta", 8)) == 101
