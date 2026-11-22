"""Publicações in the browser (docs/publishing-spec.md): the tab only where the Instagram
app is set; an admin connects a portfolio through Meta's login, comes back, and says which
client each Instagram account is for;
a picture chosen as PNG leaves as a JPEG Instagram takes; publish now, schedule, edit and
delete."""

import re

import pytest
from playwright.sync_api import expect

from fakeinstagram import IG_ID, USERNAME, mp4, png
from pauta.publishing import MOVED, NO_ACCOUNT_POST, NO_PROFILE, Posts, Publisher

pytestmark = pytest.mark.e2e


@pytest.fixture()
def ig(ig_on):
    return ig_on


def join(page, base, token, name):
    page.goto(f"{base}/#/entrar/{token}")
    page.fill("#join input[name=name]", name)
    page.get_by_role("button", name="Criar passkey e entrar").click()
    expect(page.locator("#shell")).to_be_visible()


def picture(name: str, width: int, height: int) -> dict:
    return {"name": name, "mimeType": "image/png", "buffer": png(width, height)}


def test_the_tab_only_where_the_instagram_app_is_set(live, device, ig):
    base, auth, _store = live
    ig.secret_file.unlink()
    token, _ = auth.create_invite(admin=True)
    page = device().page
    join(page, base, token, "Renato Lima")
    expect(page.locator("#nav a[data-nav='#/publicacoes']")).to_have_count(0)
    page.goto(f"{base}/#/publicacoes")
    expect(page).to_have_url(re.compile(r"/#/$"))


