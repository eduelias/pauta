#!/usr/bin/env bash
# One-time (and re-runnable) setup of du7 for release deploys. Run as root on du7 from a
# copy of this deploy/ directory:
#
#   sudo deploy/provision-du7.sh RUNNER_VERSION RUNNER_SHA256 [TOKEN_FILE]
#
# It installs pauta-deploy, the systemd units and the sudo rule, and (with TOKEN_FILE, a
# file holding a runner registration token from
# `gh api -X POST repos/eduelias/pauta/actions/runners/registration-token --jq .token`)
# registers a GitHub Actions runner for eduelias/pauta as the locked-down user gh-runner.
# The first release still has to be put in place by pauta-deploy; see deploy/README.md.
set -euo pipefail

RUNNER_VERSION=${1:?runner version, e.g. 2.338.2}
RUNNER_SHA256=${2:?sha256 of actions-runner-linux-arm64-<version>.tar.gz}
TOKEN_FILE=${3:-}
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_URL=https://github.com/eduelias/pauta
RUNNER_USER=gh-runner
RUNNER_HOME=/opt/gh-runner
SERVICE_USER=esaleh

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[ "$(uname -m)" = aarch64 ] || { echo "expected an arm64 Pi" >&2; exit 1; }

# --- the deploy script, the layout and the units -----------------------------------------
install -o root -g root -m 0755 "$HERE/pauta-deploy" /usr/local/sbin/pauta-deploy
install -d -o root -g root -m 0755 /opt/pauta /opt/pauta/releases
for unit in pauta.service pauta-backup.service pauta-backup.timer; do
    install -o root -g root -m 0644 "$HERE/$unit" "/etc/systemd/system/$unit"
done
runuser -u "$SERVICE_USER" -- mkdir -p -m 0700 /home/$SERVICE_USER/.local/share/pauta \
    /home/$SERVICE_USER/backups/pauta /home/$SERVICE_USER/backups/pauta/pre-deploy
if mountpoint -q /media/nas; then
    install -d -o "$SERVICE_USER" -g "$SERVICE_USER" /media/nas/backups/pauta
fi
systemctl daemon-reload

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
echo "provisioned: pauta-deploy, units, sudo rule, runner $(cd "$dir" && runuser -u "$RUNNER_USER" -- ./config.sh --version)"
