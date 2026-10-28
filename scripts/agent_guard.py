#!/usr/bin/env python3
"""Keep coding-agent pull requests away from what keeps Pauta safe.

    python3 scripts/agent_guard.py EVENT_JSON

Run by .github/workflows/agent-guard.yml on `pull_request_target`, so the workflow and
this script always come from the base branch: an agent PR cannot edit the check that
judges it. It never checks out or runs the PR's code; it reads the PR's file list and its
pyproject.toml through the API.

A PR is an agent PR when it carries the `agent` label or its branch starts with `agent/`
(famulus-pauta's sidecar opens them that way). Such a PR fails if it:

- touches CI or the deploy (.github/, deploy/), sign-in or rate limiting
  (src/pauta/auth.py, src/pauta/ratelimit.py), or the release and alert scripts (scripts/);
- changes dependencies (uv.lock, or the dependency lists in pyproject.toml);
- lowers the coverage gate or changes how coverage is measured (pyproject.toml).

Environment: GITHUB_TOKEN, GITHUB_REPOSITORY. Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import tomllib
import urllib.request

API = "https://api.github.com"
AGENT_LABEL = "agent"
AGENT_BRANCH = "agent/"
FORBIDDEN_DIRS = (".github/", "deploy/", "scripts/")
FORBIDDEN_FILES = {"src/pauta/auth.py", "src/pauta/ratelimit.py", "uv.lock"}


def is_agent_pr(pr: dict) -> bool:
    labels = {lb["name"] for lb in pr.get("labels", [])}
    return AGENT_LABEL in labels or pr["head"]["ref"].startswith(AGENT_BRANCH)


def forbidden_paths(files: list[dict]) -> list[str]:
    """Paths in the PR (either side of a rename) that agents may not change."""
    out = []
    for f in files:
        for path in (f["filename"], f.get("previous_filename")):
            if path and (path.startswith(FORBIDDEN_DIRS) or path in FORBIDDEN_FILES):
                out.append(path)
    return sorted(set(out))


def pyproject_problems(base: str, head: str) -> list[str]:
    """What an agent changed in pyproject.toml that it may not."""
    b, h = tomllib.loads(base), tomllib.loads(head)
    problems = []
    for key in ("dependencies", "optional-dependencies"):
        if b.get("project", {}).get(key) != h.get("project", {}).get(key):
            problems.append(f"pyproject.toml: project.{key} changed")
    bcov, hcov = b.get("tool", {}).get("coverage", {}), h.get("tool", {}).get("coverage", {})
    bmin = bcov.get("report", {}).get("fail_under", 0)
    hmin = hcov.get("report", {}).get("fail_under", 0)
    if hmin < bmin:
        problems.append(f"pyproject.toml: coverage fail_under lowered from {bmin} to {hmin}")
    if bcov.get("run") != hcov.get("run"):
        problems.append("pyproject.toml: tool.coverage.run changed")
    omit_b = bcov.get("report", {}).get("omit")
    if omit_b != hcov.get("report", {}).get("omit"):
        problems.append("pyproject.toml: tool.coverage.report.omit changed")
    return problems


def check(pr: dict, files: list[dict], pyproject: tuple[str, str] | None) -> list[str]:
    """All the reasons this PR fails the guard ([] = it passes)."""
    if not is_agent_pr(pr):
        return []
    problems = [f"{p}: agent PRs may not change this" for p in forbidden_paths(files)]
    if pyproject is not None:
        problems += pyproject_problems(*pyproject)
    return problems


def _get(url: str, raw: bool = False):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https host)
        body = r.read()
    return body.decode() if raw else json.loads(body)


def _files(repo: str, number: int) -> list[dict]:
    out, page = [], 1
    while True:
        batch = _get(f"{API}/repos/{repo}/pulls/{number}/files?per_page=100&page={page}")
        out += batch
        if len(batch) < 100:
            return out
        page += 1


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    with open(argv[1]) as f:
        pr = json.load(f)["pull_request"]
    if not is_agent_pr(pr):
        print("not an agent PR: nothing to check")
        return 0
    repo = os.environ["GITHUB_REPOSITORY"]
    files = _files(repo, pr["number"])
    pyproject = None
    if any(f["filename"] == "pyproject.toml" for f in files):
        url = f"{API}/repos/{repo}/contents/pyproject.toml?ref="
        pyproject = (
            _get(url + pr["base"]["sha"], raw=True),
            _get(url + pr["head"]["sha"], raw=True),
        )
    problems = check(pr, files, pyproject)
    for p in problems:
        print(f"::error::{p}")
    if problems:
        print(f"agent PR #{pr['number']} changes {len(problems)} thing(s) it may not")
        return 1
    print(f"agent PR #{pr['number']}: {len(files)} file(s), all allowed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
