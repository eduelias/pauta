#!/usr/bin/env bash
# One-time (and re-runnable) setup of du7 for release deploys. Run as root on du7 from a
# copy of this deploy/ directory:
#
#   sudo deploy/provision-du7.sh RUNNER_VERSION RUNNER_SHA256 [TOKEN_FILE]
#
# It makes the service's own user (`pauta`) and, once, moves the state and the backups out of
# the owner's home (move_state below; deploy/README.md, "Production's own user"). It installs
# pauta-deploy, pauta-cli, the systemd units and the sudo rule, and (with TOKEN_FILE, a
# file holding a runner registration token from
# `gh api -X POST repos/eduelias/pauta/actions/runners/registration-token --jq .token`)
# registers a GitHub Actions runner for eduelias/pauta as the locked-down user gh-runner.
# The first release still has to be put in place by pauta-deploy; see deploy/README.md.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_URL=https://github.com/eduelias/pauta
RUNNER_USER=gh-runner
RUNNER_HOME=/opt/gh-runner
SERVICE_USER=pauta
STATE_DIR=/var/lib/pauta
BACKUP_DIR=/var/backups/pauta
OWNER=esaleh   # ran the service until it got its own user; still owns the NAS drive
OLD_STATE=/home/$OWNER/.local/share/pauta
OLD_BACKUPS=/home/$OWNER/backups/pauta

say() { echo "provision: $*"; }
die() { echo "provision: $*" >&2; exit 1; }

copy_out() {  # OLD NEW: a whole copy for the service user, compared, named NEW only once complete
    rm -rf "$2.incoming" &&
        cp -a "$1" "$2.incoming" &&
        diff -r "$1" "$2.incoming" &&
        chown -R "$SERVICE_USER:$SERVICE_USER" "$2.incoming" &&
        mv "$2.incoming" "$2"
}

move_state() {
    # Once: the DB with its keys and tokens, and the backups, leave the owner's home. Nothing
    # is deleted: the old folders stay as *.moved-DATE (deploy/README.md says for how long).
    # Until the last two lines the old place is the real one, and the unit that reads it is
    # still the installed one, so a copy that fails ends with pauta running as before.
    MOVED=
    [ -e "$OLD_STATE/pauta.db" ] || return 0  # moved already, or a du7 that never had it
    local today taken
    today=$(date +%Y%m%d)
    # an empty new place is a run that stopped early; anything else is not ours to overwrite
    rmdir "$BACKUP_DIR/pre-deploy" "$BACKUP_DIR" "$STATE_DIR" 2>/dev/null || true
    for taken in "$STATE_DIR" "$BACKUP_DIR" "$OLD_STATE.moved-$today" "$OLD_BACKUPS.moved-$today"; do
        [ ! -e "$taken" ] ||
            die "$OLD_STATE has a database and $taken exists too: nothing touched. Decide" \
                "which is the real one (deploy/README.md, \"Production's own user\")"
    done
    say "moving $OLD_STATE to $STATE_DIR: pauta is down from here"
    systemctl stop pauta-backup.timer pauta-backup.service pauta.service
    if copy_out "$OLD_STATE" "$STATE_DIR" &&
            { [ ! -d "$OLD_BACKUPS" ] || copy_out "$OLD_BACKUPS" "$BACKUP_DIR"; }; then
        # the nightly copies become readable by the pauta group (the NAS copy reads them)
        find "$BACKUP_DIR" -maxdepth 1 -type f -name 'pauta-*.db' -exec chmod 0640 {} + 2>/dev/null || true
        MOVED=$today
        mv "$OLD_STATE" "$OLD_STATE.moved-$MOVED"
        [ ! -d "$OLD_BACKUPS" ] || mv "$OLD_BACKUPS" "$OLD_BACKUPS.moved-$MOVED"
    else
        rm -rf "$STATE_DIR" "$BACKUP_DIR" "$STATE_DIR.incoming" "$BACKUP_DIR.incoming"
        systemctl start pauta.service pauta-backup.timer
        die "the copy failed (above); nothing moved, pauta is running from $OLD_STATE again"
    fi
}

# sourced by the tests (tests/unit/test_deploy_scripts.py), run otherwise
[ "${BASH_SOURCE[0]}" = "$0" ] || return 0

RUNNER_VERSION=${1:?runner version, e.g. 2.338.2}
RUNNER_SHA256=${2:?sha256 of actions-runner-linux-arm64-<version>.tar.gz}
TOKEN_FILE=${3:-}

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo "expected an arm64 Pi" >&2; exit 1; }
# everything installed below, before anything is stopped or moved
for f in pauta-deploy pauta-cli runner-job-guard pauta.service pauta-backup.service \
        pauta-backup-nas.service pauta-backup.timer; do
    [ -f "$HERE/$f" ] || die "no $f next to this script: copy the whole deploy/ folder"
done
cd /

# --- the service user: no shell, and nothing of anyone else's in its reach ------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "$STATE_DIR" \
        --shell /usr/sbin/nologin --comment "Pauta (app.pauta.cc)" "$SERVICE_USER"
