"""Static files as the pages name them: one script per page, tagged addresses, long cache."""

import re
import shutil

import pytest

from pauta import assets


@pytest.fixture()
def static(tmp_path, monkeypatch):
    """A copy of static/ to edit, in place of the real one."""
    root = tmp_path / "static"
    shutil.copytree(assets.STATIC, root)
    monkeypatch.setattr(assets, "STATIC", root)
    return root


def test_the_shell_loads_one_script_and_every_address_is_tagged():
    page = assets.page("index.html")
    scripts = re.findall(r'<script src="([^"]+)"></script>', page)
    assert scripts == [assets.url("app.bundle.js")] and "?v=" in scripts[0]
    assert "<!-- bundle" not in page and "<!-- /bundle" not in page
    refs = re.findall(r'(?:src|href)="(/[^"]+)"', page)
    assert len(refs) == 6  # three icons, the manifest, the stylesheet, the script
    for ref in refs:
        rel, tag = ref.lstrip("/").split("?v=")
        assert tag == assets.tag(rel) and re.fullmatch(r"[0-9a-f]{12}", tag), ref
    # the addresses of the app's own screens are not files: left alone
    assert 'href="#/novo"' in page and 'content="https://app.pauta.cc/og.png"' in page


def test_a_bundle_is_its_scripts_in_the_order_the_page_lists_them():
    names = assets.bundles()["app.bundle.js"]
    assert names[0] == "app.js" and names[-1] == "app-router.js" and len(names) == 9
    assert "vendor/qrcode.js" not in names  # fetched when an invite is made, not on every load
    body = assets.content("app.bundle.js").decode()
    at = [body.index(f"// ---- {n}\n") for n in names]
    assert at == sorted(at)
    for n in names:
        assert (assets.STATIC / n).read_text(encoding="utf-8") in body
    assert assets.bundles()["report.bundle.js"] == ["app.js", "app-campanhas.js", "app-report.js"]
    assert assets.page("report.html").count("<script src=") == 1
    assert "{{title}}" in assets.page("report.html")  # the route still fills these in


def test_a_stylesheet_tags_the_files_it_names():
    css = assets.content("style.css").decode()
    assert f"url({assets.url('icon.svg')})" in css and "url(/icon.svg)" not in css
    assert 'url("data:image/svg+xml' in css  # inline pictures are not addresses


def test_an_address_with_the_current_tag_is_kept_for_good_and_no_other():
    tag = assets.tag("style.css")
    assert assets.cache_for("style.css", tag) == "public, max-age=31536000, immutable"
    assert assets.cache_for("style.css", "0" * 12) == "no-cache"  # an older page's address
    assert assets.cache_for("style.css", "") == "no-cache"
    assert assets.cache_for("style.css", None) == "public, max-age=300"  # asked bare


def test_a_changed_file_has_a_new_address_everywhere_it_is_named(static):
    before = {n: assets.tag(n) for n in ("app-perfil.js", "app.bundle.js", "icon.svg", "style.css")}
    shell = assets.page("index.html")
    (static / "app-perfil.js").write_text("// edited\n" + (static / "app-perfil.js").read_text())
    assert assets.tag("app-perfil.js") != before["app-perfil.js"]
    assert assets.tag("app.bundle.js") != before["app.bundle.js"]
    assert assets.tag("style.css") == before["style.css"]
    assert assets.page("index.html") != shell and assets.url("app.bundle.js") in assets.page(
        "index.html"
    )
    # a picture the stylesheet names: the stylesheet's own address changes with it
    (static / "icon.svg").write_text((static / "icon.svg").read_text() + "<!-- edited -->")
    assert assets.tag("icon.svg") != before["icon.svg"]
    assert assets.tag("style.css") != before["style.css"]


def test_only_files_under_static_are_served():
    for rel in ("../server.py", "vendor", "nope.js", "vendor/../../db.py", ""):
        assert assets.content(rel) is None and assets.tag(rel) == "", rel
    assert assets.url("nope.js") == "/nope.js"
    kept = len(assets._kept)
    for i in range(100):
        assert assets.content(f"nope-{i}.js") is None
    assert len(assets._kept) == kept  # a miss is not remembered, however many are asked for
    assert assets.content("vendor/qrcode.js").startswith(b"//")
