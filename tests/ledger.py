"""Helpers for the Financeiro tests."""


def a_day_passes(store):
    """Make every closed cycle one that closed yesterday or before: a real pause. A cycle
    closed today is reopened when the client comes back, as a slip of the finger."""
    with store.db() as db:
        db.execute("UPDATE billing SET ended=date(ended, '-1 day') WHERE ended IS NOT NULL")


def drift_cycles(store):
    """Make billing-cycle ids run ahead of client ids, as they do in any real team once a
    client has been paused and brought back. 1.5.0 shipped a panel whose rows carried the
    cycle's id as the client's; on a fresh database the two coincide, so nothing noticed.
    Finance tests start from here so that can't pass again."""
    old = store.save_client({"name": "Cliente antigo"})  # cycle 1
    store.save_client({"state": "Pausado"}, old["id"])  # closes it
    a_day_passes(store)
    store.save_client({"state": "Ativo"}, old["id"])  # cycle 2
    store.save_client({"state": "Pausado"}, old["id"])  # closed; the client stays out of the panel
    with store.db() as db:
        assert db.execute("SELECT MAX(id) FROM billing").fetchone()[0] > old["id"]
    return old
