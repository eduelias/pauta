"use strict";
// Pauta: Publicações (docs/publishing-spec.md), beta. Posts for a client's Instagram, kept
// here and published at their time. Only on a server with the Instagram app configured
// (BOOT.publishing.enabled). Shares app.js's globals; index.html loads it before the router.

const PUB_NAV = ["#/publicacoes", "send", "Publicações"];
const pubVisible = () => Boolean(BOOT?.publishing?.enabled);

// Instagram's rules for a feed image (the server checks them again)
const IG_IMAGE = { minRatio: 4 / 5, maxRatio: 1.91, slack: 0.01, maxWidth: 1440, minWidth: 320, maxBytes: 8 * 1024 * 1024 };
const CAPTION_MAX = 2200;
const POST_STATUS = {
  draft: ["rascunho", ""],
  scheduled: ["agendada", "wait"],
  publishing: ["saindo…", "wait"],
  published: ["publicada", "done"],
  failed: ["falhou", "bad"],
};
const IG_WHY = {
  cancelado: "A conexão foi cancelada no Instagram.",
  vencido: "O pedido de conexão venceu. Comece de novo.",
  perfil: "Este perfil não pôde ser ligado: ele precisa ser profissional e não estar em outro cliente.",
  instagram: "O Instagram não completou a conexão. Tente de novo.",
};