def test_connect_publish_schedule_edit_delete(live, device, ig, fake_ig):
    base, auth, store = live
    client = store.save_client({"name": "Du7"})
    store.save_client({"name": "Padaria Trigo de Ouro"})
    token, _ = auth.create_invite(admin=True)
    laptop = device()
    page = laptop.page
    page.on("dialog", lambda d: d.accept())  # the "publicar agora?" and "excluir?" questions
    join(page, base, token, "Renato Lima")

    page.locator("#nav a[data-nav='#/publicacoes']").click()
    expect(page.get_by_role("heading", name="Publicações")).to_be_visible()
    expect(page.locator("#igprofiles .empty")).to_have_text(
        "Nenhuma conta do Instagram conectada ainda."
    )
    expect(page.get_by_role("link", name="Nova publicação")).to_have_count(0)

    # Conectar Instagram: out to Meta's login and back, with the portfolio and its account
    # on the list, and the account nobody's until an admin says whose it is
    page.get_by_role("button", name="Conectar Instagram").click()
    expect(page.locator("#toast")).to_have_text("Instagram conectado")
    expect(page).to_have_url(re.compile(r"/#/publicacoes$"))
    portfolio = page.locator("#igprofiles [data-connection]").first
    expect(portfolio).to_contain_text("Du7 Portfólio")
    expect(portfolio).to_contain_text("conectado")
    row = page.locator(f"#igprofiles [data-account-row='{IG_ID}']")
    expect(row).to_contain_text(f"@{USERNAME}")
    expect(row.locator("select")).to_have_value("")
    expect(page.get_by_role("link", name="Nova publicação")).to_have_count(0)
    row.locator("select").select_option(str(client["id"]))
    expect(page.locator("#toast")).to_have_text("Conta de Du7")
    expect(row.locator("select")).to_have_value(str(client["id"]))

    # a new post: a shape Instagram refuses is told at once; a PNG becomes a JPEG
    page.get_by_role("link", name="Nova publicação").click()
    expect(page.get_by_role("heading", name="Nova publicação")).to_be_visible()
    expect(page.locator("#pclient option")).to_have_text([f"Du7 (@{USERNAME})"])
    page.set_input_files("#pfile", picture("story.png", 540, 960))
    expect(page.locator("#pimginfo")).to_contain_text("entre 4:5 (retrato) e 1,91:1 (paisagem)")
    expect(page.locator("#ppreview")).to_be_hidden()
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("escolha a imagem")
    page.set_input_files("#pfile", picture("post.png", 800, 1000))
    expect(page.locator("#pimginfo")).to_contain_text("800 × 1000 px")
    expect(page.locator("#ppreview")).to_be_visible()
    page.fill("#pcaption", "Bom dia!\n#du7 #pauta")
    expect(page.locator("#pcount")).to_have_text("20 / 2200")
    page.fill("#palt", "Um quadrado roxo")
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("Publicado no Instagram")
    expect(page).to_have_url(re.compile(r"/#/publicacoes$"))

    # Instagram fetched a real JPEG from the app and published it
    (sent,) = fake_ig.published
    assert (sent["caption"], sent["alt_text"]) == ("Bom dia!\n#du7 #pauta", "Um quadrado roxo")
    (fetch,) = fake_ig.fetched
    assert (fetch["status"], fetch["type"], fetch["magic"]) == (200, "image/jpeg", b"\xff\xd8\xff")
    out = page.locator("#ppublished .prow")
    expect(out).to_have_count(1)
    expect(out.locator(".pstatus")).to_have_text("publicada")
    expect(out.get_by_role("link", name="Ver no Instagram")).to_have_attribute(
        "href", f"https://www.instagram.com/p/{sent['id']}/"
    )
    expect(out.locator("img.pthumb")).to_be_visible()
    with store.db() as db:
        row = db.execute("SELECT width, height, status FROM post").fetchone()
    assert tuple(row) == (800, 1000, "published")

    # scheduled for a moment, in the browser's own time
    page.get_by_role("link", name="Nova publicação").click()
    page.set_input_files("#pfile", picture("b.png", 1000, 1000))
    expect(page.locator("#ppreview")).to_be_visible()
    page.fill("#pcaption", "Semana que vem")
    page.get_by_role("button", name="Agendar").click()  # no date yet: one is suggested
    expect(page.locator("#toast")).to_have_text("confira a data e toque em Agendar de novo")
    page.fill("#pdue", "2031-03-15T10:30")
    page.get_by_role("button", name="Agendar").click()
    expect(page.locator("#toast")).to_have_text("Agendada para 15/03 10:30")
    waiting = page.locator("#pscheduled .prow")
    expect(waiting).to_have_count(1)
    expect(waiting.locator(".pstatus")).to_have_text("agendada")
    expect(waiting).to_contain_text("sai em 15/03 10:30")
    assert len(fake_ig.published) == 1  # nothing left yet

    # edited back into a draft, then deleted
    waiting.get_by_role("link", name="Editar").click()
    expect(page.get_by_role("heading", name="Editar publicação")).to_be_visible()
    expect(page.locator("#pcaption")).to_have_value("Semana que vem")
    expect(page.locator("#pdue")).to_have_value("2031-03-15T10:30")
    page.fill("#pcaption", "Mudou")
    page.get_by_role("button", name="Salvar rascunho").click()
    expect(page.locator("#toast")).to_have_text("Rascunho salvo")
    draft = page.locator("#pdrafts .prow")
    expect(draft).to_have_count(1)
    expect(draft.locator(".pcap")).to_have_text("Mudou")
    expect(page.locator("#pscheduled")).to_have_count(0)
    draft.get_by_role("button", name="Excluir").click()
    expect(page.locator("#pdrafts")).to_have_count(0)
    expect(page.locator(".prow")).to_have_count(1)

    # a refusal is said on the post, and the post stays to be sent again
    page.get_by_role("link", name="Nova publicação").click()
    page.set_input_files("#pfile", picture("c.png", 1000, 1000))
    expect(page.locator("#ppreview")).to_be_visible()
    fake_ig.at_limit = True
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_contain_text("Não saiu: este perfil atingiu o limite")
    failed = page.locator("#pdrafts .prow")
    expect(failed.locator(".pstatus")).to_have_text("falhou")
    expect(failed.locator(".perr")).to_contain_text("limite de publicações do Instagram")
    fake_ig.at_limit = False
    failed.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("Publicado no Instagram")
    expect(page.locator("#ppublished .prow")).to_have_count(2)

    # Desconectar: the portfolio goes; its account stays, with its client and no connection;
    # no post changes, and one that is scheduled says why it will not go out
    page.get_by_role("link", name="Nova publicação").click()
    page.set_input_files("#pfile", picture("d.png", 1000, 1000))
    expect(page.locator("#ppreview")).to_be_visible()
    page.fill("#pdue", "2031-03-15T10:30")
    page.get_by_role("button", name="Agendar").click()
    expect(page.locator("#toast")).to_have_text("Agendada para 15/03 10:30")
    page.get_by_role("button", name="Desconectar").click()
    expect(page.locator("#toast")).to_have_text("Instagram desconectado")
    loose = page.locator("#igprofiles [data-connection='']")
    expect(loose).to_contain_text("Sem conexão")
    expect(loose.locator(f"[data-account-row='{IG_ID}'] select")).to_have_value(str(client["id"]))
    still = page.locator("#pscheduled .prow")
    expect(still.locator(".pstatus")).to_have_text("agendada")
    expect(still.locator(".pblocked")).to_have_text(NO_PROFILE)
    expect(page.get_by_role("link", name="Nova publicação")).to_have_count(0)
    expect(page.locator("#ppublished .prow")).to_have_count(2)
    # Remover: an account that is not connected leaves Pauta, and its post has no account
    loose.get_by_role("button", name="Remover").click()
    expect(page.locator("#toast")).to_have_text("Conta removida")
    expect(page.locator("#igprofiles .empty")).to_be_visible()
    expect(page.locator("#pscheduled .prow .pblocked")).to_have_text(NO_ACCOUNT_POST)


