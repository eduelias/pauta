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
    """What a release run built, and the sha256 of each file as that run hands them over."""
    wheel = tmp_path / "pauta-1.2.3-py3-none-any.whl"
    lock = tmp_path / "requirements.lock"
    wheel.write_bytes(b"the wheel this run built")
    lock.write_text("webauthn==2.7.0 --hash=sha256:abc\n")
    return wheel, lock, *(hashlib.sha256(f.read_bytes()).hexdigest() for f in (wheel, lock))


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


def install(root, wheel, lock, wheel_sha, lock_sha):
    # main, as deploy.yml calls it, up to the install: the rest are stand-ins
    script = (
        "backup_db() { :; }; activate() { :; }; prune() { :; }; "
        'install_release() { echo "installed $1"; }; '
        f"main 1.2.3 {wheel} {lock} {wheel_sha} {lock_sha}"
    )
    return deploy(root, script)


def test_this_runs_files_pass(release, tmp_path):
    r = install(tmp_path / "opt", *release)
    assert r.returncode == 0, r.stderr
    assert "are the ones this release run built" in r.stderr
    assert r.stdout == "installed 1.2.3\n"


def test_a_swapped_wheel_is_refused(release, tmp_path):
    wheel, lock, wheel_sha, lock_sha = release
    wheel.write_bytes(b"something a job built itself")
    r = install(tmp_path / "opt", wheel, lock, wheel_sha, lock_sha)
    assert r.returncode == 1
    assert "pauta-1.2.3-py3-none-any.whl is not the one this release run built" in r.stderr
    assert f"expected {wheel_sha}" in r.stderr
    assert "installed" not in r.stdout  # it dies before anything is installed


def test_a_swapped_lockfile_is_refused(release, tmp_path):
    wheel, lock, wheel_sha, lock_sha = release
    r = install(tmp_path / "opt", wheel, lock, wheel_sha, "0" * 64)  # another build's hash
    assert r.returncode == 1
    assert "requirements.lock is not the one this release run built" in r.stderr
    assert "installed" not in r.stdout


def test_the_wheel_and_lockfile_are_read_once(release, tmp_path):
    wheel, lock, wheel_sha, lock_sha = release
    root = tmp_path / "opt"
    # an install_release stand-in: the caller's file changes after the check, and it shows
    # what it was handed. The files are named as deploy.yml names them, from its directory
    # under sudo each file is read as the caller: runuser is a stand-in that says so
    script = (
        "backup_db() { :; }; activate() { :; }; prune() { :; }; "
        'runuser() { echo "as $2" >&2; shift 3; "$@"; }; '
        f'install_release() {{ echo changed > "{wheel}"; ls -ld "${{2%/*}}" | cut -c1-10; '
        'echo "$2 $3"; cat "$2"; }; '
        f"main 1.2.3 {wheel.name} {lock.name} {wheel_sha} {lock_sha}"
    )
    r = deploy(root, script, cwd=tmp_path, SUDO_USER="someone")
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("as someone") == 2  # the wheel and the lockfile
    mode, paths, content = r.stdout.splitlines()
    assert mode == "drwx------"  # root only
    assert all(path.startswith(f"{root}/.incoming.") for path in paths.split())
    assert content == "the wheel this run built"
    assert not list(root.glob(".incoming.*"))  # gone when the deploy ends
    # and when it is refused (the caller's wheel is the changed one now)
    r = deploy(root, script, cwd=tmp_path)
    assert r.returncode == 1 and "is not the one this release run built" in r.stderr
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


@linux
def test_activate_switches_to_an_installed_release(opt):
    backup = 'backup_db() { echo "backup before $1" >> "$ROOT/calls"; }; '
    r = switch(opt, backup + "main --activate 1.2.3", "1.2.2 1.2.3")
    assert r.returncode == 0, r.stderr
    assert (opt / "current").resolve().name == "1.2.3"
    assert (opt / "previous").resolve().name == "1.2.2"
    assert (opt / "calls").read_text() == "backup before 1.2.3\nsystemctl restart pauta\n"
    # one that doesn't come up healthy: back to the release before, like a deploy
    r = switch(opt, "main --activate 1.2.2", "1.2.3")
    assert r.returncode == 1
    assert (opt / "current").resolve().name == "1.2.3"


def test_activate_refuses_a_release_that_is_not_installed(opt):
    (opt / "releases" / "1.2.4").mkdir()  # an install that never finished
    for version in ("1.2.4", "1.2.5"):
        r = switch(opt, f"main --activate {version}", "1.2.2 1.2.3")
        assert r.returncode == 1
        assert f"{version} is not installed on du7" in r.stderr
        assert sorted(r.stderr.split("Installed:")[1].split()) == ["1.2.2", "1.2.3"]
    assert (opt / "current").resolve().name == "1.2.2"
    assert not (opt / "calls").exists()  # no backup, no restart


def test_capabilities_needs_no_lock(tmp_path):
    root = tmp_path / "opt"
    r = deploy(root, "flock() { return 1; }; main --capabilities")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "pinned activate\n"
    assert not root.exists()
    # deploy.yml asks for exactly this before it hands du7 anything
    workflow = DEPLOY.parent / ".github" / "workflows" / "deploy.yml"
    assert 'pauta-deploy --capabilities | grep -qx "pinned activate"' in workflow.read_text()


WHEEL = "/x/pauta-1.2.3-py3-none-any.whl"
SHA = "a" * 64


@pytest.mark.parametrize(
    ("args", "why"),
    [
        ("1.2.3", "usage"),
        ("--rollback now", "usage"),
        ("--activate", "usage"),
        ("--activate 1.2.3 now", "usage"),
        ("--activate 1.2", "bad version"),
        ("--capabilities now", "usage"),
        # the hashes: both, and each 64 hex digits as sha256sum prints them
        (f"1.2.3 {WHEEL} /x/requirements.lock", "usage"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA}", "usage"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA} ''", "bad sha256"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA[:63]} {SHA}", "bad sha256"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA} {SHA.upper()}", "bad sha256"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA} {SHA}x", "bad sha256"),
        (f"1.2 /x/pauta-1.2-py3-none-any.whl /x/requirements.lock {SHA} {SHA}", "bad version"),
        (
            f"1.2.3 /x/pauta-9.9.9-py3-none-any.whl /x/requirements.lock {SHA} {SHA}",
            "unexpected wheel",
        ),
        (f"1.2.3 {WHEEL} /x/other.lock {SHA} {SHA}", "unexpected lockfile"),
        (f"1.2.3 {WHEEL} /x/requirements.lock {SHA} {SHA}", "no wheel at"),
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
