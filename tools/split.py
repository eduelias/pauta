"""Split server.py's routes and app.js's screens into one file per area. Idempotent.

    python3 tools/split.py .

Every `# ---- <area> ---` section of the Handler class in src/pauta/server.py listed in
SERVER_AREAS moves to src/pauta/routes/<file>.py as an `install(route, store, auth, drive, meta)`
function. The handler bodies are unchanged (they still close over store/auth/drive/meta and take
the request handler as `self`); the area's helper methods become local functions. What the
areas share (ID, SENT, Reply, finance_visible, the Meta texts...) moves to routes/__init__.py;
server.py imports what it still uses and re-exports META_DOWN for the tests. Every
`// ---------- <screen> ---` section of static/app.js listed in JS_FILES moves to app-<file>.js,
and index.html loads them in order (shared helpers first, the router last). Lint and the wheel
check in ci.yml learn the files.

A tree that is already split has no such sections and is left alone; the script tags, the wheel
check and the lint line are rebuilt from the areas found, never appended twice. So after merging
main into a branch that still has the unsplit files: keep the branch's server.py and app.js,
delete src/pauta/routes/ and static/app-*.js, run this, then `make fmt` and `make check`.
"""

import ast
import re
import sys
from pathlib import Path

repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
src = repo / "src/pauta"

# ---------------------------------------------------------------- server.py
SERVER_AREAS = [  # (section marker prefix, module file, docstring)
    ("requests", "requests", "Requests and their files (the bytes are in OneDrive)."),
    ("files (in OneDrive)", "requests", None),
    ("clients", "clients", "Clients."),
    ("campaign tracking", "campaigns", "Meta (decision 8): campaign tracking and the ad accounts."),
    ("finance (decision 7)", "finance", "Finance (decision 7): the panel, billing and payments."),
    ("team and settings", "team", "Team and settings: members, OneDrive, the option lists."),
    ("Meta (decision 8", "campaigns", None),
    ("passkeys and invites", "account", "Accounts: invites, passkeys, moving house, logout."),
    ("the person's own passkeys", "account", None),
]
STAYS = {"AUTH_ROUTES", "QUIET"}  # used by the plumbing's logging, not by routes
# tests monkeypatch these on pauta.server: they stay there, and the routes read server.NAME
LIVE = {"MANUAL_SYNC_SECONDS", "SYNC_TOO_SOON"}
REEXPORT = ["META_DOWN"]  # tests import these from pauta.server
# make_handler locals that only one area uses move into that area's install()
MOVE_LOCALS = {"campaigns": re.compile(r"^    manual_(?:sync|lock) = .*\n", re.M)}


def uses(text: str, name: str) -> bool:
    """Is `name` used in the code of `text` (comments, docstrings and strings don't count)?"""
    code = re.sub(r'""".*?"""', "", text, flags=re.S)
    code = re.sub(r"#.*", "", code)
    code = re.sub(  # string literals go, except what an f-string interpolates ({ID}, {meta.x})
        r"\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'",
        lambda m: " " + " ".join(re.findall(r"\{([^}:!]*)", m.group(0))) + " ",
        code,
    )
    return re.search(rf"(?<![\w.]){re.escape(name)}\b", code) is not None


