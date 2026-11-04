"use strict";
// Pauta: the clients list and one client.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- clients -------------------------------------------------------------------------

async function viewClients(query) {
  const clients = await api("GET", "/api/clients");
  let q = query.get("q") || "";
  const states = BOOT.options.state;
  let st = states.includes(query.get("s")) ? query.get("s") : "";
  const count = (s) => clients.filter((c) => !s || c.state === s).length;
  app.innerHTML = `<div>
    <div class="head"><div><h1>Clientes</h1><p>${clients.filter((c) => c.state === "Ativo").length} ativos de ${clients.length}.</p></div>
      <div class="actions"><a class="btn primary" href="#/cliente/novo">${icon("plus")}Novo cliente</a></div></div>
    <div class="toolbar"><div class="search">${icon("search")}<input class="input" id="q" placeholder="Buscar cliente…" value="${esc(q)}"></div>
      <div class="seg" id="states">${["", ...states].map((s) => `<button type="button" data-v="${esc(s)}" class="${s === st ? "on" : ""}">${esc(s || "Todos")} <span class="n">${count(s)}</span></button>`).join("")}</div></div>
    <div id="grid"></div></div>`;
  const draw = () => {
    const n = q.trim().toLowerCase();
    const list = clients.filter((c) => (!st || c.state === st) && (!n || [c.name, c.segment, c.contact, c.instagram].join(" ").toLowerCase().includes(n)));
    $("#grid").innerHTML = list.length ? `<div class="cgrid">${list.map((c) => `<a class="ccard ${c.state === "Encerrado" ? "closed" : ""}" href="#/cliente/${c.id}">
      <div class="top">${avatar(c.name, "md")}<div style="min-width:0"><b>${esc(c.name)}</b><span>${esc(c.segment || "Sem segmento")}${c.instagram ? ` · ${esc(c.instagram)}` : ""}</span></div></div>
      <div class="foot"><span class="state ${esc(c.state)}">${esc(c.state)}</span>
        ${c.open_requests ? `<span class="open">${c.open_requests} em aberto</span>` : `<span>${c.total_requests} pedido${c.total_requests === 1 ? "" : "s"}</span>`}
        ${c.last_request ? `<span style="margin-left:auto">${esc(ago(c.last_request))}</span>` : ""}</div></a>`).join("")}</div>`
      : `<div class="panel empty"><span class="big">🏢</span>${clients.length ? (st && !n ? `Nenhum cliente ${esc(st.toLowerCase())}.` : "Nenhum cliente encontrado.") : "Nenhum cliente ainda. Comece cadastrando o primeiro."}</div>`;
  };
  $("#q").addEventListener("input", (e) => { q = e.target.value; draw(); });
  $("#states").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    st = b.dataset.v;
    $$("#states button").forEach((x) => x.classList.toggle("on", x === b));
    history.replaceState(null, "", st ? `#/clientes?s=${encodeURIComponent(st)}` : "#/clientes");
    draw();
  });
  draw();
}

function clientForm(c = {}) {
  const o = BOOT.options;
  return `<div class="form-grid">
    <div class="field wide"><label>Nome</label><input class="input" name="name" data-f="name" required value="${esc(c.name || "")}" placeholder="Ex.: Clínica Bem Estar"></div>
    <div class="field"><label>Segmento</label><select class="input" name="segment" data-f="segment">${selectOpts(o.segment, c.segment || "")}</select></div>
    <div class="field"><label>Cliente desde</label><input class="input" type="date" name="since" data-f="since" value="${esc(c.since || "")}"></div>
    <div class="field"><label>Contato no cliente</label><input class="input" name="contact" data-f="contact" value="${esc(c.contact || "")}" placeholder="Nome de quem fala com a gente"></div>
    <div class="field"><label>WhatsApp</label><input class="input" name="whatsapp" data-f="whatsapp" inputmode="tel" value="${esc(c.whatsapp || "")}" placeholder="(DDD) 9XXXX-XXXX"></div>
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
    try {
      const c = await api("POST", "/api/clients", { ...Object.fromEntries(new FormData(f)), ...segs });
      track("client_saved", { new: true });
      toast("Cliente salvo");
      location.hash = `#/cliente/${c.id}`;
    } catch (err) { toast(err.message, true); }
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
  const drawPay = () => { $("#paybox").innerHTML = payBox(c); bindPayBox(c, (fresh) => { c = { ...c, ...fresh }; drawPay(); }); };
  bindPayBox(c, (fresh) => { c = { ...c, ...fresh }; drawPay(); });
  const save = async (patch, el) => {
    try {
      c = { ...c, ...(await api("PATCH", `/api/clients/${c.id}`, patch)) };
      track("client_saved", { new: false });
      $("#cname").innerHTML = `${esc(c.name)} <span class="state ${esc(c.state)}">${esc(c.state)}</span>`;
      $(".clientbox").innerHTML = `<div class="panel-head"><h3>Atalhos</h3></div>${clientRows(c)}`;
      bindCopy($(".clientbox"));
      drawPay();
      if (el) { el.classList.remove("saved-flash"); void el.offsetWidth; el.classList.add("saved-flash"); }
      toast("Salvo");
    } catch (e) { toast(e.message, true); }
  };
  $$("[data-f]").forEach((el) => el.addEventListener("change", () => save({ [el.dataset.f]: el.value }, el)));
  $$("[data-seg]").forEach((s) => s.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b || b.classList.contains("on")) return;
    $$("button", s).forEach((x) => x.classList.toggle("on", x === b));
    save({ [s.dataset.seg]: b.dataset.v });
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
