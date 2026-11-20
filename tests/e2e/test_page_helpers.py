"""The page's small pure helpers, called in the browser with many inputs: the scripts have
no test runner of their own, and a browser is where they run."""

import re
from datetime import date, timedelta

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
    bad, kinds = gate.evaluate(
        r"""() => {
          let seed = 7;
          const pick = (n) => ((seed = (Math.imul(seed, 1103515245) + 12345) >>> 0) >>> 8) % n;
          const bits = ["<", ">", '"', "'", "&", ";", "#", "=", "/", " ", "a", "b", "`", "\\",
            "\n", "é", "💡", "&amp;", "<!--", "</i>", "]]>"];
          const bad = [], seen = new Set();
          for (let i = 0; i < 3000; i++) {
            const s = Array.from({ length: pick(14) }, () => bits[pick(bits.length)]).join("");
            seen.add(s);
            const t = document.createElement("template");
            t.innerHTML = `<i title="${esc(s)}">${esc(s)}</i>`;
            const el = t.content.firstElementChild;
            const one = t.content.childNodes.length === 1 && !el.childElementCount
              && el.getAttributeNames().join() === "title";
            const same = el.title === s && el.textContent === s;
            if (/[<>"']/.test(esc(s)) || !one || !same) bad.push(s);
          }
          return [bad, seen.size];
        }"""
    )
    assert bad == []
    assert kinds > 2000  # and the strings do differ


def test_a_whatsapp_link_is_one_whole_number_or_nothing(gate):
    """`waUrl` gives nothing, or wa.me/ and 11 to 15 digits that do not start with zero.
    Two numbers typed in one field used to run together into one 22-digit link that
    WhatsApp refuses. (The numbers here are made up.)"""

    def wa(text):
        return gate.evaluate("(n) => waUrl(n)", text)

    # however it is typed: spaces, dashes, brackets, the trunk zero, the country code
    for typed in (
        "11900000000",
        "11 90000-0000",
        "(11) 90000-0000",
        "011 90000-0000",
        "0 11 90000 0000",
        "+55 11 90000-0000",
        "+55 (11) 90000-0000",
        "0055 11 90000 0000",
        "55 11 90000.0000",
    ):
        assert wa(typed) == "https://wa.me/5511900000000", typed
    assert wa("+31 6 0000 0000") == "https://wa.me/31600000000"  # typed with its country
    # two numbers in one field: the first whole one, never both run together
    assert wa("(11) 90000-0000 / (11) 90000-0001") == "https://wa.me/5511900000000"
    assert wa("loja 11 3000-0000, cel 11 90000-0001") == "https://wa.me/551130000000"
    assert wa("11 90000-0000 11 90000-0001") == ""
    for nothing in ("", None, "sem número", "3000-0000", "123", "0000 0000 0000", "+0 000 000 000"):
        assert wa(nothing) == "", nothing
    # 3,000 made-up fields, the same ones every run
    links = gate.evaluate(
        """() => {
          let seed = 11;
          const pick = (n) => ((seed = (Math.imul(seed, 1103515245) + 12345) >>> 0) >>> 8) % n;
          const bits = [..."0123456789012345678905  -()+/.,x"];
          return Array.from({ length: 3000 }, () =>
            waUrl(Array.from({ length: pick(40) }, () => bits[pick(bits.length)]).join("")));
        }"""
    )
    assert len(set(links)) > 100  # the made-up fields do give links
    assert [u for u in links if u and not re.fullmatch(r"https://wa\.me/[1-9]\d{10,14}", u)] == []


@pytest.mark.parametrize(
    "today",
    ["2026-01-01", "2026-03-01", "2028-03-01", "2026-03-31", "2026-11-20", "2026-12-31"],
)
def test_the_quick_periods_on_any_day(gate, today):
    """Ads Manager's meaning: "últimos N dias" are N whole days ending yesterday, "mês
    passado" the whole month before, whatever the day (the 1st, a leap year, New Year)."""
    gate.clock.set_fixed_time(f"{today}T12:00:00")
    got = gate.evaluate("() => Object.fromEntries(PERIODS.map(([p]) => [p, periodDates(p)]))")
    t = date.fromisoformat(today)
    first = t.replace(day=1)
    before = first - timedelta(days=1)  # the last day of the month before
    want = {
        "today": (t, t),
        "yesterday": (t - timedelta(days=1), t - timedelta(days=1)),
        "last_7": (t - timedelta(days=7), t - timedelta(days=1)),
        "last_30": (t - timedelta(days=30), t - timedelta(days=1)),
        "this_month": (first, t),
        "last_month": (before.replace(day=1), before),
        "custom": (first, t),  # Personalizado with no dates yet: this month
    }
    assert got == {p: [a.isoformat(), b.isoformat()] for p, (a, b) in want.items()}
    assert all(a <= b <= today for a, b in got.values())
    # a range typed backwards comes out in order
    assert gate.evaluate(
        "() => periodDates('custom', { since: '2026-02-10', until: '2026-01-05' })"
    ) == ["2026-01-05", "2026-02-10"]
