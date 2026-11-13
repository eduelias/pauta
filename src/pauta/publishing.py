"""Publicações (docs/publishing-spec.md): posts for a client's Instagram, kept here and
published at their time.

A post is one JPEG and a caption for one client whose Instagram profile is connected
(instagram.py holds the tokens; `ig_profile` holds who, never a token). Instagram's API has
no scheduling: Pauta keeps the post and publishes it when it is due. Instagram fetches the
image itself from a public address, so each image lives under `<db>.media/<token>.jpg` and
is served at `/api/media/<token>.jpg`: unguessable, and gone with its post.

Publishing is three calls (a container, wait until ready, publish). A post is claimed
(`publishing`) before the first, so two taps or a tap and the scheduler never post twice. A
post found still `publishing` long after it started (the server died mid-way) is marked
failed with "confira no Instagram": whether it went out is not known, and a blind retry
could post it a second time.
"""

from __future__ import annotations

import contextlib
import logging
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import obs
from .db import CONTROL, Invalid, NotFound, Store
from .instagram import Instagram, InstagramError

MAX_IMAGE = 8 * 1024 * 1024  # Instagram's limit for an image
CAPTION_MAX = 2200
ALT_MAX = 1000
HASHTAGS_MAX, MENTIONS_MAX = 30, 20
RATIO_MIN, RATIO_MAX = 4 / 5, 1.91  # width / height: portrait 4:5 to landscape 1.91:1
WIDTH_MIN = 320
# rounding: a 1080x1350 image is exactly 0.8, a 1080x566 one 1.908
RATIO_SLACK = 0.01

STATUSES = ("draft", "scheduled", "publishing", "published", "failed")
EDITABLE = ("draft", "scheduled", "failed")  # what a person may still change or publish

TICK_SECONDS = 20
STUCK_SECONDS = 10 * 60  # a `publishing` older than this died mid-way
ORPHAN_SECONDS = 24 * 3600  # an uploaded image no post took

UNSURE = "não sabemos se esta publicação saiu: confira no Instagram antes de publicar de novo"
NO_PROFILE = "conecte o Instagram deste cliente primeiro"
TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,64}$")

# the baseline and progressive start-of-frame markers carry the picture's size
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def now() -> str:
    return _utc(datetime.now(UTC))


def jpeg_size(raw: bytes) -> tuple[int, int]:
    """(width, height) of a JPEG, read from its frame header; Invalid when it isn't one."""
    if raw[:3] != b"\xff\xd8\xff":
        raise Invalid("a imagem precisa ser JPEG")
    i, n = 2, len(raw)
    while i + 4 <= n:
        if raw[i] != 0xFF:
            break
        marker = raw[i + 1]
        if marker == 0xFF:  # padding between segments
            i += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # no length follows
            i += 2
            continue
        size = int.from_bytes(raw[i + 2 : i + 4], "big")
        if size < 2:
            break
        if marker in _SOF:
            if i + 9 > n:
                break
            height = int.from_bytes(raw[i + 5 : i + 7], "big")
            width = int.from_bytes(raw[i + 7 : i + 9], "big")
            if width and height:
                return width, height
            break
        i += 2 + size
    raise Invalid("não deu para ler o tamanho da imagem")


def check_image(raw: bytes) -> tuple[int, int]:
    """Instagram's rules for a feed image, checked before anything is kept."""
    if not raw:
        raise Invalid("envie uma imagem")
    if len(raw) > MAX_IMAGE:
        raise Invalid("a imagem passa de 8 MB")
    width, height = jpeg_size(raw)
    if width < WIDTH_MIN:
        raise Invalid(f"a imagem precisa ter pelo menos {WIDTH_MIN} px de largura")
    ratio = width / height
    if not RATIO_MIN - RATIO_SLACK <= ratio <= RATIO_MAX + RATIO_SLACK:
        raise Invalid("o Instagram aceita imagens entre 4:5 (retrato) e 1,91:1 (paisagem)")
    return width, height


def clean_caption(v) -> str:
    text = CONTROL.sub("", str(v or "").replace("\r\n", "\n")).strip()
    if len(text) > CAPTION_MAX:
        raise Invalid(f"a legenda passa de {CAPTION_MAX} caracteres")
    if len(re.findall(r"(?<!\w)#\w+", text)) > HASHTAGS_MAX:
        raise Invalid(f"a legenda tem mais de {HASHTAGS_MAX} hashtags")
    if len(re.findall(r"(?<!\w)@[\w.]+", text)) > MENTIONS_MAX:
        raise Invalid(f"a legenda marca mais de {MENTIONS_MAX} perfis")
    return text


