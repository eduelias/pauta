"use strict";
// Pauta: the clients list and one client.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- clients -------------------------------------------------------------------------

// What the clients can be ordered by, in the order of the list's columns: the label, the
// direction it starts in (the one people want first: A to Z, the most requests in the open,
// the latest request), the value, and how each direction reads on the button that turns it.
const CLIENT_SORTS = {
  name: ["Nome", 1, (c) => c.name, ["A → Z", "Z → A"]],
  segment: ["Segmento", 1, (c) => c.segment || "", ["A → Z", "Z → A"]],
  state: ["Situação", 1, (c) => BOOT.options.state.indexOf(c.state), ["Ativos primeiro", "Encerrados primeiro"]],
  open: ["Em aberto", -1, (c) => c.open_requests, ["Menos primeiro", "Mais primeiro"]],
  total: ["Pedidos", -1, (c) => c.total_requests, ["Menos primeiro", "Mais primeiro"]],
  last: ["Último pedido", -1, (c) => c.last_request || "", ["Mais antigo primeiro", "Mais recente primeiro"]],
  since: ["Cliente desde", 1, (c) => c.since || "", ["Mais antigo primeiro", "Mais novo primeiro"]],
};
// "Ótica" next to "Oficina", "Cliente 2" before "Cliente 10"
const ptCompare = (a, b) => a.localeCompare(b, "pt-BR", { sensitivity: "base", numeric: true });

// A closed client stays at the end whatever the order (unless the order is the state itself),
// one with nothing to order by (no segment, no request yet) comes after the ones that have
// it, in either direction, and the name settles a tie.
function sortClients(list, key, dir) {
  const value = CLIENT_SORTS[key][2];
  return [...list].sort((a, b) => {
    const closed = key === "state" ? 0 : (a.state === "Encerrado") - (b.state === "Encerrado");
    if (closed) return closed;
    const x = value(a), y = value(b);
    if (x !== y && (x === "" || y === "")) return x === "" ? 1 : -1;
    const d = typeof x === "number" ? x - y : ptCompare(x, y);
    return d * dir || ptCompare(a.name, b.name);
  });
}

// Cards or a list, and the order: each person's own choice, kept in this browser.
function clientPrefs() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem("pauta.clients") || "{}") || {}; } catch { saved = {}; }
  const sort = Object.hasOwn(CLIENT_SORTS, saved.sort) ? saved.sort : "name";
  return { view: saved.view === "list" ? "list" : "cards", sort, dir: [1, -1].includes(saved.dir) ? saved.dir : CLIENT_SORTS[sort][1] };
}

const NOWA = () => `<span class="nowa" title="Sem WhatsApp cadastrado: o relatório não abre a conversa">${icon("wa")}sem WhatsApp</span>`;

function clientCards(list) {
  return `<div class="cgrid">${list.map((c) => `<a class="ccard ${c.state === "Encerrado" ? "closed" : ""}" href="#/cliente/${c.id}">
      <div class="top">${avatar(c.name, "md")}<div style="min-width:0"><b>${esc(c.name)}</b><span>${esc(c.segment || "Sem segmento")}${c.instagram ? ` · ${esc(c.instagram)}` : ""}</span></div></div>
      <div class="foot"><span class="state ${esc(c.state)}">${esc(c.state)}</span>${c.whatsapp ? "" : NOWA()}
        ${c.open_requests ? `<span class="open">${c.open_requests} em aberto</span>` : `<span>${c.total_requests} pedido${c.total_requests === 1 ? "" : "s"}</span>`}
        ${c.last_request ? `<span style="margin-left:auto">${esc(ago(c.last_request))}</span>` : ""}</div></a>`).join("")}</div>`;
}

