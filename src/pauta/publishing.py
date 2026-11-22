"""Publicações (docs/publishing-spec.md): posts for a client's Instagram, kept here and
published at their time.

A connection is a business portfolio a person logged in for at Meta (`ig_connection`); it
gives access to that portfolio's Instagram accounts (`ig_account`), and an admin says which
client each account is for, as ad accounts are assigned (instagram.py holds the tokens, one
per connection; the tables hold who, never a token). A post is one file and, except for a
Story, a caption, for one of those accounts and the client it is assigned to. It goes out
only while its account is connected and still that client's (`why_not`).
Its `kind` says where it goes: `feed` (a JPEG), `story` (a JPEG or a video) or `reel` (a
video). Instagram's API has no scheduling: Pauta keeps the post and publishes it when it is
due. Instagram fetches the file itself from a public address, so each lives under
`<db>.media/<token>.<jpg|mp4|mov>` and is served at `/api/media/<token>.<ext>`: unguessable,
and gone with its post (a video goes as soon as it is published: it is large).

Publishing is three calls (a container, wait until ready, publish). A post is claimed
(`publishing`) before the first, so two taps or a tap and the scheduler never post twice. A
picture is ready in seconds and the call that publishes it waits. A video takes minutes:
the post stays `publishing` with its container, and the publisher's tick looks at it once a
minute and publishes it when Instagram is done (`advance`). A post found still `publishing`
long after it started (the server died mid-way) is marked failed with "confira no
Instagram": whether it went out is not known, and a blind retry could post it a second time.
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
from .instagram import BAD_VIDEO, SLOW_VIDEO, Instagram, InstagramError

MAX_IMAGE = 8 * 1024 * 1024  # Instagram's limit for an image
CAPTION_MAX = 2200
ALT_MAX = 1000
HASHTAGS_MAX, MENTIONS_MAX = 30, 20
RATIO_MIN, RATIO_MAX = 4 / 5, 1.91  # width / height: portrait 4:5 to landscape 1.91:1
WIDTH_MIN = 320
# rounding: a 1080x1350 image is exactly 0.8, a 1080x566 one 1.908
RATIO_SLACK = 0.01

KINDS = ("feed", "story", "reel")
STORY_RATIO, STORY_SLACK = 9 / 16, 0.02  # a Story's picture fills a phone's screen
MAX_VIDEO = 300 * 1024 * 1024  # Instagram's limit for a Reel, and the most an upload may be
VIDEO_MIN_SECONDS = 3
# a video by kind: the longest it may run (seconds) and its largest file (Instagram's limits)
VIDEO_RULES = {"story": (60, 100 * 1024 * 1024), "reel": (15 * 60, MAX_VIDEO)}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}  # what an upload may say it is
EXTENSIONS = ("jpg", "mp4", "mov")
CHUNK = 256 * 1024  # bytes read from, or written to, a connection at a time
MOOV_MAX = 32 * 1024 * 1024  # a video's index is a few MB at most

STATUSES = ("draft", "scheduled", "publishing", "published", "failed")
EDITABLE = ("draft", "scheduled", "failed")  # what a person may still change or publish

TICK_SECONDS = 20
STUCK_SECONDS = 10 * 60  # a `publishing` older than this died mid-way
VIDEO_CHECK_SECONDS = 60  # Meta: read a video container's status once a minute
VIDEO_WAIT_SECONDS = 15 * 60  # what Instagram gets to prepare a video (Meta suggests five)
VIDEO_STUCK_SECONDS = 30 * 60  # past the wait and still `publishing`: it died mid-way
ORPHAN_SECONDS = 24 * 3600  # an uploaded image no post took

UNSURE = "não sabemos se esta publicação saiu: confira no Instagram antes de publicar de novo"
NO_PROFILE = "conecte o Instagram deste cliente primeiro"
NO_ACCOUNT_POST = "escolha a conta do Instagram desta publicação"
MOVED = "a conta desta publicação não é mais deste cliente: escolha outra conta"
NO_ACCOUNT = "conta do Instagram não encontrada"
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


def clean_kind(v) -> str:
    kind = str(v or "feed")
    if kind not in KINDS:
        raise Invalid("uma publicação vai para o feed, é um Story ou é um Reel")
    return kind


def check_shape(width: int, height: int, kind: str) -> None:
    """A picture's proportion for where it goes: the feed takes 4:5 to 1.91:1, a Story 9:16."""
    ratio = width / height
    if kind == "story":
        if abs(ratio - STORY_RATIO) > STORY_SLACK:
            raise Invalid("um Story precisa de uma imagem vertical 9:16 (por exemplo 1080 × 1920)")
    elif not RATIO_MIN - RATIO_SLACK <= ratio <= RATIO_MAX + RATIO_SLACK:
        raise Invalid("o Instagram aceita imagens entre 4:5 (retrato) e 1,91:1 (paisagem)")