def split_server() -> list[str]:
    """Returns the area modules written, in registration order ([] when already split)."""
    path = src / "server.py"
    server = path.read_text()
    marker = re.compile(r"^        # ---- (.+?) -+\n", re.M)
    marks = list(marker.finditer(server))
    end_class = server.index("\n    return Handler")
    sections = {}
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else end_class
        sections[m.group(1)] = (m.start(), stop)
    found = [
        (next((n for n in sections if n.startswith(p)), None), f, d) for p, f, d in SERVER_AREAS
    ]
    found = [(n, f, d) for n, f, d in found if n]
    if not found:
        print("server.py: already split")
        return []

    lines = server.split("\n")
    tree = ast.parse(server)
    imports: dict[str, str] = {}  # every name server.py imports -> the statement for it
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                imports[a.asname or a.name] = f"import {a.name}"
        elif isinstance(node, ast.ImportFrom) and node.module != "__future__":
            mod = ("." * (node.level + 1) + (node.module or "")) if node.level else node.module
            for a in node.names:
                imports[a.asname or a.name] = f"from {mod} import {a.name}"

    # the shared module-level pieces, with the comment lines that introduce them
    top = [n for n in tree.body if not isinstance(n, ast.Import | ast.ImportFrom)]
    first = next(
        i for i, n in enumerate(top) if isinstance(n, ast.Assign) and n.targets[0].id == "ID"
    )
    handler = next(i for i, n in enumerate(top) if getattr(n, "name", "") == "make_handler")
    pieces = []
    for i in range(first, handler):
        node, prev = top[i], top[i - 1]
        name = node.targets[0].id if isinstance(node, ast.Assign) else node.name
        if name in STAYS or name in LIVE:
            continue
        start = prev.end_lineno  # the line after the previous node
        while start < node.lineno - 1 and lines[start].strip() == "":
            start += 1
        pieces.append((name, "\n".join(lines[start : node.end_lineno])))
    shared_names = {n for n, _ in pieces}

    modules: dict[str, list[str]] = {}
    docs: dict[str, str] = {}
    removed = []
    for name, file, doc in found:
        start, stop = sections[name]
        body = server[start:stop]
        removed.append((start, stop))
        body = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in body.split("\n"))
        for live in LIVE:
            body = re.sub(rf"(?<![\w.]){live}\b", f"server.{live}", body)
        for helper in re.findall(r"^    def (_\w+)\(self", body, re.M):
            body = re.sub(rf"self\.{helper}\(\)", rf"{helper}(self)", body)
            body = body.replace(f"self.{helper}(", f"{helper}(self, ")
        modules.setdefault(file, []).append(body.rstrip("\n") + "\n")
        if doc:
            docs[file] = doc
    fin = modules.get("finance")  # delete_client ends the finance section but is a client route
    if fin:
        text = "\n".join(fin)
        cut = text.index('    @route("DELETE", f"/api/clients/{ID}", "admin")')
        modules["clients"].append("\n" + text[cut:])
        modules["finance"] = [text[:cut].rstrip("\n") + "\n"]
    for file, pat in MOVE_LOCALS.items():
        if file in modules:
            modules[file].insert(0, "".join(pat.findall(server)) + "\n")

    def needed(text: str, local: bool) -> list[str]:
        out = {stmt for name, stmt in imports.items() if uses(text, name)}
        if local:
            shared = sorted(n for n in shared_names if uses(text, n))
            if shared:
                out.add("from . import " + ", ".join(shared))
            if uses(text, "server"):
                out.add("from .. import server  # for the settings the tests patch there")
        return sorted(out)

    routes_dir = src / "routes"
    routes_dir.mkdir(exist_ok=True)
    shared_text = "\n\n".join(t for _, t in pieces)
    (routes_dir / "__init__.py").write_text(
        '"""The /api routes, one module per area. Each exposes install(route, store, auth, drive,'
        " meta),\nwhich server.make_handler calls so its handlers register on the same route"
        " table; the\nhandlers are plain functions taking the request handler as `self`. What"
        ' the areas share\n(the id patterns, Reply, the Meta texts) lives here.\n"""\n\n'
        "from __future__ import annotations\n\n"
        + "\n".join(needed(shared_text, False))
        + "\n\n"
        + shared_text.rstrip("\n")
        + "\n"
    )
    for file, bodies in modules.items():
        text = "".join(bodies)
        head = f'"""{docs[file]}"""\n\nfrom __future__ import annotations\n\n'
        head += "\n".join(needed(text, True))
        (routes_dir / f"{file}.py").write_text(
            f"{head}\n\n\ndef install(route, store, auth, drive, meta):\n{text}"
        )

    for start, stop in sorted(removed, reverse=True):
        server = server[:start] + server[stop:]
    for file, pat in MOVE_LOCALS.items():  # only now: the offsets above were the original's
        if file in modules:
            server = pat.sub("", server)
    for _, text in pieces:  # by text, not line numbers: the sections above are gone already
        assert server.count(text) == 1, text[:40]
        server = server.replace(text, "", 1)
    areas = [f for f in dict.fromkeys(f for _, f, _ in found)]
    for a in areas:  # a module name must not collide with a local of make_handler
        assert not re.search(rf"^    {a} = ", server, re.M), f"make_handler has a local {a}"
    names = sorted(shared_names - set(REEXPORT)) + areas
    server = re.sub(
        r"^(from \. import .*)$",
        lambda m: (
            m.group(1) + "\nfrom .routes import (\n" + "".join(f"    {n},\n" for n in names) + ")"
        ),
        server,
        count=1,
        flags=re.M,
    )
    for name in REEXPORT:
        server = server.replace(
            "\nfrom .routes import ",
            f"\nfrom .routes import {name} as {name}  # the tests import it from here\n"
            "from .routes import ",
            1,
        )
    for old, new in (
        (
            "    routes: list[tuple[str, re.Pattern, str, str, bool]] = []",
            "    routes: list[tuple[str, re.Pattern, Callable, str, bool]] = []",
        ),
        (
            '            routes.append((method, re.compile(f"^{pattern}$"), fn.__name__, access,'
            " raw))",
            '            routes.append((method, re.compile(f"^{pattern}$"), fn, access, raw))',
        ),
        (
            "                for m, pattern, name, access, raw in routes:",
            "                for m, pattern, fn, access, raw in routes:",
        ),
        (
            "                    out = getattr(self, name)(viewer, body, *match.groups())",
            "                    out = fn(self, viewer, body, *match.groups())",
        ),
        (
            "from pathlib import Path\n",
            "from collections.abc import Callable\nfrom pathlib import Path\n",
        ),
        (
            "\n    return Handler",
            "\n    # the rest of /api, by area; same table, same order as before the split\n"
            "    for area in (" + ", ".join(areas) + "):\n"
            "        area.install(route, store, auth, drive, meta)\n"
            "    return Handler",
        ),
    ):
        assert old in server, old[:50]
        server = server.replace(old, new, 1)
    path.write_text(re.sub(r"\n{3,}(?=\S)", "\n\n\n", server))
    return areas


