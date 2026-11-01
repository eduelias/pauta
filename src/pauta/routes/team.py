"""Team and settings: members, OneDrive, the option lists."""

from __future__ import annotations

from . import ID


def install(route, store, auth, drive, meta):
    # ---- team and settings ------------------------------------------------------------

    @route("GET", "/api/members")
    def members(self, viewer, _body):
        return store.members()

    @route("PATCH", f"/api/members/{ID}", "admin")
    def edit_member(self, viewer, body, aid):
        auth.set_member(
            int(aid),
            disabled=body.get("disabled"),
            is_admin=body.get("is_admin"),
            by=viewer["account"],
        )
        return store.members()

    @route("GET", "/api/onedrive", "admin")
    def drive_status(self, viewer, _body):
        """Also how the Configurações page waits for the code to be approved: each call while
        a connection is pending asks Microsoft once."""
        state = drive.poll() if drive.pending() else "idle"
        return {**drive.status(quota=state != "pending"), "state": state}

    @route("POST", "/api/onedrive/connect", "admin")
    def drive_connect(self, viewer, _body):
        drive.start_connect()
        return {**drive.status(), "state": "pending"}

    @route("DELETE", "/api/onedrive", "admin")
    def drive_disconnect(self, viewer, _body):
        drive.disconnect()
        return {**drive.status(), "state": "idle"}
