"""Static files as the pages name them: one script per page, at addresses that cache for good.

There is no build step, so the server does two things when it serves a page:

- Every local `src`/`href` in a page (and `url(/...)` in a stylesheet) gets `?v=<tag>`, the
  start of the file's SHA-256. An address carrying the file's current tag is served with a
  year of cache (`immutable`): the browser never asks again, and a file that changes has a
  new address, so nobody waits for a cache to run out after a release.
- The scripts between `<!-- bundle NAME -->` and `<!-- /bundle -->` are served as one file,
  `/NAME`, in the order the page lists them. The source stays one file per screen, each
  still served on its own.

Everything is worked out from the files as they are on disk and kept until one of them
changes, so an edit shows on the next reload while developing.
"""

import hashlib
import re
import threading
from pathlib import Path

STATIC = Path(__file__).parent / "static"
PAGES = ("index.html", "report.html", "report-gone.html")
FOREVER = "public, max-age=31536000, immutable"

_BUNDLE = re.compile(r"([ \t]*)<!-- bundle (\S+) -->\n(.*?)[ \t]*<!-- /bundle -->\n", re.S)
_SCRIPT = re.compile(r'<script src="/([^"?#]+)"></script>')
_REF = re.compile(r'\b(src|href)="/([^"?#]+)"')
_CSS_URL = re.compile(r"url\(/([^)\"'?#]+)\)")

_lock = threading.Lock()
_stamp: tuple = ()
_kept: dict = {}


def _keep(key, make):
    """`make()`, remembered until a file under static/ changes (or is added or removed)."""
    global _stamp
    stamp = tuple(
        sorted((str(p), s.st_mtime_ns, s.st_size) for p in STATIC.rglob("*") if (s := p.stat()))
    )
    with _lock:
        if stamp != _stamp:
            _stamp = stamp
            _kept.clear()
        if key in _kept:
            return _kept[key]
    value = make()
    with _lock:
        if stamp == _stamp and value is not None:  # a miss is not kept: anyone can ask for one
            _kept[key] = value
    return value


def _file(rel: str) -> Path | None:
    target = (STATIC / rel).resolve()
    return target if STATIC.resolve() in target.parents and target.is_file() else None


def bundles() -> dict[str, list[str]]:
    """The scripts each page serves as one file: `{"app.bundle.js": ["app.js", ...]}`."""

    def read():
        found: dict[str, list[str]] = {}
        for name in PAGES:
            for _, bundle, block in _BUNDLE.findall((STATIC / name).read_text(encoding="utf-8")):
                found[bundle] = _SCRIPT.findall(block)
        return found

    return _keep("bundles", read)


def content(rel: str) -> bytes | None:
    """What `/<rel>` serves: a file under static/ (a stylesheet with its `url(/...)` tagged),
    or a bundle. None when there is no such file."""

    def read():
        if rel in bundles():
            return b"\n;\n".join(
                f"// ---- {src}\n".encode() + (STATIC / src).read_bytes() for src in bundles()[rel]
            )
        target = _file(rel)
        if target is None:
            return None
        if target.suffix == ".css":
            css = target.read_text(encoding="utf-8")
            return _CSS_URL.sub(lambda m: f"url({url(m[1])})", css).encode()
        return target.read_bytes()

    return _keep(("content", rel), read)


def tag(rel: str) -> str:
    """The `?v=` of `/<rel>` as it is now; empty when there is no such file."""
    body = content(rel)
    return hashlib.sha256(body).hexdigest()[:12] if body is not None else ""


def url(rel: str) -> str:
    """`/<rel>?v=<tag>`: the address to put in a page (unchanged for a file we don't have)."""
    t = tag(rel)
    return f"/{rel}?v={t}" if t else f"/{rel}"


def cache_for(rel: str, asked: str | None) -> str:
    """Cache-Control for `/<rel>` asked with `?v=<asked>` (None: no `v` at all). Only the
    current tag is kept for good: an old page asking for a file under its old tag must not
    pin today's file to that address."""
    if asked is None:
        return "public, max-age=300"
    return FOREVER if asked == tag(rel) else "no-cache"


def page(name: str) -> str:
    """The HTML of static/<name> as it is served: each bundle one script, addresses tagged."""

    def render():
        html = (STATIC / name).read_text(encoding="utf-8")
        html = _BUNDLE.sub(lambda m: f'{m[1]}<script src="/{m[2]}"></script>\n', html)
        return _REF.sub(lambda m: f'{m[1]}="{url(m[2])}"', html)

    return _keep(("page", name), render)
