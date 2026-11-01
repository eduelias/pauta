# The same checks CI runs, for before you push. `make help` lists them.
.PHONY: help setup lint fmt test test-fast e2e check acc run demo release

help:  ## this list
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

setup:  ## install dev tools and Chromium for the browser tests
	uv sync --extra dev --extra e2e
	uv run playwright install chromium

lint:  ## ruff, formatting, JS syntax, shellcheck, actionlint
	uv lock --check
	uv run --extra dev ruff check src tests scripts tools
	uv run --extra dev ruff format --check src tests scripts tools
	node --check src/pauta/static/app.js
	uvx --from shellcheck-py shellcheck deploy/pauta-deploy deploy/pauta-deploy-branch deploy/provision-du7.sh deploy/provision-branch-env.sh deploy/runner-job-guard scripts/repo-settings.sh
	uvx --from actionlint-py actionlint

fmt:  ## fix what ruff can fix
	uv run --extra dev ruff check --fix src tests scripts tools
	uv run --extra dev ruff format src tests scripts tools

test:  ## unit and API tests with coverage (fails under 90%), in parallel
	uv run --extra dev pytest -n auto --cov

test-fast:  ## the inner loop: unit and API tests in parallel, no coverage (~5 s)
	uv run --extra dev pytest -n auto

e2e:  ## browser journeys in Chromium, in parallel (make setup once)
	uv run --extra dev --extra e2e pytest -m e2e -n auto

check: lint test e2e  ## everything CI checks (~1 min; run before you push)

acc:  ## put this branch on https://acc.pauta.cc (owner only; pushes first, then watches)
	@git diff --quiet HEAD || { echo "commit (or stash) first: acc deploys what is pushed"; exit 1; }
	git push -u origin HEAD
	@before=$$(gh run list --workflow deploy-branch.yml --limit 1 --json databaseId --jq '.[0].databaseId'); \
	gh workflow run deploy-branch.yml -f ref="$$(git branch --show-current)"; \
	for _ in $$(seq 30); do sleep 2; \
	  run=$$(gh run list --workflow deploy-branch.yml --limit 1 --json databaseId --jq '.[0].databaseId'); \
	  [ "$$run" != "$$before" ] && break; done; \
	gh run watch "$$run" --exit-status && curl -fsS https://acc.pauta.cc/healthz

run:  ## the app on http://localhost:8088, open mode, data in ./state
	uv run pauta serve

demo:  ## made-up clients and requests in ./state (never on du7)
	uv run pauta demo

release:  ## cut a release: make release V=1.2.0 (tags and pushes; CI deploys)
	@test -n "$(V)" || { echo "usage: make release V=X.Y.Z"; exit 1; }
	python3 scripts/release.py cut $(V) --push