def clean_due(v) -> str | None:
    """A moment as the browser sends it (ISO, with Z or an offset), kept as UTC to the
    second; None when blank."""
    if v in (None, ""):
        return None
    try:
        dt = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except ValueError:
        raise Invalid("a data de publicação não é válida") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return _utc(dt)


class Posts:
    """The profiles and the posts, over the Store's database, and the images next to it."""

    def __init__(self, store: Store):
        self.store = store
        self.media_dir = Path(f"{store.path}.media")

    # ---- images ---------------------------------------------------------------------------

    def keep_media(self, raw: bytes) -> dict:
        width, height = check_image(raw)
        token = secrets.token_urlsafe(32)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.media_dir / f".{token}.{threading.get_ident()}.tmp"
        tmp.write_bytes(raw)
        tmp.replace(self.media_dir / f"{token}.jpg")
        return {"media": token, "width": width, "height": height, "bytes": len(raw)}

    def media_path(self, token: str) -> Path | None:
        if not TOKEN.match(token or ""):
            return None
        path = self.media_dir / f"{token}.jpg"
        return path if path.is_file() else None

    def _forget_media(self, token: str) -> None:
        path = self.media_path(token)
        if path:
            with contextlib.suppress(OSError):
                path.unlink()

    def sweep_media(self, older_than: int = ORPHAN_SECONDS) -> int:
        """Images uploaded and never attached to a post (a form left half-way)."""
        if not self.media_dir.is_dir():
            return 0
        with self.store.db() as db:
            used = {r[0] for r in db.execute("SELECT media FROM post")}
        limit = datetime.now(UTC).timestamp() - older_than
        gone = 0
        for path in self.media_dir.glob("*.jpg"):
            with contextlib.suppress(OSError):
                if path.stem not in used and path.stat().st_mtime < limit:
                    path.unlink()
                    gone += 1
        return gone

    # ---- profiles -------------------------------------------------------------------------

    _PROFILE = (
        "SELECT p.*, c.name AS client_name, a.name AS by_name FROM ig_profile p "
        "JOIN client c ON c.id=p.client LEFT JOIN account a ON a.id=p.connected_by "
    )

    def profiles(self) -> list[dict]:
        with self.store.db() as db:
            rows = db.execute(self._PROFILE + "ORDER BY c.name COLLATE NOCASE").fetchall()
        return [dict(r) for r in rows]

    def profile(self, client: int) -> dict | None:
        with self.store.db() as db:
            row = db.execute(self._PROFILE + "WHERE p.client=?", (client,)).fetchone()
        return dict(row) if row else None

    def save_profile(self, client: int, who: dict, expires: str | None, by: int | None) -> dict:
        """The Instagram profile an admin just connected for `client`. One profile serves
        one client: connecting it for a second one is refused, naming the first."""
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM client WHERE id=?", (client,)).fetchone():
                raise NotFound("cliente não encontrado")
            other = db.execute(
                "SELECT c.name FROM ig_profile p JOIN client c ON c.id=p.client "
                "WHERE p.ig_id=? AND p.client<>?",
                (who["ig_id"], client),
            ).fetchone()
            if other:
                raise Invalid(f"este perfil já está ligado a {other['name']}")
            db.execute(
                "INSERT INTO ig_profile(client, ig_id, username, name, account_type, state, "
                "error, expires, connected_by, connected_at) VALUES (?,?,?,?,?,'ok','',?,?,?) "
                "ON CONFLICT(client) DO UPDATE SET ig_id=excluded.ig_id, "
                "username=excluded.username, name=excluded.name, "
                "account_type=excluded.account_type, state='ok', error='', "
                "expires=excluded.expires, connected_by=excluded.connected_by, "
                "connected_at=excluded.connected_at",
                (
                    client,
                    who["ig_id"],
                    who.get("username") or "",
                    who.get("name") or "",
                    who.get("account_type") or "",
                    expires,
                    by,
                    now(),
                ),
            )
        obs.event("ig_connected", account=by, client=client)
        return self.profile(client)

    def set_profile(self, client: int, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("state", "error", "expires")}
        if not allowed:
            return
        sets = ", ".join(f"{k}=?" for k in allowed)
        with self.store.db() as db:
            db.execute(f"UPDATE ig_profile SET {sets} WHERE client=?", (*allowed.values(), client))

    def remove_profile(self, client: int) -> dict | None:
        """Forget the profile; what was scheduled for it goes back to a draft."""
        was = self.profile(client)
        if not was:
            return None
        with self.store.db() as db:
            db.execute("DELETE FROM ig_profile WHERE client=?", (client,))
            db.execute(
                "UPDATE post SET status='draft', updated=? WHERE client=? AND status='scheduled'",
                (now(), client),
            )
        obs.event("ig_disconnected", client=client)
        return was

    # ---- posts ----------------------------------------------------------------------------

    _POST = (
        "SELECT p.*, c.name AS client_name, a.name AS by_name, g.username AS ig_username, "
        "g.state AS ig_state FROM post p JOIN client c ON c.id=p.client "
        "LEFT JOIN account a ON a.id=p.account LEFT JOIN ig_profile g ON g.client=p.client "
    )

    def posts(self) -> list[dict]:
        with self.store.db() as db:
            rows = db.execute(self._POST + "ORDER BY p.id DESC LIMIT 500").fetchall()
        return [dict(r) for r in rows]

    def post(self, pid: int) -> dict:
        with self.store.db() as db:
            row = db.execute(self._POST + "WHERE p.id=?", (pid,)).fetchone()
        if not row:
            raise NotFound("publicação não encontrada")
        return dict(row)

    def _when(self, db, client: int, status, due) -> tuple[str, str | None]:
        """`status` and `due` as a person may set them: a draft, or scheduled for a moment,
        which needs the client's profile connected."""
        if status not in ("draft", "scheduled"):
            raise Invalid("uma publicação é um rascunho ou fica agendada")
        when = clean_due(due)
        if status == "scheduled":
            if not when:
                raise Invalid("escolha quando publicar")
            ok = db.execute(
                "SELECT 1 FROM ig_profile WHERE client=? AND state='ok'", (client,)
            ).fetchone()
            if not ok:
                raise Invalid(NO_PROFILE)
        return status, when

    def create(self, body: dict, by: int | None) -> dict:
        try:
            client = int(body.get("client"))
        except (TypeError, ValueError):
            raise Invalid("escolha o cliente") from None
        media = str(body.get("media") or "")
        path = self.media_path(media)
        if not path:
            raise Invalid("envie a imagem de novo")
        width, height = jpeg_size(path.read_bytes())
        caption = clean_caption(body.get("caption"))
        alt = CONTROL.sub("", str(body.get("alt_text") or "")).strip()[:ALT_MAX]
        with self.store.db() as db:
            if not db.execute("SELECT 1 FROM client WHERE id=?", (client,)).fetchone():
                raise NotFound("cliente não encontrado")
            if db.execute("SELECT 1 FROM post WHERE media=?", (media,)).fetchone():
                raise Invalid("envie a imagem de novo")  # one image, one post
            status, due = self._when(db, client, body.get("status") or "draft", body.get("due"))
            pid = db.execute(
                "INSERT INTO post(client, caption, alt_text, media, width, height, status, due, "
                "account) VALUES (?,?,?,?,?,?,?,?,?)",
                (client, caption, alt, media, width, height, status, due, by),
            ).lastrowid
        obs.event("post_created", account=by, post=pid, status=status)
        return self.post(pid)

    def update(self, pid: int, body: dict) -> dict:
        """Caption, description, moment and draft/scheduled, while the post hasn't gone out."""
        post = self.post(pid)
        if post["status"] not in EDITABLE:
            raise Invalid("esta publicação já saiu ou está saindo")
        caption = clean_caption(body["caption"]) if "caption" in body else post["caption"]
        alt = post["alt_text"]
        if "alt_text" in body:
            alt = CONTROL.sub("", str(body.get("alt_text") or "")).strip()[:ALT_MAX]
        with self.store.db() as db:
            status = body.get("status") or (
                "draft" if post["status"] == "failed" else post["status"]
            )
            due_in = body["due"] if "due" in body else post["due"]
            status, due = self._when(db, post["client"], status, due_in)
            done = db.execute(
                "UPDATE post SET caption=?, alt_text=?, status=?, due=?, error='', updated=? "
                f"WHERE id=? AND status IN ({','.join('?' for _ in EDITABLE)})",
                (caption, alt, status, due, now(), pid, *EDITABLE),
            ).rowcount
        if not done:
            raise Invalid("esta publicação já saiu ou está saindo")
        return self.post(pid)

    def delete(self, pid: int) -> dict:
        """Remove a post from Pauta (never from Instagram: a published one stays there)."""
        post = self.post(pid)
        if post["status"] == "publishing":
            raise Invalid("esta publicação está saindo agora; espere um instante")
        with self.store.db() as db:
            db.execute("DELETE FROM post WHERE id=?", (pid,))
        self._forget_media(post["media"])
        return post

    # ---- the publisher's steps ------------------------------------------------------------

    def due(self, at: str | None = None) -> list[int]:
        with self.store.db() as db:
            rows = db.execute(
                "SELECT id FROM post WHERE status='scheduled' AND due<=? ORDER BY due, id",
                (at or now(),),
            ).fetchall()
        return [r[0] for r in rows]

    def claim(self, pid: int) -> bool:
        """Take the post for publishing; False when someone else has it or it went out."""
        with self.store.db() as db:
            done = db.execute(
                "UPDATE post SET status='publishing', started=?, error='', container='' "
                f"WHERE id=? AND status IN ({','.join('?' for _ in EDITABLE)})",
                (now(), pid, *EDITABLE),
            ).rowcount
        return bool(done)

    def mark(self, pid: int, **fields) -> None:
        allowed = ("status", "container", "media_id", "permalink", "error", "published_at")
        kept = {k: v for k, v in fields.items() if k in allowed}
        sets = ", ".join(f"{k}=?" for k in kept)
        with self.store.db() as db:
            db.execute(
                f"UPDATE post SET {sets}, updated=? WHERE id=?", (*kept.values(), now(), pid)
            )

    def fail_stuck(self, older_than: int = STUCK_SECONDS) -> int:
        limit = _utc(datetime.now(UTC) - timedelta(seconds=older_than))
        with self.store.db() as db:
            n = db.execute(
                "UPDATE post SET status='failed', error=?, updated=? "
                "WHERE status='publishing' AND started<?",
                (UNSURE, now(), limit),
            ).rowcount
        if n:
            obs.event("post_stuck", logging.WARNING, posts=n)
        return n