def connected(page, base, auth, store):
    """Renato (admin) signed in, on Publicações, the portfolio connected and its account
    given to the client."""
    client = store.save_client({"name": "Du7"})
    token, _ = auth.create_invite(admin=True)
    page.on("dialog", lambda d: d.accept())
    join(page, base, token, "Renato Lima")
    page.locator("#nav a[data-nav='#/publicacoes']").click()
    page.get_by_role("button", name="Conectar Instagram").click()
    expect(page.locator("#toast")).to_have_text("Instagram conectado")
    page.locator(f"[data-account-row='{IG_ID}'] select").select_option(str(client["id"]))
    expect(page.locator("#toast")).to_have_text("Conta de Du7")
    return client


def test_a_story_and_a_reel(live, device, ig, fake_ig):
    base, auth, store = live
    laptop = device()
    laptop.expected.add((400, "/api/posts"))  # the Story the server refuses, below
    page = laptop.page
    connected(page, base, auth, store)
    clip = {"name": "clip.mp4", "mimeType": "video/mp4", "buffer": mp4(65, pad=300_000)}

    # the form opens as it always did: a picture for the feed, with its caption
    page.get_by_role("link", name="Nova publicação").click()
    expect(page.locator("#pkind button.on")).to_have_text("Feed")
    expect(page.locator("#pcaption")).to_be_visible()
    expect(page.locator("#palt")).to_be_visible()
    page.set_input_files("#pfile", clip)
    expect(page.locator("#toast")).to_contain_text("um vídeo sai como Reel ou como Story")

    # a Story: a tall picture, no caption and no description
    page.locator("#pkind").get_by_role("button", name="Story").click()
    expect(page.locator("#pimginfo")).to_contain_text("Um Story não leva legenda")
    expect(page.locator("#pcaption")).to_be_hidden()
    expect(page.locator("#palt")).to_be_hidden()
    page.set_input_files("#pfile", picture("square.png", 800, 800))
    expect(page.locator("#pimginfo")).to_contain_text("imagem vertical 9:16")
    page.set_input_files("#pfile", clip)  # 65 seconds: the server says a Story takes 60
    expect(page.locator("#pvideo")).to_be_visible()
    expect(page.locator("#pimginfo")).to_have_text("1:05, 0,3 MB")
    page.get_by_role("button", name="Salvar rascunho").click()
    expect(page.locator("#toast")).to_contain_text("Story tem no máximo 60 segundos")
    page.set_input_files("#pfile", picture("tall.png", 540, 960))
    expect(page.locator("#pimginfo")).to_contain_text("540 × 960 px")
    expect(page.locator("#ppreview")).to_be_visible()
    expect(page.locator("#pvideo")).to_be_hidden()
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("Publicado no Instagram")
    (story,) = fake_ig.published
    assert (story["kind"], story["video"], story["caption"]) == ("STORIES", False, "")
    out = page.locator("#ppublished .prow")
    expect(out.locator(".tag")).to_have_text("Story")
    expect(out.locator("img.pthumb")).to_be_visible()

    # a Reel: the video goes up as it is, and Instagram takes its time with it
    page.get_by_role("link", name="Nova publicação").click()
    page.locator("#pkind").get_by_role("button", name="Reel").click()
    expect(page.locator("#pcaption")).to_be_visible()
    expect(page.locator("#palt")).to_be_hidden()
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("escolha o vídeo")
    page.set_input_files("#pfile", picture("post.png", 800, 1000))
    expect(page.locator("#toast")).to_have_text("um Reel precisa de um vídeo")
    page.set_input_files("#pfile", clip)
    expect(page.locator("#pvideo")).to_be_visible()
    expect(page.locator("#pvideo")).to_have_attribute("src", re.compile(r"^/api/posts/media/"))
    page.fill("#pcaption", "Bastidores #du7")
    fake_ig.not_ready = 1
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_contain_text("O Instagram está preparando o vídeo")
    going = page.locator("#pscheduled .prow")
    expect(going.locator(".pstatus")).to_have_text("saindo…")
    expect(going.locator(".tag")).to_have_text("Reel")
    expect(going.locator(".pthumb.pvideo")).to_be_visible()
    expect(going.get_by_role("button")).to_have_count(0)  # nothing to do while it goes out
    assert len(fake_ig.published) == 1

    # the publisher's looks, a minute apart: not ready, then out
    pub = Publisher(Posts(store), ig, base)
    for _ in range(2):
        with store.db() as db:
            db.execute("UPDATE post SET updated=datetime('now','-61 seconds')")
        pub.tick()
    reel = fake_ig.published[1]
    assert (reel["kind"], reel["video"], reel["caption"]) == ("REELS", True, "Bastidores #du7")
    page.reload()
    done = page.locator("#ppublished .prow").first
    expect(done.locator(".pstatus")).to_have_text("publicada")
    expect(done.locator(".tag")).to_have_text("Reel")
    expect(done.get_by_role("link", name="Ver no Instagram")).to_be_visible()
    expect(page.locator("#pscheduled")).to_have_count(0)


