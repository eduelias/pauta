"""deploy/runner-job-guard, pauta-deploy and provision-du7.sh: what may reach du7, the switch,
the rollback, and production's own user (its units, the one-time move, pauta-cli)."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_deploy_branch import fake_wheel

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
    """Source pauta-deploy with /opt/pauta in a temporary folder and stand-ins for root, the
    lock and a unit that runs as pauta, then run `script`."""
    stubs = (
        f'source "{DEPLOY / "pauta-deploy"}"; ROOT="{root}"; RELEASES="{root}/releases"; '
        f'PYTHON="{sys.executable}"; id() {{ echo 0; }}; flock() {{ :; }}; '
        "systemctl() { echo pauta; }; "
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
        'systemctl() { if [ "$1" = show ]; then echo pauta; else '
        'echo "systemctl $*" >> "$ROOT/calls"; fi; }; backup_db() { :; }; '
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


@pytest.mark.parametrize("user", ["esaleh", ""])  # the owner's login user; root
@pytest.mark.parametrize("args", ["--activate 1.2.3", "--rollback", "1.2.3 {} {} {} {}"])
def test_no_deploy_while_the_unit_runs_as_someone_else(args, user, opt, release):
    # du7 before provision-du7.sh moved the service to its own user, or after a rollback of that
    (opt / "previous").symlink_to(opt / "releases" / "1.2.3")
    stubs = (
        'systemctl() { if [ "$1" = show ]; then echo "$UNIT_USER"; '
        'else echo "$*" >> "$ROOT/calls"; fi; }; '
        'backup_db() { echo backup >> "$ROOT/calls"; }; install_release() { echo reached; }; '
    )
    r = deploy(opt, stubs + f"main {args.format(*release)}", UNIT_USER=user)
    assert r.returncode == 1
    assert f"pauta runs as '{user or 'root'}', not pauta" in r.stderr
    assert "provision-du7.sh" in r.stderr
    assert not (opt / "calls").exists() and "reached" not in r.stdout
    assert (opt / "current").resolve().name == "1.2.2"
    assert not list(opt.glob(".incoming.*"))


@linux
def test_install_builds_as_the_service_user_and_hands_the_release_to_root(tmp_path):
    root = tmp_path / "opt"
    (root / "releases").mkdir(parents=True)
    wheel = tmp_path / "in" / "pauta-1.2.3-py3-none-any.whl"
    wheel.parent.mkdir()
    ran = tmp_path / "ran"
    fake_wheel(wheel, "1.2.3", ran)
    lock = tmp_path / "in" / "requirements.lock"
    lock.write_text("")  # no dependencies: nothing to fetch
    # as the current user instead of runuser; who owns what is du7's business
    stubs = (
        'as_user() { "$@"; }; chown() { echo "chown $*" >> "$ROOT/calls"; }; '
        'install() { if [ "$1" = -d ]; then mkdir -p "${@: -1}"; '
        'else cp "${@: -3:2}" "${@: -1}"; fi; }; '
    )
    r = deploy(root, stubs + f'install_release 1.2.3 "{wheel}" "{lock}"')
    assert r.returncode == 0, r.stderr
    dest = root / "releases" / "1.2.3"
    assert (dest / ".complete").exists()
    assert f"chown -R -P root:root {dest}" in (root / "calls").read_text()
    # the release's code only ever runs in the unit's sandbox, never during the install
    assert not ran.exists()
    assert subprocess.run([dest / "bin" / "pauta"], capture_output=True, text=True).stdout == (
        "pauta 1.2.3\n"
    )
    # a wheel that says another version is refused, and its folder is not a release
    other = tmp_path / "in2" / "pauta-1.2.4-py3-none-any.whl"
    other.parent.mkdir()
    fake_wheel(other, "9.9.9")
    (other.parent / "requirements.lock").write_text("")
    r = deploy(root, stubs + f'install_release 1.2.4 "{other}" "{other.parent}/requirements.lock"')
    assert r.returncode == 1 and "the wheel says version '9.9.9'" in r.stderr
    assert not (root / "releases" / "1.2.4" / ".complete").exists()


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


def units():
    return {name: (DEPLOY / name).read_text() for name in ("pauta.service", "pauta-backup.service")}


def test_acceptance_sees_no_home_and_no_other_drive():
    lines = (DEPLOY / "pauta-acc.service").read_text().splitlines()
    assert "User=pauta-acc" in lines and "ProtectHome=yes" in lines
    assert "InaccessiblePaths=-/media -/mnt" in lines


def test_production_runs_as_its_own_user_out_of_everyones_home():
    for name, text in units().items():
        lines = text.splitlines()
        assert "User=pauta" in lines and "Group=pauta" in lines, name
        assert "ProtectHome=yes" in lines and "InaccessiblePaths=-/media -/mnt" in lines, name
        assert "/home" not in text.replace("no /home at all", ""), name
        assert "Environment=PAUTA_STATE_DIR=/var/lib/pauta" in lines, name
    # the same user and places in the script that deploys, asked of the script itself
    r = deploy("/nowhere", 'echo "$SERVICE_USER $STATE_DIR $BACKUPS"')
    assert r.stdout.split() == ["pauta", "/var/lib/pauta", "/var/backups/pauta/pre-deploy"]
    # the NAS is the owner's drive: pauta's backup doesn't go there, the owner's copy does
    assert "/media/nas" not in units()["pauta-backup.service"]
    assert "OnSuccess=pauta-backup-nas.service" in units()["pauta-backup.service"]
    nas = (DEPLOY / "pauta-backup-nas.service").read_text()
    assert "User=esaleh" in nas and "ReadWritePaths=/media/nas/backups/pauta" in nas
    assert "-type f" in nas and "--no-dereference" in nas  # a planted link is never followed


def provision(tmp_path, script, **env):
    """Source provision-du7.sh with the owner's home and /var in a temporary folder, the unit
    and chown as stand-ins, then run `script`."""
    stubs = (
        f'source "{DEPLOY / "provision-du7.sh"}"; '
        f'OLD_STATE="{tmp_path}/home/share/pauta"; OLD_BACKUPS="{tmp_path}/home/backups/pauta"; '
        f'STATE_DIR="{tmp_path}/var/lib/pauta"; BACKUP_DIR="{tmp_path}/var/backups/pauta"; '
        f'systemctl() {{ echo "systemctl $*" >> "{tmp_path}/calls"; }}; '
        f'chown() {{ echo "chown $*" >> "{tmp_path}/calls"; }}; '
    )
    full = {"PATH": os.environ["PATH"], **env}
    return subprocess.run(["bash", "-c", stubs + script], env=full, capture_output=True, text=True)


@pytest.fixture
def old_home(tmp_path):
    """du7 as it was: the state and the backups in the owner's home, nothing in /var."""
    state = tmp_path / "home" / "share" / "pauta"
    (state / "pauta.db.thumbs").mkdir(parents=True)
    (state / "pauta.db").write_bytes(b"the database")
    (state / "pauta.db.session-key").write_text("key")
    (state / "pauta.db.session-key").chmod(0o600)
    (state / "pauta.db.thumbs" / "1.abc.jpg").write_bytes(b"jpg")
    backups = tmp_path / "home" / "backups" / "pauta"
    (backups / "pre-deploy").mkdir(parents=True)
    (backups / "pauta-20261119-034228.db").write_bytes(b"last night")
    (backups / "pauta-20261119-034228.db").chmod(0o600)
    (backups / "pre-deploy" / "pauta-20261120-105600-before-1.16.1.db").write_bytes(b"before")
    (tmp_path / "var" / "lib").mkdir(parents=True)
    (tmp_path / "var" / "backups").mkdir()
    return tmp_path


