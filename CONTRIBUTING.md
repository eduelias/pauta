# Contributing

> **Em resumo:** crie um branch `contrib/…`, faça a mudança com testes e uma linha no `CHANGELOG.md`, rode
> `make check` e abra um pull request. Com o CI verde você mesmo pode fazer o merge. Mudanças
> em CI, deploy, login, dependências ou nestas regras pedem a aprovação do Eduardo. Quem
> publica uma versão (e coloca no ar) é o Eduardo.

## The flow

1. `make setup` once (needs [uv](https://docs.astral.sh/uv/) and Node for the JS check).
2. A branch per change, under `contrib/`: `git switch -c contrib/short-name`. The repository
   refuses pushes to `main` and to any other branch (those are the owner's).
3. Make the change with its tests (`tests/unit`, `tests/api`, and `tests/e2e` for anything on
   screen) and a line under `## [Unreleased]` in `CHANGELOG.md`, written for the team.
4. `make check` must pass: it is exactly what CI runs (lint, tests with coverage ≥ 90%,
   browser tests).
5. Push and open a pull request. When every check is green, merge it yourself. If it touches
   a path in `.github/CODEOWNERS`, the owner reviews it first. Before a release the owner
   sees every commit that isn't theirs.
6. Releasing is the owner's job (`make release V=X.Y.Z`): it deploys to du7. Ask when a
   batch of merged changes should go live.

## Ground rules

- Keep schema changes additive (new tables and columns, with a migration for existing
  databases): an older release must still run on a newer database, so a rollback is safe.
- No new runtime dependencies without asking: the only one is `webauthn`, and the deploy
  installs exact hashes.
- No secrets, client data or real phone numbers in code, tests, issues or commits. Test data
  is made up (`example.com`, `31600000000`).
- Never point anything at https://pauta.genic.dev or du7: `make run` gives you a local copy
  in open mode, `make demo` fills it with made-up data.
- UI text is Brazilian Portuguese; code, comments, commits and docs are English.

## For the owner, reviewing a PR

Merge your own PRs (you bypass the rulesets) pinned to the commit you reviewed, so nothing
pushed after it slips in: `gh pr merge N --merge --match-head-commit <sha>`.

Read the diff on GitHub; CI has already run the tests on GitHub's machines. Don't check out a
collaborator's branch and run `make check`, `make run` or its tests on the Mac outside a
container: tests are code, and they would run with your keys and 1Password session.

## Working with Claude Code

`CLAUDE.md` is what Claude reads first; it already knows the shape of the app, the commands
and these rules. A good request names the screen and what should change, then let it run
`make check` before it opens the PR. Read the diff before you merge: you are the reviewer.
