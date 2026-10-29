# The same checks CI runs, for before you push. `make help` lists them.
.PHONY: help setup lint fmt test e2e check run demo release

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
	uvx --from shellcheck-py shellcheck deploy/pauta-deploy deploy/provision-du7.sh deploy/runner-job-guard scripts/repo-settings.sh
	uvx --from actionlint-py actionlint

fmt:  ## fix what ruff can fix
	uv run --extra dev ruff check --fix src tests scripts tools
	uv run --extra dev ruff format src tests scripts tools

test:  ## unit and API tests with coverage (fails under 90%)
	uv run --extra dev pytest --cov

e2e:  ## browser journeys in Chromium (make setup once)
	uv run --extra dev --extra e2e pytest -m e2e

check: lint test e2e  ## everything CI checks

run:  ## the app on http://localhost:8088, open mode, data in ./state
	uv run pauta serve

demo:  ## made-up clients and requests in ./state (never on du7)
	uv run pauta demo

release:  ## cut a release: make release V=1.2.0 (tags and pushes; CI deploys)
	@test -n "$(V)" || { echo "usage: make release V=X.Y.Z"; exit 1; }
	python3 scripts/release.py cut $(V) --push