def tree(folder):
    return {str(f.relative_to(folder)): f.read_bytes() for f in folder.rglob("*") if f.is_file()}


def test_sourcing_provision_changes_nothing(tmp_path):
    r = provision(tmp_path, "echo sourced")
    assert r.returncode == 0 and r.stdout.strip() == "sourced", r.stderr
    assert not (tmp_path / "calls").exists()


def test_the_state_moves_once_and_the_old_copy_stays(old_home):
    state, backups = old_home / "home" / "share" / "pauta", old_home / "home" / "backups" / "pauta"
    before = tree(state), tree(backups)
    r = provision(old_home, 'move_state; echo "moved=$MOVED"')
    assert r.returncode == 0, r.stderr
    new, new_backups = old_home / "var" / "lib" / "pauta", old_home / "var" / "backups" / "pauta"
    assert (tree(new), tree(new_backups)) == before
    # modes travel with the files; the nightly copies open up to the group, nothing else does
    assert (new / "pauta.db.session-key").stat().st_mode & 0o777 == 0o600
    assert (new_backups / "pauta-20261119-034228.db").stat().st_mode & 0o777 == 0o640
    # the old folders are kept under another name, whole
    stamp = r.stdout.splitlines()[-1].removeprefix("moved=")
    assert len(stamp) == 8 and stamp.isdigit()
    assert not state.exists() and not backups.exists()
    assert (tree(state.with_name(f"pauta.moved-{stamp}")),) == before[:1]
    assert (tree(backups.with_name(f"pauta.moved-{stamp}")),) == before[1:]
    # stopped before anything is read, the copies handed to the service user, and no start:
    # that is for the new unit, which the caller installs next
    assert (old_home / "calls").read_text().splitlines() == [
        "systemctl stop pauta-backup.timer pauta-backup.service pauta.service",
        f"chown -R pauta:pauta {new}.incoming",
        f"chown -R pauta:pauta {new_backups}.incoming",
    ]
    # again: nothing to move, nothing stopped, nothing changed
    (old_home / "calls").unlink()
    r = provision(old_home, 'move_state; echo "moved=$MOVED"')
    assert r.returncode == 0 and r.stdout == "moved=\n", r.stderr
    assert not (old_home / "calls").exists()
    assert (tree(new), tree(new_backups)) == before


