"""The client's link to a report over HTTP (decision 12): making one needs a session and a
valid card, the public data and page open without one and carry only the card, unknown,
expired and revoked tokens are a plain 404 page, Revogar, and the rate limits."""

import http.client
from urllib.parse import urlparse

import pytest
from test_campaigns_api import synced

from fakemeta import CONVERSATIONS
from pauta.ratelimit import RateLimiter
from softpasskey import ORIGIN, SoftPasskey, call, join, start


@pytest.fixture()
def meta(meta_on):
    return meta_on


def raw(base, method, path, headers=None):
    u = urlparse(base)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=5)
    try:
        conn.request(method, path, headers=headers or {})
        r = conn.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        conn.close()


def clinic_campaign(base, cookie) -> tuple[int, int]:
    """The clinic's campaign id and the clinic's id."""
    doc = call(f"{base}/api/campaigns", cookie=cookie)[1]
    k = {x["meta_id"]: x for c in doc["clients"] for x in c["campaigns"]}
    return k["23850001"]["id"], k["23850001"]["client"]


PERIOD = {"since": "2026-10-10", "until": "2026-10-12"}
NOBODY = "nobody-made-this-one-at-all-0123456789abcdef"


def test_making_a_link_needs_a_session_and_a_valid_card(team, fake_meta):
    base, nato, piero, _ = synced(team, fake_meta)
    cid, _ = clinic_campaign(base, piero)
    body = {**PERIOD, "metrics": ["results", "cpr", "spend"]}
    assert call(f"{base}/api/campaigns/{cid}/links", body)[0] == 401
    assert call(f"{base}/api/campaigns/999/links", body, piero)[0] == 404
    for bad, text in [
        ({"metrics": ["results"]}, "período"),
        ({**PERIOD, "metrics": []}, "métrica"),
        ({**PERIOD, "metrics": ["budget"]}, "desconhecida"),
        ({**PERIOD, "metrics": ["act:Lead"]}, "desconhecida"),
        ({**PERIOD, "metrics": "results"}, "métrica"),
        ({"since": "2026-10-12", "until": "2026-10-10", "metrics": ["results"]}, "depois"),
        ({"since": "2025-01-01", "until": "2026-10-10", "metrics": ["results"]}, "grande"),
        ({"since": "10/10/2026", "until": "2026-10-12", "metrics": ["results"]}, "inválida"),
    ]:
        status, doc, _ = call(f"{base}/api/campaigns/{cid}/links", bad, piero)
        assert status == 400 and text in doc["error"], (bad, doc)
    status, link, _ = call(f"{base}/api/campaigns/{cid}/links", body, piero)
    assert status == 200, link
    assert link["url"] == f"{base}/r/{link['token']}" and len(link["token"]) >= 32
    assert link["metrics"] == ["results", "cpr", "spend"] and link["live"]
    assert link["since"] == "2026-10-10" and link["until"] == "2026-10-12"
    assert link["by_name"] == "Piero" and link["created_by"] == 2
    assert link["expires"] > link["created"] and link["revoked"] is None
    assert link["reach"] is None  # no reach tile: Meta wasn't asked
    # the link_click action is the Cliques no link tile: the card has no chip for it
    aliased = call(
        f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["act:link_click"]}, piero
    )[1]
    assert aliased["metrics"] == ["leads"]
    # the same card again is the same link; the campaign carries its links
    assert call(f"{base}/api/campaigns/{cid}/links", body, piero)[1]["token"] == link["token"]
    doc = call(f"{base}/api/campaigns/{cid}?since=2026-10-10&until=2026-10-12", cookie=nato)[1]
    assert [x["token"] for x in doc["links"]] == [aliased["token"], link["token"]]  # newest first
    assert doc["links"][1]["url"] == link["url"]
    # a reach tile reads Meta once, when the link is made, and keeps the number
    with_reach = call(f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["reach"]}, piero)[
        1
    ]
    assert with_reach["reach"] == 500 * 3
    # the address is the one the app is open on (production: app.pauta.cc through Caddy)
    status, doc, _ = call(
        f"{base}/api/campaigns/{cid}/links",
        {**PERIOD, "metrics": ["leads"]},
        piero,
        headers={"Origin": ORIGIN},
    )
    assert status == 200 and doc["url"] == f"{ORIGIN}/r/{doc['token']}"


