"""Score pages against YSlow's V2 ruleset: its 23 rules, penalties and weights, as written
in yslow/src/common/rules.js (github.com/marcelduran/yslow). Not YSlow's own code: the same
rules applied to a real Chromium page load (Playwright, the browser tests' dependency).

    uv run --extra e2e python tools/yslow_audit.py LABEL [--cookie NAME=VALUE] [--assume-gzip] \\
        NAME=URL ...

Prints a table (overall score and grade per page, then each rule) and what each rule found,
and writes one JSON file per page to test-results/yslow/LABEL/.

--cookie       a session cookie, for the signed-in screens of a local or acceptance copy
--assume-gzip  the server has no proxy in front (a local `pauta serve`): count text answers
               of 500 bytes or more as compressed, as Caddy does in production
"""

import json
import re
import sys
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

WEIGHTS = {
    "ynumreq": 8,
    "ycdn": 6,
    "yemptysrc": 30,
    "yexpires": 10,
    "ycompress": 8,
    "ycsstop": 4,
    "yjsbottom": 4,
    "yexpressions": 3,
    "yexternal": 4,
    "ydns": 3,
    "yminify": 4,
    "yredirects": 4,
    "ydupes": 4,
    "yetags": 2,
    "yxhr": 4,
    "yxhrmethod": 3,
    "ymindom": 3,
    "yno404": 4,
    "ymincookie": 3,
    "ycookiefree": 3,
    "ynofilter": 4,
    "yimgnoscale": 3,
    "yfavicon": 2,
}
NAMES = {
    "ynumreq": "Make fewer HTTP requests",
    "ycdn": "Use a CDN",
    "yemptysrc": "Avoid empty src or href",
    "yexpires": "Add Expires headers",
    "ycompress": "Compress components with gzip",
    "ycsstop": "Put CSS at top",
    "yjsbottom": "Put JavaScript at bottom",
    "yexpressions": "Avoid CSS expressions",
    "yexternal": "Make JS and CSS external",
    "ydns": "Reduce DNS lookups",
    "yminify": "Minify JavaScript and CSS",
    "yredirects": "Avoid URL redirects",
    "ydupes": "Remove duplicate JS and CSS",
    "yetags": "Configure ETags",
    "yxhr": "Make AJAX cacheable",
    "yxhrmethod": "Use GET for AJAX",
    "ymindom": "Reduce the number of DOM elements",
    "yno404": "Avoid HTTP 404",
    "ymincookie": "Reduce cookie size",
    "ycookiefree": "Use cookie-free domains",
    "ynofilter": "Avoid AlphaImageLoader",
    "yimgnoscale": "Do not scale images in HTML",
    "yfavicon": "Make favicon small and cacheable",
}
CDN_SERVERS = re.compile(r"cloudflare|cloudfront|akamai|fastly|github\.com|netlify|vercel", re.I)

DOM_FACTS = """() => {
  const abs = (u) => { try { return new URL(u, location.href).href } catch { return u } };
  const q = (s) => [...document.querySelectorAll(s)];
  return {
    elements: document.getElementsByTagName('*').length,
    cssInBody: q('body link[rel~=stylesheet]').map(l => abs(l.href)),
    jsInHead: q('head script[src]').filter(s => !s.defer && !s.async && s.type !== 'module')
      .map(s => abs(s.src)),
    inlineScripts: q('script:not([src])').filter(s => !/json/.test(s.type))
      .map(s => s.textContent),
    inlineStyles: q('style').map(s => s.textContent),
    emptySrc: q('img[src=""], script[src=""], link[href=""]').length,
    imgs: q('img').map(i => abs(i.currentSrc || i.src)),
    scaled: q('img[width][height]').filter(i => i.naturalWidth
      && (i.naturalWidth !== +i.getAttribute('width')
        || i.naturalHeight !== +i.getAttribute('height')))
      .map(i => abs(i.currentSrc || i.src) + ` ${i.naturalWidth}x${i.naturalHeight} shown `
        + `${i.getAttribute('width')}x${i.getAttribute('height')}`),
    favicon: abs((document.querySelector('link[rel~=icon]') || {}).href || '/favicon.ico'),
    scripts: q('script[src]').map(s => abs(s.src)),
    sheets: q('link[rel~=stylesheet]').map(l => abs(l.href)),
  };
}"""


