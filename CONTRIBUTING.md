# Contributing

> **Em resumo:** crie um branch, faça a mudança com testes e uma linha no `CHANGELOG.md`, rode
> `make check` e abra um pull request. Com o CI verde você mesmo pode fazer o merge. Mudanças
> em CI, deploy, login, dependências ou nestas regras pedem a aprovação do Eduardo. Quem
> publica uma versão (e coloca no ar) é o Eduardo.

## The flow

1. `make setup` once (needs [uv](https://docs.astral.sh/uv/) and Node for the JS check).
2. A branch per change: `git switch -c feat/short-name` (or `fix/…`). Never push to `main`;
   the repository refuses it.
3. Make the change with its tests (`tests/unit`, `tests/api`, and `tests/e2e` for anything on
   screen) and a line under `## [Unreleased]` in `CHANGELOG.md`, written for the team.
4. `make check` must pass: it is exactly what CI runs (lint, tests with coverage ≥ 90%,
   browser tests), about 30 s. `make test-fast` is the 5 s inner loop (below).
5. Push and open a pull request. When every check is green, merge it yourself. If it touches
   a path in `.github/CODEOWNERS`, the owner reviews it first.
6. Releasing is the owner's job (`make release V=X.Y.Z`): it deploys to du7. Ask when a
   batch of merged changes should go live.

## The loop, and how long it takes

Measured on 2026-11-01 on an M-series Mac (11 cores) and GitHub's `ubuntu-latest` (4 vCPU),
on `main` (328 unit/API tests, 73 browser tests).

| Step | Command | Before | Now |
|---|---|---|---|
| Inner loop | `make test-fast` (unit + API, parallel, no coverage) | 19.5 s (`make test`) | ~5 s |
| Unit + API with coverage | `make test` | 19.5 s | 7 s |
| Browser suite | `make e2e` | 64 s | 20–26 s |
| Everything CI runs | `make check` | ~1.5 min | **30 s** |
| CI on a push | lint, tests ×3, browser, audit, build | 2.5–3 min | ~1.5 min (see below) |
| Branch on acc.pauta.cc | `make acc` | 1–2 min after a manual dispatch | 1–2 min, in one command |

1. **While coding:** `make test-fast`. A single file (`uv run pytest tests/unit/test_store.py`)
   runs serially and starts faster still; `-k name` picks one test.
2. **Before you push:** `make check`. It is exactly what CI runs: lint, unit/API with the
   coverage gate, the browser suite. Both suites run in parallel (`pytest-xdist`, one
   Chromium per worker); every test has its own database and its own server on a free port,
   so nothing needs to be serialised.
3. **Push.** CI is the merge gate; it runs the same commands with `-n auto`. The browser job
   is the critical path (its Chromium comes from a cache keyed on the Playwright version;
   the first run after a Playwright bump installs it, ~30 s). Coverage is computed once, on
   Python 3.11 (du7's); 3.12 and 3.13 only run the tests.
4. **To try it on a real server:** `make acc` (owner only) pushes the branch, dispatches
   *Deploy branch to acceptance* for it, watches the run and ends with `acc.pauta.cc`'s
   `/healthz`. It does not wait for CI: run it right after `make check`, and CI runs
   alongside. The build gets a version like `1.6.2.dev8+g6d784cb`; `#/equipe` shows it.
   Only the owner's dispatches reach du7 (the runner's guard checks the actor).
5. **Merge** when CI is green and the owner has reviewed (see the flow above).

When a browser test fails, `test-results/traces/<test>-<device>.<page>.png` is a screenshot of
each page it had open. `PAUTA_TRACE=1 make e2e` records a full Playwright trace instead (open it with
`uv run playwright show-trace <zip>`); CI always records one and uploads it on failure.

## Ground rules

- Keep schema changes additive (new tables and columns, with a migration for existing
  databases): an older release must still run on a newer database, so a rollback is safe.
- No new runtime dependencies without asking: the only one is `webauthn`, and the deploy
  installs exact hashes.
- No secrets, client data or real phone numbers in code, tests, issues or commits. Test data
  is made up (`example.com`, `31600000000`).
- Never point anything at https://app.pauta.cc (or the old pauta.genic.dev) or du7: `make run` gives you a local copy
  in open mode, `make demo` fills it with made-up data.
- UI text is Brazilian Portuguese; code, comments, commits and docs are English.

## Working with Claude Code

`CLAUDE.md` is what Claude reads first; it already knows the shape of the app, the commands
and these rules. A good request names the screen and what should change, then let it run
`make check` before it opens the PR. Read the diff before you merge: you are the reviewer.
