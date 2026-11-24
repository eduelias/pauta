# The same checks CI runs, for before you push. `make help` lists them.
.PHONY: help setup lint fmt test test-fast e2e check acc dev run demo release

help:  ## this list
	@grep -E '^[a-z0-9 -]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

setup:  ## install dev tools and Chromium for the browser tests
	uv sync --extra dev --extra e2e
	uv run playwright install chromium

lint:  ## ruff, formatting, JS syntax, shellcheck, actionlint
	uv lock --check
	uv run --extra dev ruff check src tests scripts tools
	uv run --extra dev ruff format --check src tests scripts tools
	for f in src/pauta/static/app*.js; do node --check "$$f"; done
	uvx --from shellcheck-py shellcheck deploy/pauta-deploy deploy/pauta-deploy-branch deploy/provision-du7.sh deploy/provision-branch-env.sh deploy/runner-job-guard scripts/repo-settings.sh
	uvx --from actionlint-py==1.7.12.25 actionlint

fmt:  ## fix what ruff can fix
	uv run --extra dev ruff check --fix src tests scripts tools
	uv run --extra dev ruff format src tests scripts tools

test:  ## unit and API tests with coverage (fails under 90%), in parallel
	uv run --extra dev pytest -n auto --cov

test-fast:  ## the inner loop: unit and API tests in parallel, no coverage (~5 s)
	uv run --extra dev pytest -n auto

e2e:  ## browser journeys in Chromium, in parallel (make setup once)
	uv run --extra dev --extra e2e pytest -m e2e -n auto

check: lint test e2e  ## everything CI checks (~30 s; run before you push)

acc dev:  ## put this branch on https://acc.pauta.cc or dev.pauta.cc (owner only; pushes, then watches)
	@git status --porcelain | grep -q . && { echo "commit first: $@ deploys what is pushed (untracked files too)"; exit 1; } || true
	git push -u origin HEAD
	@me=$$(gh api user --jq .login); \
	before=$$(gh run list --workflow deploy-branch.yml --user "$$me" --limit 1 --json databaseId --jq '.[0].databaseId'); \
	gh workflow run deploy-branch.yml -f ref="$$(git branch --show-current)" -f environment=$@; \
	run=$$before; for _ in $$(seq 30); do sleep 2; \
	  run=$$(gh run list --workflow deploy-branch.yml --user "$$me" --limit 1 --json databaseId --jq '.[0].databaseId'); \
	  [ "$$run" != "$$before" ] && break; done; \
	[ "$$run" != "$$before" ] || { echo "the dispatch did not show up in 60 s; see gh run list --workflow deploy-branch.yml"; exit 1; }; \
	gh run watch "$$run" --exit-status; \
	sha=$$(git rev-parse --short=12 HEAD); live=$$(curl -fsS https://$@.pauta.cc/healthz | jq -r .version); \
	echo "$@.pauta.cc is on $$live (this branch: $$sha)"; \
	case "$$live" in *"+g$$sha") ;; *) echo "that is not this commit"; exit 1;; esac

run:  ## the app on http://localhost:8088, open mode, data in ./state
	uv run pauta serve

demo:  ## made-up clients and requests in ./state (never on du7)
	uv run pauta demo

release:  ## cut a release: make release V=1.2.0 (tags and pushes; CI deploys)
	@test -n "$(V)" || { echo "usage: make release V=X.Y.Z"; exit 1; }
	python3 scripts/release.py cut $(V) --push