def is_minified(body: str) -> bool:
    """YSLOW.util.isMinified: at most 20% of the text is newlines, tabs and double spaces."""
    if not body:
        return True
    stripped = re.sub(r"\n| {2}|\t|\r", "", body)
    return (len(body) - len(stripped)) / len(body) <= 0.2


def lifetime(headers: dict, now: float) -> float | None:
    """Seconds the answer stays fresh: Cache-Control max-age, else Expires. None: no such header."""
    cc = headers.get("cache-control", "")
    if m := re.search(r"max-age=(\d+)", cc):
        return float(m.group(1))
    if exp := headers.get("expires"):
        try:
            return parsedate_to_datetime(exp).timestamp() - now
        except (TypeError, ValueError):
            return None
    return None


def grade(score: float) -> str:
    return next(
        g
        for floor, g in ((90, "A"), (80, "B"), (70, "C"), (60, "D"), (50, "E"), (-1e9, "F"))
        if score >= floor
    )


def capture(page, url, assume_gzip):
    comps, now = [], time.time()

    def on_response(resp):
        req = resp.request
        headers = {k.lower(): v for k, v in resp.headers.items()}
        try:
            body = resp.body() if not (300 <= resp.status < 400) else b""
        except Exception:
            body = b""
        comps.append(
            {
                "url": resp.url,
                "method": req.method,
                "rtype": req.resource_type,
                "status": resp.status,
                "headers": headers,
                "size": len(body),
                "body": body,
                "cookie": req.all_headers().get("cookie", ""),
                "redirected": req.redirected_from is not None,
            }
        )

    page.on("response", on_response)
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1200)
    dom = page.evaluate(DOM_FACTS)
    page.remove_listener("response", on_response)

    seen = {c["url"] for c in comps}
    if dom["favicon"] not in seen:  # Chromium fetches it outside the page's own requests
        r = page.context.request.get(dom["favicon"])
        body = r.body() if r.ok else b""
        comps.append(
            {
                "url": dom["favicon"],
                "method": "GET",
                "rtype": "favicon",
                "status": r.status,
                "headers": {k.lower(): v for k, v in r.headers.items()},
                "size": len(body),
                "body": body,
                "cookie": "",
                "redirected": False,
            }
        )
    doc_host = urlparse(page.url).hostname
    for c in comps:
        t = c["rtype"]
        ctype = c["headers"].get("content-type", "")
        c["type"] = (
            "favicon"
            if c["url"] == dom["favicon"]
            else "doc"
            if t == "document"
            else "js"
            if t == "script"
            else "css"
            if t == "stylesheet"
            else "xhr"
            if t in ("xhr", "fetch")
            else ("image" if c["url"] in dom["imgs"] else "cssimage")
            if t == "image"
            else t
        )
        enc = c["headers"].get("content-encoding", "")
        text = re.match(r"text/|application/(json|javascript)|image/svg", ctype) is not None
        c["compressed"] = bool(enc) or (
            assume_gzip and text and c["size"] >= 500 and urlparse(c["url"]).hostname == doc_host
        )
        c["life"] = lifetime(c["headers"], now)
        c["text"] = c.pop("body").decode("utf-8", "replace") if text else ""
    return comps, dom, page.url