def publish(posts: Posts, ig: Instagram, pid: int, origin: str) -> dict:
    """Publish one post now. Returns the post as it ended: `published`, or `failed` with the
    reason on it (an Instagram refusal is the post's state, not this call's error). Raises
    Invalid only for what the person can fix before anything is sent."""
    post = posts.post(pid)
    profile = posts.profile(post["client"])
    if not profile or profile["state"] != "ok":
        raise Invalid(NO_PROFILE)
    if not posts.media_path(post["media"]):
        raise Invalid("a imagem desta publicação se perdeu: crie de novo")
    if not posts.claim(pid):
        raise Invalid("esta publicação já saiu ou está saindo")
    url = f"{origin.rstrip('/')}/api/media/{post['media']}.jpg"
    try:
        container = ig.create_container(profile["ig_id"], url, post["caption"], post["alt_text"])
        posts.mark(pid, container=container)
        ig.wait_ready(profile["ig_id"], container)
        media_id = ig.publish(profile["ig_id"], container)
    except InstagramError as e:
        posts.mark(pid, status="failed", error=str(e))
        if e.revoked:
            posts.set_profile(post["client"], state="revoked", error=str(e))
        obs.event("post_failed", logging.WARNING, post=pid, code=e.code, step=e.step)
        return posts.post(pid)
    except Exception:
        # a surprise after the first call: whether it went out is not known
        posts.mark(pid, status="failed", error=UNSURE)
        obs.event("post_failed", logging.ERROR, post=pid, step="unknown")
        raise
    link = ""
    with contextlib.suppress(InstagramError):  # the post is out; the link is a nicety
        link = ig.permalink(profile["ig_id"], media_id)
    posts.mark(pid, status="published", media_id=media_id, permalink=link, published_at=now())
    obs.event("post_published", post=pid, client=post["client"])
    return posts.post(pid)