def check_image(raw: bytes, kind: str = "feed") -> tuple[int, int]:
    """Instagram's rules for a picture, checked before anything is kept."""
    if not raw:
        raise Invalid("envie uma imagem")
    if len(raw) > MAX_IMAGE:
        raise Invalid("a imagem passa de 8 MB")
    width, height = jpeg_size(raw)
    if width < WIDTH_MIN:
        raise Invalid(f"a imagem precisa ter pelo menos {WIDTH_MIN} px de largura")
    check_shape(width, height, kind)
    return width, height


def _boxes(raw: bytes):
    """The boxes of an MP4 or MOV, one inside the other: (type, body) for each at this level."""
    i = 0
    while i + 8 <= len(raw):
        size = int.from_bytes(raw[i : i + 4], "big")
        if size < 8 or i + size > len(raw):
            return
        yield raw[i + 4 : i + 8], raw[i + 8 : i + size]
        i += size


def video_seconds(path: Path) -> float:
    """How long an MP4 or MOV runs, read from its own header (`moov` → `mvhd`), wherever in
    the file that is; Invalid when the file isn't one. Nothing is decoded, and what is inside
    (the codec, the frame rate, the proportion) is left to Instagram, which says so when it
    cannot prepare the video."""
    bad = Invalid("o vídeo precisa ser MP4 ou MOV")
    end = path.stat().st_size
    with path.open("rb") as f:
        pos = 0
        while pos + 8 <= end:
            f.seek(pos)
            head = f.read(16)
            size, kind, header = int.from_bytes(head[:4], "big"), head[4:8], 8
            if size == 1:  # the real size follows, in 64 bits
                size, header = int.from_bytes(head[8:16], "big"), 16
            elif size == 0:  # to the end of the file
                size = end - pos
            if size < header or pos + size > end or (pos == 0 and kind != b"ftyp"):
                raise bad
            if kind == b"moov":
                if size > MOOV_MAX:
                    raise bad
                f.seek(pos + header)
                for name, body in _boxes(f.read(size - header)):
                    if name == b"mvhd":
                        wide = body[:1] == b"\x01"  # version 1: 64-bit times
                        scale = int.from_bytes(body[20:24] if wide else body[12:16], "big")
                        ticks = int.from_bytes(body[24:32] if wide else body[16:20], "big")
                        if scale:
                            return ticks / scale
                break
            pos += size
    raise bad


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


def why_not(post_client: int, account: dict | None) -> str:
    """Why a post cannot go out as it stands, or "" when it can. `account` is the post's
    `ig_account` row with its connection's `state` ("" when it has no connection), or None
    when the post has no account. The one rule: asked when a post is scheduled, when it is
    sent, and for the notice on the list."""
    if account is None:
        return NO_ACCOUNT_POST
    if account["client"] != post_client:
        return MOVED
    if not account["business_id"] or account["state"] != "ok":
        return NO_PROFILE
    return ""


