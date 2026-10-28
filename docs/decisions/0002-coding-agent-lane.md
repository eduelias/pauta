# 2. Coding-agent pull requests stay in their lane

- **Status:** accepted (decided 2026-10-28)

## Context

The team will ask for changes over WhatsApp, through famulus (famulus-pauta). Once the owner
approves a request, a coding agent (a local model first, Claude when it gets stuck) writes the
change and opens a pull request. Its PRs go through the same CI and the same merge button as
anyone's, but an agent can be wrong in ways a person rarely is, and a prompt hidden in a
request could steer it. Some parts of Pauta must never change that way.

## Decision

A PR is an agent PR when it has the `agent` label or its branch starts with `agent/` (the
famulus-pauta sidecar always opens them that way). The **Agent guard** workflow fails an agent
PR that:

| Changes | Why |
|---|---|
| `.github/`, `deploy/` | CI, releases and the root-run deploy on du7 |
| `src/pauta/auth.py`, `src/pauta/ratelimit.py` | sign-in and abuse limits |
| `scripts/` | release cutting, WhatsApp alerts, and this guard itself |
| `uv.lock`, the dependency lists in `pyproject.toml` | new code from outside |
| the coverage settings in `pyproject.toml` (lower `fail_under`, `run`, `omit`) | the 90% gate stays |

It runs on `pull_request_target`, so the workflow and `scripts/agent_guard.py` always come from
`main`: a PR can't weaken the check that judges it. It never checks out or runs the PR's code
(it reads the file list and `pyproject.toml` through the API) and has no secrets.

A person who needs one of those changes makes it in their own PR.

## Consequences

- "Agent guard / Agent PR scope" should be a required check on `main`, next to CI.
- An agent request that genuinely needs, say, a new dependency stops at the guard; the owner
  makes that part by hand.
- Removing the `agent` label isn't enough to bypass it: the branch name still marks the PR.