def test_editing_a_video_draft_shows_the_video(live, device, ig, fake_ig):
    base, auth, store = live
    page = device().page
    connected(page, base, auth, store)
    page.get_by_role("link", name="Nova publicação").click()
    page.locator("#pkind").get_by_role("button", name="Reel").click()
    page.set_input_files(
        "#pfile", {"name": "IMG_0001.MOV", "mimeType": "", "buffer": mp4(12)}
    )  # a phone's file with no type: its name says what it is
    expect(page.locator("#pimginfo")).to_contain_text("0:12")
    page.fill("#pcaption", "Rascunho de vídeo")
    page.get_by_role("button", name="Salvar rascunho").click()
    expect(page.locator("#toast")).to_have_text("Rascunho salvo")
    draft = page.locator("#pdrafts .prow")
    expect(draft.locator(".tag")).to_have_text("Reel")
    draft.get_by_role("link", name="Editar").click()
    expect(page.locator("#pkindshown")).to_have_value("Reel")
    expect(page.locator("#pvideo")).to_be_visible()
    expect(page.locator("#paltfield")).to_be_hidden()
    page.fill("#pcaption", "Mudou")
    page.get_by_role("button", name="Salvar rascunho").click()
    expect(page.locator("#pdrafts .prow .pcap")).to_have_text("Mudou")
    with store.db() as db:
        kept = db.execute("SELECT media FROM post").fetchone()[0]
    assert Posts(store).media_path(kept).suffix == ".mov"


