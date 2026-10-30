"""The finance routes over HTTP: who may see money, recording and voiding, settings."""

from datetime import date, timedelta

from softpasskey import call

TODAY = date.today().isoformat()
AGO_40 = (date.today() - timedelta(days=40)).isoformat()


def client(base, cookie, name="Clínica Bem Estar"):
    status, c, _ = call(f"{base}/api/clients", {"name": name}, cookie)
    assert status == 200
    return c


def test_everyone_sees_money_by_default(team):
    base, nato, piero, _ = team
    c = client(base, nato)
    assert c["billing"]["status"] == "awaiting_first" and c["payments"] == []
    boot = call(f"{base}/api/boot", cookie=piero)[1]
    assert boot["finance"]["visible"] and boot["finance"]["currency"] == "BRL"
    assert boot["finance"]["amount"] == 100
    status, panel, _ = call(f"{base}/api/finance", cookie=piero)
    assert status == 200 and panel["counts"]["awaiting_first"] == 1
    assert panel["clients"][0]["name"] == c["name"]


def test_members_record_and_void_their_own_payments(team):
    base, nato, piero, _ = team
    c = client(base, nato)
    status, c, _ = call(
        f"{base}/api/clients/{c['id']}/payments",
        {"paid_on": AGO_40, "amount": "100", "method": "Pix"},
        piero,
    )
    assert status == 200
    pid = c["payments"][0]["id"]
    assert c["payments"][0]["recorded_by_name"] == "Piero"
    assert c["billing"]["anchor"] == AGO_40 and c["billing"]["months_active"] == 2
    assert c["billing"]["status"] == "late"  # the second month started 10 days ago
    panel = call(f"{base}/api/finance", cookie=nato)[1]
    assert panel["counts"]["late"] == 1 and panel["owed"] == 100
    assert panel["received_total"] == 100
    # the admin may void it too; a stranger to the payment may not
    status, c, _ = call(f"{base}/api/payments/{pid}", cookie=nato, method="DELETE")
    assert status == 200 and c["payments"][0]["voided_by_name"] == "Renato Lima"
    assert c["billing"]["status"] == "awaiting_first"
    status, c, _ = call(
        f"{base}/api/clients/{c['id']}/payments", {"paid_on": TODAY, "amount": 100}, nato
    )
    pid = c["payments"][0]["id"]
    assert call(f"{base}/api/payments/{pid}", cookie=piero, method="DELETE")[0] == 400
    assert call(f"{base}/api/payments/{pid}", cookie=nato, method="DELETE")[0] == 200
    assert call(f"{base}/api/payments/999", cookie=nato, method="DELETE")[0] == 404


def test_bad_payments_are_refused(team):
    base, nato, _, _ = team
    c = client(base, nato)
    for body in ({"paid_on": TODAY}, {"amount": 1}, {"paid_on": "2999-01-01", "amount": 1}):
        assert call(f"{base}/api/clients/{c['id']}/payments", body, nato)[0] == 400
    assert call(f"{base}/api/clients/999/payments", {"paid_on": TODAY, "amount": 1}, nato)[0] == 404


def test_billing_fee_and_billed_flag(team):
    base, nato, piero, _ = team
    c = client(base, nato)
    status, c, _ = call(
        f"{base}/api/clients/{c['id']}/billing", {"amount": "R$ 150"}, piero, "PATCH"
    )
    assert status == 200 and c["billing"]["amount"] == 150
    status, c, _ = call(f"{base}/api/clients/{c['id']}/billing", {"billed": False}, piero, "PATCH")
    assert status == 200 and c["billed"] == 0 and c["billing"] is None
    assert call(f"{base}/api/finance", cookie=nato)[1]["clients"] == []
    # `billed` doesn't sneak in through the plain client routes
    status, c, _ = call(f"{base}/api/clients/{c['id']}", {"billed": True}, nato, "PATCH")
    assert status == 200 and c["billed"] == 0
    assert call(f"{base}/api/clients", {"name": "X", "billed": False}, nato)[1]["billed"] == 1


