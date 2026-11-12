"""Publicações (docs/publishing-spec.md): a client's Instagram profile and the posts for it."""

from __future__ import annotations

import contextlib
import logging
from urllib.parse import parse_qs, urlparse

from .. import obs
from ..db import Invalid, NotFound
from ..instagram import InstagramError
from ..publishing import MAX_IMAGE, Posts, publish
from . import ID, SENT, TOKEN, Reply

OFF = "as publicações não estão ligadas neste servidor"
# why a connection didn't happen, as the callback's redirect says it (the screen has the text)
REASONS = {"cancelado", "vencido", "perfil", "instagram"}


def install(route, store, auth, ig):
    posts = Posts(store)

    def _on() -> None:
        if not ig.enabled:
            raise Reply(404, {"error": OFF})

    def _post(post: dict) -> dict:
        return {k: v for k, v in post.items() if k != "container"}

    def _state() -> dict:
        return {
            "enabled": True,
            "profiles": posts.profiles(),
            "posts": [_post(p) for p in posts.posts()],
            "limits": {"image_mb": MAX_IMAGE // (1024 * 1024)},
        }

    @route("GET", "/api/publishing")
    def publishing(self, viewer, _body):
        """The connected profiles and every post, newest first. `enabled: false` and nothing
        else on a server without the Instagram app configured."""
        if not ig.enabled:
            return {"enabled": False, "profiles": [], "posts": []}
        return _state()

    # ---- a client's Instagram profile -----------------------------------------------------

    @route("POST", f"/api/clients/{ID}/instagram", "admin")
    def connect(self, viewer, _body, cid):
        """Where to send the admin: Instagram's login, with a one-time state for this
        client. Whoever is signed in to Instagram in that browser is the profile connected."""
        _on()
        store.client(int(cid))  # NotFound for a client that isn't there
        return {"url": ig.start(int(cid), viewer["account"])}

    @route("GET", "/api/instagram/callback", "open")
    def callback(self, viewer, _body):
        """Instagram's login sends the browser back here without the session cookie
        (SameSite=Strict, a cross-site redirect): the one-time state is the authorization."""
        q = parse_qs(urlparse(self.path).query)
        state, code = q.get("state", [""])[0], q.get("code", [""])[0]
        why = ""
        try:
            if not ig.enabled:
                raise InstagramError(OFF, step="off")
            if q.get("error") or not code:  # cancelled in Instagram's dialog
                with contextlib.suppress(InstagramError):
                    ig.take_state(state)
                obs.event("ig_connect_cancelled", logging.WARNING)
                why = "cancelado"
            else:
                client, account = ig.take_state(state)
                who, expires = ig.finish(code)
                try:
                    posts.save_profile(client, who, expires, account)
                except (Invalid, NotFound):
                    # linked to another client (whose connection this login just renewed:
                    # the token stays), or the client is gone (nobody uses it: it goes)
                    if not any(p["ig_id"] == who["ig_id"] for p in posts.profiles()):
                        ig.forget(who["ig_id"])
                    why = "perfil"
        except InstagramError as e:
            why = "vencido" if e.step == "state" else "perfil" if e.step == "me" else "instagram"
        self._redirect(f"/#/publicacoes?ig=erro&motivo={why}" if why else "/#/publicacoes?ig=ok")
        return SENT

    @route("DELETE", f"/api/clients/{ID}/instagram", "admin")
    def disconnect(self, viewer, _body, cid):
        """Forget the profile and its token. Scheduled posts go back to drafts; nothing
        already on Instagram changes."""
        _on()
        was = posts.remove_profile(int(cid))
        if not was:
            raise NotFound("este cliente não tem Instagram conectado")
        ig.forget(was["ig_id"])
        return _state()

    # ---- images ---------------------------------------------------------------------------

    @route("POST", "/api/posts/media", raw=True)
    def upload(self, viewer, _body):
        """The body is one JPEG (the screen converts and sizes it first). Checked against
        Instagram's rules here too, then kept until a post takes it."""
        _on()
        self.close_connection = True  # after an error the rest of the body is unread
        length = (self.headers.get("Content-Length") or "").strip()
        if not length.isdigit():
            raise Reply(411, {"error": "envie o tamanho do arquivo"})
        if int(length) > MAX_IMAGE:
            raise Reply(413, {"error": "a imagem passa de 8 MB"})
        try:
            raw = self.rfile.read(int(length))
        except TimeoutError:
            raise Reply(408, {"error": "o envio parou no meio; tente de novo"}) from None
        return posts.keep_media(raw)

    def _image(self, path, cache: str):
        raw = path.read_bytes()
        self.send_response(200)
        self._headers("image/jpeg", len(raw), {"Cache-Control": cache})
        self._write(raw)
        return SENT

    @route("GET", f"/api/posts/media/{TOKEN}")
    def preview(self, viewer, _body, token):
        """A post's image for the team (the list, the form's preview)."""
        path = posts.media_path(token)
        if not path:
            raise NotFound("imagem não encontrada")
        return _image(self, path, "private, max-age=86400")

    @route("GET", f"/api/media/{TOKEN}\\.jpg", "open")
    def public_image(self, viewer, _body, token):
        """Where Instagram fetches an image from. Open, by an unguessable name, and only
        while its post is being published: a draft's image is never public."""
        path = posts.media_path(token)
        with store.db() as db:
            live = db.execute(
                "SELECT 1 FROM post WHERE media=? AND status='publishing'", (token,)
            ).fetchone()
        if not path or not live:
            raise NotFound("não encontrado")
        return _image(self, path, "no-store")

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
        """Publish now, and wait for it (a few seconds). The answer is the post as it
        ended: `published`, or `failed` with Instagram's reason on it."""
        _on()
        return _post(publish(posts, ig, int(pid), ig.origin))

    return posts