// "12/11 14:30" in the browser's time zone, from a UTC stamp
const postWhen = (s) => {
  const d = stamp(s);
  return `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
};
// a UTC stamp as a datetime-local value, and back as ISO
const toLocalInput = (s) => {
  const d = stamp(s), p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};
const fromLocalInput = (v) => (v ? new Date(v).toISOString() : "");

function postRow(p) {
  const [label, tone] = POST_STATUS[p.status] || [p.status, ""];
  const when = p.status === "published" && p.published_at ? `publicada em ${postWhen(p.published_at)}`
    : p.status === "scheduled" && p.due ? `sai em ${postWhen(p.due)}`
    : p.due ? `era para ${postWhen(p.due)}` : `criada em ${postWhen(p.created)}`;
  const open = ["draft", "scheduled", "failed"].includes(p.status);
  const mine = ME.is_admin || p.account === ME.account;
  const acts = [
    open ? `<button class="btn small primary" data-pub="${p.id}">${icon("send")}Publicar agora</button>` : "",
    open ? `<a class="btn small" href="#/publicacoes/${p.id}">Editar</a>` : "",
    p.status === "published" && p.permalink ? `<a class="btn small" href="${esc(safeUrl(p.permalink))}" target="_blank" rel="noopener">Ver no Instagram</a>` : "",
    mine && p.status !== "publishing" ? `<button class="btn small ghost" data-del="${p.id}" data-status="${esc(p.status)}">${p.status === "published" ? "Tirar da lista" : "Excluir"}</button>` : "",
  ].join("");
  return `<div class="prow" data-post="${p.id}" data-status="${esc(p.status)}">
    <img class="pthumb" src="/api/posts/media/${esc(p.media)}" alt="" loading="lazy" width="64" height="64">
    <div class="pbody">
      <div class="pwho"><b>${esc(p.client_name)}</b>${p.ig_username ? `<span class="muted small">@${esc(p.ig_username)}</span>` : ""}<span class="pstatus ${tone}">${label}</span></div>
      <p class="pcap">${p.caption ? esc(p.caption) : `<span class="muted">sem legenda</span>`}</p>
      <span class="muted small">${esc(when)}${p.by_name ? ` · ${esc(firstName(p.by_name))}` : ""}</span>
      ${p.status === "failed" && p.error ? `<p class="perr">${esc(p.error)}</p>` : ""}
    </div>
    <div class="pacts">${acts}</div>
  </div>`;
}

function profilesPanel(doc, clients) {
  const taken = new Set(doc.profiles.map((p) => p.client));
  const free = clients.filter((c) => !taken.has(c.id));
  const rows = doc.profiles.map((p) => {
    const ok = p.state === "ok";
    const line = ok ? `conectado${p.expires ? `, renova sozinho até ${stamp(p.expires).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })}` : ""}`
      : `${p.state === "expired" ? "a conexão venceu" : "o Instagram não aceita mais a conexão"}: conecte de novo`;
    return `<div class="member" data-profile="${p.client}">${avatar(p.client_name)}<div class="who"><b>${esc(p.client_name)}</b>
      <span class="muted small">@${esc(p.username)} · <span class="${ok ? "" : "pbad"}">${esc(line)}</span></span></div>
      ${ME.is_admin ? `<div class="row-gap">${ok ? "" : `<button class="btn small" data-connect="${p.client}">Conectar de novo</button>`}<button class="btn small ghost" data-disconnect="${p.client}" data-name="${esc(p.client_name)}">Desconectar</button></div>` : ""}</div>`;
  }).join("");
  const add = ME.is_admin
    ? free.length ? `<div class="row-gap pconnect"><select class="input" id="igclient" aria-label="Cliente">${free.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select><button class="btn" id="igconnect">${icon("plus")}Conectar Instagram</button></div>
      <p class="muted small">Abre o login do Instagram. Entre lá com o perfil do cliente: ele precisa ser profissional (Empresa ou Criador de conteúdo).</p>`
      : `<p class="muted small">Todos os clientes já têm um perfil conectado.</p>`
    : doc.profiles.length ? "" : `<p class="muted small">Um administrador conecta o Instagram de cada cliente.</p>`;
  return `<section class="panel" id="igprofiles"><div class="panel-head"><h2>${icon("user")}Perfis do Instagram</h2></div>
    ${rows || `<div class="empty">Nenhum perfil conectado ainda.</div>`}${add}</section>`;
}

async function viewPublishing(query) {
  if (!pubVisible()) { location.hash = "#/"; return; }
  const [doc, clients] = await Promise.all([api("GET", "/api/publishing"), api("GET", "/api/clients")]);
  const back = query?.get("ig");  // the way back from Instagram's login
  if (back) {
    keepHash("#/publicacoes");
    toast(back === "ok" ? "Instagram conectado" : IG_WHY[query.get("motivo")] || IG_WHY.instagram, back !== "ok");
  }
  const by = (statuses) => doc.posts.filter((p) => statuses.includes(p.status));
  const scheduled = by(["scheduled", "publishing"]).sort((a, b) => (a.due || "").localeCompare(b.due || ""));
  const group = (title, id, list) => list.length ? `<section class="panel mt" id="${id}"><div class="panel-head"><h2>${title}</h2><span class="muted small">${list.length}</span></div><div class="prows">${list.map(postRow).join("")}</div></section>` : "";
  const ready = doc.profiles.some((p) => p.state === "ok");
  app.innerHTML = `<div style="max-width:980px">
    <div class="head"><div><h1>Publicações <span class="pbeta">beta</span></h1><p>O que vai sair no Instagram dos clientes. A Pauta guarda a publicação e publica na hora marcada.</p></div>
      ${ready ? `<a class="btn primary" href="#/publicacoes/nova">${icon("plus")}Nova publicação</a>` : ""}</div>
    ${profilesPanel(doc, clients)}
    ${group("Agendadas", "pscheduled", scheduled)}
    ${group("Rascunhos e falhas", "pdrafts", by(["draft", "failed"]))}
    ${group("Publicadas", "ppublished", by(["published"]))}
    ${doc.posts.length ? "" : `<section class="panel mt"><div class="empty"><span class="big">📸</span>${ready ? "Nenhuma publicação ainda." : "Conecte um perfil para criar a primeira publicação."}</div></section>`}
  </div>`;
  const again = () => viewPublishing(new URLSearchParams());
  const connect = async (client) => {
    try { location.assign((await api("POST", `/api/clients/${client}/instagram`, {})).url); }
    catch (e) { toast(e.message, true); }
  };
  // on this render's own root (gone with the next one): #app itself outlives every screen,
  // and a listener there would pile up with each redraw and answer one tap several times
  app.firstElementChild.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b || b.disabled) return;
    try {
      if (b.id === "igconnect") return void (await connect($("#igclient").value));
      if (b.dataset.connect) return void (await connect(b.dataset.connect));
      if (b.dataset.disconnect) {
        if (!confirm(`Desconectar o Instagram de ${b.dataset.name}? O que estava agendado volta a ser rascunho. Nada muda no Instagram.`)) return;
        await api("DELETE", `/api/clients/${b.dataset.disconnect}/instagram`);
        toast("Instagram desconectado");
        return void (await again());
      }
      if (b.dataset.pub) {
        if (!confirm("Publicar agora no Instagram do cliente?")) return;
        b.disabled = true;
        b.textContent = "Publicando…";
        const p = await api("POST", `/api/posts/${b.dataset.pub}/publish`, {});
        toast(p.status === "published" ? "Publicado no Instagram" : `Não saiu: ${p.error}`, p.status !== "published");
        return void (await again());
      }
      if (b.dataset.del) {
        const gone = b.dataset.status === "published" ? "Tirar esta publicação da lista? Ela continua no Instagram." : "Excluir esta publicação?";
        if (!confirm(gone)) return;
        await api("DELETE", `/api/posts/${b.dataset.del}`);
        return void (await again());
      }
    } catch (err) { toast(err.message, true); await again(); }
  });
}

// The chosen picture as a JPEG Instagram takes: its proportion checked, scaled down to 1440
// wide, re-encoded (a PNG or anything else the browser can decode becomes JPEG here). No
// blob: address anywhere (the page's content policy allows none): the file is decoded
// straight into a bitmap, and the preview is a small data: image.
async function igImage(file) {
  let bmp;
  try { bmp = await createImageBitmap(file); }
  catch { throw new Error("não deu para abrir esta imagem"); }
  try {
    const w = bmp.width, h = bmp.height, ratio = w / h;
    if (w < IG_IMAGE.minWidth) throw new Error(`a imagem precisa ter pelo menos ${IG_IMAGE.minWidth} px de largura`);
    if (ratio < IG_IMAGE.minRatio - IG_IMAGE.slack || ratio > IG_IMAGE.maxRatio + IG_IMAGE.slack) throw new Error("o Instagram aceita imagens entre 4:5 (retrato) e 1,91:1 (paisagem): recorte e escolha de novo");
    const draw = (width) => {
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(width);
      canvas.height = Math.round(width * h / w);
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#fff";  // JPEG has no transparency
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
      return canvas;
    };
    const canvas = draw(Math.min(w, IG_IMAGE.maxWidth));
    const preview = draw(Math.min(w, 480)).toDataURL("image/jpeg", 0.8);
    for (const quality of [0.92, 0.85, 0.75]) {
      const blob = await new Promise((ok) => canvas.toBlob(ok, "image/jpeg", quality));
      if (blob && blob.size <= IG_IMAGE.maxBytes) return { blob, width: canvas.width, height: canvas.height, preview };
    }
    throw new Error("a imagem passa de 8 MB");
  } finally { bmp.close?.(); }
}

async function sendPostImage(blob) {
  const res = await fetch("/api/posts/media", { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob });
  const doc = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(doc.error || "não deu para enviar a imagem");
  return doc;
}

async function viewPost(_query, id) {
  if (!pubVisible()) { location.hash = "#/"; return; }
  const doc = await api("GET", "/api/publishing");
  const post = id === "nova" ? null : doc.posts.find((p) => p.id === Number(id));
  if (id !== "nova" && !post) throw new Error("publicação não encontrada");
  if (post && !["draft", "scheduled", "failed"].includes(post.status)) { location.hash = "#/publicacoes"; return; }
  const profiles = doc.profiles.filter((p) => p.state === "ok");
  if (!post && !profiles.length) { location.hash = "#/publicacoes"; return; }
  let image = null;  // {blob, width, height, preview}, a new post's picture
  const soon = toLocalInput(new Date(Date.now() + 3600e3).toISOString());
  app.innerHTML = `<div style="max-width:860px">
    <div class="head"><div><h1>${post ? "Editar publicação" : "Nova publicação"}</h1><p>Uma imagem e a legenda, para o Instagram de um cliente.</p></div></div>
    <form class="panel" id="postform" autocomplete="off"><div class="form-grid">
      <div class="field wide"><label for="pclient">Cliente</label>${post
        ? `<input class="input" id="pclient" value="${esc(post.client_name)}${post.ig_username ? ` (@${esc(post.ig_username)})` : ""}" disabled>`
        : `<select class="input" id="pclient">${profiles.map((p) => `<option value="${p.client}">${esc(p.client_name)} (@${esc(p.username)})</option>`).join("")}</select>`}</div>
      <div class="field wide"><label>Imagem</label>
        <div class="ppick">${post ? `<img id="ppreview" src="/api/posts/media/${esc(post.media)}" alt="">` : `<img id="ppreview" alt="" hidden>`}
          ${post ? "" : `<div><input type="file" id="pfile" accept="image/*"><span class="hint" id="pimginfo">JPEG ou PNG, entre 4:5 (retrato) e 1,91:1 (paisagem). A Pauta converte e ajusta o tamanho.</span></div>`}</div></div>
      <div class="field wide"><label for="pcaption">Legenda <span class="muted" id="pcount"></span></label><textarea class="input" id="pcaption" rows="7" maxlength="${CAPTION_MAX}" placeholder="O texto que vai junto, com as hashtags">${esc(post?.caption || "")}</textarea></div>
      <div class="field wide"><label for="palt">Descrição da imagem <span class="muted">(opcional, para leitores de tela)</span></label><input class="input" id="palt" maxlength="1000" value="${esc(post?.alt_text || "")}"></div>
      <div class="field"><label for="pdue">Agendar para</label><input class="input" type="datetime-local" id="pdue" value="${post?.due ? toLocalInput(post.due) : ""}" min="${toLocalInput(new Date().toISOString())}"><span class="hint">no seu horário; em branco para rascunho ou publicar agora</span></div>
    </div>
    <div class="spread mt-lg pbuttons"><a class="btn ghost" href="#/publicacoes">Cancelar</a>
      <div class="row-gap"><button type="button" class="btn" data-go="draft">Salvar rascunho</button><button type="button" class="btn" data-go="scheduled">${icon("cal")}Agendar</button><button type="button" class="btn primary" data-go="now">${icon("send")}Publicar agora</button></div></div>
    </form></div>`;
  const count = () => { $("#pcount").textContent = `${$("#pcaption").value.length} / ${CAPTION_MAX}`; };
  count();
  $("#pcaption").addEventListener("input", count);
  $("#pfile")?.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    image = null;
    $("#ppreview").hidden = true;
    if (!file) return;
    try {
      image = await igImage(file);
      $("#ppreview").src = image.preview;
      $("#ppreview").hidden = false;
      $("#pimginfo").textContent = `${image.width} × ${image.height} px, ${(image.blob.size / 1024 / 1024).toFixed(1).replace(".", ",")} MB`;
    } catch (err) { e.target.value = ""; $("#pimginfo").textContent = err.message; toast(err.message, true); }
  });
  $("#postform").addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-go]");
    if (!b) return;
    const go = b.dataset.go, due = fromLocalInput($("#pdue").value);
    if (!post && !image) return toast("escolha a imagem", true);
    if (go === "scheduled" && !due) { $("#pdue").value = soon; return toast("confira a data e toque em Agendar de novo", true); }
    if (go === "now" && !confirm("Publicar agora no Instagram do cliente?")) return;
    const buttons = $$("#postform button");
    buttons.forEach((x) => { x.disabled = true; });
    try {
      const fields = { caption: $("#pcaption").value, alt_text: $("#palt").value, status: go === "scheduled" ? "scheduled" : "draft", due: go === "scheduled" ? due : "" };
      let saved;
      if (post) saved = await api("PATCH", `/api/posts/${post.id}`, fields);
      else {
        const media = await sendPostImage(image.blob);
        saved = await api("POST", "/api/posts", { ...fields, client: Number($("#pclient").value), media: media.media });
      }
      if (go === "now") {
        b.textContent = "Publicando…";
        // the post exists from here on: whatever happens, the list shows where it stands
        try {
          const out = await api("POST", `/api/posts/${saved.id}/publish`, {});
          toast(out.status === "published" ? "Publicado no Instagram" : `Não saiu: ${out.error}`, out.status !== "published");
        } catch (err) { toast(`Não saiu: ${err.message}`, true); }
      } else toast(go === "scheduled" ? `Agendada para ${postWhen(saved.due)}` : "Rascunho salvo");
      location.hash = "#/publicacoes";
    } catch (err) {
      toast(err.message, true);
      buttons.forEach((x) => { x.disabled = false; });
    }
  });
}
