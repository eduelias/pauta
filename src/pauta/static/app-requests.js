"use strict";
// Pauta: the dashboard, the board, the list, one request and its files, a new request.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- dashboard -----------------------------------------------------------------------

async function viewDash() {
  const [reqs, clients] = await Promise.all([loadReqs(), api("GET", "/api/clients")]);
  const open = reqs.filter(isOpen);
  const late = open.filter(isLate);
  const waiting = open.filter((r) => r.status === "waiting");
  const since = addDays(todayISO(), -30);
  const done = reqs.filter((r) => r.status === "done" && (r.done_on || "") >= since)
    .sort((a, b) => (b.done_on || "").localeCompare(a.done_on || ""));
  const active = clients.filter((c) => c.state === "Ativo").length;
  const attention = open.filter((r) => r.status !== "waiting").sort(sortOpen).slice(0, 8);
  const mine = waiting.filter((r) => ME.account && r.created_by === ME.account);
  const h = new Date().getHours();
  const hello = h < 12 ? "Bom dia" : h < 18 ? "Boa tarde" : "Boa noite";
  const today = new Date().toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
  const summary = late.length ? `${late.length} ${late.length === 1 ? "pedido atrasado" : "pedidos atrasados"}${mine.length ? ` e ${mine.length} esperando por você` : ""}.`
    : mine.length ? `${mine.length} ${mine.length === 1 ? "pedido espera" : "pedidos esperam"} uma resposta sua.`
    : open.length ? "Nada atrasado. Bom ritmo!" : "Nenhum pedido em aberto.";
  const stat = (n, t, href, c, hot) => `<a class="stat ${hot ? "hot" : ""}" href="${href}" style="--c:${c}"><div class="n">${n}</div><div class="t">${t}</div></a>`;
  app.innerHTML = `<div>
    <div class="hello"><h1>${hello}, <em>${esc(firstName(ME.name))}</em></h1><p>${esc(today[0].toUpperCase() + today.slice(1))} · ${esc(summary)}</p></div>
    <div class="stats">
      ${stat(open.length, "Em aberto", "#/pedidos?f=open", "var(--accent)")}
      ${stat(late.length, "Atrasados", "#/pedidos?f=late", "var(--danger)", late.length > 0)}
      ${stat(waiting.length, "Aguardando retorno", "#/pedidos?f=waiting", "var(--s-waiting)")}
      ${stat(done.length, "Concluídos em 30 dias", "#/pedidos?f=done", "var(--s-done)")}
      ${stat(active, "Clientes ativos", "#/clientes", "var(--warm)")}
    </div>
    <div class="dash">
      <section class="panel">
        <div class="panel-head"><h2>Para fazer agora</h2><div class="row-gap">${finVisible() && metaVisible() ? `<a class="btn ghost small" href="#/financeiro">${icon("money")}Financeiro</a>` : ""}<a class="btn ghost small" href="#/quadro">Ver quadro</a></div></div>
        ${attention.length ? `<div class="rcards">${attention.map((r) => rcard(r)).join("")}</div>`
          : `<div class="empty"><span class="big">🎉</span>Nada na fila. Hora de um café.</div>`}
      </section>
      <div>
        <section class="panel">
          <div class="panel-head"><h2>Aguardando retorno</h2><span class="muted small">${waiting.length}</span></div>
          ${waiting.length ? `<div class="rcards">${waiting.sort(sortOpen).map((r) => rcard(r)).join("")}</div>`
            : `<div class="empty">Ninguém está esperando por nada.</div>`}
        </section>
        <section class="panel">
          <div class="panel-head"><h2>Concluídos recentemente</h2></div>
          ${done.length ? `<div class="rcards">${done.slice(0, 5).map((r) => rcard(r)).join("")}</div>`
            : `<div class="empty">Nada concluído nos últimos 30 dias.</div>`}
        </section>
      </div>
    </div>
  </div>`;
}

// ---------- board ---------------------------------------------------------------------------