def test_two_accounts_of_one_client(live, device, ig, fake_ig):
    base, auth, store = live
    du7 = store.save_client({"name": "Du7", "instagram": "@du7dev"})
    other = store.save_client({"name": "Padaria"})
    fake_ig.accounts = [
        {"id": "17841000000000001", "username": "du7dev"},
        {"id": "17841000000000002", "username": "pautacc"},
    ]
    first, second = (a["id"] for a in fake_ig.accounts)
    token, _ = auth.create_invite(admin=True)
    page = device().page
    asked, say = [], {"yes": True}
    page.on(
        "dialog", lambda d: (asked.append(d.message), d.accept() if say["yes"] else d.dismiss())
    )
    join(page, base, token, "Renato Lima")
    page.locator("#nav a[data-nav='#/publicacoes']").click()
    page.get_by_role("button", name="Conectar Instagram").click()
    expect(page.locator("#toast")).to_have_text("Instagram conectado")

    def chooser(ig_id):
        return page.locator(f"[data-account-row='{ig_id}'] select")

    # one login brought both; the first is the one Du7's cadastro names
    expect(page.locator(f"[data-account-row='{first}']")).to_contain_text("sugestão: Du7")
    expect(page.locator(f"[data-account-row='{second}']")).not_to_contain_text("sugestão")
    # to another client than the cadastro says: asked first, and a no leaves it nobody's
    say["yes"] = False
    chooser(first).select_option(str(other["id"]))
    expect(chooser(first)).to_have_value("")
    assert asked == ["O cadastro de Du7 diz @du7dev. Colocar esta conta em Padaria mesmo assim?"]
    assert Posts(store).account(first)["client"] is None
    # to the client it names, and a second account to the same client: nothing to ask
    say["yes"] = True
    chooser(first).select_option(str(du7["id"]))
    expect(chooser(first)).to_have_value(str(du7["id"]))
    chooser(second).select_option(str(du7["id"]))
    expect(chooser(second)).to_have_value(str(du7["id"]))
    assert len(asked) == 1

    # the client is on the form once per account, and a post goes to the one chosen
    page.get_by_role("link", name="Nova publicação").click()
    expect(page.locator("#pclient option")).to_have_text(["Du7 (@du7dev)", "Du7 (@pautacc)"])
    page.select_option("#pclient", second)
    page.set_input_files("#pfile", picture("a.png", 800, 1000))
    expect(page.locator("#ppreview")).to_be_visible()
    page.get_by_role("button", name="Publicar agora").click()
    expect(page.locator("#toast")).to_have_text("Publicado no Instagram")
    assert [sent["ig_id"] for sent in fake_ig.published] == [second]

    # a draft made for the first account moves to the second when edited, and is scheduled
    page.get_by_role("link", name="Nova publicação").click()
    page.set_input_files("#pfile", picture("b.png", 1000, 1000))
    expect(page.locator("#ppreview")).to_be_visible()
    page.get_by_role("button", name="Salvar rascunho").click()
    expect(page.locator("#toast")).to_have_text("Rascunho salvo")
    page.locator("#pdrafts .prow").get_by_role("link", name="Editar").click()
    expect(page.locator("#pclient")).to_have_value(first)
    page.select_option("#pclient", second)
    page.fill("#pdue", "2031-03-15T10:30")
    page.get_by_role("button", name="Agendar").click()
    expect(page.locator("#toast")).to_have_text("Agendada para 15/03 10:30")
    waiting = page.locator("#pscheduled .prow")
    expect(waiting).to_contain_text("@pautacc")
    expect(waiting.locator(".pblocked")).to_have_count(0)

    # that account goes to another client: asked, naming both, and the post says why it waits
    asked.clear()
    chooser(second).select_option(str(other["id"]))
    expect(chooser(second)).to_have_value(str(other["id"]))
    assert asked == ["@pautacc está com Du7. Passar para Padaria?"]
    expect(waiting.locator(".pstatus")).to_have_text("agendada")
    expect(waiting.locator(".pblocked")).to_have_text(MOVED)
