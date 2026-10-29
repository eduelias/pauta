#!/usr/bin/env bash
# Setup of du7 for release deploys: once, after every change to deploy/, and to update the
# runner. Run as root on du7 from a copy of this deploy/ directory:
#
#   sudo deploy/provision-du7.sh RUNNER_VERSION RUNNER_SHA256 [TOKEN_FILE]
#
# RUNNER_VERSION/RUNNER_SHA256: the GitHub Actions runner to run (the arm64 tarball's sha256,
# from https://github.com/actions/runner/releases). TOKEN_FILE: a file holding a runner
# registration token (`gh api -X POST repos/eduelias/pauta/actions/runners/registration-token
# --jq .token`), needed the first time and whenever the runner must be registered again.
#
# It is re-runnable and does, in order:
#   - the `pauta` system user, and moves the DB and backups out of /home/esaleh (once);
#   - pauta-deploy, pauta-cli, the NAS copy, the units, the sudo rule;
#   - pauta's old runner (as the shared gh-runner) retired, once;
#   - the runner, as its own pauta-runner: installed or updated to RUNNER_VERSION, registered
#     with self-update off, its files owned by root (only _work and _diag are its user's),
#     and the job guard, which refuses every job but the owner's deploy.
# The first release still has to be put in place by pauta-deploy; see deploy/README.md.
set -euo pipefail

RUNNER_VERSION=${1:?runner version, e.g. 2.338.2}
RUNNER_SHA256=${2:?sha256 of actions-runner-linux-arm64-<version>.tar.gz}
TOKEN_FILE=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_URL=https://github.com/eduelias/pauta
# pauta's runner has a user of its own: anything running as it may `sudo pauta-deploy`, so no
# other repository's runner may share it (gh-runner is dominion-archive's)
RUNNER_USER=pauta-runner
RUNNER_HOME=/opt/pauta-runner
OLD_RUNNER_DIR=/opt/gh-runner/actions-runner   # pauta's runner until 2026-10, as gh-runner
RUNNER_UNIT=actions.runner.eduelias-pauta.du7.service
SERVICE_USER=pauta
STATE_DIR=/var/lib/pauta
BACKUP_DIR=/var/backups/pauta
NAS_DIR=/media/nas/backups/pauta
OLD_USER=esaleh                       # who ran pauta before 2026-10 (decision 2)
OLD_STATE=/home/$OLD_USER/.local/share/pauta
OLD_BACKUPS=/home/$OLD_USER/backups/pauta

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo "expected an arm64 Pi" >&2; exit 1; }
cd /
say() { echo "provision: $*"; }

# --- the service user: its own, with nothing of anyone else's in reach ----------------------
if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$STATE_DIR" --no-create-home --shell /usr/sbin/nologin \
        --comment "Pauta (pauta.genic.dev)" "$SERVICE_USER"
fi
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$STATE_DIR"
# 0750: the owner (in the pauta group) and the NAS copy, which runs as the owner, may read
# the nightly backups; the pre-deploy ones stay pauta's
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0750 "$BACKUP_DIR"
install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0700 "$BACKUP_DIR/pre-deploy"
usermod -a -G "$SERVICE_USER" "$OLD_USER"
if mountpoint -q /media/nas; then
    install -d "$NAS_DIR"   # exFAT: every file there is the owner's, whoever writes it
fi

# --- once: move the DB and backups from /home/esaleh to the pauta user ----------------------
if [ -f "$OLD_STATE/pauta.db" ] && [ ! -f "$STATE_DIR/pauta.db" ]; then
    say "moving $OLD_STATE to $STATE_DIR"
    systemctl stop pauta-backup.timer pauta.service 2>/dev/null || true
    cp -a "$OLD_STATE/." "$STATE_DIR/"   # the DB, its -wal/-shm and its session key
    if [ -d "$OLD_BACKUPS" ]; then
        cp -a "$OLD_BACKUPS/." "$BACKUP_DIR/"
    fi
    chown -R "$SERVICE_USER:$SERVICE_USER" "$STATE_DIR" "$BACKUP_DIR"
    chmod 0700 "$STATE_DIR" "$BACKUP_DIR/pre-deploy"
    chmod 0750 "$BACKUP_DIR"
    # kept, not deleted: remove by hand once the new place has run for a while
    mv "$OLD_STATE" "$OLD_STATE.moved-$(date +%Y%m%d)"
    say "the old copy is in $OLD_STATE.moved-$(date +%Y%m%d)"
fi
# installed releases are root's: the service may read them, never change them
if [ -d /opt/pauta/releases ]; then
    chown -R -h root:root /opt/pauta/releases
fi

# --- the deploy script, the tools and the units ---------------------------------------------
install -o root -g root -m 0755 "$HERE/pauta-deploy" /usr/local/sbin/pauta-deploy
install -o root -g root -m 0755 "$HERE/pauta-cli" /usr/local/sbin/pauta-cli
install -d -o root -g root -m 0755 /usr/local/lib/pauta /opt/pauta /opt/pauta/releases
install -o root -g root -m 0755 "$HERE/pauta-nas-copy" /usr/local/lib/pauta/pauta-nas-copy
install -o root -g root -m 0755 "$HERE/runner-job-guard" /usr/local/lib/pauta/runner-job-guard
for unit in pauta.service pauta-backup.service pauta-backup-nas.service pauta-backup.timer; do
    install -o root -g root -m 0644 "$HERE/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
if [ -e /opt/pauta/current ]; then
    systemctl enable --now pauta.service pauta-backup.timer
    systemctl restart pauta.service
