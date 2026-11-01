"""Requests and their files (the bytes are in OneDrive)."""

from __future__ import annotations

from urllib.parse import unquote

from .. import obs
from . import ID, SENT, Reply


def install(route, store, auth, drive, meta):
    # ---- requests ---------------------------------------------------------------------

    @route("GET", "/api/requests")
    def list_requests(self, viewer, _body):
        return store.requests()

    @route("POST", "/api/requests")
    def new_request(self, viewer, body):
        return store.create_request(body, viewer["account"])

    @route("GET", f"/api/requests/{ID}")
    def get_request(self, viewer, _body, rid):
        return store.request(int(rid))

    @route("PATCH", f"/api/requests/{ID}")
    def edit_request(self, viewer, body, rid):
        return store.update_request(int(rid), body, viewer["account"])

    @route("POST", f"/api/requests/{ID}/comments")
    def comment(self, viewer, body, rid):
        return store.comment(int(rid), body.get("text"), viewer["account"])

    @route("DELETE", f"/api/requests/{ID}", "admin")
    def delete_request(self, viewer, _body, rid):
        store.delete_request(int(rid))  # its files stay in OneDrive
        return {"ok": True}

    # ---- files (in OneDrive) ----------------------------------------------------------

    @route("POST", f"/api/requests/{ID}/files", raw=True)
    def upload(self, viewer, _body, rid):
        """The body is the file; its name comes URI-encoded in X-File-Name."""
        # one upload per connection: after an error the rest of the body is unread
        self.close_connection = True
        folder = store.file_folder(int(rid))
        length = (self.headers.get("Content-Length") or "").strip()
        if not length.isdigit():
            raise Reply(411, {"error": "envie o tamanho do arquivo"})
        name = unquote(self.headers.get("X-File-Name") or "").strip()
        if not name:
            raise Reply(400, {"error": "o arquivo precisa de um nome"})
        item = drive.upload(folder, name, int(length), self._reader())
        obs.event("file_uploaded", bytes=item["size"])
        return store.add_file(int(rid), item, viewer["account"])

    @route("GET", f"/api/files/{ID}")
    def download(self, viewer, _body, fid):
        self._redirect(drive.download_url(store.file(int(fid))["item"]))
        return SENT

    @route("GET", f"/api/files/{ID}/thumb")
    def thumb(self, viewer, _body, fid):
        raw, ctype = drive.thumbnail(store.file(int(fid))["item"])
        self.send_response(200)
        self._headers(ctype, len(raw), {"Cache-Control": "private, max-age=86400"})
        self._write(raw)
        return SENT

    @route("DELETE", f"/api/files/{ID}")
    def remove_file(self, viewer, _body, fid):
        f = store.file(int(fid))
        if not viewer["is_admin"] and f["account"] != viewer["account"]:
            raise Reply(403, {"error": "só quem enviou ou um administrador pode remover"})
        drive.delete(f["item"])
        return store.remove_file(int(fid), viewer["account"])

    @route("POST", f"/api/requests/{ID}/share")
    def share(self, viewer, _body, rid):
        folder = store.request_folder(int(rid))
        if not folder:
            raise Reply(400, {"error": "envie um arquivo primeiro"})
        return {"url": drive.share_link(folder)}
