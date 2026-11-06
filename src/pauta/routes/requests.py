"""Requests and their files (the bytes are in OneDrive)."""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote

from .. import obs
from . import ID, SENT, Reply

SUBTYPE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,30}")  # image/<this>: safe as a file suffix


def install(route, store, auth, drive, meta):
    # a file's thumbnail never changes: once fetched from OneDrive (two round trips, a
    # second or three) it is kept next to the database as <file id>.<image subtype>
    thumbs = Path(f"{store.path}.thumbs")

    def _cached_thumbnail(fid: int, item: str) -> tuple[bytes, str]:
        hit = next(thumbs.glob(f"{fid}.*"), None)
        if hit is not None:
            with contextlib.suppress(OSError):
                return hit.read_bytes(), f"image/{hit.suffix[1:]}"
        raw, ctype = drive.thumbnail(item)
        subtype = ctype.partition("/")[2]
        if SUBTYPE.fullmatch(subtype):
            try:
                thumbs.mkdir(parents=True, exist_ok=True)
                tmp = thumbs / f"{fid}.{subtype}.{os.getpid()}.tmp"
                tmp.write_bytes(raw)
                tmp.replace(thumbs / f"{fid}.{subtype}")
            except OSError:  # a full or read-only disk: the page still gets its thumbnail
                obs.event("thumbnail_not_kept", logging.WARNING)
        return raw, ctype

    def _forget_thumbnail(fid: int) -> None:
        for p in thumbs.glob(f"{fid}.*"):
            with contextlib.suppress(OSError):
                p.unlink()

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
        raw, ctype = _cached_thumbnail(int(fid), store.file(int(fid))["item"])
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
        _forget_thumbnail(int(fid))
        return store.remove_file(int(fid), viewer["account"])

    @route("POST", f"/api/requests/{ID}/share")
    def share(self, viewer, _body, rid):
        folder = store.request_folder(int(rid))
        if not folder:
            raise Reply(400, {"error": "envie um arquivo primeiro"})
        return {"url": drive.share_link(folder)}
