"""deploy/pauta-deploy-branch: branch builds on a test environment, never on production."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "pauta-deploy-branch"
VERSION = "1.6.2.dev3+gabc1234def56"
# readlink -e, mv -T, stat -c, runuser: GNU/Linux, like du7 and CI
linux = pytest.mark.skipif(sys.platform != "linux", reason="GNU coreutils (du7, CI)")


def bash(script, **env):
    full = {"PATH": os.environ["PATH"], **env}
    return subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; {script}'], env=full, capture_output=True, text=True
    )


def test_sourcing_does_not_deploy():
    r = bash("echo sourced")
    assert r.returncode == 0 and r.stdout.strip() == "sourced"


def test_acceptance_is_its_own_everything():
    r = bash('env_config acc; echo "$ROOT $SERVICE $SERVICE_USER $STATE_DIR $BACKUPS $HEALTH"')
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == [
        "/opt/pauta-acc",
        "pauta-acc",
        "pauta-acc",
        "/var/lib/pauta-acc",
        "/var/backups/pauta-acc",
        "http://127.0.0.1:8089/healthz",
    ]


@pytest.mark.parametrize(
    "name", ["", "prod", "production", "pauta", "main", "ACC", "acc ", "../acc", "acc/..", "dev"]
)
def test_only_known_environments(name):
    r = bash('env_config "$NAME"; echo reached', NAME=name)
    assert r.returncode == 1 and "unknown environment" in r.stderr
    assert "reached" not in r.stdout


@pytest.mark.parametrize(
    ("var", "value"),
    [
        ("ROOT", "/opt/pauta"),
        ("ROOT", "/opt/pauta/"),
        ("ROOT", "/opt/pauta/releases"),
        ("ROOT", "/opt/pauta-acc/../pauta"),
        ("SERVICE", "pauta"),
        ("SERVICE", "pauta.service"),
        ("SERVICE_USER", "esaleh"),
        ("SERVICE_USER", "pauta"),
        ("SERVICE_USER", "root"),
        ("STATE_DIR", "/home/esaleh/.local/share/pauta"),
        ("STATE_DIR", "/var/lib/pauta"),
        ("HEALTH", "http://127.0.0.1:8088/healthz"),
        ("HEALTH", "https://app.pauta.cc/healthz"),
    ],
)
def test_production_can_never_be_the_target(var, value):
    # what a bad edit to env_config would produce: not_production still says no
    r = bash(f'env_config acc; {var}="$V"; not_production; echo reached', V=value)
    assert r.returncode == 1 and "refusing" in r.stderr
    assert "reached" not in r.stdout


@pytest.mark.parametrize("v", [VERSION, "1.6.2.dev1+gabc1234", "10.0.0.dev123456+g" + "f" * 40])
def test_good_versions(v):
    assert bash('check_version "$V"', V=v).returncode == 0


@pytest.mark.parametrize(
    "v",
    [
        "1.6.1",  # a release: those only come through pauta-deploy
        "1.6.2.dev3",
        "1.6.2.dev3+gXYZ1234",
        "1.6.2.dev3+gabc12",
        "../1.6.2.dev3+gabc1234",
        "1.6.2.dev3+gabc1234/..",
        "1.6.2.dev3+gabc1234 x",
        "1.6.2rc1+gabc1234",
    ],
)
def test_bad_versions(v):
    r = bash('check_version "$V"', V=v)
    assert r.returncode == 1 and "bad version" in r.stderr


@pytest.mark.parametrize(
    ("note", "ok"),
    [
        ("", True),
        ("feat/meta-connect@abc1234def56", True),
        ("x" * 201, False),
        ("feat/x@abc\nFAILED 1.0", False),
        ("$(reboot)", False),
    ],
)
def test_source_note(note, ok):
    assert (bash('check_source "$N"', N=note).returncode == 0) is ok


# systemctl/id stand-ins: what du7 reports for the unit and its user
GOOD = {
    "User": "pauta-acc",
    "ProtectHome": "yes",
    "ExecStart": "{ path=/opt/pauta-acc/current/bin/pauta ; argv[]=/opt/pauta-acc/current/bin/"
    "pauta serve --host 127.0.0.1 --port 8089 ; ignore_errors=no }",
    "uid": "991",
    "groups": "pauta-acc",
}


def isolation(**over):
    facts = {**GOOD, **over}
    stubs = (
        'systemctl() { case "$3" in User) echo "$F_User";; ProtectHome) echo "$F_ProtectHome";;'
        ' ExecStart) echo "$F_ExecStart";; esac; }; '
        'id() { case "$1" in -u) echo "$F_uid";; -nG) echo "$F_groups";; esac; }; '
    )
    env = {f"F_{k}": v for k, v in facts.items()}
    return bash(f"{stubs} env_config acc; check_isolation && echo isolated", **env)


def test_isolation_holds():
    r = isolation()
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "isolated"


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"User": "esaleh"}, "runs as 'esaleh'"),
        ({"User": ""}, "runs as 'root'"),
        ({"ProtectHome": "no"}, "can see /home"),
        ({"ProtectHome": "read-only"}, "can see /home"),
        ({"groups": "pauta-acc esaleh"}, "other groups"),
        ({"groups": "pauta-acc docker"}, "other groups"),
        ({"uid": "0"}, "is root"),
        ({"ExecStart": GOOD["ExecStart"].replace("pauta-acc", "pauta")}, "doesn't run"),
    ],
)
def test_isolation_is_checked_before_a_deploy(over, why):
    r = isolation(**over)
    assert r.returncode == 1 and why in r.stderr


@pytest.mark.parametrize(
    ("args", "why"),
    [
        (["prod", VERSION, "/w", "/l"], "unknown environment"),
        (["", "--status"], "unknown environment"),
        (["acc"], "usage"),
        ([], "usage"),
    ],
)
def test_main_refuses_before_touching_anything(args, why):
    # pretend to be root; env_config refuses before any directory is made
    script = 'id() { echo 0; }; install() { echo "install $*"; }; main "$@"'
    r = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}"; {script}', "_", *args],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 1 and why in r.stderr
    assert "install" not in r.stdout


@pytest.fixture
def env_dir(tmp_path):
    """A fake /opt/pauta-acc with two builds; systemctl and /healthz are stand-ins."""
    root = tmp_path / "opt"
    for v in ("1.5.0.dev16", VERSION):
        (root / "releases" / v / "bin").mkdir(parents=True)
        (root / "releases" / v / "bin" / "pauta").write_text("")
        (root / "releases" / v / "bin" / "pauta").chmod(0o755)
    (root / "current").symlink_to(root / "releases" / "1.5.0.dev16")
    return root


def run_env(root, script, healthy):
    # health_version answers with the version `current` points at, if that one is healthy
    stubs = (
        f'env_config acc; ROOT="{root}"; RELEASES="{root}/releases"; '
        'systemctl() { echo "systemctl $*" >> "$ROOT/calls"; }; '
        "journalctl() { :; }; logger() { :; }; "
        'health_version() { v=$(basename "$(readlink -e "$ROOT/current")"); '
        'case " $HEALTHY " in *" $v "*) echo "$v";; *) echo "";; esac; }; '
    )
    return bash(stubs + script, HEALTHY=healthy)


@linux
def test_a_healthy_build_goes_live(env_dir):
    r = run_env(env_dir, f'activate "{VERSION}" feat/x@abc', f"1.5.0.dev16 {VERSION}")
    assert r.returncode == 0, r.stderr
    assert (env_dir / "current").resolve().name == VERSION
    assert (env_dir / "previous").resolve().name == "1.5.0.dev16"
    assert f"live {VERSION} (feat/x@abc) (was 1.5.0.dev16)" in (env_dir / "deploy.log").read_text()
    assert "systemctl restart pauta-acc" in (env_dir / "calls").read_text()


@linux
def test_a_broken_build_rolls_back(env_dir):
    r = run_env(env_dir, f'activate "{VERSION}" feat/x@abc', "1.5.0.dev16")
    assert r.returncode == 1
    assert (env_dir / "current").resolve().name == "1.5.0.dev16"
    assert not (env_dir / "previous").exists()
    log = (env_dir / "deploy.log").read_text()
    assert f"FAILED {VERSION} (feat/x@abc), rolled back to 1.5.0.dev16" in log


@linux
def test_rollback_goes_to_previous(env_dir):
    r = run_env(env_dir, f'activate "{VERSION}"', f"1.5.0.dev16 {VERSION}")
    assert r.returncode == 0, r.stderr
    # what --rollback does after its checks
    r = run_env(
        env_dir,
        'activate "$(basename "$(readlink -e "$ROOT/previous")")" rollback',
        f"1.5.0.dev16 {VERSION}",
    )
    assert r.returncode == 0, r.stderr
    assert (env_dir / "current").resolve().name == "1.5.0.dev16"
    assert (env_dir / "previous").resolve().name == VERSION
    assert "live 1.5.0.dev16 (rollback)" in (env_dir / "deploy.log").read_text()


@linux
def test_prune_keeps_current_and_previous(env_dir):
    for i in range(8):
        d = env_dir / "releases" / f"1.6.2.dev{10 + i}+gabc1234"
        d.mkdir()
        os.utime(d, (2_000_000_000 + i, 2_000_000_000 + i))  # newer than the two above
    (env_dir / "previous").symlink_to(env_dir / "releases" / VERSION)
    r = run_env(env_dir, "prune", "")
    assert r.returncode == 0, r.stderr
    left = {p.name for p in (env_dir / "releases").iterdir()}
    assert {"1.5.0.dev16", VERSION} <= left
    assert len(left) == 5 + 2


def fake_wheel(path, version):
    """A tiny but real wheel named pauta whose console script prints its version."""
    dist = f"pauta-{version}.dist-info"
    files = {
        "pauta_fake.py": f"def main():\n    print('pauta {version}')\n",
        f"{dist}/METADATA": f"Metadata-Version: 2.1\nName: pauta\nVersion: {version}\n",
        f"{dist}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
        "Tag: py3-none-any\n",
        f"{dist}/entry_points.txt": "[console_scripts]\npauta = pauta_fake:main\n",
    }
    record = "".join(f"{name},,\n" for name in files) + f"{dist}/RECORD,,\n"
    with zipfile.ZipFile(path, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
        z.writestr(f"{dist}/RECORD", record)


@linux
def test_install_builds_a_venv_and_checks_the_version(tmp_path):
    root = tmp_path / "opt"
    (root / "releases").mkdir(parents=True)
    wheel = tmp_path / "in" / f"pauta-{VERSION}-py3-none-any.whl"
    wheel.parent.mkdir()
    fake_wheel(wheel, VERSION)
    lock = tmp_path / "in" / "requirements.lock"
    lock.write_text("")  # no dependencies: nothing to fetch
    # as the current user instead of runuser; chown to root is du7's business
    stubs = (
        f'env_config acc; ROOT="{root}"; RELEASES="{root}/releases"; PYTHON="{sys.executable}"; '
        'as_user() { "$@"; }; chown() { echo "chown $*" >> "$ROOT/calls"; }; '
        'install() { [ "$1" = -d ] && mkdir -p "${@: -1}"; }; '
    )
    script = f'install_release "{VERSION}" "{wheel}" "{lock}"'
    r = bash(stubs + script)
    assert r.returncode == 0, r.stderr
    dest = root / "releases" / VERSION
    assert (dest / ".complete").exists()
    assert (dest / wheel.name).read_bytes() == wheel.read_bytes()
    assert f"chown -R -P root:root {dest}" in (root / "calls").read_text()
    # a wheel that says another version is refused
    other = tmp_path / "in2" / "pauta-9.9.9.dev1+gabc1234-py3-none-any.whl"
    other.parent.mkdir()
    fake_wheel(other, "9.9.9.dev1+gabc1234")
    lock2 = other.parent / "requirements.lock"
    lock2.write_text("")
    r = bash(stubs + f'install_release "1.6.2.dev4+gabc1234" "{other}" "{lock2}"')
    assert r.returncode == 1
    assert "the wheel says 'pauta 9.9.9.dev1+gabc1234'" in r.stderr
