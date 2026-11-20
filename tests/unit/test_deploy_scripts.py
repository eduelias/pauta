"""deploy/runner-job-guard and pauta-deploy: what may reach du7, the switch, the rollback."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
WF = "eduelias/pauta/.github/workflows"
# readlink -e, mv -T: GNU/Linux, like du7 and CI
linux = pytest.mark.skipif(sys.platform != "linux", reason="GNU coreutils (du7, CI)")


def guard(**env):
    base = {
        "GITHUB_REPOSITORY": "eduelias/pauta",
        "GITHUB_JOB": "du7",
        "GITHUB_ACTOR": "someone",
        "GITHUB_TRIGGERING_ACTOR": "someone",
        "PATH": os.environ["PATH"],
    }
    base.update(env)
    return subprocess.run(
        ["bash", str(DEPLOY / "runner-job-guard")], env=base, capture_output=True, text=True
    )


@pytest.mark.parametrize(
    ("ref", "event"),
    [
        (f"{WF}/release.yml@refs/tags/v1.2.3", "push"),
        (f"{WF}/release.yml@refs/tags/v10.0.12", "push"),
    ],
)
def test_guard_allows_the_deploy(ref, event):
    r = guard(
        GITHUB_WORKFLOW_REF=ref,
        GITHUB_EVENT_NAME=event,
        GITHUB_ACTOR="eduelias",
        GITHUB_TRIGGERING_ACTOR="eduelias",
    )
    assert r.returncode == 0, r.stderr
    assert "may deploy" in r.stdout


@pytest.mark.parametrize(
    ("env", "why"),
    [
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
        (
            {
                "GITHUB_WORKFLOW_REF": f"{WF}/release.yml@refs/tags/v1.2.3",
                "GITHUB_EVENT_NAME": "workflow_dispatch",
            },
            "release tag",
        ),
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
    full = {
        "GITHUB_WORKFLOW_REF": f"{WF}/release.yml@refs/tags/v1.2.3",
        "GITHUB_EVENT_NAME": "push",
    }
    full.update(env)
    r = guard(**full)
    assert r.returncode == 1
    assert "refusing this job on du7" in r.stderr and why in r.stderr


BY_HAND = f"{WF}/deploy.yml@refs/heads/main"
BRANCH = f"{WF}/deploy-branch.yml@refs/heads/main"


@pytest.mark.parametrize("ref", [BY_HAND, BRANCH])
def test_guard_lets_the_owner_deploy_by_hand(ref):
    r = guard(
        GITHUB_WORKFLOW_REF=ref,
        GITHUB_EVENT_NAME="workflow_dispatch",
        GITHUB_ACTOR="eduelias",
        GITHUB_TRIGGERING_ACTOR="eduelias",
    )
    assert r.returncode == 0, r.stderr
    assert "may deploy" in r.stdout


@pytest.mark.parametrize(
    "env", [{}, {"GITHUB_ACTOR": "eduelias"}, {"GITHUB_TRIGGERING_ACTOR": "eduelias"}]
)
@pytest.mark.parametrize(
    ("ref", "event"),
    [
        (BY_HAND, "workflow_dispatch"),
        (BRANCH, "workflow_dispatch"),
        (f"{WF}/release.yml@refs/tags/v1.2.3", "push"),  # an old release's run, run again
    ],
)
def test_guard_refuses_a_deploy_from_anyone_else(env, ref, event):
    # started, or run again, by someone who is not the owner
    r = guard(GITHUB_WORKFLOW_REF=ref, GITHUB_EVENT_NAME=event, **env)
    assert r.returncode == 1
    assert "refusing this job on du7: only eduelias may deploy" in r.stderr


@pytest.mark.parametrize(
    ("env", "why"),
    [
        # the owner, but the workflow from a branch (where anyone could have edited it)
        (
            {
                "GITHUB_ACTOR": "eduelias",
                "GITHUB_TRIGGERING_ACTOR": "eduelias",
                "GITHUB_WORKFLOW_REF": f"{WF}/deploy-branch.yml@refs/heads/feat/x",
            },
            "run by hand on main",
        ),
        # the owner, but not by hand
        (
            {
                "GITHUB_ACTOR": "eduelias",
                "GITHUB_TRIGGERING_ACTOR": "eduelias",
                "GITHUB_EVENT_NAME": "push",
            },
            "run by hand on main",
        ),
        # the owner, but another job of the workflow
        (
            {
                "GITHUB_ACTOR": "eduelias",
                "GITHUB_TRIGGERING_ACTOR": "eduelias",
                "GITHUB_JOB": "build",
            },
            "only the deploy job",
        ),
    ],
)
def test_guard_refuses_other_branch_deploys(env, why):
    full = {"GITHUB_WORKFLOW_REF": BRANCH, "GITHUB_EVENT_NAME": "workflow_dispatch"}
    full.update(env)
    r = guard(**full)
    assert r.returncode == 1
    assert "refusing this job on du7" in r.stderr and why in r.stderr


@pytest.fixture
def release(tmp_path):
    wheel = tmp_path / "pauta-1.2.3-py3-none-any.whl"
    lock = tmp_path / "requirements.lock"
    wheel.write_bytes(b"the published wheel")
    lock.write_text("webauthn==2.7.0 --hash=sha256:abc\n")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text(
        "".join(f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.name}\n" for f in (wheel, lock))
        + f"{'0' * 64}  pauta-1.2.3.tar.gz\n"
    )
    return wheel, lock, sums


def verify(sums, wheel, lock):
    # fetch_sums is the only network call: swap it for the file
    script = (
        f'source "{DEPLOY / "pauta-deploy"}"; fetch_sums() {{ cat "$SUMS"; }}; '
        f'verify_release 1.2.3 "$WHEEL" "$LOCK"'
    )
    env = {"SUMS": str(sums), "WHEEL": str(wheel), "LOCK": str(lock), "PATH": os.environ["PATH"]}
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)


def test_published_files_pass(release):
    r = verify(release[2], release[0], release[1])
    assert r.returncode == 0, r.stderr
    assert "match the published v1.2.3" in r.stderr


def test_a_swapped_wheel_is_refused(release):
    wheel, lock, sums = release
    wheel.write_bytes(b"something a job built itself")
    r = verify(sums, wheel, lock)
    assert r.returncode == 1
    assert "pauta-1.2.3-py3-none-any.whl is not the published one" in r.stderr


def test_a_swapped_lockfile_is_refused(release):
    wheel, lock, sums = release
    lock.write_text("evil==1.0\n")
    r = verify(sums, wheel, lock)
    assert r.returncode == 1 and "requirements.lock is not the published one" in r.stderr


def test_missing_entry_or_release_is_refused(release, tmp_path):
    wheel, lock, sums = release
    sums.write_text(sums.read_text().splitlines()[1] + "\n")  # the lockfile's line only
    r = verify(sums, wheel, lock)
    assert r.returncode == 1 and "lists no pauta-1.2.3-py3-none-any.whl" in r.stderr
    r = verify(tmp_path / "missing", wheel, lock)
    assert r.returncode == 1 and "can't fetch SHA256SUMS of v1.2.3" in r.stderr


def test_sourcing_does_not_deploy():
    r = subprocess.run(
        ["bash", "-c", f'source "{DEPLOY / "pauta-deploy"}" && echo sourced'],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and r.stdout.strip() == "sourced"


def deploy(root, script, cwd=None, **env):
    """Source pauta-deploy with /opt/pauta in a temporary folder and stand-ins for root and
    the lock, then run `script`."""
    stubs = (
        f'source "{DEPLOY / "pauta-deploy"}"; ROOT="{root}"; RELEASES="{root}/releases"; '
        f'PYTHON="{sys.executable}"; id() {{ echo 0; }}; flock() {{ :; }}; '
    )
    full = {"PATH": os.environ["PATH"], **env}
    return subprocess.run(
        ["bash", "-c", stubs + script], env=full, cwd=cwd, capture_output=True, text=True
    )


def test_python_runs_isolated_and_from_the_root_directory(tmp_path):
    # a module of the same name in the caller's directory is never the one imported
    here = tmp_path / "here"
    here.mkdir()
    (here / "json.py").write_text("raise SystemExit('json.py of the current directory')\n")
    health = 'curl() { echo \'{"status": "ok", "version": "1.2.3"}\'; }; '
    r = deploy(tmp_path / "opt", health + "health_version", cwd=here)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "1.2.3"
    text = (DEPLOY / "pauta-deploy").read_text()
    assert text.count('"$PYTHON"') == text.count('"$PYTHON" -I ') > 0  # every call, not just this
    r = deploy(tmp_path / "opt", health + "main --status; pwd", cwd=here)
    assert r.returncode == 0, r.stderr
    assert "(healthz: 1.2.3)" in r.stdout
    assert r.stdout.splitlines()[-1] == "/"


def test_the_wheel_and_lockfile_are_read_once(release, tmp_path):
    wheel, lock, sums = release
    root = tmp_path / "opt"
    # an install_release stand-in: the caller's file changes after the check, and it shows
    # what it was handed. The files are named as deploy.yml names them, from its directory
    script = (
        'fetch_sums() { cat "$SUMS"; }; backup_db() { :; }; activate() { :; }; prune() { :; }; '
        f'install_release() {{ echo changed > "{wheel}"; ls -ld "${{2%/*}}" | cut -c1-10; '
        'echo "$2 $3"; cat "$2"; }; '
        f"main 1.2.3 {wheel.name} {lock.name}"
    )
    r = deploy(root, script, cwd=tmp_path, SUMS=str(sums))
    assert r.returncode == 0, r.stderr
    mode, paths, content = r.stdout.splitlines()
    assert mode == "drwx------"  # root only
    assert all(path.startswith(f"{root}/.incoming.") for path in paths.split())
    assert content == "the published wheel"
    assert not list(root.glob(".incoming.*"))  # gone when the deploy ends
    # and when it is refused (the caller's wheel is the changed one now)
    r = deploy(root, script, cwd=tmp_path, SUMS=str(sums))
    assert r.returncode == 1 and "is not the published one" in r.stderr
    assert not list(root.glob(".incoming.*"))


@pytest.fixture
def opt(tmp_path):
    """A fake /opt/pauta with two installed releases, 1.2.2 live."""
    root = tmp_path / "opt"
    for v in ("1.2.2", "1.2.3"):
        (root / "releases" / v).mkdir(parents=True)
        (root / "releases" / v / ".complete").write_text("")
    (root / "current").symlink_to(root / "releases" / "1.2.2")
    return root


def switch(root, script, healthy):
    # the unit and /healthz are stand-ins: health_version answers with the version `current`
    # points at, if that one is healthy
    stubs = (
        'systemctl() { echo "systemctl $*" >> "$ROOT/calls"; }; backup_db() { :; }; '
        "journalctl() { :; }; logger() { :; }; "
        'health_version() { v=$(basename "$(readlink -e "$ROOT/current")"); '
        'case " $HEALTHY " in *" $v "*) echo "$v";; *) echo "";; esac; }; '
    )
    return deploy(root, stubs + script, HEALTHY=healthy)


@linux
def test_a_healthy_release_goes_live(opt):
    r = switch(opt, "activate 1.2.3", "1.2.2 1.2.3")
    assert r.returncode == 0, r.stderr
    assert (opt / "current").resolve().name == "1.2.3"
    assert (opt / "previous").resolve().name == "1.2.2"
    assert "live 1.2.3 (was 1.2.2)" in (opt / "deploy.log").read_text()
    assert (opt / "calls").read_text() == "systemctl restart pauta\n"


@linux
def test_a_broken_release_rolls_back(opt):
    r = switch(opt, "activate 1.2.3", "1.2.2")
    assert r.returncode == 1
    assert (opt / "current").resolve().name == "1.2.2"
    assert not (opt / "previous").exists()
    assert "FAILED 1.2.3, rolled back to 1.2.2 (healthz: 1.2.2)" in (opt / "deploy.log").read_text()
    assert (opt / "calls").read_text() == "systemctl restart pauta\n" * 2


@linux
def test_rollback_goes_to_the_release_before(opt):
    r = switch(opt, "main --rollback", "1.2.2 1.2.3")
    assert r.returncode == 1 and "no previous release" in r.stderr
    assert switch(opt, "activate 1.2.3", "1.2.2 1.2.3").returncode == 0
    r = switch(opt, "main --rollback", "1.2.2 1.2.3")
    assert r.returncode == 0, r.stderr
    assert (opt / "current").resolve().name == "1.2.2"
    assert (opt / "previous").resolve().name == "1.2.3"
    assert "live 1.2.2 (was 1.2.3)" in (opt / "deploy.log").read_text()


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ("1.2.3", "usage"),
        ("--rollback now", "usage"),
        ("1.2 /x/pauta-1.2-py3-none-any.whl /x/requirements.lock", "bad version"),
        ("1.2.3 /x/pauta-9.9.9-py3-none-any.whl /x/requirements.lock", "unexpected wheel"),
        ("1.2.3 /x/pauta-1.2.3-py3-none-any.whl /x/other.lock", "unexpected lockfile"),
        ("1.2.3 /x/pauta-1.2.3-py3-none-any.whl /x/requirements.lock", "no wheel at"),
    ],
)
def test_main_refuses_bad_arguments(args, why, tmp_path):
    r = deploy(tmp_path / "opt", f"main {args}; echo reached")
    assert r.returncode == 1 and why in r.stderr
    assert "reached" not in r.stdout


@pytest.mark.parametrize("script", ["provision-du7.sh", "provision-branch-env.sh"])
def test_the_guard_is_installed_where_the_runner_will_run_it(script):
    # the runner fails every job when the hook's name doesn't end in .sh, .ps1 or .js
    text = (DEPLOY / script).read_text()
    hooks = [
        line.split("=", 2)[2].strip().strip('"')
        for line in text.splitlines()
        if "ACTIONS_RUNNER_HOOK_JOB_STARTED=" in line
    ]
    assert hooks == ["/usr/local/lib/pauta/runner-job-guard.sh"]
    assert 'runner-job-guard" /usr/local/lib/pauta/runner-job-guard.sh' in text
