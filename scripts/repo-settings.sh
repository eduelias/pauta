#!/usr/bin/env bash
# GitHub settings for eduelias/pauta, as code: what protects main, releases, du7 and the
# secrets once other people can push. Idempotent; run it again after any change here.
# Why each one: docs/decisions/0002-collaborators-and-a-public-repo.md.
#
#   scripts/repo-settings.sh apply            repo options, Actions, environments, rulesets,
#                                             security features
#   scripts/repo-settings.sh secrets          move the WhatsApp secrets into the `alerts`
#                                             environment (WA_TOKEN from 1Password)
#   scripts/repo-settings.sh invite LOGIN     add a maintainer (only after the du7 guard is on)
#   scripts/repo-settings.sh show             print what is set now
#
# Needs `gh` signed in as the owner (and `op` for `secrets`). On GitHub Free, rulesets,
# required reviews, secret scanning and private vulnerability reporting only work on a
# public repository: those steps say so and carry on while it is private.
set -euo pipefail

REPO=${PAUTA_REPO:-eduelias/pauta}
ADMIN_ROLE=5   # RepositoryRole id of "admin": the owner bypasses the rulesets
WA_TOKEN_REF="op://Du7 Tech/famulus-stack .env/WA_TOKEN"
CHECKS=("Lint" "Tests (Python 3.11)" "Tests (Python 3.12)" "Tests (Python 3.13)"
        "Browser (end to end)" "Dependency audit" "Build and smoke test")

say() { printf '%s\n' "$*"; }
try() {  # DESCRIPTION gh-api-args...: run it, explain a refusal instead of stopping
    local what=$1 out
    shift
    if out=$(gh api "$@" 2>&1); then
        say "ok    $what"
    elif grep -q -e "Upgrade to GitHub Pro" -e "make this repository public" \
            -e "not available for private" -e "only available for public" \
            -e "not available for this repository" -e "not allowed for private" <<<"$out"; then
        say "later $what (needs the repo public, or GitHub Pro)"
    else
        say "FAIL  $what: $out"
        FAILED=1
    fi
}
FAILED=0

public_only() {  # DESCRIPTION gh-api-args...: on GitHub Free these exist for public repos only
    if [ "$VISIBILITY" = public ]; then
        try "$@"
    else
        say "later $1 (when the repo is public)"
    fi
}

ruleset() {  # NAME JSON: create the ruleset, or replace the one with that name
    local name=$1 body=$2 id
    # (on a refusal gh prints the error body on stdout: treat that as "none yet")
    id=$(gh api "repos/$REPO/rulesets" --jq ".[] | select(.name == \"$name\") | .id" \
        2>/dev/null) || id=
    if [ -n "$id" ]; then
        public_only "ruleset '$name' (updated)" -X PUT "repos/$REPO/rulesets/$id" --input - <<<"$body"
    else
        public_only "ruleset '$name'" -X POST "repos/$REPO/rulesets" --input - <<<"$body"
    fi
}

environment() {  # NAME: deployable only from main and release tags
    local name=$1 have
    try "environment $name" -X PUT "repos/$REPO/environments/$name" --input - <<'EOF'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
EOF
    have=$(gh api "repos/$REPO/environments/$name/deployment-branch-policies" \
        --jq '.branch_policies[] | "\(.type):\(.name)"' 2>/dev/null || true)
    for policy in branch:main tag:v*; do
        grep -qxF "$policy" <<<"$have" && continue
        try "environment $name: deploy from ${policy#*:}" -X POST \
            "repos/$REPO/environments/$name/deployment-branch-policies" \
            -f "name=${policy#*:}" -f "type=${policy%%:*}"
    done
}