let showCancelled = false;
async function viewBoard() {
  const reqs = await loadReqs();
  const since = addDays(todayISO(), -30);
  const cols = ["todo", "doing", "waiting", "done", ...(showCancelled ? ["cancelled"] : [])];
  const inCol = (s) => reqs.filter((r) => r.status === s && (s !== "done" || (r.done_on || "") >= since)).sort(sortOpen);
  app.innerHTML = `<div>
    <div class="head"><div><h1>Quadro</h1><p>Arraste um cartão para mudar o status.</p></div>
      <div class="actions"><label class="toggle"><input type="checkbox" id="showc" ${showCancelled ? "checked" : ""}>Cancelados</label></div></div>
    <div class="board-wrap"><div class="board ${showCancelled ? "with-cancelled" : ""}" style="--cols:${cols.length}">
      ${cols.map((s) => {
        const list = inCol(s);
        return `<div class="col" data-status="${s}">
          <div class="col-head"><span class="status ${s}">${esc(STATUS()[s])}</span><span class="n">${list.length}</span></div>
          <div class="rcards">${list.map((r) => rcard(r, { drag: true })).join("") || ""}</div>
          ${s === "done" ? `<div class="faint small" style="padding:8px 6px 2px">Últimos 30 dias · <a class="linkbtn" href="#/pedidos?f=done">ver todos</a></div>` : ""}
        </div>`;
      }).join("")}
    </div></div></div>`;
  $("#showc").addEventListener("change", (e) => { showCancelled = e.target.checked; viewBoard(); });
  let dragId = null;
  $$(".rcard[draggable]").forEach((c) => {
    c.addEventListener("dragstart", (e) => { dragId = c.dataset.id; c.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragId); });
    c.addEventListener("dragend", () => c.classList.remove("dragging"));
  });
  $$(".col").forEach((col) => {
    col.addEventListener("dragover", (e) => { e.preventDefault(); col.classList.add("drop"); });
    col.addEventListener("dragleave", (e) => { if (!col.contains(e.relatedTarget)) col.classList.remove("drop"); });
    col.addEventListener("drop", async (e) => {
      e.preventDefault();
      col.classList.remove("drop");
      const id = Number(e.dataTransfer.getData("text/plain") || dragId);
      const r = REQS.find((x) => x.id === id);
      const status = col.dataset.status;
      if (!r || r.status === status) return;
      const patch = { status };
      if (status === "waiting") {
        const missing = await askMissing(r);
        if (missing === null) return;
        patch.missing = missing;
      }
      try {
        await api("PATCH", `/api/requests/${id}`, patch);
        track("request_status", { from: r.status, to: status, via: "board" });
        toast(`#${id} → ${STATUS()[status]}`);
        viewBoard();
      } catch (err) { toast(err.message, true); }
    });
  });
}