def score(comps, dom, final_url):
    def by(*types):
        return [c for c in comps if c["type"] in types and c["status"] < 300]

    def short(c):
        return urlparse(c["url"]).path.rsplit("/", 1)[-1] or c["url"]

    out = {}

    def rule(rid, sc, offenders=(), note=""):
        out[rid] = {"score": max(0, min(100, sc)), "offenders": list(offenders), "note": note}

    js, css, cssimg = by("js"), by("css"), by("cssimage")
    sc = 100 - max(0, len(js) - 3) * 4 - max(0, len(css) - 2) * 4 - max(0, len(cssimg) - 6) * 3
    rule(
        "ynumreq",
        sc,
        note=f"{len(js)} scripts, {len(css)} stylesheets, {len(cssimg)} background images",
    )

    static = by("js", "css", "image", "cssimage", "flash", "favicon")
    off = [
        short(c)
        for c in static
        if not CDN_SERVERS.search(
            c["headers"].get("server", "")
            + c["headers"].get("via", "")
            + c["headers"].get("x-served-by", "")
        )
    ]
    rule("ycdn", 100 - len(off) * 10, off)
    rule("yemptysrc", 100 - dom["emptySrc"] * 100)
    off = [
        f"{short(c)} ({'no lifetime' if c['life'] is None else str(int(c['life'])) + ' s'})"
        for c in static
        if c["life"] is None or c["life"] <= 172800
    ]
    rule("yexpires", 100 - len(off) * 11, off)
    off = [
        f"{short(c)} ({c['size']} B)"
        for c in by("doc", "iframe", "xhr", "js", "css")
        if not c["compressed"] and c["size"] >= 500
    ]
    rule("ycompress", 100 - len(off) * 11, off)
    rule(
        "ycsstop",
        100 - (1 + len(dom["cssInBody"]) * 10 if dom["cssInBody"] else 0),
        dom["cssInBody"],
    )
    rule("yjsbottom", 100 - len(dom["jsInHead"]) * 5, dom["jsInHead"])
    rule("yexpressions", 100)
    inline = sum(len(s) for s in dom["inlineScripts"] + dom["inlineStyles"])
    rule(
        "yexternal",
        100,
        note=f"not scored by YSlow (advice only); {len(dom['inlineScripts'])} inline scripts, "
        f"{len(dom['inlineStyles'])} inline styles, {inline} chars",
    )
    hosts = sorted({urlparse(c["url"]).hostname for c in comps})
    rule(
        "ydns",
        100 - max(0, len(hosts) - 4) * 5,
        hosts if len(hosts) > 4 else [],
        f"{len(hosts)} hosts",
    )
    off = [short(c) for c in by("js", "css") if not is_minified(c["text"])]
    off += [
        f"inline <style> #{i + 1}" for i, s in enumerate(dom["inlineStyles"]) if not is_minified(s)
    ]
    off += [
        f"inline <script> #{i + 1}"
        for i, s in enumerate(dom["inlineScripts"])
        if not is_minified(s)
    ]
    rule("yminify", 100 - len(off) * 10, off)
    off = [c["url"] for c in comps if 300 <= c["status"] < 400 and c["status"] != 304]
    rule("yredirects", 100 - len(off) * 10, off)
    urls = dom["scripts"] + dom["sheets"]
    off = sorted({u for u in urls if urls.count(u) > 1})
    rule("ydupes", 100 - len(off) * 5, off)
    bad = re.compile(r"^[0-9a-f]+-[0-9a-f]+-[0-9a-f]+$|^[0-9a-f]+:[0-9a-f]+$")  # Apache inode, IIS
    off = [
        short(c)
        for c in by("flash", "js", "css", "cssimage", "image", "favicon")
        if (e := c["headers"].get("etag", "").strip('W/"')) and bad.match(e)
    ]
    rule("yetags", 100 - len(off) * 11, off)
    xhr = by("xhr")
    off = [
        short(c)
        for c in xhr
        if c["method"] == "GET"
        and not re.search(r"no-cache|no-store", c["headers"].get("cache-control", ""))
        and not (c["life"] is not None and c["life"] > 3600)
    ]
    rule("yxhr", 100 - len(off) * 5, off, f"{len(xhr)} XHR answers")
    off = [f"{c['method']} {short(c)}" for c in xhr if c["method"] != "GET"]
    rule("yxhrmethod", 100 - len(off) * 5, off)
    n = dom["elements"]
    rule("ymindom", 100 if n <= 900 else 99 - -(-(n - 900) // 250) * 10, note=f"{n} elements")
    off = [c["url"] for c in comps if c["status"] == 404]
    rule("yno404", 100 - len(off) * 5, off)
    cookie = max(
        (
            len(c["cookie"])
            for c in comps
            if urlparse(c["url"]).hostname == urlparse(final_url).hostname
        ),
        default=0,
    )
    rule(
        "ymincookie",
        100 if cookie <= 1000 else 99 - (cookie // 1000) * 10,
        note=f"{cookie} bytes of cookies",
    )
    off = [short(c) for c in by("js", "css", "image", "cssimage", "flash") if c["cookie"]]
    rule("ycookiefree", 100 - len(off) * 5, off)
    rule("ynofilter", 100)
    rule("yimgnoscale", 100 - len(dom["scaled"]) * 5, dom["scaled"])
    fav = [c for c in comps if c["type"] == "favicon"]
    msgs = []
    if fav:
        f = fav[0]
        if f["status"] == 404:
            msgs.append("not found")
        if f["size"] > 2000:
            msgs.append(f"{f['size']} bytes (over 2000)")
        if not (f["life"] is not None and f["life"] >= 3600):
            msgs.append("not cacheable for an hour" if f["status"] != 404 else "")
    msgs = [m for m in msgs if m]
    rule("yfavicon", 100 - len(msgs) * 5, msgs)

    total = sum(out[r]["score"] * w for r, w in WEIGHTS.items()) / sum(WEIGHTS.values())
    weight = sum(c["size"] for c in comps)
    return {
        "overall": round(total),
        "grade": grade(total),
        "requests": len(comps),
        "bytes": weight,
        "rules": out,
    }


def main():
    args = sys.argv[1:]
    label = args.pop(0)
    cookie = None
    assume = False
    while args and args[0].startswith("--"):
        flag = args.pop(0)
        if flag == "--cookie":
            cookie = args.pop(0)
        elif flag == "--assume-gzip":
            assume = True
    outdir = Path("test-results/yslow") / label
    outdir.mkdir(parents=True, exist_ok=True)
    rows = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for spec in args:
            name, url = spec.split("=", 1)
            ctx = browser.new_context(locale="pt-BR", viewport={"width": 1440, "height": 900})
            if cookie:
                k, v = cookie.split("=", 1)
                origin = "{0.scheme}://{0.netloc}".format(urlparse(url))
                ctx.add_cookies([{"name": k, "value": v, "url": origin}])
            page = ctx.new_page()
            comps, dom, final = capture(page, url, assume)
            res = score(comps, dom, final)
            res["url"] = final
            res["components"] = [
                {k: c[k] for k in ("url", "type", "status", "size", "compressed", "life")}
                | {"cache": c["headers"].get("cache-control", "")}
                for c in comps
            ]
            (outdir / f"{name}.json").write_text(json.dumps(res, indent=1, ensure_ascii=False))
            rows[name] = res
            ctx.close()
        browser.close()
    rules = list(WEIGHTS)
    print(
        f"{'page':14}{'score':>6} {'req':>4} {'KB':>6}  " + " ".join(r[1:6].ljust(5) for r in rules)
    )
    for name, res in rows.items():
        print(
            f"{name:14}{res['overall']:>4} {res['grade']} {res['requests']:>4} "
            f"{res['bytes'] / 1024:>6.0f}  "
            + " ".join(
                f"{grade(res['rules'][r]['score'])}{res['rules'][r]['score']:<4.0f}" for r in rules
            )
        )
    for name, res in rows.items():
        print(f"\n== {name}  {res['url']}")
        for r in rules:
            x = res["rules"][r]
            if x["score"] < 100 or x["note"]:
                found = "; ".join(map(str, x["offenders"][:14]))
                print(f"  {grade(x['score'])} {x['score']:>3.0f}  {NAMES[r]}: {x['note']} {found}")


main()
