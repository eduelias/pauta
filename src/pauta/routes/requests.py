"""Requests and their files (the bytes are in OneDrive)."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import re
import threading
from pathlib import Path
from urllib.parse import unquote

from .. import obs
from ..onedrive import DriveError
from . import ID, SENT, Reply

SUBTYPE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,30}")  # image/<this>: safe as a file suffix


def install(route, store, auth, drive, meta):
    # a file's thumbnail never changes: once fetched from OneDrive (two round trips, a
    # second or three) it is kept next to the database as <file id>.<item digest>.<image
    # subtype>. The digest is of the OneDrive item: SQLite hands a deleted file's id to the
    # next upload, and that one must never get the old picture. Safe to delete wholesale.
    thumbs = Path(f"{store.path}.thumbs")
    # one fetch per picture at a time: a page that redraws while files are still going up
    # asks for the same new thumbnail again and again, and the upload itself is already
    # fetching it (_warm). The others wait for that one and read what it kept
    fetching: dict[str, threading.Lock] = {}
    fetching_guard = threading.Lock()

    def _kept(key: str) -> tuple[bytes, str] | None:
        hit = next(thumbs.glob(f"{key}.*"), None)  # never a half-written .<name>.tmp
        if hit is not None:
            with contextlib.suppress(OSError):
                return hit.read_bytes(), f"image/{hit.name.split('.', 2)[2]}"
        return None

    def _cached_thumbnail(fid: int, item: str) -> tuple[bytes, str]:
        key = f"{fid}.{hashlib.sha256(item.encode()).hexdigest()[:12]}"
        if hit := _kept(key):
            return hit
        with fetching_guard:
            mine = fetching.setdefault(key, threading.Lock())
        with mine:
            try:
                if hit := _kept(key):  # someone fetched it while this one waited
                    return hit
                raw, ctype = drive.thumbnail(item)
                subtype = ctype.partition("/")[2]
                if SUBTYPE.fullmatch(subtype):
                    try:
                        thumbs.mkdir(parents=True, exist_ok=True)
                        tmp = thumbs / f".{key}.{subtype}.{threading.get_ident()}.tmp"
                        tmp.write_bytes(raw)
                        tmp.replace(thumbs / f"{key}.{subtype}")
                    except OSError:  # a full or read-only disk: the page still gets it
                        obs.event("thumbnail_not_kept", logging.WARNING)
                return raw, ctype
            finally:
                with fetching_guard:
                    fetching.pop(key, None)

    def _warm(item: dict) -> None:
        """Fetch a new picture's thumbnail before anyone asks for it. The page draws it the
        moment the upload ends, and that first fetch is a second and a half of OneDrive: by
        then it is under way, and whoever opens the request later finds it on disk."""
        fid = store.file_id(item["id"])
        if fid is None or not item["mime"].startswith(("image/", "video/")):
            return

        def work():
            with contextlib.suppress(DriveError, OSError):  # no thumbnail yet: the page asks
                _cached_thumbnail(fid, item["id"])

        threading.Thread(target=work, name="thumb-warm", daemon=True).start()

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
        files = store.request(int(rid)).get("files") or []
        store.delete_request(int(rid))  # its files stay in OneDrive
        for f in files:
            _forget_thumbnail(int(f["id"]))
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
        doc = store.add_file(int(rid), item, viewer["account"])
        _warm(item)
        return doc

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