function askMissing(r) {
  return new Promise((resolve) => {
    const m = $("#modal");
    m.innerHTML = `<div class="panel"><h2>O que falta?</h2>
      <p class="muted small" style="margin:-8px 0 14px">${esc(r.created_by_name ? `${firstName(r.created_by_name)} vai ver isto no pedido #${r.id}.` : `Fica anotado no pedido #${r.id}.`)}</p>
      <textarea class="input" id="missing" placeholder="Ex.: falta a liberação da conta de anúncios">${esc(r.missing)}</textarea>
      <div class="actions"><button class="btn ghost" data-a="cancel">Cancelar</button><button class="btn primary" data-a="ok">Mover</button></div></div>`;
    m.hidden = false;
    $("#missing").focus();
    const done = (v) => { m.hidden = true; m.innerHTML = ""; resolve(v); };
    m.onclick = (e) => {
      if (e.target === m || e.target.dataset.a === "cancel") done(null);
      if (e.target.dataset.a === "ok") done($("#missing").value);
    };
  });
}

// ---------- list ----------------------------------------------------------------------------

const FILTERS = [
  ["open", "Abertos"], ["late", "Atrasados"], ["todo", "A fazer"], ["doing", "Em andamento"],
  ["waiting", "Aguardando"], ["done", "Concluídos"], ["cancelled", "Cancelados"], ["all", "Todos"],
];
async function viewList(query) {
  const reqs = await loadReqs();
  let f = query.get("f") || "open";
  let q = query.get("q") || "";
  let client = query.get("c") || "";
  const clients = [...new Map(reqs.map((r) => [r.client, r.client_name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  app.innerHTML = `<div>
    <div class="head"><div><h1>Pedidos</h1><p>Tudo o que foi pedido, do mais urgente ao menos.</p></div>
      <div class="actions"><a class="btn primary" href="#/novo">${icon("plus")}Novo pedido</a></div></div>
    <div class="toolbar">
      <div class="search">${icon("search")}<input class="input" id="q" placeholder="Buscar cliente, tipo, texto…" value="${esc(q)}"></div>
      <select class="input" id="cl"><option value="">Todos os clientes</option>${clients.map(([id, n]) => `<option value="${id}" ${String(id) === client ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
    </div>
    <div class="seg" id="filters" style="margin-bottom:16px">${FILTERS.map(([k, t]) => `<button data-f="${k}" class="${k === f ? "on" : ""}">${t}</button>`).join("")}</div>
    <div id="rows"></div></div>`;
  const draw = () => {
    const needle = q.trim().toLowerCase();
    let rows = reqs.filter((r) =>
      (f === "all" || (f === "open" && isOpen(r)) || (f === "late" && isLate(r)) || r.status === f) &&
      (!client || String(r.client) === client) &&
      (!needle || [r.client_name, r.kind, r.what, r.goal, r.missing, `#${r.id}`].join(" ").toLowerCase().includes(needle)));
    rows = ["done", "cancelled", "all"].includes(f) ? rows.sort((a, b) => b.id - a.id) : rows.sort(sortOpen);
    $("#rows").innerHTML = rows.length ? `<table class="table"><thead><tr><th>Nº</th><th>Cliente</th><th>Tipo</th><th>O que fazer</th><th>Prazo</th><th>Status</th></tr></thead><tbody>
      ${rows.map((r) => `<tr data-id="${r.id}"><td class="num">#${r.id}</td>
        <td><span class="cl">${avatar(r.client_name)}${esc(r.client_name)}</span></td>
        <td class="kind-cell"><span class="tag">${esc(r.kind || "—")}</span></td>
        <td class="what-cell"><div>${esc(r.what)}</div></td>
        <td class="nowrap">${dueBadge(r) || '<span class="faint">—</span>'} ${prio(r.priority)}</td>
        <td>${statusBadge(r)}</td></tr>`).join("")}
      </tbody></table>` : `<div class="panel empty"><span class="big">🔎</span>Nenhum pedido aqui.</div>`;
    $$("#rows tr[data-id]").forEach((tr) => tr.addEventListener("click", () => { location.hash = `#/pedido/${tr.dataset.id}`; }));
    history.replaceState(null, "", `#/pedidos?f=${f}${q ? `&q=${encodeURIComponent(q)}` : ""}${client ? `&c=${client}` : ""}`);
  };
  let typing;
  $("#q").addEventListener("input", (e) => {
    q = e.target.value;
    draw();
    clearTimeout(typing);  // one `search` per pause in typing, not one per key
    if (q.trim()) typing = setTimeout(() => track("search", { what: "text" }), 800);
  });
  $("#cl").addEventListener("change", (e) => { client = e.target.value; if (client) track("filter", { what: "client" }); draw(); });
  $("#filters").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]");
    if (!b) return;
    f = b.dataset.f;
    track("filter", { what: "status" });
    $$("#filters button").forEach((x) => x.classList.toggle("on", x === b));
    draw();
  });
  draw();
}

// ---------- one request ---------------------------------------------------------------------

function seg(name, values, current, labels = null, cls = "") {
  return `<div class="seg ${cls}" data-seg="${name}">${values.map((v) => `<button type="button" data-v="${esc(v)}" class="${v === current ? "on" : ""}">${esc(labels ? labels[v] : v)}</button>`).join("")}</div>`;
}
function selectOpts(values, current, blank = "—") {
  const list = current && !values.includes(current) ? [current, ...values] : values;
  return `<option value="">${blank}</option>` + list.map((v) => `<option ${v === current ? "selected" : ""}>${esc(v)}</option>`).join("");
}
const memberOpts = (current) => `<option value="">Ninguém</option>` + BOOT.members.map((m) => `<option value="${m.id}" ${m.id === current ? "selected" : ""}>${esc(m.name)}</option>`).join("");

function linkField(name, value, placeholder) {
  const u = safeUrl(value);
  return `<div style="display:flex;gap:8px;align-items:center;width:100%"><input class="input" data-f="${name}" value="${esc(value)}" placeholder="${placeholder}">${u ? `<a class="btn icon-only ghost" href="${esc(u)}" target="_blank" rel="noopener" title="Abrir">${icon("ext")}</a>` : ""}</div>`;
}

function timeline(r) {
  const who = (e) => `<b>${esc(e.account_name || (e.kind === "campaign" ? "A Pauta" : ME.auth ? "Alguém" : "Você"))}</b>`;
  return r.events.slice().reverse().map((e) => {
    if (e.kind === "comment") {
      return `<div class="ev comment"><div class="ic">${icon("msg")}</div><div class="body">${who(e)}<span class="when">${esc(ago(e.at))}</span><div class="bubble">${esc(e.text)}</div></div></div>`;
    }
    let what = "", ic = "edit";
    if (e.kind === "created") { what = "criou o pedido"; ic = "sparkle"; }
    if (e.kind === "status") {
      const [, to] = e.text.split(">");
      what = `mudou o status para <span class="status ${esc(to)}">${esc(STATUS()[to] || to)}</span>`;
      ic = "swap";
    }
    if (e.kind === "edited") what = `editou ${esc(e.text)}`;
    if (e.kind === "file") { what = `anexou <b>${esc(e.text)}</b>`; ic = "clip"; }
    if (e.kind === "unfile") { what = `removeu o arquivo ${esc(e.text)}`; ic = "trash"; }
    if (e.kind === "campaign") { what = "vinculou a campanha da Meta ao pedido"; ic = "link"; }
    return `<div class="ev"><div class="ic">${icon(ic)}</div><div class="body">${who(e)} ${what}<span class="when">${esc(ago(e.at))}</span></div></div>`;
  }).join("");
}

// ---------- files (stored in OneDrive) -------------------------------------------------------

function fileSize(n) {
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))} KB`;
  return `${(n / 1048576).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} MB`;
}

function filesPanel(r) {
  const F = BOOT.files || {};
  if (!F.enabled) return "";
  const title = `<div class="section-title">${icon("clip")} Arquivos</div>`;
  if (!F.connected) {
    return `<div class="panel">${title}<p class="muted small">${ME.is_admin
      ? `Conecte o OneDrive em <a href="#/configuracoes">Configurações → Arquivos</a> para anexar arquivos aos pedidos.`
      : "Os anexos ainda não estão ligados; um administrador conecta o OneDrive."}</p></div>`;
  }
  return `<div class="panel" id="files">
    <div class="panel-head">${title}<div class="row-gap">
      <button class="btn ghost small" id="share" ${r.files.length ? "" : "hidden"}>${icon("link")}Link para o cliente</button>
      <label class="btn small" for="pick">${icon("upload")}Enviar arquivos</label><input type="file" id="pick" multiple hidden></div></div>
    <div id="sharebox"></div>
    <div id="uploads"></div>
    <div class="files" id="filelist">${fileList(r)}</div>
    <p class="muted small mt">Ou arraste para cá. Até ${F.max_mb} MB por arquivo; ficam no OneDrive do time.</p>
  </div>`;
}

function fileList(r) {
  if (!r.files.length) return `<div class="empty small">Nenhum arquivo ainda.</div>`;
  return r.files.map((f) => {
    const thumb = /^(image|video)\//.test(f.mime) ? `<img loading="lazy" alt="" src="/api/files/${f.id}/thumb">` : icon("file");
    const canDel = ME.is_admin || f.account === ME.account;
    return `<div class="file"><a class="thumb" href="/api/files/${f.id}" target="_blank" rel="noopener" title="Baixar">${thumb}</a>
      <div class="meta"><a href="/api/files/${f.id}" target="_blank" rel="noopener">${esc(f.name)}</a>
      <span>${esc(fileSize(f.size))} · ${esc(firstName(f.account_name) || (ME.auth ? "Alguém" : "Você"))} · ${esc(ago(f.created))}</span></div>
      ${canDel ? `<button class="btn ghost icon-only" data-unfile="${f.id}" data-name="${esc(f.name)}" aria-label="Remover ${esc(f.name)}">${icon("trash")}</button>` : ""}</div>`;
  }).join("");
}

// XHR, not fetch: only XHR reports upload progress
function sendFile(rid, file, onProgress) {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api/requests/${rid}/files`);
    x.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    x.setRequestHeader("X-File-Name", encodeURIComponent(file.name));
    x.upload.addEventListener("progress", (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); });
    x.addEventListener("load", () => {
      let doc = {};
      try { doc = JSON.parse(x.responseText); } catch { /* not JSON: use the status */ }
      if (x.status === 401 && ME?.auth) { ME.logged_in = false; showGate(); }
      if (x.status >= 200 && x.status < 300) { resolve(doc); return; }
      trackApi("POST", `/api/requests/${rid}/files`, x.status, 0);
      const err = new Error(doc.error || `erro ${x.status}`);
      err.status = x.status;
      reject(err);
    });
    x.addEventListener("error", () => {
      trackApi("POST", `/api/requests/${rid}/files`, 0, 0);
      const err = new Error("a conexão caiu; tente de novo");
      err.status = 0;
      reject(err);
    });
    x.send(file);
  });
}