class Posts:
    """The connections, their accounts and the posts, over the Store's database, and the
    posts' files next to it."""

    def __init__(self, store: Store):
        self.store = store
        self.media_dir = Path(f"{store.path}.media")

    # ---- images ---------------------------------------------------------------------------

    def keep_media(self, raw: bytes, kind: str = "feed") -> dict:
        width, height = check_image(raw, clean_kind(kind))
        token = secrets.token_urlsafe(32)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.media_dir / f".{token}.{threading.get_ident()}.tmp"
        tmp.write_bytes(raw)
        tmp.replace(self.media_dir / f"{token}.jpg")
        return {
            "media": token,
            "media_type": "image",
            "width": width,
            "height": height,
            "bytes": len(raw),
        }

    def keep_video(self, read, length: int, ext: str) -> dict:
        """A video as it was exported, straight to the disk (never whole in memory): `read(n)`
        gives the next bytes of the upload. Kept when it is an MP4 or MOV of a length some
        kind takes; which kind is checked when the post is made."""
        if ext not in EXTENSIONS[1:] or not 0 < length <= MAX_VIDEO:
            raise Invalid(f"o vídeo passa de {MAX_VIDEO // (1024 * 1024)} MB")
        token = secrets.token_urlsafe(32)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.media_dir / f".{token}.{threading.get_ident()}.tmp"
        try:
            left = length
            with tmp.open("wb") as f:
                while left:
                    chunk = read(min(CHUNK, left))
                    if not chunk:
                        raise Invalid("o envio parou no meio; tente de novo")
                    f.write(chunk)
                    left -= len(chunk)
            seconds = video_seconds(tmp)
            check_video(seconds, length, "reel")  # the widest rules: a Story's come later
            tmp.replace(self.media_dir / f"{token}.{ext}")
        finally:
            with contextlib.suppress(OSError):
                tmp.unlink()
        return {"media": token, "media_type": "video", "seconds": seconds, "bytes": length}

    def media_path(self, token: str) -> Path | None:
        if not TOKEN.match(token or ""):
            return None
        for ext in EXTENSIONS:
            path = self.media_dir / f"{token}.{ext}"
            if path.is_file():
                return path
        return None

    def forget_media(self, token: str) -> None:
        path = self.media_path(token)
        if path:
            with contextlib.suppress(OSError):
                path.unlink()

    def sweep_media(self, older_than: int = ORPHAN_SECONDS) -> int:
        """Files uploaded and never attached to a post (a form left half-way), and what an
        upload that died left behind."""
        if not self.media_dir.is_dir():
            return 0
        with self.store.db() as db:
            used = {r[0] for r in db.execute("SELECT media FROM post")}
        limit = datetime.now(UTC).timestamp() - older_than
        gone = 0
        for path in self.media_dir.iterdir():
            with contextlib.suppress(OSError):
                if path.stem not in used and path.stat().st_mtime < limit:
                    path.unlink()
                    gone += 1
        return gone

    # ---- connections and accounts ---------------------------------------------------------

    _ACCOUNT = (
        "SELECT g.*, c.name AS client_name, COALESCE(n.state, '') AS state FROM ig_account g "
        "LEFT JOIN client c ON c.id=g.client "
        "LEFT JOIN ig_connection n ON n.business_id=g.business_id AND g.business_id<>'' "
    )

    def connections(self) -> list[dict]:
        """Every connected portfolio, oldest first, with how many accounts it has."""
        with self.store.db() as db:
            rows = db.execute(
                "SELECT n.*, a.name AS by_name, (SELECT COUNT(*) FROM ig_account g "
                "WHERE g.business_id=n.business_id) AS accounts FROM ig_connection n "
                "LEFT JOIN account a ON a.id=n.connected_by "
                "ORDER BY n.connected_at, n.business_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def accounts(self) -> list[dict]:
        """Every Instagram account, with its client's name and its connection's state
        ("" when it has no connection)."""
        with self.store.db() as db:
            rows = db.execute(self._ACCOUNT + "ORDER BY g.username, g.ig_id").fetchall()
        return [dict(r) for r in rows]

    def account(self, ig_id: str) -> dict | None:
        with self.store.db() as db:
            return self._account(db, ig_id)

    def _account(self, db, ig_id: str) -> dict | None:
        row = db.execute(self._ACCOUNT + "WHERE g.ig_id=?", (str(ig_id or ""),)).fetchone()
        return dict(row) if row else None

    def save_connection(
        self, portfolio: dict, accounts: list[dict], expires: str | None, by: int | None
    ) -> None:
        """What a login gave: the portfolio and the accounts it lists. An account is new, or
        known and now under this portfolio whichever held it before (the last login wins);
        its client is never touched. An account of this portfolio the login no longer lists
        is no longer connected: the new token does not reach it."""
        business = portfolio["business_id"]
        listed = [a["ig_id"] for a in accounts]
        with self.store.db() as db:
            db.execute(
                "INSERT INTO ig_connection(business_id, business_name, connected_by, "
                "connected_at, state, error, expires) VALUES (?,?,?,?,'ok','',?) "
                "ON CONFLICT(business_id) DO UPDATE SET business_name=excluded.business_name, "
                "connected_by=excluded.connected_by, connected_at=excluded.connected_at, "
                "state='ok', error='', expires=excluded.expires",
                (business, portfolio.get("business_name") or "", by, now(), expires),
            )
            db.execute(
                "UPDATE ig_account SET business_id='' WHERE business_id=? "
                f"AND ig_id NOT IN ({','.join('?' for _ in listed)})",
                (business, *listed),
            )
            for a in accounts:
                db.execute(
                    "INSERT INTO ig_account(ig_id, username, business_id) VALUES (?,?,?) "
                    "ON CONFLICT(ig_id) DO UPDATE SET username=excluded.username, "
                    "business_id=excluded.business_id",
                    (a["ig_id"], a.get("username") or "", business),
                )
        obs.event("ig_connected", account=by, business=business, accounts=len(listed))

    def assign(self, ig_id: str, client: int | None, by: int | None) -> dict:
        """Say which client an account is for (None: none). No post changes: one whose
        account is no longer its client's says so and is refused when it would go out."""
        with self.store.db() as db:
            if not self._account(db, ig_id):
                raise NotFound(NO_ACCOUNT)
            known = db.execute("SELECT 1 FROM client WHERE id=?", (client,)).fetchone()
            if client is not None and not known:
                raise NotFound("cliente não encontrado")
            db.execute("UPDATE ig_account SET client=? WHERE ig_id=?", (client, ig_id))
            account = self._account(db, ig_id)
        obs.event("ig_account_assigned", account=by, ig=ig_id, client=client)
        return account

    def set_connection(self, business_id: str, **fields) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("state", "error", "expires")}
        if not allowed:
            return
        sets = ", ".join(f"{k}=?" for k in allowed)
        with self.store.db() as db:
            db.execute(
                f"UPDATE ig_connection SET {sets} WHERE business_id=?",
                (*allowed.values(), business_id),
            )

    def remove_connection(self, business_id: str) -> bool:
        """Forget the portfolio. Its accounts stay, with their clients and no connection, so
        connecting again loses no assignment; no post changes."""
        with self.store.db() as db:
            gone = db.execute(
                "DELETE FROM ig_connection WHERE business_id=?", (business_id,)
            ).rowcount
            if gone:
                db.execute(
                    "UPDATE ig_account SET business_id='' WHERE business_id=?", (business_id,)
                )
        if gone:
            obs.event("ig_disconnected", business=business_id)
        return bool(gone)

    def remove_account(self, ig_id: str, by: int | None) -> None:
        """Take an account that is not connected off Pauta. Its posts keep their text and
        file, and have no account from then on."""
        with self.store.db() as db:
            account = self._account(db, ig_id)
            if not account:
                raise NotFound(NO_ACCOUNT)
            if account["business_id"]:
                raise Invalid("desconecte o portfólio desta conta antes de remover")
            db.execute("DELETE FROM ig_account WHERE ig_id=?", (ig_id,))
        obs.event("ig_account_removed", account=by, ig=ig_id)

    def _ready(self, db, post_client: int, ig_id: str) -> dict:
        """The post's account, when the post can go out; Invalid with the reason otherwise."""
        account = self._account(db, ig_id) if ig_id else None
        why = why_not(post_client, account)
        if why:
            raise Invalid(why)
        return account

    def ready(self, post_client: int, ig_id: str) -> dict:
        with self.store.db() as db:
            return self._ready(db, post_client, ig_id)

    # ---- posts ----------------------------------------------------------------------------

    _POST = (
        "SELECT p.*, c.name AS client_name, a.name AS by_name, g.username AS ig_username, "
        "g.ig_id AS ig_known, g.client AS ig_client, g.business_id AS ig_business, "
        "n.state AS ig_state FROM post p JOIN client c ON c.id=p.client "
        "LEFT JOIN account a ON a.id=p.account LEFT JOIN ig_account g ON g.ig_id=p.ig_id "
        "LEFT JOIN ig_connection n ON n.business_id=g.business_id AND g.business_id<>'' "
    )

    @staticmethod
    def _row(row) -> dict:
        """A post as the rest of the app gets it: with `blocked`, why it cannot go out as it
        stands ("" when it can, and for one that is going out or went)."""
        post = dict(row)
        known, client = post.pop("ig_known"), post.pop("ig_client")
        business, state = post.pop("ig_business"), post.pop("ig_state")
        account = (
            {"client": client, "business_id": business, "state": state or ""} if known else None
        )
        post["blocked"] = why_not(post["client"], account) if post["status"] in EDITABLE else ""
        return post

    def posts(self) -> list[dict]:
        with self.store.db() as db:
            rows = db.execute(self._POST + "ORDER BY p.id DESC LIMIT 500").fetchall()
        return [self._row(r) for r in rows]

    def post(self, pid: int) -> dict:
        with self.store.db() as db:
            row = db.execute(self._POST + "WHERE p.id=?", (pid,)).fetchone()
        if not row:
            raise NotFound("publicação não encontrada")
        return self._row(row)

    def _when(self, db, client: int, ig_id: str, status, due) -> tuple[str, str | None]:
        """`status` and `due` as a person may set them: a draft, or scheduled for a moment,
        which needs the post's account connected and its client's."""
        if status not in ("draft", "scheduled"):
            raise Invalid("uma publicação é um rascunho ou fica agendada")
        when = clean_due(due)
        if status == "scheduled":
            if not when:
                raise Invalid("escolha quando publicar")
            self._ready(db, client, ig_id)
        return status, when

    def create(self, body: dict, by: int | None) -> dict:
        ig_id = str(body.get("ig_id") or "")
        kind = clean_kind(body.get("kind"))
        media = str(body.get("media") or "")
        path = self.media_path(media)
        if not path:
            raise Invalid("envie o arquivo de novo")
        video = path.suffix != ".jpg"
        width = height = 0
        if video:
            check_video(video_seconds(path), path.stat().st_size, kind)
        elif kind == "reel":
            raise Invalid("um Reel precisa de um vídeo")
        else:
            width, height = jpeg_size(path.read_bytes())
            check_shape(width, height, kind)
        # a Story has no caption, and only a picture in the feed has a description
        caption = "" if kind == "story" else clean_caption(body.get("caption"))
        alt = CONTROL.sub("", str(body.get("alt_text") or "")).strip()[:ALT_MAX]
        alt = alt if kind == "feed" else ""
        with self.store.db() as db:
            # the account says whom the post is for: one with no client is nobody's yet
            account = self._account(db, ig_id) if ig_id else None
            if not account or account["client"] is None:
                raise Invalid(NO_ACCOUNT_POST)
            client = account["client"]
            if db.execute("SELECT 1 FROM post WHERE media=?", (media,)).fetchone():
                raise Invalid("envie o arquivo de novo")  # one file, one post
            status, due = self._when(
                db, client, ig_id, body.get("status") or "draft", body.get("due")
            )
            pid = db.execute(
                "INSERT INTO post(client, ig_id, caption, alt_text, media, width, height, kind, "
                "media_type, status, due, account) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    client,
                    ig_id,
                    caption,
                    alt,
                    media,
                    width,
                    height,
                    kind,
                    "video" if video else "image",
                    status,
                    due,
                    by,
                ),
            ).lastrowid
        obs.event("post_created", account=by, post=pid, status=status, kind=kind)
        return self.post(pid)

    def update(self, pid: int, body: dict) -> dict:
        """Caption, description, moment, draft/scheduled and, among its client's accounts,
        the account, while the post hasn't gone out."""
        post = self.post(pid)
        if post["status"] not in EDITABLE:
            raise Invalid("esta publicação já saiu ou está saindo")
        caption = clean_caption(body["caption"]) if "caption" in body else post["caption"]
        alt = post["alt_text"]
        if "alt_text" in body:
            alt = CONTROL.sub("", str(body.get("alt_text") or "")).strip()[:ALT_MAX]
        if post["kind"] == "story":
            caption = ""
        if post["kind"] != "feed":
            alt = ""
        with self.store.db() as db:
            status = body.get("status") or (
                "draft" if post["status"] == "failed" else post["status"]
            )
            due_in = body["due"] if "due" in body else post["due"]
            ig_id = str(body.get("ig_id") or "") or post["ig_id"]
            if ig_id != post["ig_id"]:
                account = self._account(db, ig_id)
                if not account:
                    raise Invalid(NO_ACCOUNT_POST)
                if account["client"] != post["client"]:
                    raise Invalid(MOVED)
            status, due = self._when(db, post["client"], ig_id, status, due_in)
            done = db.execute(
                "UPDATE post SET caption=?, alt_text=?, ig_id=?, status=?, due=?, error='', "
                f"updated=? WHERE id=? AND status IN ({','.join('?' for _ in EDITABLE)})",
                (caption, alt, ig_id, status, due, now(), pid, *EDITABLE),
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
        self.forget_media(post["media"])
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
        """Set what the publisher learned; with nothing to set, only `updated` moves."""
        allowed = ("status", "container", "media_id", "permalink", "error", "published_at")
        kept = {k: v for k, v in fields.items() if k in allowed}
        sets = ", ".join(f"{k}=?" for k in (*kept, "updated"))
        with self.store.db() as db:
            db.execute(f"UPDATE post SET {sets} WHERE id=?", (*kept.values(), now(), pid))

    def waiting(self, quiet: int = VIDEO_CHECK_SECONDS) -> list[int]:
        """The videos Instagram is preparing that nobody looked at for `quiet` seconds."""
        limit = _utc(datetime.now(UTC) - timedelta(seconds=quiet))
        with self.store.db() as db:
            rows = db.execute(
                "SELECT id FROM post WHERE status='publishing' AND media_type='video' "
                "AND container<>'' AND updated<=? ORDER BY id",
                (limit,),
            ).fetchall()
        return [r[0] for r in rows]

    def fail_stuck(
        self, older_than: int = STUCK_SECONDS, video_older_than: int = VIDEO_STUCK_SECONDS
    ) -> int:
        def limit(seconds: int) -> str:
            return _utc(datetime.now(UTC) - timedelta(seconds=seconds))

        with self.store.db() as db:
            n = db.execute(
                "UPDATE post SET status='failed', error=?, updated=? WHERE status='publishing' "
                "AND started < CASE media_type WHEN 'video' THEN ? ELSE ? END",
                (UNSURE, now(), limit(video_older_than), limit(older_than)),
            ).rowcount
        if n:
            obs.event("post_stuck", logging.WARNING, posts=n)
        return n


def check_video(seconds: float, size: int, kind: str) -> None:
    """Instagram's rules for a video of this kind: how long it runs and how large it is."""
    if kind not in VIDEO_RULES:
        raise Invalid("um vídeo sai como Reel ou como Story")
    longest, largest = VIDEO_RULES[kind]
    name = "Story" if kind == "story" else "Reel"
    if size > largest:
        raise Invalid(f"o vídeo de um {name} tem no máximo {largest // (1024 * 1024)} MB")
    if seconds < VIDEO_MIN_SECONDS:
        raise Invalid(f"o vídeo precisa ter pelo menos {VIDEO_MIN_SECONDS} segundos")
    if seconds > longest:
        limit = f"{longest} segundos" if longest < 120 else f"{longest // 60} minutos"
        raise Invalid(f"o vídeo de um {name} tem no máximo {limit}")


def _failed(posts: Posts, post: dict, conn: str, e: InstagramError) -> dict:
    """An Instagram refusal is the post's state, with a reason a person can act on. A token
    Instagram no longer takes is its connection's (`conn`, "" when the post has none)."""
    posts.mark(post["id"], status="failed", error=str(e))
    if e.revoked and conn:
        posts.set_connection(conn, state="revoked", error=str(e))
    obs.event("post_failed", logging.WARNING, post=post["id"], code=e.code, step=e.step)
    return posts.post(post["id"])


def _published(posts: Posts, ig: Instagram, post: dict, conn: str, media_id: str) -> dict:
    link = ""
    with contextlib.suppress(InstagramError):  # the post is out; the link is a nicety
        link = ig.permalink(conn, media_id)
    posts.mark(
        post["id"], status="published", media_id=media_id, permalink=link, published_at=now()
    )
    if post["media_type"] == "video":  # hundreds of MB nobody needs here any more
        posts.forget_media(post["media"])
    obs.event("post_published", post=post["id"], client=post["client"], kind=post["kind"])
    return posts.post(post["id"])


def publish(posts: Posts, ig: Instagram, pid: int, origin: str) -> dict:
    """Publish one post now. Returns the post as it ended: `published`, or `failed` with the
    reason on it (an Instagram refusal is the post's state, not this call's error), or, for
    a video, still `publishing`: Instagram has it, and the publisher's tick takes it from
    there (`advance`). Raises Invalid only for what the person can fix before anything is
    sent: no account, an account that is not its client's any more or is not connected."""
    post = posts.post(pid)
    account = posts.ready(post["client"], post["ig_id"])
    conn = account["business_id"]
    path = posts.media_path(post["media"])
    if not path:
        raise Invalid("o arquivo desta publicação se perdeu: crie de novo")
    if not posts.claim(pid):
        raise Invalid("esta publicação já saiu ou está saindo")
    video = post["media_type"] == "video"
    url = f"{origin.rstrip('/')}/api/media/{post['media']}{path.suffix}"
    try:
        container = ig.create_container(
            conn, post["ig_id"], url, post["caption"], post["alt_text"], post["kind"], video
        )
        posts.mark(pid, container=container)
        if video:
            obs.event("post_waiting", post=pid, kind=post["kind"])
            return posts.post(pid)
        ig.wait_ready(conn, container)
        media_id = ig.publish(conn, post["ig_id"], container)
    except InstagramError as e:
        return _failed(posts, post, conn, e)
    except Exception:
        # a surprise after the first call: whether it went out is not known
        posts.mark(pid, status="failed", error=UNSURE)
        obs.event("post_failed", logging.ERROR, post=pid, step="unknown")
        raise
    return _published(posts, ig, post, conn, media_id)


def advance(posts: Posts, ig: Instagram, pid: int) -> dict:
    """One look at a video Instagram is preparing: published when it is ready, failed when
    Instagram gave up on it or took too long, or its account is no longer connected or its
    client's, left as it is otherwise. Until `media_publish` is called nothing has gone out,
    so these failures are safe to try again."""
    post = posts.post(pid)
    if post["status"] != "publishing" or not post["container"]:
        return post
    conn = ""
    try:
        try:
            conn = posts.ready(post["client"], post["ig_id"])["business_id"]
        except Invalid as e:
            raise InstagramError(str(e), step="status") from None
        state = ig.container_state(conn, post["container"])
        if state == "IN_PROGRESS":
            started = datetime.fromisoformat(post["started"]).replace(tzinfo=UTC)
            if datetime.now(UTC) - started > timedelta(seconds=VIDEO_WAIT_SECONDS):
                raise InstagramError(SLOW_VIDEO, step="status")
            posts.mark(pid)  # looked at: the next look is a minute away
            return posts.post(pid)
        if state != "FINISHED":
            obs.event("ig_container_failed", logging.WARNING, state=state)
            raise InstagramError(BAD_VIDEO, step="status")
        media_id = ig.publish(conn, post["ig_id"], post["container"])
    except InstagramError as e:
        return _failed(posts, post, conn, e)
    return _published(posts, ig, post, conn, media_id)


class Publisher:
    """The scheduled posts on a daemon thread: every tick publishes what is due, looks at
    the videos Instagram is preparing, marks what died mid-way, notices a lapsed connection
    and clears forgotten files. Nothing it meets can kill it."""

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
            for pid in self.posts.waiting():
                out.append(advance(self.posts, self.ig, pid))
            for pid in self.posts.due(_utc(self.clock())):
                try:
                    out.append(publish(self.posts, self.ig, pid, self.origin))
                except Invalid as e:  # its account is not connected, or not its client's
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
        """Say so on the connection when its token is gone or lapsed (a system-user token of
        a "never" configuration doesn't lapse); clear files no post took."""
        self.posts.sweep_media()
        for n in self.posts.connections():
            if n["state"] != "ok":
                continue
            left = self.ig.expires_in(n["business_id"], self.clock())
            if left is None or left <= timedelta(0):
                self.posts.set_connection(
                    n["business_id"], state="expired", error="a conexão venceu"
                )