def test_the_public_data_is_open_and_carries_the_card_only(team, fake_meta):
    base, nato, piero, m = synced(team, fake_meta)
    cid, clinic = clinic_campaign(base, piero)
    call(
        f"{base}/api/clients/{clinic}",
        {"whatsapp": "(11) 98888-7777", "contact": "Carla Mendes"},
        nato,
        "PATCH",
    )
    link = call(
        f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["results", "cpr"]}, piero
    )[1]
    status, doc, headers = call(f"{base}/api/r/{link['token']}")  # no cookie
    assert status == 200, doc
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Robots-Tag"] == "noindex, nofollow"
    assert doc == {
        "since": "2026-10-10",
        "until": "2026-10-12",
        "metrics": ["results", "cpr"],
        "last_sync": m["last_sync"],
        "prepared_by": "Piero",
        "expires": link["expires"],
        "campaign": {
            "name": "Limpeza de pele novembro",
            "client_name": "Clínica Bem Estar",
            "state": "active",
            "ended": None,
            "currency": "BRL",
            "results": 6,
            "result_indicator": CONVERSATIONS,
            "cost_per_result_cents": round((1010 + 1011 + 1012) / 6),
            "days": [
                {"day": f"2026-10-{d}", "spend_cents": 1000 + d, "results": 2} for d in (10, 11, 12)
            ],
        },
    }
    # the team's view of the same campaign has the rest; the public one never does
    full = call(f"{base}/api/campaigns/{cid}?since=2026-10-10&until=2026-10-12", cookie=piero)[1]
    for key in ("client_whatsapp", "client_contact", "account_id", "meta_id", "client"):
        assert key in full["campaign"] and key not in doc["campaign"], key
    assert "98888" not in str(doc) and "Carla" not in str(doc) and "23850001" not in str(doc)
    assert "spend_cents" in doc["campaign"]["days"][0]  # cpr's bars need it...
    assert "spend_cents" not in doc["campaign"]  # ...but the period's spend is not a tile
    assert "impressions" not in doc["campaign"] and "link_clicks" not in doc["campaign"]
    # HEAD works on the page (a preview may ask), not on the data (as every /api); the
    # page takes nothing but GET
    status, headers, body = raw(base, "HEAD", f"/r/{link['token']}")
    assert status == 200 and body == b"" and int(headers["Content-Length"]) > 1000
    assert raw(base, "HEAD", f"/api/r/{link['token']}")[0] == 405
    for method in ("POST", "PUT", "DELETE"):
        assert raw(base, method, f"/r/{link['token']}")[0] == 405, method
    # a reach tile shows the number read when the link was made: opening never asks Meta
    with_reach = call(
        f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["reach", "freq"]}, piero
    )[1]
    seen = len(fake_meta.seen)
    doc = call(f"{base}/api/r/{with_reach['token']}")[1]
    assert doc["campaign"]["reach"] == 500 * 3 and doc["campaign"]["impressions"] == 3300
    assert len(fake_meta.seen) == seen


def test_the_public_page_has_the_preview_and_the_card_scripts(site, team, fake_meta):
    _, _, store = site
    base, nato, piero, _ = synced(team, fake_meta)
    cid, _ = clinic_campaign(base, piero)
    link = call(
        f"{base}/api/campaigns/{cid}/links",
        {**PERIOD, "metrics": ["results", "cpr", "spend"]},
        piero,
        headers={"Origin": ORIGIN},
    )[1]
    status, headers, body = raw(base, "GET", f"/r/{link['token']}")
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert headers["Cache-Control"] == "no-store"
    assert headers["X-Robots-Tag"] == "noindex, nofollow"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]
    page = body.decode()
    title = "Relatório da campanha Limpeza de pele novembro · Clínica Bem Estar · 10 out – 12 out"
    assert f"<title>{title}</title>" in page
    assert f'<meta property="og:title" content="{title}">' in page
    assert f'<meta property="og:url" content="{base}/r/{link["token"]}">' in page
    assert f'<meta property="og:image" content="{base}/og.png">' in page
    assert (
        'content="3 métricas da campanha, com os dados da Meta, preparado na Pauta. '
        'O link vale por 5 dias."' in page
    )
    assert '<meta name="robots" content="noindex, nofollow">' in page
    assert "{{" not in page
    for script in ("/app.js", "/app-campanhas.js", "/app-report.js"):
        assert f'<script src="{script}"></script>' in page
    assert "98888" not in page and "23850001" not in page
    # a campaign name with markup in it is text in the page
    with store.db() as db:
        db.execute("UPDATE campaign SET name=? WHERE id=?", ('<b>Promo</b> & "Natal"', cid))
    page = raw(base, "GET", f"/r/{link['token']}")[2].decode()
    assert "<b>Promo</b>" not in page
    assert "Relatório da campanha &lt;b&gt;Promo&lt;/b&gt; &amp; &quot;Natal&quot; ·" in page