function bindFiles(get, set) {
  const panel = $("#files");
  if (!panel) return;
  const redraw = () => {
    const r = get();
    $("#filelist").innerHTML = fileList(r);
    $("#tl").innerHTML = timeline(r);
    $("#share").hidden = !r.files.length;
    bindFileList();
  };
  const bindFileList = () => {
    $$("#filelist img").forEach((img) => img.addEventListener("error", () => { img.replaceWith(document.createRange().createContextualFragment(icon("file"))); }));
    $$("[data-unfile]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm(`Remover ${b.dataset.name}? Ele vai para a lixeira do OneDrive.`)) return;
      try { set(await api("DELETE", `/api/files/${b.dataset.unfile}`)); redraw(); toast("Arquivo removido"); }
      catch (e) { toast(e.message, true); }
    }));
  };
  const upload = async (files) => {
    const max = (BOOT.files.max_mb || 200) * 1048576;
    for (const file of files) {
      if (!file.size) { track("file_failed", { reason: "empty" }); toast(`${file.name} está vazio`, true); continue; }
      if (file.size > max) { track("file_failed", { reason: "size" }); toast(`${file.name} passa de ${BOOT.files.max_mb} MB`, true); continue; }
      const row = document.createElement("div");
      row.className = "upl";
      row.innerHTML = `<span>${esc(file.name)}</span><progress max="1" value="0"></progress>`;
      $("#uploads").append(row);
      try {
        set(await sendFile(get().id, file, (f) => { $("progress", row).value = f; }));
        track("file_added");
        redraw();
        toast(`${file.name} enviado`);
      } catch (e) {
        track("file_failed", { reason: e.status === 0 ? "network" : "drive" });
        toast(`${file.name}: ${e.message}`, true);
      }
      row.remove();
    }
  };
  $("#pick").addEventListener("change", (e) => { upload([...e.target.files]); e.target.value = ""; });
  panel.addEventListener("dragover", (e) => { e.preventDefault(); panel.classList.add("drop"); });
  panel.addEventListener("dragleave", () => panel.classList.remove("drop"));
  panel.addEventListener("drop", (e) => { e.preventDefault(); panel.classList.remove("drop"); upload([...e.dataTransfer.files]); });
  $("#share").addEventListener("click", async () => {
    try {
      const { url } = await api("POST", `/api/requests/${get().id}/share`);
      track("request_sent");
      const msg = `Os arquivos do seu pedido estão aqui: ${url}`;
      $("#sharebox").innerHTML = `<div class="sharebox"><code class="invlink">${esc(url)}</code>
        <div class="row-gap"><button class="btn small" data-copy="${esc(url)}">${icon("link")}Copiar link</button>
        <a class="btn small" href="https://wa.me/?text=${encodeURIComponent(msg)}" target="_blank" rel="noopener">${icon("wa")}Enviar no WhatsApp</a></div>
        <p class="muted small">Quem tiver o link vê (e baixa) os arquivos deste pedido, sem editar.</p></div>`;
      bindCopy($("#sharebox"));
    } catch (e) { toast(e.message, true); }
  });
  bindFileList();
}