// The list: a line per client, a column per thing to order by; a heading orders by its
// column, and again turns the order round. The name takes the width the others leave and is
// cut short before the list is wider than the screen; a narrow screen drops the two columns
// that say least. On the phone the headings are gone ("Ordenar por" above does it) and a
// line keeps the name, the state, the segment, what is open and the last request.
function clientTable(list, pref) {
  const none = '<span class="faint">—</span>';
  const cell = {
    name: (c) => `<div class="who"><a class="cl" href="#/cliente/${c.id}">${avatar(c.name)}<b>${esc(c.name)}</b></a>${c.whatsapp ? "" : NOWA()}</div>`,
    segment: (c) => esc(c.segment) || none,
    state: (c) => `<span class="state ${esc(c.state)}">${esc(c.state)}</span>`,
    open: (c) => c.open_requests ? `<b>${c.open_requests}</b><span class="unit"> em aberto</span>` : '<span class="faint">0</span>',
    total: (c) => c.total_requests || '<span class="faint">0</span>',
    last: (c) => c.last_request ? esc(ago(c.last_request)) : none,
    since: (c) => c.since ? esc(fmtDate(c.since, { month: "short", year: "numeric" })) : none,
  };
  const head = ([k, [label]]) => {
    const on = k === pref.sort;
    return `<th class="c-${k}" aria-sort="${on ? (pref.dir > 0 ? "ascending" : "descending") : "none"}"><button type="button" data-sort="${k}">${label}${on ? icon(pref.dir > 0 ? "up" : "down") : ""}</button></th>`;
  };
  return `<table class="table ctable"><thead><tr>${Object.entries(CLIENT_SORTS).map(head).join("")}</tr></thead><tbody>
    ${list.map((c) => `<tr data-id="${c.id}" class="${c.state === "Encerrado" ? "closed" : ""}${c.open_requests ? "" : " idle"}">${Object.keys(CLIENT_SORTS).map((k) => `<td class="c-${k}">${cell[k](c)}</td>`).join("")}</tr>`).join("")}
    </tbody></table>`;
}