apply() {
    VISIBILITY=$(gh api "repos/$REPO" --jq .visibility)
    say "== repository ($VISIBILITY)"
    try "merge options, branch cleanup, no wiki/projects" -X PATCH "repos/$REPO" \
        -F allow_merge_commit=true -F allow_squash_merge=true -F allow_rebase_merge=false \
        -F delete_branch_on_merge=true -F allow_auto_merge=true -F allow_update_branch=true \
        -F has_wiki=false -F has_projects=false

    say "== Actions"
    # only GitHub's own actions plus the two this repo uses, each pinned to a full SHA
    try "allowed actions: selected, SHA-pinned" -X PUT "repos/$REPO/actions/permissions" \
        -F enabled=true -f allowed_actions=selected -F sha_pinning_required=true
    try "allowed actions: github/*, astral-sh/setup-uv, rhysd/actionlint" -X PUT \
        "repos/$REPO/actions/permissions/selected-actions" --input - <<'EOF'
{"github_owned_allowed": true, "verified_allowed": false,
 "patterns_allowed": ["astral-sh/setup-uv@*", "rhysd/actionlint@*"]}
EOF
    try "GITHUB_TOKEN read-only, can't approve PRs" -X PUT \
        "repos/$REPO/actions/permissions/workflow" \
        -f default_workflow_permissions=read -F can_approve_pull_request_reviews=false
    # nobody's fork runs a workflow until the owner has looked at it (while private: not at all)
    if [ "$VISIBILITY" = public ]; then
        try "fork PRs from anyone outside need approval to run" -X PUT \
            "repos/$REPO/actions/permissions/fork-pr-contributor-approval" \
            -f approval_policy=all_external_contributors
    else
        try "fork PRs run no workflows (private repo)" -X PUT \
            "repos/$REPO/actions/permissions/fork-pr-workflows-private-repos" \
            -F run_workflows_from_fork_pull_requests=false
    fi

    say "== environments"
    environment production   # the du7 deploy job
    environment alerts       # the WhatsApp secrets (see `secrets`)

    say "== rulesets"
    local checks
    checks=$(printf '{"context": "%s"},' "${CHECKS[@]}")
    ruleset main "$(cat <<EOF
{"name": "main", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "bypass_actors": [{"actor_id": $ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
 "rules": [
  {"type": "deletion"},
  {"type": "non_fast_forward"},
  {"type": "pull_request", "parameters": {
     "required_approving_review_count": 0, "require_code_owner_review": true,
     "dismiss_stale_reviews_on_push": true, "require_last_push_approval": false,
     "required_review_thread_resolution": false,
     "allowed_merge_methods": ["merge", "squash"]}},
  {"type": "required_status_checks", "parameters": {
     "strict_required_status_checks_policy": false, "do_not_enforce_on_create": false,
     "required_status_checks": [${checks%,}]}}
 ]}
EOF
)"
    # only the owner pushes, moves or deletes release tags (a tag deploys to du7)
    ruleset "release tags" "$(cat <<EOF
{"name": "release tags", "target": "tag", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
 "bypass_actors": [{"actor_id": $ADMIN_ROLE, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
 "rules": [{"type": "creation"}, {"type": "update"}, {"type": "deletion"}]}
EOF
)"

    say "== security"
    try "Dependabot alerts" -X PUT "repos/$REPO/vulnerability-alerts"
    try "Dependabot security updates" -X PUT "repos/$REPO/automated-security-fixes"
    # a published release (its wheel and SHA256SUMS, which pauta-deploy checks) never changes
    try "immutable releases" -X PUT "repos/$REPO/immutable-releases"
    public_only "secret scanning and push protection" -X PATCH "repos/$REPO" --input - <<'EOF'
{"security_and_analysis": {"secret_scanning": {"status": "enabled"},
                           "secret_scanning_push_protection": {"status": "enabled"}}}
EOF
    public_only "private vulnerability reporting" -X PUT "repos/$REPO/private-vulnerability-reporting"
    public_only "CodeQL (default setup)" -X PATCH "repos/$REPO/code-scanning/default-setup" \
        -f state=configured
}

secrets() {
    # Repository secrets reach any workflow on any branch a collaborator pushes; environment
    # secrets only reach jobs on main and release tags.
    command -v op >/dev/null || { say "needs the 1Password CLI (op)"; exit 1; }
    local phone to
    read -r -p "WA_PHONE_ID (the famulus number's phone id): " phone
    read -r -p "WA_TO (the owner's number, digits only): " to
    [[ $phone =~ ^[0-9]+$ && $to =~ ^[0-9]+$ ]] || { say "digits only"; exit 1; }
    OP_ACCOUNT=${OP_ACCOUNT:-my.1password.eu} op read "$WA_TOKEN_REF" |
        gh secret set WA_TOKEN --repo "$REPO" --env alerts
    gh secret set WA_PHONE_ID --repo "$REPO" --env alerts --body "$phone"
    gh secret set WA_TO --repo "$REPO" --env alerts --body "$to"
    if [ -n "$(gh variable list --repo "$REPO" --json name --jq '.[] | select(.name == "WA_TEMPLATE") | .name')" ]; then
        say "note: the variable WA_TEMPLATE stays a repository variable (not secret)"
    fi
    for name in WA_TOKEN WA_PHONE_ID WA_TO; do
        gh secret delete "$name" --repo "$REPO" 2>/dev/null && say "removed repository secret $name" || true
    done
    say "ok    WhatsApp secrets now live only in the alerts environment"
}

invite() {
    local login=${1:?usage: repo-settings.sh invite LOGIN}
    say "Before this: the du7 job guard is on (deploy/README.md, 'Collaborators')."
    read -r -p "Is it? [y/N] " yes
    [ "$yes" = y ] || { say "not inviting"; exit 1; }
    gh api -X PUT "repos/$REPO/collaborators/$login" -f permission=maintain >/dev/null
    say "ok    invited $login as maintainer"
}

show() {
    gh api "repos/$REPO" --jq '"visibility: \(.visibility)  delete_branch_on_merge: \(.delete_branch_on_merge)  rebase: \(.allow_rebase_merge)"'
    gh api "repos/$REPO/actions/permissions" --jq '"actions: \(.allowed_actions), sha pinning: \(.sha_pinning_required)"'
    gh api "repos/$REPO/collaborators" --jq '.[] | "collaborator: \(.login) (\(.role_name))"'
    gh api "repos/$REPO/environments" --jq '.environments[] | "environment: \(.name)"'
    gh secret list --repo "$REPO" | sed 's/^/repository secret: /'
    gh secret list --repo "$REPO" --env alerts 2>/dev/null | sed 's/^/alerts secret: /' || true
    local rules
    if rules=$(gh api "repos/$REPO/rulesets" --jq '.[] | "ruleset: \(.name) (\(.enforcement))"' 2>/dev/null); then
        say "${rules:-rulesets: none}"
    else
        say "rulesets: unavailable (needs the repo public, or GitHub Pro)"
    fi
    gh api "repos/$REPO/immutable-releases" --jq '"immutable releases: \(.enabled)"' 2>/dev/null || true
}

case "${1:-}" in
    apply)
        apply
        [ "$FAILED" = 0 ] || { say "some steps failed (FAIL above)"; exit 1; }
        ;;
    secrets) secrets ;;
    invite) invite "${2:-}" ;;
    show) show ;;
    *) sed -n '2,15p' "$0"; exit 2 ;;
esac