def test_unknown_expired_and_revoked_links_are_a_plain_404_page(site, team, fake_meta):
    _, _, store = site
    base, nato, piero, _ = synced(team, fake_meta)
    cid, _ = clinic_campaign(base, piero)
    gone = "Este relatório não está mais disponível"
    for path in (f"/r/{NOBODY}", "/r/short", "/r/", "/r/has%20a%20space-in-it-0123456789abcdef"):
        status, headers, body = raw(base, "GET", path)
        assert status == 404, path
        assert headers["Content-Type"] == "text/html; charset=utf-8"
        assert headers["Cache-Control"] == "no-store"
        assert gone in body.decode() and "<script" not in body.decode(), path
    assert call(f"{base}/api/r/{NOBODY}")[0] == 404
    assert call(f"{base}/api/r/short")[0] == 404
    # expired
    link = call(f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["spend"]}, piero)[1]
    assert call(f"{base}/api/r/{link['token']}")[0] == 200
    with store.db() as db:
        db.execute(
            "UPDATE report_link SET expires='2020-01-01 00:00:00' WHERE token=?", (link["token"],)
        )
    assert call(f"{base}/api/r/{link['token']}")[0] == 404
    assert raw(base, "GET", f"/r/{link['token']}")[0] == 404
    doc = call(f"{base}/api/campaigns/{cid}?since=2026-10-10&until=2026-10-12", cookie=piero)[1]
    assert doc["links"][0]["live"] is False and doc["links"][0]["revoked"] is None
    # revoked: needs a session, the campaign's own link, and then it is a 404 for good
    link = call(f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["spend"]}, piero)[1]
    assert link["live"] and raw(base, "GET", f"/r/{link['token']}")[0] == 200
    revoke = f"{base}/api/campaigns/{cid}/links/{link['token']}"
    assert call(revoke, method="DELETE")[0] == 401
    assert (
        call(f"{base}/api/campaigns/{cid + 1}/links/{link['token']}", cookie=nato, method="DELETE")[
            0
        ]
        == 404
    )
    assert (
        call(f"{base}/api/campaigns/{cid}/links/{NOBODY}", cookie=nato, method="DELETE")[0] == 404
    )
    status, row, _ = call(revoke, cookie=nato, method="DELETE")
    assert status == 200 and row["live"] is False and len(row["revoked"]) == 19
    assert row["url"] == link["url"]
    assert call(f"{base}/api/r/{link['token']}")[0] == 404
    assert raw(base, "GET", f"/r/{link['token']}")[0] == 404
    # again: the same row, nothing changes
    assert call(revoke, cookie=nato, method="DELETE")[1]["revoked"] == row["revoked"]
    # the next ask for the same card is a new link
    fresh = call(f"{base}/api/campaigns/{cid}/links", {**PERIOD, "metrics": ["spend"]}, piero)[1]
    assert fresh["token"] != link["token"] and fresh["live"]
    # the export never carries tokens
    assert "report_link" not in call(f"{base}/api/export", cookie=nato)[1]
    assert link["token"] not in str(call(f"{base}/api/export", cookie=nato)[1])


def test_guesses_and_link_making_are_rate_limited(store, auth):
    """A guess at a token (page or data) counts like a login attempt; making a link counts
    like an invite."""
    httpd, base = start(store, auth, RateLimiter({"login": (2, 60), "invite": (1, 60)}))
    try:
        codes = [raw(base, "GET", f"/r/{NOBODY}")[0] for _ in range(3)]
        assert codes == [404, 404, 429]
        assert call(f"{base}/api/r/{NOBODY}")[0] == 429
        token, _ = auth.create_invite(admin=True)
        status, _, nato = join(base, token, "Renato Lima", SoftPasskey())
        assert status == 200
        body = {**PERIOD, "metrics": ["spend"]}
        codes = [call(f"{base}/api/campaigns/1/links", body, nato)[0] for _ in range(2)]
        assert codes == [404, 429]  # no campaign 1 here: the limit comes before the lookup
    finally:
        httpd.shutdown()
        httpd.server_close()