async function viewClients(query) {
  const clients = await api("GET", "/api/clients");
  let q = query.get("q") || "";
  const states = BOOT.options.state;
  let st = states.includes(query.get("s")) ? query.get("s") : "";
  const pref = clientPrefs();
  const count = (s) => clients.filter((c) => !s || c.state === s).length;
  app.innerHTML = `<div>
    <div class="head"><div><h1>Clientes</h1><p>${clients.filter((c) => c.state === "Ativo").length} ativos de ${clients.length}.</p></div>
      <div class="actions"><a class="btn primary" href="#/cliente/novo">${icon("plus")}Novo cliente</a></div></div>
    <div class="toolbar"><div class="search">${icon("search")}<input class="input" id="q" placeholder="Buscar cliente…" value="${esc(q)}"></div>
      <div class="seg" id="states">${["", ...states].map((s) => `<button type="button" data-v="${esc(s)}" class="${s === st ? "on" : ""}">${esc(s || "Todos")} <span class="n">${count(s)}</span></button>`).join("")}</div>
      <div class="ctools"><label class="pick">Ordenar por<select class="input" id="sort">${Object.entries(CLIENT_SORTS).map(([k, [label]]) => `<option value="${k}">${label}</option>`).join("")}</select></label>
        <button type="button" class="btn" id="dir" title="Inverter a ordem"></button>
        <div class="seg views" id="view" role="group" aria-label="Como mostrar os clientes">${[["cards", "grid", "Cartões"], ["list", "list", "Lista"]].map(([v, i, t]) => `<button type="button" data-v="${v}" aria-label="${t}" title="${t}">${icon(i)}</button>`).join("")}</div></div></div>
    <div id="grid"></div></div>`;
  const draw = () => {
    const n = q.trim().toLowerCase();
    const list = sortClients(clients.filter((c) => (!st || c.state === st) && (!n || [c.name, c.segment, c.contact, c.instagram].join(" ").toLowerCase().includes(n))), pref.sort, pref.dir);
    $("#sort").value = pref.sort;
    $("#dir").textContent = CLIENT_SORTS[pref.sort][3][pref.dir > 0 ? 0 : 1];
    $$("#view button").forEach((b) => { b.classList.toggle("on", b.dataset.v === pref.view); b.setAttribute("aria-pressed", b.dataset.v === pref.view); });
    $("#grid").innerHTML = list.length ? (pref.view === "list" ? clientTable(list, pref) : clientCards(list))
      : `<div class="panel empty"><span class="big">🏢</span>${clients.length ? (st && !n ? `Nenhum cliente ${esc(st.toLowerCase())}.` : "Nenhum cliente encontrado.") : "Nenhum cliente ainda. Comece cadastrando o primeiro."}</div>`;
  };
  const choose = (change, what) => {
    change();
    try { localStorage.setItem("pauta.clients", JSON.stringify(pref)); } catch { /* private mode: not remembered */ }
    track("filter", { what });
    draw();
  };
  // a column starts in its own direction; asking for the same one again turns it round
  const order = (key) => choose(() => { pref.dir = key === pref.sort ? -pref.dir : CLIENT_SORTS[key][1]; pref.sort = key; }, "sort");
  $("#q").addEventListener("input", (e) => { q = e.target.value; draw(); });
  $("#states").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    st = b.dataset.v;
    $$("#states button").forEach((x) => x.classList.toggle("on", x === b));
    keepHash(st ? `#/clientes?s=${encodeURIComponent(st)}` : "#/clientes");
    draw();
  });
  $("#sort").addEventListener("change", (e) => choose(() => { pref.sort = e.target.value; pref.dir = CLIENT_SORTS[pref.sort][1]; }, "sort"));
  $("#dir").addEventListener("click", () => order(pref.sort));
  $("#view").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (b && b.dataset.v !== pref.view) choose(() => { pref.view = b.dataset.v; }, "view");
  });
  $("#grid").addEventListener("click", (e) => {
    const th = e.target.closest("[data-sort]");
    if (th) return order(th.dataset.sort);
    const tr = e.target.closest("tr[data-id]");  // the whole line opens the client, as the card does
    if (tr && !e.target.closest("a")) location.hash = `#/cliente/${tr.dataset.id}`;
  });
  draw();
}

function clientForm(c = {}) {
  const o = BOOT.options;
  return `<div class="form-grid">
    <div class="field wide"><label>Nome</label><input class="input" name="name" data-f="name" required value="${esc(c.name || "")}" placeholder="Ex.: Clínica Bem Estar"></div>
    <div class="field wide wa"><label>${icon("wa")}WhatsApp do cliente</label><input class="input" name="whatsapp" data-f="whatsapp" inputmode="tel" value="${esc(c.whatsapp || "")}" placeholder="(DDD) 9XXXX-XXXX"><span class="hint">para abrir a conversa do relatório daqui</span></div>
    <div class="field"><label>Segmento</label><select class="input" name="segment" data-f="segment">${selectOpts(o.segment, c.segment || "")}</select></div>
    <div class="field"><label>Cliente desde</label><input class="input" type="date" name="since" data-f="since" value="${esc(c.since || "")}"></div>
    <div class="field"><label>Contato no cliente</label><input class="input" name="contact" data-f="contact" value="${esc(c.contact || "")}" placeholder="Nome de quem fala com a gente"></div>
    <div class="field"><label>Instagram / página</label><input class="input" name="instagram" data-f="instagram" value="${esc(c.instagram || "")}" placeholder="@perfil"></div>
    <div class="field"><label>ID da conta de anúncios</label><input class="input" name="ad_account" data-f="ad_account" value="${esc(c.ad_account || "")}" placeholder="1234567890"></div>
    <div class="field wide"><label>Link da página de anúncios</label><input class="input" name="ads_page" data-f="ads_page" value="${esc(c.ads_page || "")}" placeholder="https://www.facebook.com/ads/library/…"></div>
    <div class="field"><label>Acesso à conta</label>${seg("access", o.access, c.access || "Pendente")}</div>
    <div class="field"><label>Situação</label>${seg("state", o.state, c.state || "Ativo")}</div>
    <div class="field wide"><label>Pasta de criativos (Drive)</label><input class="input" name="drive_url" data-f="drive_url" value="${esc(c.drive_url || "")}" placeholder="https://drive.google.com/…"></div>
    <div class="field wide"><label>Observações</label><textarea class="input" name="notes" data-f="notes">${esc(c.notes || "")}</textarea></div>
  </div>`;
}

