"""The page's small pure helpers, called in the browser with many inputs: the scripts have
no test runner of their own, and a browser is where they run."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.e2e


@pytest.fixture()
def gate(live, device):
    """The sign-in screen: the scripts are loaded and nobody is signed in."""
    base, _, _ = live
    page = device().page
    page.goto(base)
    expect(page.get_by_role("button", name="Entrar com passkey")).to_be_visible()
    return page


def test_esc_leaves_nothing_the_page_would_parse(gate):
    """For any text: no <, >, " or ' is left, and as an attribute's value and as an element's
    text it reads back exactly. 3,000 made-up strings, the same ones every run."""
    bad = gate.evaluate(
        r"""() => {
          let seed = 7;
          const pick = (n) => (seed = (seed * 1103515245 + 12345) % 2147483648) % n;
          const bits = ["<", ">", '"', "'", "&", ";", "#", "=", "/", " ", "a", "b", "`", "\\",
            "\n", "é", "💡", "&amp;", "<!--", "</i>", "]]>"];
          const bad = [];
          for (let i = 0; i < 3000; i++) {
            const s = Array.from({ length: pick(14) }, () => bits[pick(bits.length)]).join("");
            const t = document.createElement("template");
            t.innerHTML = `<i title="${esc(s)}">${esc(s)}</i>`;
            const el = t.content.firstElementChild;
            const one = t.content.childNodes.length === 1 && !el.childElementCount
              && el.getAttributeNames().join() === "title";
            const same = el.title === s && el.textContent === s;
            if (/[<>"']/.test(esc(s)) || !one || !same) bad.push(s);
          }
          return bad;
        }"""
    )
    assert bad == []