fi
# the owner may list the nightly backups (the watchdog reads their age) and copy them to the NAS
usermod -a -G "$SERVICE_USER" "$OWNER"
move_state
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$BACKUP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$STATE_DIR" "$BACKUP_DIR/pre-deploy"
if mountpoint -q /media/nas; then
    install -d /media/nas/backups/pauta  # exFAT: everything there is the drive owner's
fi

# --- the deploy script, the layout and the units -----------------------------------------
install -o root -g root -m 0755 "$HERE/pauta-deploy" /usr/local/sbin/pauta-deploy
install -o root -g root -m 0755 "$HERE/pauta-cli" /usr/local/sbin/pauta-cli
install -d -o root -g root -m 0755 /opt/pauta /opt/pauta/releases
# installed releases are root's: the service reads them, and can't change them
chown -R -P root:root /opt/pauta/releases
for unit in pauta.service pauta-backup.service pauta-backup-nas.service pauta-backup.timer; do
    install -o root -g root -m 0644 "$HERE/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
if [ -n "$MOVED" ]; then
    systemctl start pauta.service pauta-backup.timer
    # waits for /healthz; a unit that won't start in its new place needs the rollback by hand
    /usr/local/sbin/pauta-deploy --status | grep -E '^live: .*\(healthz: [0-9]' ||
        die "pauta is NOT healthy as $SERVICE_USER: journalctl -u pauta -n 30, then the" \
            "rollback in deploy/README.md (\"Production's own user\"); the old state is" \
            "$OLD_STATE.moved-$MOVED"
    say "pauta runs as $SERVICE_USER from $STATE_DIR; the old copies are $OLD_STATE.moved-$MOVED" \
        "and $OLD_BACKUPS.moved-$MOVED (README: what else changes now, and when to delete them)"
fi

# --- the runner user: no shell, no groups, one sudo rule ---------------------------------
if ! id "$RUNNER_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$RUNNER_HOME" --create-home --shell /usr/sbin/nologin \
        --comment "GitHub Actions runner (eduelias/pauta deploys)" "$RUNNER_USER"
fi
chmod 0750 "$RUNNER_HOME"
rule=/etc/sudoers.d/gh-runner-pauta
cat > "$rule.tmp" <<EOF
# The GitHub Actions runner may deploy Pauta releases, and nothing else, as root.
Defaults:$RUNNER_USER !requiretty
$RUNNER_USER ALL=(root) NOPASSWD: /usr/local/sbin/pauta-deploy
EOF
chmod 0440 "$rule.tmp"
visudo -cf "$rule.tmp" >/dev/null
mv "$rule.tmp" "$rule"

# --- the runner itself ---------------------------------------------------------------------
dir=$RUNNER_HOME/actions-runner
if [ ! -x "$dir/config.sh" ]; then
    tarball=actions-runner-linux-arm64-$RUNNER_VERSION.tar.gz
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/$tarball" \
        "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$tarball"
    echo "$RUNNER_SHA256  $tmp/$tarball" | sha256sum -c -
    install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0750 "$dir"
    tar -xzf "$tmp/$tarball" -C "$dir"
    chown -R "$RUNNER_USER:$RUNNER_USER" "$dir"
    rm -rf "$tmp"
    "$dir/bin/installdependencies.sh"
fi
if [ -n "$TOKEN_FILE" ] && [ ! -f "$dir/.runner" ]; then
    token=$(cat "$TOKEN_FILE")
    rm -f "$TOKEN_FILE"
    (cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --unattended --replace \
        --url "$REPO_URL" --token "$token" --name du7 --labels du7,pauta \
        --work _work)
    (cd "$dir" && ./svc.sh install "$RUNNER_USER" && ./svc.sh start)
fi

# --- the job guard: the runner refuses every job but the deploy ----------------------------
# Root-owned, outside the runner's own (gh-runner-writable) directory, and set through a
# systemd drop-in, so no job can switch it off for the jobs after it.
install -d -o root -g root -m 0755 /usr/local/lib/pauta
install -o root -g root -m 0755 "$HERE/runner-job-guard" /usr/local/lib/pauta/runner-job-guard.sh
rm -f /usr/local/lib/pauta/runner-job-guard  # before 2026-10-31: no .sh, which the runner refuses
unit=actions.runner.eduelias-pauta.du7.service
if [ -f "/etc/systemd/system/$unit" ]; then
    install -d -o root -g root -m 0755 "/etc/systemd/system/$unit.d"
    cat > "/etc/systemd/system/$unit.d/job-guard.conf" <<EOF
# Every job on du7 first passes /usr/local/lib/pauta/runner-job-guard.sh (deploy/README.md).
[Service]
Environment=ACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/lib/pauta/runner-job-guard.sh
EOF
    systemctl daemon-reload
    systemctl restart "$unit"
fi

echo "provisioned: user $SERVICE_USER, pauta-deploy, pauta-cli, units, sudo rule, job guard, runner $(cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --version)"