@pytest.mark.parametrize("taken", ["var/lib/pauta", "var/backups/pauta"])
def test_the_move_never_overwrites_a_place_that_has_something(taken, old_home):
    # the old folder is back (a rollback) while the new place still has its files
    (old_home / taken).mkdir()
    (old_home / taken / "pauta.db").write_bytes(b"newer")
    r = provision(old_home, "move_state; echo reached")
    assert r.returncode == 1 and "nothing touched" in r.stderr and taken in r.stderr
    assert "reached" not in r.stdout
    assert not (old_home / "calls").exists()  # the service was not even stopped
    assert (old_home / taken / "pauta.db").read_bytes() == b"newer"
    assert (old_home / "home" / "share" / "pauta" / "pauta.db").read_bytes() == b"the database"


def test_an_empty_new_place_is_not_in_the_way(old_home):
    (old_home / "var" / "backups" / "pauta" / "pre-deploy").mkdir(parents=True)
    (old_home / "var" / "lib" / "pauta").mkdir()
    r = provision(old_home, "move_state")
    assert r.returncode == 0, r.stderr
    assert (old_home / "var" / "lib" / "pauta" / "pauta.db").read_bytes() == b"the database"


def test_a_copy_that_fails_leaves_the_old_place_running(old_home):
    state = old_home / "home" / "share" / "pauta"
    before = tree(state)
    # the second copy (the backups) comes out different: both new folders go, the old unit starts
    script = 'diff() { [[ "$2" != */backups/* ]]; }; move_state; echo reached'
    r = provision(old_home, script)
    assert r.returncode == 1 and "nothing moved" in r.stderr
    assert "reached" not in r.stdout
    assert tree(state) == before
    assert not list((old_home / "var" / "lib").iterdir())
    assert not list((old_home / "var" / "backups").iterdir())
    assert not list((old_home / "home" / "share").glob("pauta.moved-*"))
    assert (old_home / "calls").read_text().splitlines()[-1] == (
        "systemctl start pauta.service pauta-backup.timer"
    )


def test_provision_installs_what_the_units_need():
    text = (DEPLOY / "provision-du7.sh").read_text()
    for name in ("pauta.service", "pauta-backup.service", "pauta-backup-nas.service"):
        assert f" {name} " in text or f" {name};" in text, name
    # the move comes before the new unit is installed, and the new unit before the start
    order = ["\nmove_state\n", "/etc/systemd/system/$unit", "systemctl start pauta.service"]
    at = [text.index(o, text.index("# sourced by the tests")) for o in order]
    assert at == sorted(at)
    assert "chown -R -P root:root /opt/pauta/releases" in text


def test_the_owners_commands_run_as_the_service_user(tmp_path):
    # id, systemctl and systemd-run are stand-ins on PATH: what would be run, and as whom
    for name, body in {
        "id": "echo 0",
        "systemctl": 'echo "PAUTA_STATE_DIR=/var/lib/pauta PAUTA_ORIGIN=https://app.pauta.cc"',
        "systemd-run": 'printf "%s\\n" "$@"',
    }.items():
        (tmp_path / name).write_text(f"#!/bin/sh\n{body}\n")
        (tmp_path / name).chmod(0o755)
    env = {"PATH": f"{tmp_path}:{os.environ['PATH']}"}
    r = subprocess.run(
        ["bash", str(DEPLOY / "pauta-cli"), "invite", "--admin"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    args = r.stdout.splitlines()
    assert "--uid=pauta" in args and "--gid=pauta" in args and "ProtectHome=yes" in args
    # the unit's own environment, and the live release's command with the arguments as given
    assert "--setenv=PAUTA_STATE_DIR=/var/lib/pauta" in args
    assert "--setenv=PAUTA_ORIGIN=https://app.pauta.cc" in args
    assert args[-3:] == ["/opt/pauta/current/bin/pauta", "invite", "--admin"]
    assert "--pty" not in args and "-t" not in args  # never on the owner's terminal