def test_admins_only_when_the_team_says_so(team):
    base, nato, piero, _ = team
    c = client(base, nato)
    assert call(f"{base}/api/finance/settings", cookie=piero)[0] == 403
    status, s, _ = call(f"{base}/api/finance/settings", {"visibility": "admins"}, nato, "PATCH")
    assert status == 200 and s["visibility"] == "admins"
    assert call(f"{base}/api/finance/settings", cookie=nato)[1]["visibility"] == "admins"
    assert call(f"{base}/api/boot", cookie=piero)[1]["finance"]["visible"] is False
    assert call(f"{base}/api/boot", cookie=nato)[1]["finance"]["visible"] is True
    assert call(f"{base}/api/finance", cookie=piero)[0] == 403
    assert (
        call(f"{base}/api/clients/{c['id']}/payments", {"paid_on": TODAY, "amount": 1}, piero)[0]
        == 403
    )
    assert call(f"{base}/api/clients/{c['id']}/billing", {"amount": 1}, piero, "PATCH")[0] == 403
    # and the client payload carries no money for them
    doc = call(f"{base}/api/clients/{c['id']}", cookie=piero)[1]
    assert doc["billing"] is None and doc["payments"] == []
    assert call(f"{base}/api/clients/{c['id']}", cookie=nato)[1]["billing"]
    assert call(f"{base}/api/finance", cookie=nato)[0] == 200
    assert call(f"{base}/api/finance/settings", {"anchor": "lunar"}, nato, "PATCH")[0] == 400


def test_switched_off(team):
    base, nato, piero, _ = team
    c = client(base, nato)
    assert call(f"{base}/api/finance/settings", {"enabled": False}, nato, "PATCH")[0] == 200
    assert call(f"{base}/api/boot", cookie=nato)[1]["finance"]["visible"] is False
    assert call(f"{base}/api/finance", cookie=nato)[0] == 404
    assert (
        call(f"{base}/api/clients/{c['id']}/payments", {"paid_on": TODAY, "amount": 1}, nato)[0]
        == 404
    )
    assert call(f"{base}/api/clients/{c['id']}", cookie=nato)[1]["billing"] is None
    assert call(f"{base}/api/finance/settings", cookie=nato)[0] == 200  # admins still reach them


def test_the_panel_by_month(team):
    base, nato, _, _ = team
    c = client(base, nato)
    call(f"{base}/api/clients/{c['id']}/payments", {"paid_on": AGO_40, "amount": 100}, nato)
    status, panel, _ = call(f"{base}/api/finance?month={AGO_40[:7]}", cookie=nato)
    assert status == 200 and panel["month"] == AGO_40[:7]
    assert [p["name"] for p in panel["payments"]] == [c["name"]]
    assert panel["received_month"] == 100
    assert {m["month"] for m in panel["months"]} >= {AGO_40[:7], TODAY[:7]}
    assert call(f"{base}/api/finance?month=2001-01", cookie=nato)[1]["payments"] == []
    assert call(f"{base}/api/finance?month=nope", cookie=nato)[0] == 400


def test_panel_rows_point_at_the_client_even_when_cycles_drift(team):
    """1.5.0 regression: the panel's row id was the billing cycle's, so Registrar posted to
    the wrong client once someone had been paused and brought back."""
    base, nato, piero, _ = team
    old = client(base, nato, "Cliente antigo")
    for state in ("Pausado", "Ativo", "Pausado"):  # cycles 1 and 2, both closed
        assert call(f"{base}/api/clients/{old['id']}", {"state": state}, nato, "PATCH")[0] == 200
    delta = client(base, nato, "Delta")  # client 2, cycle 3
    isabel = client(base, nato, "Isabel")  # client 3, cycle 4
    assert isabel["billing"]["id"] != isabel["id"]
    rows = {r["name"]: r for r in call(f"{base}/api/finance", cookie=piero)[1]["clients"]}
    assert rows == {"Delta": rows["Delta"], "Isabel": rows["Isabel"]}
    assert (
        rows["Isabel"]["id"] == isabel["id"]
        and rows["Isabel"]["billing"] == isabel["billing"]["id"]
    )
    assert rows["Delta"]["id"] == delta["id"]
    # the id the panel hands out is the one Registrar posts to
    status, c, _ = call(
        f"{base}/api/clients/{rows['Isabel']['id']}/payments",
        {"paid_on": TODAY, "amount": 100},
        piero,
    )
    assert status == 200 and c["id"] == isabel["id"] and c["payments"][0]["amount"] == 100
    assert call(f"{base}/api/clients/{delta['id']}", cookie=piero)[1]["payments"] == []


def test_export_carries_the_ledger(team):
    base, nato, _, _ = team
    c = client(base, nato)
    call(f"{base}/api/clients/{c['id']}/payments", {"paid_on": TODAY, "amount": 100}, nato)
    doc = call(f"{base}/api/export", cookie=nato)[1]
    assert doc["finance"]["currency"] == "BRL"
    assert [p["amount"] for p in doc["payments"]] == [100]