# ---------------------------------------------------------------- app.js
JS_FILES = [  # (section marker prefix, file)
    ("dashboard", "requests"),
    ("board", "requests"),
    ("list", "requests"),
    ("one request", "requests"),
    ("files (stored in OneDrive)", "requests"),
    ("new request", "requests"),
    ("clients", "clients"),
    ("financeiro", "financeiro"),
    ("campanhas", "campanhas"),
    ("team, account, settings", "team"),
    ("moving to a new address", "team"),
    ("passkeys", "team"),
    ("gate: login and join", "team"),
    ("perfil", "perfil"),
    ("router", "router"),
    ("start", "router"),
]
JS_DOC = {
    "requests": "the dashboard, the board, the list, one request and its files, a new request",
    "clients": "the clients list and one client",
    "financeiro": "Financeiro (decision 7)",
    "campanhas": "Campanhas (decision 8)",
    "team": "Equipe and Configurações, the account menu, moving house, passkeys, the login and"
    " join gate",
    "perfil": "Perfil (decision 10): the person's own name, e-mail, WhatsApp and passkeys",
    "router": "the hash router and start-up; loaded last, after every screen it routes to",
}
SHARED_NOTE = (
    "// This file is the shared part (helpers, the shell); the screens are app-<area>.js and the\n"
    "// router is app-router.js, loaded in that order by index.html (one global scope, no modules)."
)


def split_js() -> list[str]:
    """Returns the screen files written, in load order ([] when already split)."""
    path = src / "static/app.js"
    js = path.read_text()
    marker = re.compile(r"^// ---------- (.+?) -+\n", re.M)
    marks = list(marker.finditer(js))
    sections = {}
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(js)
        sections[m.group(1)] = (m.start(), stop)
    files: dict[str, list[str]] = {}
    removed = []
    for prefix, file in JS_FILES:
        name = next((n for n in sections if n.startswith(prefix)), None)
        if not name:
            continue
        start, stop = sections[name]
        files.setdefault(file, []).append(js[start:stop].rstrip("\n") + "\n")
        removed.append((start, stop))
    if not files:
        print("app.js: already split")
        return []
    for start, stop in sorted(removed, reverse=True):
        js = js[:start] + js[stop:]
    if SHARED_NOTE not in js:
        js = js.replace(
            "// Pauta: one small single-page app. Routes are #/..., data comes from /api, nothing"
            " else.",
            "// Pauta: one small single-page app. Routes are #/..., data comes from /api, nothing"
            " else.\n" + SHARED_NOTE,
        )
    path.write_text(js.rstrip("\n") + "\n")
    order = [f for f in dict.fromkeys(f for _, f in JS_FILES) if f in files]
    for file in order:
        head = f'"use strict";\n// Pauta: {JS_DOC[file]}.\n'
        head += "// Shares app.js's globals; index.html loads it after app.js.\n\n"
        (src / f"static/app-{file}.js").write_text(head + "\n".join(files[file]))
    return order


def wire(order: list[str]) -> None:
    """index.html, lint and the wheel check: rebuilt from `order`, never appended twice."""
    html = src / "static/index.html"
    t = re.sub(r'  <script src="/app-[\w-]+\.js"></script>\n', "", html.read_text())
    tags = "".join(f'  <script src="/app-{f}.js"></script>\n' for f in order)
    html.write_text(
        t.replace(
            '  <script src="/app.js"></script>\n', '  <script src="/app.js"></script>\n' + tags
        )
    )
    mk = repo / "Makefile"
    mk.write_text(
        mk.read_text().replace(
            "node --check src/pauta/static/app.js",
            'for f in src/pauta/static/app*.js; do node --check "$$f"; done',
        )
    )
    ci = repo / ".github/workflows/ci.yml"
    t = ci.read_text().replace(
        "node --check src/pauta/static/app.js",
        'for f in src/pauta/static/app*.js; do node --check "$f"; done',
    )
    t = re.sub(
        r"for f in index\.html app\.js (?:app-[\w-]+\.js \\?\s*)*style\.css",
        "for f in index.html app.js "
        + " ".join(f"app-{f}.js" for f in order)
        + " \\\n                   style.css",
        t,
    )
    ci.write_text(t)


areas = split_server()
screens = split_js()
if screens:
    wire(screens)
print("routes:", ", ".join(areas) or "-", "| screens:", ", ".join(screens) or "-")