async function viewRequest(_q, id) {
  let r = await api("GET", `/api/requests/${id}`);
  const o = BOOT.options;
  const c = r.client_info;
  app.innerHTML = `<div>
    <div class="crumb"><a href="#/pedidos">Pedidos</a><span>/</span><span>#${r.id}</span></div>
    <div class="req">
      <div>
        <div class="row-gap"><a class="cl" href="#/cliente/${c.id}">${avatar(c.name, "md")}<span style="font-size:16px">${esc(c.name)}</span></a>${r.kind ? `<span class="tag accent">${esc(r.kind)}</span>` : ""}</div>
        <div class="quiet"><textarea class="input req-title" data-f="what" rows="1">${esc(r.what)}</textarea></div>
        <div class="req-meta">${personAvatar(r.created_by, r.created_by_name || "?")}<span>Pedido por <b>${esc(r.created_by_name || "—")}</b> · ${esc(ago(r.created))}</span><span id="duebadge">${dueBadge(r)}</span></div>
        <div class="panel">
          <div class="section-title">Status</div>
          ${seg("status", Object.keys(o.status), r.status, o.status, "statuses")}
          <div id="missingbox" class="mt" ${r.status === "waiting" || r.missing ? "" : "hidden"}>
            <div class="field"><label>O que falta${r.created_by_name ? ` (${esc(firstName(r.created_by_name))})` : ""}</label>
            <textarea class="input" data-f="missing" placeholder="O que está faltando para seguir?">${esc(r.missing)}</textarea></div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">${icon("target")} Briefing</div>
          <div class="kv quiet">
            <div class="k">Tipo</div><div class="v"><select class="input" data-f="kind">${selectOpts(o.kind, r.kind)}</select></div>
            <div class="k">Objetivo</div><div class="v"><select class="input" data-f="goal">${selectOpts(o.goal, r.goal)}</select></div>
            <div class="k">Público-alvo</div><div class="v"><textarea class="input" data-f="audience" rows="1" placeholder="Quem deve ver o anúncio">${esc(r.audience)}</textarea></div>
            <div class="k">Região</div><div class="v"><input class="input" data-f="region" value="${esc(r.region)}" placeholder="Cidade, bairro, raio…"></div>
            <div class="k">Criativos</div><div class="v">${linkField("creatives_url", r.creatives_url, "Link da pasta (Drive)")}</div>
            <div class="k">Pág. de anúncios</div><div class="v ads-page">${c.ads_page
              ? `${adsPage(c.ads_page)}<button class="copy" data-copy="${esc(c.ads_page)}">Copiar</button>`
              : `<a class="muted" href="#/cliente/${c.id}">Cadastrar no cliente</a>`}</div>
          </div>
        </div>
        <div class="panel">
          <div class="section-title">${icon("check")} Execução</div>
          <div class="kv quiet">
            <div class="k">Campanha</div><div class="v">${linkField("campaign_url", r.campaign_url, "Link da campanha no Gerenciador")}</div>
            <div class="k">Concluído em</div><div class="v"><input class="input" type="date" data-f="done_on" value="${esc(r.done_on || "")}"></div>
            <div class="k">Observações</div><div class="v"><textarea class="input" data-f="notes" rows="2" placeholder="Anotações da execução">${esc(r.notes)}</textarea></div>
          </div>
        </div>
        ${filesPanel(r)}
        <div class="panel">
          <div class="section-title">${icon("msg")} Conversa e histórico</div>
          <div class="compose"><textarea class="input" id="comment" placeholder="Escreva uma mensagem para o time…" rows="1"></textarea><button class="btn primary icon-only" id="send" aria-label="Enviar">${icon("send")}</button></div>
          <div class="timeline mt" id="tl">${timeline(r)}</div>
        </div>
      </div>
      <aside>
        <div class="panel">
          <div class="kv quiet">
            <div class="k">Prazo</div><div class="v"><input class="input" type="date" data-f="due" value="${esc(r.due || "")}"></div>
            <div class="k">Prioridade</div><div class="v">${seg("priority", o.priority, r.priority)}</div>
            <div class="k">Responsável</div><div class="v"><select class="input" data-f="assignee">${memberOpts(r.assignee)}</select></div>
            <div class="k">Verba</div><div class="v"><div class="money" style="width:100%"><span>R$</span><input class="input" type="number" min="0" step="0.01" inputmode="decimal" data-f="budget" value="${r.budget ?? ""}"></div></div>
            <div class="k">Saldo</div><div class="v"><select class="input" data-f="balance">${selectOpts(o.balance, r.balance)}</select></div>
          </div>
        </div>
        <div class="panel clientbox">
          <div class="panel-head"><h3>Dados do cliente</h3><a class="linkbtn small" href="#/cliente/${c.id}">Abrir</a></div>
          ${clientRows(c)}
        </div>
        ${ME.is_admin ? `<div class="mt"><button class="btn ghost danger" id="del">${icon("trash")}Excluir pedido</button></div>` : ""}
      </aside>
    </div></div>`;

  const save = async (patch, el) => {
    try {
      r = await api("PATCH", `/api/requests/${r.id}`, patch);
      $("#tl").innerHTML = timeline(r);
      $("#duebadge").innerHTML = dueBadge(r);
      const done = $('[data-f="done_on"]');
      if (done && document.activeElement !== done) done.value = r.done_on || "";
      if (el) { el.classList.remove("saved-flash"); void el.offsetWidth; el.classList.add("saved-flash"); }
      return true;
    } catch (e) { toast(e.message, true); return false; }
  };
  $$("[data-f]").forEach((el) => el.addEventListener("change", () => {
    const f = el.dataset.f;
    let v = el.value;
    if (f === "assignee") v = v ? Number(v) : null;
    save({ [f]: v }, el);
  }));
  $$("[data-seg]").forEach((s) => s.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.classList.contains("on")) return;
    $$("button", s).forEach((x) => x.classList.toggle("on", x === b));
    const f = s.dataset.seg;
    if (f === "status") {
      $("#missingbox").hidden = !(b.dataset.v === "waiting" || r.missing);
      if (b.dataset.v === "waiting") setTimeout(() => $('[data-f="missing"]').focus(), 50);
      toast(`Status: ${STATUS()[b.dataset.v]}`);
    }
    const from = r.status;
    save({ [f]: b.dataset.v }).then((ok) => { if (ok && f === "status") track("request_status", { from, to: b.dataset.v, via: "page" }); });
  }));
  const autosize = (t) => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
  $$("textarea.input").forEach((t) => { autosize(t); t.addEventListener("input", () => autosize(t)); });
  const send = async () => {
    const t = $("#comment");
    if (!t.value.trim()) return;
    try {
      r = await api("POST", `/api/requests/${r.id}/comments`, { text: t.value });
      track("comment_added");
      t.value = "";
      autosize(t);
      $("#tl").innerHTML = timeline(r);
    } catch (e) { toast(e.message, true); }
  };
  $("#send").addEventListener("click", send);
  $("#comment").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send(); });
  $("#del")?.addEventListener("click", async () => {
    if (!confirm(`Excluir o pedido #${r.id}? Para desistir de um pedido, prefira marcar Cancelado.`)) return;
    await api("DELETE", `/api/requests/${r.id}`);
    toast(`Pedido #${r.id} excluído`);
    location.hash = "#/pedidos";
  });
  bindCopy(app);
  bindFiles(() => r, (doc) => { r = doc; });
}