class Publisher:
    """The scheduled posts on a daemon thread: every tick publishes what is due, marks what
    died mid-way, notices a lapsed connection and clears forgotten images.
    Nothing it meets can kill it."""

    def __init__(self, posts: Posts, ig: Instagram, origin: str, clock=lambda: datetime.now(UTC)):
        self.posts, self.ig, self.origin, self.clock = posts, ig, origin, clock
        self.last_chores: datetime | None = None
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, name="publisher", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            self.tick()

    def tick(self) -> list[dict]:
        """One check. Returns the posts it tried, as they ended."""
        out: list[dict] = []
        try:
            self.posts.fail_stuck()
            for pid in self.posts.due(_utc(self.clock())):
                try:
                    out.append(publish(self.posts, self.ig, pid, self.origin))
                except Invalid as e:  # the profile went away since it was scheduled
                    self.posts.mark(pid, status="failed", error=str(e))
                    out.append(self.posts.post(pid))
            now_ = self.clock()
            if self.last_chores is None or now_ - self.last_chores >= timedelta(hours=6):
                self.last_chores = now_
                self.chores()
        except Exception as e:  # noqa: BLE001 - the thread must outlive any surprise
            obs.event("publisher_failed", logging.ERROR, error=type(e).__name__)
        return out

    def chores(self) -> None:
        """Say so on the profile when its token is gone or lapsed (a system-user token of a
        "never" configuration doesn't lapse); clear images no post took."""
        self.posts.sweep_media()
        for p in self.posts.profiles():
            if p["state"] != "ok":
                continue
            left = self.ig.expires_in(p["ig_id"], self.clock())
            if left is None or left <= timedelta(0):
                self.posts.set_profile(p["client"], state="expired", error="a conexão venceu")
