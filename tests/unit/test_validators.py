"""Field checks: what the forms may send, and what ends up stored."""

import hashlib

import pytest

from pauta import db as m
from pauta.db import Invalid, clean, gravatar


def test_text_collapses_whitespace_and_truncates():
    check = m._text(5)
    assert check("  a \n\t b  ", None) == "a b"
    assert check("abcdefgh", None) == "abcde"
    assert check(None, None) == ""


def test_long_keeps_lines_but_normalises_them():
    check = m._long(100)
    assert check("  one\r\ntwo  \n", None) == "one\ntwo"
    assert check("x" * 200, None) == "x" * 100


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("", ""),
        ("https://drive.google.com/x", "https://drive.google.com/x"),
        ("HTTP://example.com", "HTTP://example.com"),
        ("drive.google.com/x", "https://drive.google.com/x"),
    ],
)
def test_url_accepts_and_completes(given, stored):
    assert m._url(given, None) == stored


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "not a link", "ftp//x", "data:text/html,x"])
def test_url_refuses_other_schemes(bad):
    with pytest.raises(Invalid):
        m._url(bad, None)


def test_date():
    assert m._date("2026-11-05", None) == "2026-11-05"
    assert m._date("", None) is None
    assert m._date(None, None) is None
    assert m._date("1990-01-01", None) == "1990-01-01"
    # "0202-11-05" is a year typed halfway: the browser sends it as it stands
    for bad in ("05/11/2026", "2026-02-30", "2026-13-01", "tomorrow", "0202-11-05", "1989-12-31"):
        with pytest.raises(Invalid):
            m._date(bad, None)


@pytest.mark.parametrize(
    ("given", "value"),
    [
        (None, None),
        ("", None),
        ("1.500,50", 1500.5),
        ("R$ 200", 200.0),
        ("R$ 1.234.567,89", 1234567.89),
        ("99.5", 99.5),  # a dot alone is a decimal point
        ("1500.50", 1500.5),  # what the page puts back in a field
        ("1.500", 1500.0),  # the Brazilian way: a dot before three digits marks thousands
        ("R$ 2.000", 2000.0),
        ("1.500.000", 1500000.0),
        ("1500.500", 1500.5),  # not grouped in threes from the left: a decimal point
        ("0.250", 0.25),
        ("1.500,00", 1500.0),
        (1.5, 1.5),  # a JSON number is taken as it is
        (12.345, 12.35),
        (0, 0.0),
    ],
)
def test_money(given, value):
    assert m._money(given, None) == value


@pytest.mark.parametrize(
    "bad",
    ["muito", "-1", -5, 100_000_001, [1], "nan", "inf", float("nan"), float("inf")]
    + ["2,500.00", "1,500.50", "1.5,00"]  # the other order is refused, never read as 2,50
    + [pytest.param(10**400, id="too big for a float")],
)
def test_money_refuses(bad):
    with pytest.raises(Invalid):
        m._money(bad, None)


def test_choice():
    check = m._choice(("A", "B"))
    assert check(" A ", None) == "A"
    with pytest.raises(Invalid, match="vazio"):
        check("", None)
    with pytest.raises(Invalid):
        check("C", None)
    assert m._choice(("A",), blank=True)("", None) == ""


def test_clean_only_touches_sent_fields(store):
    with store.db() as conn:
        with pytest.raises(Invalid):
            clean(m.REQUEST_FIELDS, ["not", "a", "dict"], conn, partial=True)
        assert clean(m.REQUEST_FIELDS, {"priority": "Alta"}, conn, partial=True) == {
            "priority": "Alta"
        }
        with pytest.raises(Invalid, match="cliente"):  # a new request needs a client
            clean(m.REQUEST_FIELDS, {"what": "x"}, conn, partial=False)
        assert clean(m.CLIENT_FIELDS, {"unknown": 1}, conn, partial=True) == {}


def test_client_and_account_references(store):
    c = store.save_client({"name": "Real"})
    with store.db() as conn:
        assert m._client(str(c["id"]), conn) == c["id"]
        for bad in (None, "x", 999):
            with pytest.raises(Invalid):
                m._client(bad, conn)
        assert m._account(None, conn) is None
        assert m._account(0, conn) is None
        conn.execute("INSERT INTO account(id, name, handle, disabled) VALUES (7, 'Off', 'h', 1)")
        for bad in ("x", 999, 7):  # unknown, and disabled people can't be assigned
            with pytest.raises(Invalid):
                m._account(bad, conn)


def test_gravatar_hash():
    assert gravatar(None) == "" and gravatar("  ") == ""
    want = hashlib.sha256(b"ana@example.com").hexdigest()
    assert gravatar(" Ana@Example.COM ") == want