function clientRows(c) {
  const ig = igUrl(c.instagram), wa = waUrl(c.whatsapp), drive = safeUrl(c.drive_url);
  const row = (ic, content, href) => href
    ? `<a class="row" href="${esc(href)}" target="_blank" rel="noopener">${icon(ic)}<span class="grow">${content}</span>${icon("ext", "faint")}</a>`
    : `<div class="row">${icon(ic)}<span class="grow">${content}</span></div>`;
  return [
    c.contact || c.whatsapp ? row("wa", `${esc(c.contact || "")}${c.contact && c.whatsapp ? " · " : ""}${esc(c.whatsapp || "")}`, wa) : "",
    c.instagram ? row("at", esc(c.instagram), ig) : "",
    c.ad_account ? `<div class="row">${icon("hash")}<span class="grow">Conta ${esc(c.ad_account)}</span><button class="copy" data-copy="${esc(c.ad_account)}">Copiar</button></div>` : "",
    c.ads_page ? `<div class="row ads-page">${icon("link")}${adsPage(c.ads_page)}<button class="copy" data-copy="${esc(c.ads_page)}">Copiar</button></div>` : "",
    `<div class="row">${icon("key")}<span class="grow">Acesso à conta</span><span class="state ${c.access === "Liberado" ? "Ativo" : c.access === "Solicitado" ? "Pausado" : "Encerrado"}">${esc(c.access)}</span></div>`,
    drive ? row("folder", "Pasta de criativos", drive) : "",
  ].join("");
}

