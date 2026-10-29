"""deploy/runner-job-guard and pauta-deploy's checks: what may reach du7, and how."""

import hashlib
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
WF = "eduelias/pauta/.github/workflows"
RELEASE = f"{WF}/release.yml@refs/tags/v1.2.3"


def guard(**env):
    base = {
        "GITHUB_REPOSITORY": "eduelias/pauta",
        "GITHUB_JOB": "du7",
        "GITHUB_ACTOR": "eduelias",
        "GITHUB_TRIGGERING_ACTOR": "eduelias",
        "PATH": os.environ["PATH"],
    }
    base.update(env)
    return subprocess.run(
        ["bash", str(DEPLOY / "runner-job-guard")], env=base, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    ("ref", "event"),
    [
        (RELEASE, "push"),
        (f"{WF}/release.yml@refs/tags/v10.0.12", "push"),
        (f"{WF}/deploy.yml@refs/heads/main", "workflow_dispatch"),
    ],
)
def test_guard_allows_the_owners_deploy(ref, event):
    r = guard(GITHUB_WORKFLOW_REF=ref, GITHUB_EVENT_NAME=event)
    assert r.returncode == 0, r.stderr
    assert "may deploy" in r.stdout


@pytest.mark.parametrize(
    ("env", "why"),
    [
        # a collaborator starting the deploy, or re-running the owner's
        ({"GITHUB_ACTOR": "cousin", "GITHUB_TRIGGERING_ACTOR": "cousin"}, "only eduelias's runs"),
        ({"GITHUB_TRIGGERING_ACTOR": "cousin"}, "only eduelias may (re-)run"),
        ({"GITHUB_TRIGGERING_ACTOR": ""}, "only eduelias may (re-)run"),
        # a branch or a pull request, even with a copy of the real workflow
        ({"GITHUB_WORKFLOW_REF": f"{WF}/deploy.yml@refs/heads/x"}, "run by hand on main"),
        (
            {
                "GITHUB_WORKFLOW_REF": f"{WF}/ci.yml@refs/pull/9/merge",
                "GITHUB_EVENT_NAME": "pull_request",
            },
            "release tag",
        ),
        ({"GITHUB_WORKFLOW_REF": f"{WF}/release.yml@refs/heads/main"}, "release tag"),
        ({"GITHUB_WORKFLOW_REF": f"{WF}/release.yml@refs/tags/v1.2.3-rc1"}, "release tag"),
        ({"GITHUB_WORKFLOW_REF": f"{WF}/evil.yml@refs/tags/v1.2.3"}, "release tag"),
        # the right workflow and ref, started some other way
        (
            {
                "GITHUB_WORKFLOW_REF": f"{WF}/deploy.yml@refs/heads/main",
                "GITHUB_EVENT_NAME": "push",
            },
            "by hand",
        ),
        ({"GITHUB_EVENT_NAME": "workflow_dispatch"}, "release tag"),
        # any other job, or another repository (a fork's run)
        ({"GITHUB_JOB": "fetch"}, "only the deploy job"),
        ({"GITHUB_REPOSITORY": "someone/pauta"}, "not eduelias/pauta"),
        (
            {"GITHUB_WORKFLOW_REF": "someone/pauta/.github/workflows/release.yml@refs/tags/v1.2.3"},
            "release tag",
        ),
        ({"GITHUB_WORKFLOW_REF": ""}, "release tag"),
    ],
)
def test_guard_refuses_everything_else(env, why):
    full = {"GITHUB_WORKFLOW_REF": RELEASE, "GITHUB_EVENT_NAME": "push"}
    full.update(env)
    r = guard(**full)
    assert r.returncode == 1
    assert "refusing this job on du7" in r.stderr and why in r.stderr


def make_wheel(path: Path, name="pauta", version="1.2.3"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"{name}-{version}.dist-info/METADATA", f"Name: {name}\nVersion: {version}\n")
        z.writestr("pauta/__init__.py", "")
    return path


@pytest.fixture
def build(tmp_path):
    """What the release run built: a wheel, a lockfile and their sha256s; plus /opt/pauta."""
    out = tmp_path / "bundle"
    out.mkdir()
    wheel = make_wheel(out / "pauta-1.2.3-py3-none-any.whl")
    lock = out / "requirements.lock"
    lock.write_text("webauthn==2.7.0 --hash=sha256:abc\n")
    root = tmp_path / "opt-pauta"
    root.mkdir()
    sums = {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in (wheel, lock)}
    return {"wheel": wheel, "lock": lock, "root": root, "sums": sums, "tmp": tmp_path}


