#!/usr/bin/env bash
# One-time (and re-runnable) setup of a test environment on du7 for branch deploys
# (decision 9). Run as root on du7 from a copy of this deploy/ directory:
#
#   sudo deploy/provision-branch-env.sh acc
#
# It installs pauta-deploy-branch and its sudo rule, the environment's user, layout and unit
# (deploy/pauta-ENV.service), and the runner's job guard. It never starts or restarts the
# environment and never touches its state dir (/var/lib/pauta-ENV: DB, tokens, secrets).
# A new environment (`dev`) needs its line in pauta-deploy-branch's env_config, a
# deploy/pauta-dev.service, a Caddy block and a choice in deploy-branch.yml; then this.
set -euo pipefail

ENV_NAME=${1:?environment, e.g. acc}
HERE=$(cd "$(dirname "$0")" && pwd)
RUNNER_USER=gh-runner
UNIT=pauta-$ENV_NAME.service
USER_NAME=pauta-$ENV_NAME

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
[[ $ENV_NAME =~ ^[a-z]+$ ]] || { echo "bad environment '$ENV_NAME'" >&2; exit 1; }
[ -f "$HERE/$UNIT" ] || { echo "no $UNIT next to this script" >&2; exit 1; }
# the installer only knows the environments it lists; this fails for any other
bash -c 'source "$1"; env_config "$2"' _ "$HERE/pauta-deploy-branch" "$ENV_NAME"

# --- the environment: its own user (no shell, no groups), code layout and unit ------------
if ! id "$USER_NAME" >/dev/null 2>&1; then
    useradd --system --no-create-home --home-dir "/var/lib/$USER_NAME" \
        --shell /usr/sbin/nologin --comment "Pauta $ENV_NAME (branch builds)" "$USER_NAME"
fi
install -d -o root -g root -m 0755 "/opt/$USER_NAME" "/opt/$USER_NAME/releases"
install -d -o "$USER_NAME" -g "$USER_NAME" -m 0700 "/var/backups/$USER_NAME"
if ! cmp -s "$HERE/$UNIT" "/etc/systemd/system/$UNIT"; then
    install -o root -g root -m 0644 "$HERE/$UNIT" "/etc/systemd/system/$UNIT"
    systemctl daemon-reload
    echo "installed $UNIT (takes effect on the next deploy or restart)"
fi
systemctl enable --quiet "$UNIT"

# --- the installer and the one sudo rule that reaches it ----------------------------------
install -o root -g root -m 0755 "$HERE/pauta-deploy-branch" /usr/local/sbin/pauta-deploy-branch
rule=/etc/sudoers.d/gh-runner-pauta-branch
cat > "$rule.tmp" <<EOF
# The GitHub Actions runner may put branch builds on Pauta's test environments (never
# production: pauta-deploy-branch can't name it), and nothing else, as root. Decision 9.
Defaults:$RUNNER_USER !requiretty
$RUNNER_USER ALL=(root) NOPASSWD: /usr/local/sbin/pauta-deploy-branch
EOF
chmod 0440 "$rule.tmp"
visudo -cf "$rule.tmp" >/dev/null
mv "$rule.tmp" "$rule"

# --- the job guard: only the owner's deploy-branch.yml from main gets this far -------------
# The same as provision-du7.sh's; installed here too because a sudo rule for unreleased
# code must never exist on an unguarded runner.
install -d -o root -g root -m 0755 /usr/local/lib/pauta
install -o root -g root -m 0755 "$HERE/runner-job-guard" /usr/local/lib/pauta/runner-job-guard
runner=actions.runner.eduelias-pauta.du7.service
dropin=/etc/systemd/system/$runner.d/job-guard.conf
if [ -f "/etc/systemd/system/$runner" ]; then
    want="# Every job on du7 first passes /usr/local/lib/pauta/runner-job-guard (deploy/README.md).
[Service]
Environment=ACTIONS_RUNNER_HOOK_JOB_STARTED=/usr/local/lib/pauta/runner-job-guard"
    if [ "$(cat "$dropin" 2>/dev/null)" != "$want" ]; then
        install -d -o root -g root -m 0755 "/etc/systemd/system/$runner.d"
        printf '%s\n' "$want" > "$dropin"
        systemctl daemon-reload
        systemctl restart "$runner"
        echo "job guard switched on for $runner"
    fi
fi

echo "provisioned $ENV_NAME: $UNIT ($(systemctl is-active "$UNIT" || true)), pauta-deploy-branch, sudo rule, job guard"
/usr/local/sbin/pauta-deploy-branch "$ENV_NAME" --status