// the ads page is free text: a link opens in a new tab, anything else is shown as written
function adsPage(v) {
  const u = safeUrl(v);
  return u ? `<a class="grow" href="${esc(u)}" target="_blank" rel="noopener" title="${esc(v)}">Página de anúncios</a>`
    : `<span class="grow">${esc(v)}</span>`;
}

function bindCopy(root) {
  $$("[data-copy]", root).forEach((b) => b.addEventListener("click", async (e) => {
    e.preventDefault();
    await navigator.clipboard.writeText(b.dataset.copy);
    toast("Copiado");
  }));
}

// ---------- new request ---------------------------------------------------------------------

async function viewNew(_q, clientId) {
  const clients = await api("GET", "/api/clients");
  const o = BOOT.options;
  const opts = (sel) => clients.filter((c) => c.state !== "Encerrado").map((c) => `<option value="${c.id}" ${String(c.id) === String(sel) ? "selected" : ""}>${esc(c.name)}</option>`).join("");
  const t = todayISO();
  app.innerHTML = `<div style="max-width:860px">
    <div class="head"><div><h1>Novo pedido</h1><p>O que precisa ser feito, para quem e até quando.</p></div></div>
    <form id="f" class="panel" autocomplete="off">
      <div class="form-grid">
        <div class="field wide"><label>Cliente</label>
          <div style="display:flex;gap:8px"><select class="input" name="client" required><option value="">Escolha…</option>${opts(clientId)}</select>
          <button type="button" class="btn" id="newclient">${icon("plus")}Novo</button></div></div>
        <div class="field wide"><label>Tipo de pedido</label>${seg("kind", o.kind, o.kind[0])}</div>
        <div class="field wide"><label>O que precisa ser feito</label><textarea class="input" name="what" required placeholder="Ex.: campanha de limpeza de pele com 20% de desconto em novembro"></textarea></div>
        <div class="field"><label>Objetivo</label><select class="input" name="goal">${selectOpts(o.goal, "")}</select></div>
        <div class="field"><label>Região</label><input class="input" name="region" placeholder="Ex.: raio de 8 km da clínica"></div>
        <div class="field wide"><label>Público-alvo</label><input class="input" name="audience" placeholder="Ex.: mulheres de 25 a 50 anos, interesse em estética"></div>
        <div class="field"><label>Verba</label><div class="money"><span>R$</span><input class="input" name="budget" type="number" min="0" step="0.01" inputmode="decimal" placeholder="0"></div></div>
        <div class="field"><label>Saldo na conta</label>${seg("balance", o.balance, "")}</div>
        <div class="field wide"><label>Link dos criativos</label><input class="input" name="creatives_url" placeholder="https://drive.google.com/…"></div>
        <div class="field"><label>Prazo</label><input class="input" type="date" name="due">
          <div class="seg" id="quickdue" style="margin-top:4px">${[["Hoje", 0], ["Amanhã", 1], ["+3 dias", 3], ["+1 semana", 7]].map(([l, n]) => `<button type="button" class="chip" data-d="${addDays(t, n)}">${l}</button>`).join("")}</div></div>
        <div class="field"><label>Prioridade</label>${seg("priority", o.priority, "Média")}</div>
      </div>
      <div class="spread mt-lg"><a class="btn ghost" href="#/">Cancelar</a><button class="btn primary big" type="submit">${icon("send")}Enviar pedido</button></div>
    </form></div>`;
  const f = $("#f");
  const segs = { kind: o.kind[0], balance: "", priority: "Média" };
  $$("[data-seg]", f).forEach((s) => s.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const on = !b.classList.contains("on") || s.dataset.seg === "priority" || s.dataset.seg === "kind";
    $$("button", s).forEach((x) => x.classList.toggle("on", on && x === b));
    segs[s.dataset.seg] = on ? b.dataset.v : "";
  }));
  $("#quickdue").addEventListener("click", (e) => {
    const b = e.target.closest("[data-d]");
    if (!b) return;
    f.due.value = b.dataset.d;
    $$("#quickdue button").forEach((x) => x.classList.toggle("on", x === b));
  });
  f.due.addEventListener("input", () => $$("#quickdue button").forEach((x) => x.classList.toggle("on", x.dataset.d === f.due.value)));
  $("#newclient").addEventListener("click", async () => {
    const c = await quickClient();
    if (!c) return;
    f.client.insertAdjacentHTML("beforeend", `<option value="${c.id}">${esc(c.name)}</option>`);
    f.client.value = c.id;
  });
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button[type=submit]", f);
    btn.disabled = true;
    const data = Object.fromEntries(new FormData(f));
    try {
      const r = await api("POST", "/api/requests", { ...data, ...segs });
      track("request_created", { kind: data.kind || "", has_deadline: Boolean(data.due) });
      toast(`Pedido #${r.id} enviado`);
      location.hash = `#/pedido/${r.id}`;
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

function quickClient() {
  return new Promise((resolve) => {
    const m = $("#modal");
    m.innerHTML = `<form class="panel" id="qc"><h2>Novo cliente</h2>
      <div class="field"><label>Nome</label><input class="input" name="name" required placeholder="Ex.: Clínica Bem Estar"></div>
      <div class="field mt"><label>Segmento</label><select class="input" name="segment">${selectOpts(BOOT.options.segment, "")}</select></div>
      <p class="muted small">Os outros dados (contato, Instagram, conta de anúncios) dá para completar depois na página do cliente.</p>
      <div class="actions"><button type="button" class="btn ghost" data-a="cancel">Cancelar</button><button class="btn primary">Criar cliente</button></div></form>`;
    m.hidden = false;
    $("#qc").name.focus();
    const done = (v) => { m.hidden = true; m.innerHTML = ""; resolve(v); };
    m.onclick = (e) => { if (e.target === m || e.target.dataset.a === "cancel") done(null); };
    $("#qc").addEventListener("submit", async (e) => {
      e.preventDefault();
      try { done(await api("POST", "/api/clients", Object.fromEntries(new FormData(e.target)))); track("client_saved", { new: true }); }
      catch (err) { toast(err.message, true); }
    });
  });
}