def deploy_fn(call: str, b, cwd=None, **env):
    """Source pauta-deploy (unprivileged: copies owned by the caller, ROOT in tmp) and run."""
    script = f'source "{DEPLOY / "pauta-deploy"}"; STAGED_OWNER=(); ROOT="$ROOT_DIR"; {call}'
    full = {"ROOT_DIR": str(b["root"]), "PATH": os.environ["PATH"], **env}
    return subprocess.run(["bash", "-c", script], env=full, capture_output=True, text=True, cwd=cwd)


def stage(b, wheel_sha=None, lock_sha=None, version="1.2.3"):
    return deploy_fn(
        'stage "$V" "$W" "$L" "$WS" "$LS"',
        b,
        V=version,
        W=str(b["wheel"]),
        L=str(b["lock"]),
        WS=wheel_sha or b["sums"][b["wheel"]],
        LS=lock_sha or b["sums"][b["lock"]],
    )


def test_the_built_files_are_staged_as_copies(build):
    r = stage(build)
    assert r.returncode == 0, r.stderr
    staged = Path(r.stdout.strip())
    assert staged.parent == build["root"] and staged.name.startswith(".incoming.")
    assert (staged / "pauta-1.2.3-py3-none-any.whl").read_bytes() == build["wheel"].read_bytes()
    assert (staged / "requirements.lock").read_text() == build["lock"].read_text()
    # changing the caller's file afterwards changes nothing that gets installed
    build["wheel"].write_bytes(b"swapped after the check")
    assert (staged / "pauta-1.2.3-py3-none-any.whl").read_bytes() != b"swapped after the check"


def test_a_swapped_wheel_is_refused(build):
    make_wheel(build["wheel"], version="1.2.3")  # same name and version, other bytes
    with zipfile.ZipFile(build["wheel"], "a") as z:
        z.writestr("pauta/payload.py", "import os")
    r = stage(build)
    assert r.returncode == 1
    assert "the wheel is not the one the release built" in r.stderr
    assert not list(build["root"].glob(".incoming.*"))  # nothing left behind


def test_a_swapped_lockfile_is_refused(build):
    build["lock"].write_text("evil==1.0\n")
    r = stage(build)
    assert r.returncode == 1 and "requirements.lock is not the one the release built" in r.stderr


def test_the_version_comes_from_the_metadata(build):
    other = make_wheel(build["tmp"] / "x.whl", version="9.9.9")
    build["wheel"].write_bytes(other.read_bytes())
    sha = hashlib.sha256(other.read_bytes()).hexdigest()
    r = stage(build, wheel_sha=sha)
    assert r.returncode == 1 and "the wheel says version '9.9.9', expected '1.2.3'" in r.stderr
    imposter = make_wheel(build["tmp"] / "y.whl", name="notpauta")
    build["wheel"].write_bytes(imposter.read_bytes())
    r = stage(build, wheel_sha=hashlib.sha256(imposter.read_bytes()).hexdigest())
    assert r.returncode == 1 and "can't read the wheel's metadata" in r.stderr
    assert "'notpauta', not pauta" in r.stderr


def test_python_never_imports_from_the_callers_directory(build, tmp_path):
    trap = tmp_path / "trap"
    trap.mkdir()
    marker = tmp_path / "ran"
    (trap / "zipfile.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    (trap / "json.py").write_text(f"open({str(marker)!r}, 'w').write('x')\n")
    r = deploy_fn('wheel_version "$W"', build, cwd=trap, W=str(build["wheel"]))
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1.2.3"
    assert not marker.exists()


def test_capabilities_and_sourcing():
    r = subprocess.run(
        ["bash", "-c", f'source "{DEPLOY / "pauta-deploy"}" && echo sourced'],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and r.stdout.strip() == "sourced"
    text = (DEPLOY / "pauta-deploy").read_text()
    assert 'echo "pinned activate"' in text  # what deploy.yml checks for
    assert "/usr/bin/python3 -I" in text and '"$PYTHON"' not in text