async function viewNewClient() {
  app.innerHTML = `<div style="max-width:860px">
    <div class="head"><div><h1>Novo cliente</h1><p>Os dados fixos, preenchidos uma vez.</p></div></div>
    <form class="panel" id="f" autocomplete="off">${clientForm()}
      <div class="spread mt-lg"><a class="btn ghost" href="#/clientes">Cancelar</a><button class="btn primary big">${icon("check")}Salvar cliente</button></div></form></div>`;
  const f = $("#f");
  const segs = { access: "Pendente", state: "Ativo" };
  $$("[data-seg]", f).forEach((s) => s.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    $$("button", s).forEach((x) => x.classList.toggle("on", x === b));
    segs[s.dataset.seg] = b.dataset.v;
  }));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button.primary", f);
    btn.disabled = true;
    try {
      const c = await api("POST", "/api/clients", { ...Object.fromEntries(new FormData(f)), ...segs });
      track("client_saved", { new: true });
      toast("Cliente salvo");
      location.hash = `#/cliente/${c.id}`;
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
}

async function viewClient(_q, id) {
  let c = await api("GET", `/api/clients/${id}`);
  const open = c.requests.filter(isOpen).sort(sortOpen);
  const past = c.requests.filter((r) => !isOpen(r));
  app.innerHTML = `<div>
    <div class="crumb"><a href="#/clientes">Clientes</a><span>/</span><span>${esc(c.name)}</span></div>
    <div class="client-hero">${avatar(c.name, "lg")}<div style="flex:1;min-width:200px"><h1 id="cname">${esc(c.name)} <span class="state ${esc(c.state)}">${esc(c.state)}</span></h1>
      <p class="muted" style="margin:4px 0 0">${esc(c.segment || "Sem segmento")}${c.since ? ` · cliente desde ${esc(fmtDate(c.since, { month: "long", year: "numeric" }))}` : ""}</p></div>
      <a class="btn primary" href="#/novo/${c.id}">${icon("plus")}Novo pedido</a></div>
    <div class="req">
      <div>
        <section class="panel"><div class="panel-head"><h2>Em aberto</h2><span class="muted small">${open.length}</span></div>
          ${open.length ? `<div class="rcards">${open.map((r) => rcard(r, { client: false })).join("")}</div>` : `<div class="empty">Nenhum pedido em aberto.</div>`}</section>
        ${past.length ? `<section class="panel"><div class="panel-head"><h2>Histórico</h2><span class="muted small">${past.length}</span></div>
          <div class="rcards">${past.map((r) => rcard(r, { client: false })).join("")}</div></section>` : ""}
        <section class="panel"><div class="panel-head"><h2>Cadastro</h2><span class="muted small">Salva sozinho</span></div>
          <div class="quiet-off">${clientForm(c)}</div></section>
      </div>
      <aside><div class="panel clientbox"><div class="panel-head"><h3>Atalhos</h3></div>${clientRows(c)}</div>
        <div id="clientmeta"></div>
        <div id="paybox">${payBox(c)}</div>
        ${ME.is_admin ? `<div class="mt"><button class="btn ghost danger" id="del">${icon("trash")}Excluir cliente</button></div>` : ""}</aside>
    </div></div>`;
  const root = app.firstElementChild;  // off the page once the person leaves this client
  const drawPay = () => { if (!root.isConnected) return; $("#paybox").innerHTML = payBox(c); bindPayBox(c, (fresh) => { c = { ...c, ...fresh }; drawPay(); }); };
  bindPayBox(c, (fresh) => { c = { ...c, ...fresh }; drawPay(); });
  const save = async (patch, el) => {
    try {
      c = { ...c, ...(await api("PATCH", `/api/clients/${c.id}`, patch)) };
      track("client_saved", { new: false });
      if (!root.isConnected) return true;
      $("#cname").innerHTML = `${esc(c.name)} <span class="state ${esc(c.state)}">${esc(c.state)}</span>`;
      $(".clientbox").innerHTML = `<div class="panel-head"><h3>Atalhos</h3></div>${clientRows(c)}`;
      bindCopy($(".clientbox"));
      drawPay();
      if (el) { el.classList.remove("saved-flash"); void el.offsetWidth; el.classList.add("saved-flash"); }
      toast("Salvo");
      return true;
    } catch (e) { toast(e.message, true); return false; }
  };
  // not saved: back to what the server has, as on the request (typed text stays)
  $$("[data-f]").forEach((el) => el.addEventListener("change", async () => {
    if (!await save({ [el.dataset.f]: el.value }, el) && el.matches("select, [type=date]")) el.value = c[el.dataset.f] ?? "";
  }));
  $$("[data-seg]").forEach((s) => s.addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b || b.classList.contains("on")) return;
    segOn(s, b.dataset.v);
    await save({ [s.dataset.seg]: b.dataset.v });
    segOn(s, c[s.dataset.seg]);  // what the server has now, saved or not
  }));
  $("#del")?.addEventListener("click", () => deleteClient(c));
  bindCopy(app);
  loadClientMeta(c);
}

