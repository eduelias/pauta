"""Publicações (docs/publishing-spec.md): the connected portfolios, their Instagram accounts
and the client each is for, and the posts."""

from __future__ import annotations

import contextlib
import logging
import re
from urllib.parse import parse_qs, urlparse

from .. import obs
from ..db import Invalid, NotFound
from ..instagram import InstagramError, handle
from ..publishing import CHUNK, MAX_IMAGE, MAX_VIDEO, VIDEO_TYPES, Posts, publish
from . import ID, SENT, TOKEN, Reply

IG = r"([0-9]{5,20})"  # an Instagram account's id, or a portfolio's

OFF = "as publicações não estão ligadas neste servidor"
# why a connection didn't happen, as the callback's redirect says it (the screen has the text)
REASONS = {"cancelado", "vencido", "perfil", "instagram"}
MEDIA_TYPES = {".jpg": "image/jpeg", ".mp4": "video/mp4", ".mov": "video/quicktime"}
RANGE = re.compile(r"bytes=(\d{0,18})-(\d{0,18})")  # one range: what a video player asks for


def install(route, store, auth, ig):
    posts = Posts(store)

    def _on() -> None:
        if not ig.enabled:
            raise Reply(404, {"error": OFF})

    def _post(post: dict) -> dict:
        return {k: v for k, v in post.items() if k != "container"}

    def _accounts() -> list[dict]:
        """The accounts, each with `match`: the one client whose Instagram field is a clean
        handle equal to the account's. A suggestion and a reason to ask, never an
        assignment."""
        by_handle: dict[str, list[dict]] = {}
        for c in store.clients():
            by_handle.setdefault(handle(c.get("instagram")), []).append(c)
        out = []
        for a in posts.accounts():
            same = by_handle.get(handle(a["username"])) or []
            one = same[0] if len(same) == 1 and handle(a["username"]) else None
            out.append({**a, "match": {"id": one["id"], "name": one["name"]} if one else None})
        return out

    def _state() -> dict:
        return {
            "enabled": True,
            "connections": posts.connections(),
            "accounts": _accounts(),
            "posts": [_post(p) for p in posts.posts()],
            "limits": {
                "image_mb": MAX_IMAGE // (1024 * 1024),
                "video_mb": MAX_VIDEO // (1024 * 1024),
            },
        }

    @route("GET", "/api/publishing")
    def publishing(self, viewer, _body):
        """The connected portfolios, their accounts and every post, newest first.
        `enabled: false` and nothing else on a server without the Instagram app configured."""
        if not ig.enabled:
            return {"enabled": False, "connections": [], "accounts": [], "posts": []}
        return _state()

    # ---- a portfolio's connection and its accounts ----------------------------------------

    @route("POST", "/api/instagram/connect", "admin")
    def connect(self, viewer, _body):
        """Where to send the admin: Meta's login, with a one-time state. Whatever portfolio
        and accounts they pick there is what gets connected."""
        _on()
        return {"url": ig.start(viewer["account"])}

    @route("GET", "/api/instagram/callback", "open")
    def callback(self, viewer, _body):
        """Meta's login sends the browser back here without the session cookie
        (SameSite=Strict, a cross-site redirect): the one-time state is the authorization."""
        q = parse_qs(urlparse(self.path).query)
        state, code = q.get("state", [""])[0], q.get("code", [""])[0]
        why = ""
        try:
            if not ig.enabled:
                raise InstagramError(OFF, step="off")
            if q.get("error") or not code:  # cancelled in Meta's dialog
                with contextlib.suppress(InstagramError):
                    ig.take_state(state)
                obs.event("ig_connect_cancelled", logging.WARNING)
                why = "cancelado"
            else:
                by = ig.take_state(state)
                portfolio, accounts, expires = ig.finish(code)
                posts.save_connection(portfolio, accounts, expires, by)
        except InstagramError as e:
            why = "vencido" if e.step == "state" else "perfil" if e.step == "me" else "instagram"
        self._redirect(f"/#/publicacoes?ig=erro&motivo={why}" if why else "/#/publicacoes?ig=ok")
        return SENT

    @route("PATCH", f"/api/instagram/accounts/{IG}", "admin")
    def assign(self, viewer, body, ig_id):
        """Which client this account is for (`null`: none)."""
        _on()
        client = body.get("client", "")
        if client is not None and (not isinstance(client, int) or isinstance(client, bool)):
            raise Invalid("informe o cliente (ou null para deixar sem cliente)")
        posts.assign(ig_id, client, viewer["account"])
        return _state()

    @route("DELETE", f"/api/instagram/accounts/{IG}", "admin")
    def remove_account(self, viewer, _body, ig_id):
        """An account that is not connected leaves Pauta; nothing on Instagram changes."""
        _on()
        posts.remove_account(ig_id, viewer["account"])
        return _state()

    @route("DELETE", f"/api/instagram/connections/{IG}", "admin")
    def disconnect(self, viewer, _body, business_id):
        """Forget the portfolio and its token. Its accounts stay listed with their clients,
        not connected; no post changes; nothing on Instagram changes."""
        _on()
        if not posts.remove_connection(business_id):
            raise NotFound("esta conexão não existe")
        ig.forget(business_id)
        return _state()

    # ---- images ---------------------------------------------------------------------------

    @route("POST", "/api/posts/media", raw=True)
    def upload(self, viewer, _body):
        """The body is the post's file. A picture is one JPEG (the screen converts and sizes
        it first; `?kind=story` says it is for a Story) and is checked against Instagram's
        rules here too. A video (`Content-Type: video/mp4` or `video/quicktime`) comes as it
        was exported and goes straight to the disk. Either is kept until a post takes it."""
        _on()
        self.close_connection = True  # after an error the rest of the body is unread
        length = (self.headers.get("Content-Length") or "").strip()
        if not length.isdigit():
            raise Reply(411, {"error": "envie o tamanho do arquivo"})

        def read(n: int) -> bytes:
            try:
                return self.rfile.read(n)
            except TimeoutError:
                raise Reply(408, {"error": "o envio parou no meio; tente de novo"}) from None

        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype in VIDEO_TYPES:
            if int(length) > MAX_VIDEO:
                raise Reply(413, {"error": f"o vídeo passa de {MAX_VIDEO // (1024 * 1024)} MB"})
            return posts.keep_video(read, int(length), VIDEO_TYPES[ctype])
        if int(length) > MAX_IMAGE:
            raise Reply(413, {"error": "a imagem passa de 8 MB"})
        kind = parse_qs(urlparse(self.path).query).get("kind", ["feed"])[0]
        return posts.keep_media(read(int(length)), kind)

    def _file(self, path, cache: str):
        """A post's file, a piece at a time (a video is never whole in memory), and only the
        part asked for when the request names a range: a video player asks for nothing else."""
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        extra = {"Cache-Control": cache, "Accept-Ranges": "bytes"}
        asked = RANGE.fullmatch(self.headers.get("Range") or "")
        if asked and (asked.group(1) or asked.group(2)):
            first, last = asked.groups()
            if first:
                start, end = int(first), min(int(last), size - 1) if last else size - 1
            else:  # the last so many bytes
                start = max(0, size - int(last))
            if start > end:
                self.send_response(416)
                self._headers("text/plain", 0, {"Content-Range": f"bytes */{size}"})
                return SENT
            status, extra["Content-Range"] = 206, f"bytes {start}-{end}/{size}"
        self.send_response(status)
        self._headers(MEDIA_TYPES[path.suffix], end - start + 1, extra)
        left = end - start + 1
        try:
            with path.open("rb") as f:
                f.seek(start)
                while left and self.command != "HEAD":
                    chunk = f.read(min(CHUNK, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()  # out now: the answer is otherwise held until the end
                    left -= len(chunk)
        except TimeoutError:  # whoever was reading stopped: the same as going away
            raise ConnectionResetError from None
        return SENT

    @route("GET", f"/api/posts/media/{TOKEN}")
    def preview(self, viewer, _body, token):
        """A post's picture or video for the team (the list, the form's preview)."""
        path = posts.media_path(token)
        if not path:
            raise NotFound("arquivo não encontrado")
        return _file(self, path, "private, max-age=86400")

    @route("GET", f"/api/media/{TOKEN}\\.(jpg|mp4|mov)", "open")
    def public_media(self, viewer, _body, token, ext):
        """Where Instagram fetches a post's file from. Open, by an unguessable name, and only
        while its post is being published: a draft's file is never public."""
        path = posts.media_path(token)
        with store.db() as db:
            live = db.execute(
                "SELECT 1 FROM post WHERE media=? AND status='publishing'", (token,)
            ).fetchone()
        if not path or not live or path.suffix != f".{ext}":
            raise NotFound("não encontrado")
        return _file(self, path, "no-store")

    # ---- posts ----------------------------------------------------------------------------

    @route("POST", "/api/posts")
    def create(self, viewer, body):
        _on()
        return _post(posts.create(body, viewer["account"]))

    @route("PATCH", f"/api/posts/{ID}")
    def edit(self, viewer, body, pid):
        _on()
        return _post(posts.update(int(pid), body))

    @route("DELETE", f"/api/posts/{ID}")
    def remove(self, viewer, _body, pid):
        """Out of Pauta only: a published post stays on Instagram."""
        _on()
        post = posts.post(int(pid))
        if not viewer["is_admin"] and post["account"] != viewer["account"]:
            raise Reply(403, {"error": "só quem criou ou um administrador pode excluir"})
        posts.delete(int(pid))
        return {"ok": True}

    @route("POST", f"/api/posts/{ID}/publish")
    def publish_now(self, viewer, _body, pid):
        """Publish now. A picture is waited for (a few seconds): the answer is the post as
        it ended, `published`, or `failed` with Instagram's reason on it. A video comes back
        `publishing`: Instagram takes minutes over it, and the list shows how it ended."""
        _on()
        return _post(publish(posts, ig, int(pid), ig.origin))

    return posts