fi

# --- once: retire the runner that ran as the shared gh-runner --------------------------------
# Unconditionally: that user (dominion-archive's runner) may no longer deploy Pauta.
rm -f /etc/sudoers.d/gh-runner-pauta
if [ -f "/etc/systemd/system/$RUNNER_UNIT" ] &&
        grep -q "^ExecStart=$OLD_RUNNER_DIR/" "/etc/systemd/system/$RUNNER_UNIT"; then
    say "retiring the old runner in $OLD_RUNNER_DIR (as gh-runner)"
    systemctl disable --now "$RUNNER_UNIT"
    rm -f "/etc/systemd/system/$RUNNER_UNIT"
    rm -rf "/etc/systemd/system/$RUNNER_UNIT.d"
    systemctl daemon-reload
fi
if [ -f "$OLD_RUNNER_DIR/.runner" ] &&
        grep -q '"gitHubUrl": *"https://github.com/eduelias/pauta"' "$OLD_RUNNER_DIR/.runner"; then
    rm -rf "$OLD_RUNNER_DIR"   # its credentials; the new runner registers under the same name
fi

# --- the runner user: no shell, no groups, nothing of its own but its work dirs --------------
if ! id "$RUNNER_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$RUNNER_HOME" --no-create-home --shell /usr/sbin/nologin \
        --comment "GitHub Actions runner (eduelias/pauta deploys)" "$RUNNER_USER"
fi
rule=/etc/sudoers.d/pauta-runner
cat > "$rule.tmp" <<EOF
# The GitHub Actions runner may deploy Pauta releases, and nothing else, as root.
Defaults:$RUNNER_USER !requiretty
$RUNNER_USER ALL=(root) NOPASSWD: /usr/local/sbin/pauta-deploy
EOF
chmod 0440 "$rule.tmp"
visudo -cf "$rule.tmp" >/dev/null
mv "$rule.tmp" "$rule"

# --- the runner itself: a fresh install, owned by root, updated by this script --------------
dir=$RUNNER_HOME/actions-runner
install -d -o root -g "$RUNNER_USER" -m 0750 "$RUNNER_HOME"
installed=$( [ -x "$dir/config.sh" ] && (cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --version) 2>/dev/null || echo none)
systemctl stop "$RUNNER_UNIT" 2>/dev/null || true
if [ "$installed" != "$RUNNER_VERSION" ]; then
    say "runner $installed -> $RUNNER_VERSION"
    tarball=actions-runner-linux-arm64-$RUNNER_VERSION.tar.gz
    tmp=$(mktemp -d)
    curl -fsSL --proto '=https' -o "$tmp/$tarball" \
        "https://github.com/actions/runner/releases/download/v$RUNNER_VERSION/$tarball"
    echo "$RUNNER_SHA256  $tmp/$tarball" | sha256sum -c -
    install -d -o root -g root -m 0755 "$dir"
    tar -xzf "$tmp/$tarball" --no-same-owner -C "$dir"   # over an older one: keeps .runner
    rm -rf "$tmp"
    "$dir/bin/installdependencies.sh"
fi
# It may not update itself (its files are root's). Register when it isn't registered yet or
# was registered with self-update on; --replace takes over the name du7 on GitHub.
if [ ! -f "$dir/.runner" ] || ! grep -q '"disableUpdate": *true' "$dir/.runner"; then
    [ -n "$TOKEN_FILE" ] || {
        echo "the runner needs registering (with self-update off): pass a TOKEN_FILE" >&2
        exit 1
    }
    token=$(cat "$TOKEN_FILE")
    rm -f "$TOKEN_FILE"
    chown -R "$RUNNER_USER:$RUNNER_USER" "$dir"   # config.sh writes as the runner user
    (cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --unattended --replace \
        --url "$REPO_URL" --token "$token" --name du7 --labels du7,pauta \
        --work _work --disableupdate)
fi
# Root writes what the runner reads at start, so a job can't change it for the next one: the
# Listener loads .env over the unit's environment, so the guard is set there too.
printf 'LANG=C.UTF-8\nACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/lib/pauta/runner-job-guard\n' > "$dir/.env"
printf '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n' > "$dir/.path"
install -o root -g root -m 0755 "$dir/bin/runsvc.sh" "$dir/runsvc.sh"
chown -R -h root:root "$dir"
chmod -R go-w "$dir"
for f in .runner .credentials .credentials_rsaparams; do
    if [ -f "$dir/$f" ]; then
        chown root:"$RUNNER_USER" "$dir/$f"
        chmod 0640 "$dir/$f"
    fi
done
install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0750 "$dir/_work" "$dir/_diag"
chown -R -h "$RUNNER_USER:$RUNNER_USER" "$dir/_work" "$dir/_diag"
install -o root -g root -m 0644 "$HERE/pauta-runner.service" "/etc/systemd/system/$RUNNER_UNIT"
systemctl daemon-reload
systemctl enable --now "$RUNNER_UNIT"
sleep 5
if ! systemctl is-active -q "$RUNNER_UNIT"; then
    journalctl -u "$RUNNER_UNIT" -n 30 --no-pager >&2 || true
    echo "the runner didn't start: see above (deploy/README.md, 'If the runner won't start')" >&2
    exit 1
fi

say "done: pauta user, pauta-deploy $(/usr/local/sbin/pauta-deploy --capabilities), units, sudo rule, job guard, runner $(cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --version)"
say "on du7 outside this repo: point ~/du7-watchdog.py's pauta-backup check at $BACKUP_DIR"