// Deleting a client with requests takes them (and their history) along, so the name has to
// be typed to confirm; to keep the history, mark the client Encerrado instead.
function deleteClient(c) {
  const n = c.requests.length;
  const m = $("#modal");
  m.innerHTML = `<form class="panel" id="delc"><h2>Excluir ${esc(c.name)}?</h2>
    <p>${n ? `Isso apaga o cliente <b>e ${n === 1 ? "o pedido" : `os ${n} pedidos`}</b> dele, com todo o histórico e os comentários.` : "Isso apaga o cadastro do cliente."} Não dá para desfazer.</p>
    ${n ? `<p class="muted small">Para guardar o histórico, marque o cliente como <b>Encerrado</b> em vez de excluir.</p>
    <div class="field mt"><label>Digite o nome do cliente para confirmar</label><input class="input" name="confirm" autocomplete="off" placeholder="${esc(c.name)}"></div>` : ""}
    <div class="actions"><button type="button" class="btn ghost" data-a="cancel">Cancelar</button><button class="btn danger-solid" ${n ? "disabled" : ""}>${icon("trash")}Excluir</button></div></form>`;
  m.hidden = false;
  const f = $("#delc");
  const go = $("button:not([data-a])", f);
  const close = () => { m.hidden = true; m.innerHTML = ""; };
  const norm = (s) => s.trim().toLowerCase().replace(/\s+/g, " ");
  if (n) {
    f.confirm.focus();
    f.confirm.addEventListener("input", () => { go.disabled = norm(f.confirm.value) !== norm(c.name); });
  } else go.focus();
  m.onclick = (e) => { if (e.target === m || e.target.dataset.a === "cancel") close(); };
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (go.disabled) return;
    go.disabled = true;
    try {
      await api("DELETE", `/api/clients/${c.id}${n ? "?with_requests=1" : ""}`);
      close();
      toast(n ? `${c.name} e ${n === 1 ? "1 pedido excluídos" : `${n} pedidos excluídos`}` : `${c.name} excluído`);
      location.hash = "#/clientes";
    } catch (err) { toast(err.message, true); go.disabled = false; }
  });
}
