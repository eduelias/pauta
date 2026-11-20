"use strict";
// Pauta: Perfil (decision 10): the person's own name, e-mail, WhatsApp and passkeys.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- perfil (decision 10) --------------------------------------------------------------

// What is about the person signed in, and only them: name, WhatsApp, e-mail, their passkeys
// (a label each, add one here, remove one while another stays, a link for a new phone) and
// the way out of every device. Removing a passkey signs the other devices out; the server
// re-issues this one's cookie in the same answer, so the page carries on without a reload.
// The team's settings are on Configurações.
const KEY_KINDS = { internal: "Face ID, digital ou PIN", hybrid: "celular, pelo QR", usb: "chave USB", nfc: "chave NFC", ble: "chave Bluetooth" };
function passkeyRow(k, alone) {
  const kinds = (k.transports || "").split(",").filter(Boolean).map((t) => KEY_KINDS[t] || t).join(", ");
  const made = fmtDate(String(k.created).slice(0, 10), { day: "numeric", month: "short", year: "numeric" });
  const used = k.last_used ? `usada ${esc(ago(k.last_used))}` : "nunca usada";
  return `<div class="member" data-pk="${esc(k.id)}">${icon("key", "keyic")}
    <div class="who"><b>${esc(k.label || "Passkey")}</b><span>criada em ${esc(made)} · ${used}${kinds ? ` · ${esc(kinds)}` : ""}</span></div>
    <div class="row-gap"><button class="btn ghost small" data-relabel="${esc(k.id)}" data-label="${esc(k.label)}">${icon("edit")}Renomear</button>
      <button class="btn ghost small danger" data-remove="${esc(k.id)}" data-label="${esc(k.label || "Passkey")}" ${alone ? 'disabled title="Adicione outra passkey antes de tirar esta"' : ""}>${icon("trash")}Remover</button></div></div>`;
}

// "Tela inicial": the Painel and the screens this person can see, plus the one they had
// chosen if it went out of sight (Meta switched off), so saving their name doesn't drop it
function startOptions() {
  const shown = Object.entries(STARTS).filter(([k]) => startVisible(k) || k === ME.start);
  return [["", "Painel"], ...shown].map(([k, label]) => `<option value="${k}"${k === (ME.start || "") ? " selected" : ""}>${label}</option>`).join("");
}

async function viewProfile() {
  const keys = ME.auth ? await api("GET", "/api/me/passkeys") : [];
  if (!onScreen("#/perfil")) return;
  app.innerHTML = `<div style="max-width:760px">
    <div class="head"><div><h1>Perfil</h1><p>Como você aparece para o time e como entra na Pauta.</p></div></div>
    <section class="panel" id="me">
      <div class="member">${avatar(ME.name, "lg round", ME.avatar)}<div class="who"><b>${esc(ME.name)}${ME.is_admin ? ` <span class="tag accent">${icon("shield")}Admin</span>` : ""}</b>
        <span>${ME.auth ? "Entra com passkey: Face ID, digital ou PIN do aparelho." : "Modo local, sem contas."}</span></div></div>
      ${ME.auth ? `<div class="form-grid mt">
        <div class="field"><label>Seu nome</label><input class="input" id="myname" autocomplete="name" value="${esc(ME.name)}"></div>
        <div class="field"><label>WhatsApp <span class="muted">(opcional)</span></label><input class="input" id="mywa" inputmode="tel" autocomplete="tel" placeholder="+55 11 90000-0000" value="${esc(ME.whatsapp || "")}">
          <span class="muted small">Só você vê o número; ele não aparece para o time.</span></div>
        <div class="field wide"><label>E-mail <span class="muted">(opcional)</span></label><input class="input" id="myemail" type="email" inputmode="email" autocomplete="email" placeholder="voce@exemplo.com" value="${esc(ME.email || "")}">
          <span class="muted small">Só para mostrar sua foto do <a href="https://gravatar.com" target="_blank" rel="noopener">Gravatar</a>. O endereço não aparece para o time, mas quem já souber seu e-mail consegue confirmar que é ele.</span></div>
        <div class="field wide"><label for="mystart">Tela inicial</label><select class="input" id="mystart">${startOptions()}</select>
          <span class="muted small">A tela que abre quando você entra na Pauta, neste e nos outros aparelhos. Um link para um pedido continua abrindo o pedido, e o Painel segue no menu.</span></div>
      </div>
      <div class="mt"><button class="btn" id="saveme">${icon("check")}Salvar</button></div>` : ""}
    </section>
    ${ME.auth ? `<section class="panel mt" id="passkeys">
      <div class="panel-head"><h2>${icon("key")}Passkeys</h2><span class="muted small">${keys.length} ${keys.length === 1 ? "aparelho" : "aparelhos"}</span></div>
      <p class="muted small" style="margin-top:-6px">Cada aparelho em que você entra tem a própria passkey. Dê nomes para saber qual é qual e tire a de um aparelho que você não usa mais.</p>
      ${keys.map((k) => passkeyRow(k, keys.length === 1)).join("")}
      <div class="row-gap mt"><button class="btn" id="addkey">${icon("key")}Adicionar passkey neste aparelho</button>
        <button class="btn" id="newlink">${icon("link")}Link de nova passkey</button></div>
      <p class="muted small">O link é para um celular novo (ou perdido): abra-o lá, confirme com o Face ID e a mesma conta entra. Vale uma vez, por 10 minutos, e sair de todos os aparelhos também o cancela.</p>
      <div id="mv-me"></div>
    </section>
    <section class="panel mt" id="sessions"><div class="panel-head"><h2>${icon("logout")}Sessões</h2></div>
      <p class="muted small" style="margin-top:-6px">Sair encerra a Pauta em todos os aparelhos em que você entrou; as passkeys continuam valendo para entrar de novo.</p>
      <button class="btn ghost" id="logout">${icon("logout")}Sair em todos os aparelhos</button></section>` : ""}
  </div>`;
  $("#saveme")?.addEventListener("click", async () => {
    try {
      const body = { name: $("#myname").value, email: $("#myemail").value, whatsapp: $("#mywa").value, start: $("#mystart").value };
      ME = { ...ME, ...(await api("PATCH", "/api/me", body)) };
      track("settings_changed", { section: "perfil" });
      BOOT = await api("GET", "/api/boot");
      renderShell();
      toast("Salvo");
      viewProfile();
    } catch (e) { toast(e.message, true); }
  });
  $("#addkey")?.addEventListener("click", async () => { if (await addPasskey()) viewProfile(); });
  $("#newlink")?.addEventListener("click", () => makeMoveLink("me", ME.name, true));
  $("#logout")?.addEventListener("click", logout);
  $$("[data-relabel]").forEach((b) => b.addEventListener("click", async () => {
    const label = prompt("Nome deste aparelho (por exemplo “iPhone do Piero”)", b.dataset.label);
    if (label === null) return;
    try { await api("PATCH", `/api/me/passkeys/${b.dataset.relabel}`, { label }); viewProfile(); }
    catch (e) { toast(e.message, true); }
  }));
  $$("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Remover a passkey “${b.dataset.label}”? O aparelho dela sai da Pauta agora e só volta a entrar com outra passkey. Este aparelho continua.`)) return;
    try { await api("DELETE", `/api/me/passkeys/${b.dataset.remove}`); toast("Passkey removida"); viewProfile(); }
    catch (e) { toast(e.message, true); }
  }));
}

// The OneDrive card: connect with a code (device code flow), see the account, disconnect.
let DRIVE_TIMER;
async function loadDrive(doc) {
  clearTimeout(DRIVE_TIMER);
  if (!$("#drivebody")) return;
  try { doc = doc || await api("GET", "/api/onedrive"); }
  catch (e) { if ($("#drivebody")) $("#drivebody").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  const box = $("#drivebody");
  if (!box) return;  // left the page while waiting
  box.innerHTML = driveBody(doc);
  bindCopy(box);
  const refreshBoot = async () => { BOOT = await api("GET", "/api/boot"); };
  $("#driveconnect")?.addEventListener("click", async () => {
    try { loadDrive(await api("POST", "/api/onedrive/connect")); track("settings_changed", { section: "arquivos" }); } catch (e) { toast(e.message, true); }
  });
  $("#drivecancel")?.addEventListener("click", async () => {
    loadDrive(await api("DELETE", "/api/onedrive"));
    await refreshBoot();
  });
  $("#driveoff")?.addEventListener("click", async () => {
    if (!confirm("Desconectar o OneDrive? Os arquivos continuam lá, mas a Pauta deixa de enviar e abrir arquivos até alguém reconectar.")) return;
    loadDrive(await api("DELETE", "/api/onedrive"));
    track("settings_changed", { section: "arquivos" });
    await refreshBoot();
    toast("OneDrive desconectado");
  });
  if (doc.state === "pending") DRIVE_TIMER = setTimeout(() => loadDrive(), Math.max(1000, (doc.pending?.interval || 5) * 1000));
  // the toast comes once the app's own state (BOOT.files) knows it too, like the disconnect
  if (doc.state === "connected") { await refreshBoot(); toast("OneDrive conectado"); }
  if (doc.state === "expired") toast("O código expirou; gere outro", true);
  if (doc.state === "denied") toast("A conexão foi recusada na conta Microsoft", true);
}

function driveBody(d) {
  if (!d.enabled) {
    return `<p class="muted">Para anexar arquivos aos pedidos, o servidor precisa de <code>PAUTA_ONEDRIVE_CLIENT_ID</code> (veja <code>deploy/README.md</code>).</p>`;
  }
  if (d.pending) {
    const p = d.pending;
    const until = new Date(p.expires * 1000).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    return `<p>No celular ou no computador, abra <a href="${esc(p.verification_uri)}" target="_blank" rel="noopener"><b>${esc(p.verification_uri.replace(/^https?:\/\//, ""))}</b></a>, entre com a conta Microsoft dona do OneDrive e digite o código:</p>
      <div class="drivecode"><code id="usercode">${esc(p.user_code)}</code><button class="copy" data-copy="${esc(p.user_code)}">Copiar</button></div>
      <p class="muted small">Esta página confere sozinha a cada poucos segundos. O código vale até ${esc(until)}.</p>
      <button class="btn ghost" id="drivecancel">Cancelar</button>`;
  }
  if (!d.connected) {
    return `<p class="muted">Conecte o OneDrive onde os arquivos dos pedidos vão ficar. Quem é dono da conta aprova uma vez, com um código; o time não precisa de acesso a ela.</p>
      <button class="btn primary" id="driveconnect">${icon("cloud")}Conectar OneDrive</button>`;
  }
  const q = d.quota && d.quota.total ? `<div class="quota"><div style="width:${Math.min(100, Math.round(100 * d.quota.used / d.quota.total))}%"></div></div>
    <span class="muted small">${esc(fileSize(d.quota.used))} usados de ${esc(fileSize(d.quota.total))}</span>`
    : d.used != null ? `<p class="muted small mt">A Pauta ocupa ${esc(fileSize(d.used))} neste OneDrive.</p>` : "";
  return `${d.error ? `<p class="warnbox">${esc(d.error)}</p>` : ""}
    <div class="member">${avatar(d.name || d.account || "OneDrive", "md round")}<div class="who"><b>${esc(d.name || d.account)}</b>
      <span>${esc(d.account)} · pasta ${esc(d.folder)} · até ${esc(d.max_mb)} MB por arquivo</span></div></div>
    ${q}
    <div class="row-gap mt">${d.error ? `<button class="btn primary" id="driveconnect">${icon("cloud")}Reconectar</button>` : ""}
      <button class="btn ghost danger" id="driveoff">Desconectar</button></div>`;
}

// The Meta card: connect the agency's business portfolio (Facebook Login for Business, a
// full-page trip to facebook.com and back), then this month's numbers per ad account.
const META_ERRORS = {
  cancelado: "A conexão foi cancelada na Meta",
  expirou: "O pedido de conexão expirou; tente de novo",
};

// The account list answers at once from the server's last read; when that read is past
// its ten minutes (`stale`, after a connect too) Meta is read again behind it and the
// page asks again every few seconds until the new list lands, then redraws itself.
const META_POLL_MS = 2500, META_POLL_MAX = 24;  // about a minute
let metaPoll = 0;  // the poll's own number: a redraw or a new screen stops an older one
async function loadMeta(refresh = false) {
  if (!$("#metabody")) return;
  let html = "", error = "", stale = false;
  try {
    const [doc, clients, log] = await Promise.all([
      api("GET", `/api/meta${refresh ? "?refresh=1" : ""}`), api("GET", "/api/clients"), api("GET", "/api/meta/log")]);
    html = metaBody(doc, clients, log);  // inside the try: an odd answer must not leave the spinner
    stale = Boolean(doc.stale && doc.connected && !doc.error && !doc.accounts_error);
  } catch (e) { error = e.message || "não foi possível mostrar a Meta"; }
  const box = $("#metabody");
  if (!box) return;  // left the page while waiting
  const mine = ++metaPoll;
  if (stale) {
    (async () => {
      for (let i = 0; i < META_POLL_MAX && mine === metaPoll && document.contains(box); i++) {
        await new Promise((r) => setTimeout(r, META_POLL_MS));
        if (mine !== metaPoll || !document.contains(box) || $("select[data-link]:focus")) continue;
        let fresh;
        try { fresh = await api("GET", "/api/meta"); } catch { return; }
        if (mine !== metaPoll) return;
        if (!fresh.stale || fresh.accounts_error) { loadMeta(); return; }
      }
    })();
  }
  box.innerHTML = error
    ? `<p class="warnbox">${esc(error)}</p>
      <div class="row-gap mt"><button class="btn" id="metarefresh">${icon("swap")}Tentar de novo</button></div>`
    : html;
  // the Cliente column: picking saves at once; a suggestion is only a suggestion until picked
  $$("select[data-link]").forEach((sel) => sel.addEventListener("change", async (e) => {
    const el = e.currentTarget, value = el.value;
    el.disabled = true;
    try {
      const row = await api("PATCH", `/api/meta/accounts/${el.dataset.link}`, { client: value ? Number(value) : null });
      track("settings_changed", { section: "meta" });
      toast(row.client ? `Conta vinculada a ${row.client.name}` : "Conta desvinculada");
      loadMeta();
    } catch (err) { toast(err.message, true); el.disabled = false; }
  }));
  // Conectar Meta, Conectar outro portfólio and Adicionar contas are the same trip through
  // Meta's login; the last one names the portfolio it is adding to (a re-login on it)
  $$("[data-metaconnect]").forEach((b) => b.addEventListener("click", async (e) => {
    const btn = e.currentTarget, business = btn.dataset.business;
    if (business && !confirm("Na Meta, entre com o portfólio " + (btn.dataset.name || "") + " e marque todas as contas de anúncios que a Pauta deve ler: as que já estão aqui e as novas. Uma conta que ficar desmarcada pode sair da lista.")) return;
    btn.disabled = true;
    try { location.href = (await api("POST", "/api/meta/connect", business ? { business_id: business } : {})).url; }
    catch (err) { toast(err.message, true); btn.disabled = false; }
  }));
  $("#metarefresh")?.addEventListener("click", (e) => { e.currentTarget.disabled = true; loadMeta(true); });
  $$("[data-metaoff]").forEach((b) => b.addEventListener("click", async (e) => {
    const btn = e.currentTarget, name = btn.dataset.name || "este portfólio";
    if (!confirm(`Desconectar o portfólio ${name}? A Pauta esquece o acesso e para de ler as contas dele; as contas continuam na lista, sem números, até alguém reconectar. Para tirar o acesso também do lado da Meta, remova o app Pauta nas Configurações do negócio desse portfólio (Integrações → Apps conectados).`)) return;
    try { await api("DELETE", `/api/meta/connections/${btn.dataset.metaoff}`); track("settings_changed", { section: "meta" }); toast("Portfólio desconectado"); loadMeta(); }
    catch (err) { toast(err.message, true); }
  }));
}

const META_STATES = {
  revoked: "acesso revogado na Meta; reconecte em Adicionar contas",
};
const stampBR = (iso) => {
  const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : iso.replace(" ", "T") + "Z");
  if (Number.isNaN(d.getTime())) return "";
  return `${d.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`;
};
// one line of the Meta history: who did what to which portfolio or account
function metaLogLine(l) {
  const who = l.by?.name || "Alguém", d = l.detail || {}, port = d.business_name || l.business_id || "";
  const text = {
    connected: `<b>${esc(who)}</b> conectou o portfólio <b>${esc(port)}</b>`,
    disconnected: `<b>${esc(who)}</b> desconectou o portfólio <b>${esc(port)}</b>`,
    linked: `<b>${esc(who)}</b> vinculou a conta <b>${esc(d.account_name || d.account_id || "")}</b> a <b>${esc(d.client_name || "")}</b>`,
    unlinked: `<b>${esc(who)}</b> desvinculou a conta <b>${esc(d.account_name || d.account_id || "")}</b>`,
    revoked: `A Meta revogou o acesso ao portfólio <b>${esc(port)}</b>`,
  }[l.kind] || esc(l.kind);
  return `<li>${text} <span class="muted small">· ${esc(stampBR(l.at))}</span></li>`;
}

function metaBody(d, clients = [], log = []) {
  if (!d.connected) {
    return `<p class="muted">Conecte o portfólio empresarial da agência, ou o do cliente onde a Pauta foi adicionada, para a Pauta ler os números das campanhas. A Pauta só lê; não altera nada na Meta.</p>
      <button class="btn primary" data-metaconnect>${icon("target")}Conectar Meta</button>`;
  }
  const accs = d.accounts || [], conns = d.connections || [];
  // Ativo clients first, then the rest, each group as /api/clients orders them
  const sorted = [...clients.filter((c) => c.state === "Ativo"), ...clients.filter((c) => c.state !== "Ativo")];
  const pick = (a) => {
    const cur = a.client?.id, sug = !cur && a.suggested ? a.suggested.id : null;
    return `<select class="input small" data-link="${esc(a.id)}" aria-label="Cliente da conta ${esc(a.name)}"><option value="">— sem cliente —</option>
      ${sorted.map((c) => `<option value="${c.id}" ${c.id === cur ? "selected" : ""}>${esc(c.name)}${c.id === sug ? " (sugestão)" : ""}</option>`).join("")}</select>
      ${sug ? `<span class="muted small hint">Sugestão: ${esc(a.suggested.name)}</span>` : ""}`;
  };
  // the connection belongs to the team: "conectado à Pauta em <data> (por <pessoa>)", never
  // "conectado por" as if it were theirs. One block per portfolio, with its own buttons.
  const block = (c) => {
    const when = c.connected_at ? new Date(c.connected_at).toLocaleDateString("pt-BR") : "";
    const name = c.business_name || c.business_id;
    const state = c.state === "ok" ? "" : `<span class="warnline">${esc(META_STATES[c.state] || c.error || "problema na conexão")}</span>`;
    return `<div class="member conn" data-conn="${esc(c.business_id)}"><div class="who"><b>Portfólio ${esc(name)}</b>
      <span>conectado à Pauta${when ? ` em ${esc(when)}` : ""}${c.by_name ? ` (por ${esc(c.by_name)})` : ""}${c.last_sync ? ` · sincronizado ${esc(stampBR(c.last_sync))}` : ""}</span>${state}</div>
      <div class="row-gap"><button class="btn primary small" data-metaconnect="add" data-business="${esc(c.business_id)}" data-name="${esc(name)}">${icon("plus")}Adicionar contas</button>
        <button class="btn ghost small danger" data-metaoff="${esc(c.business_id)}" data-name="${esc(name)}">Desconectar</button></div></div>`;
  };
  // the numbers live in Campanhas (decision 8): here only the account, whose it is, the balance
  const rows = accs.map((a) => `<tr${a.stale ? ' class="stale"' : ""} data-business="${esc(a.business_id || "")}"><td><b>${esc(a.name)}</b><span class="muted small">${esc(a.id)}${a.status !== 1 && a.status_label ? ` · ${esc(a.status_label)}` : ""}${a.business_name ? ` · Portfólio ${esc(a.business_name)}` : ""}</span></td>
      <td class="pick">${pick(a)}</td>
      ${a.stale ? `<td class="muted">não aparece mais na Meta</td>` : `<td class="r">${metaBalance(a)}</td>`}</tr>`).join("");
  return `${d.error ? `<p class="warnbox">${esc(d.error)}</p>` : ""}${d.accounts_error && d.accounts_error !== d.error ? `<p class="warnbox">A Meta não respondeu à última leitura: ${esc(d.accounts_error)}</p>` : ""}
    <div class="row-gap"><span class="muted small grow">As contas de anúncios de cada portfólio conectado e de quem é cada uma. Os números das campanhas ficam em <a href="#/campanhas">Campanhas</a>.${d.stale && !d.error && !d.accounts_error ? ` <span id="metareading" title="A lista é da última leitura; a Meta está sendo lida de novo e a tabela se atualiza sozinha">Lendo a Meta de novo…</span>` : ""}</span>
      <button class="btn small" data-metaconnect>${icon("target")}Conectar outro portfólio</button>
      <button class="btn small" id="metarefresh">${icon("swap")}Atualizar</button></div>
    <div id="metaconns">${conns.map(block).join("")}</div>
    ${accs.length ? `<div class="scrollx"><table class="mtable" id="metaaccounts"><thead><tr><th>Conta</th><th>Cliente</th><th class="r">Saldo</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
    : `<div class="empty small">Nenhuma conta de anúncios liberada para a Pauta nos portfólios conectados.</div>`}
    <p class="muted small mt">Cliente novo? Se a conta está num portfólio já conectado, toque em <b>Adicionar contas</b> nele e marque, na Meta, todas as contas que a Pauta deve ler. Se o cliente tem o próprio portfólio, <b>Conectar outro portfólio</b>. Ou, nas Configurações do negócio da Meta (Integrações → Apps conectados → Pauta), adicione a conta e toque em Atualizar. Na coluna <b>Cliente</b>, diga de quem é cada conta: as campanhas dela entram em Campanhas e na página do cliente.</p>
    ${log.length ? `<details class="mt" id="metalog"><summary class="muted small">Histórico</summary><ul class="metalog">${log.map(metaLogLine).join("")}</ul></details>` : ""}`;
}

// The Meta card on a client's page: the last 30 days' tracked campaigns (name, Resultados,
// Custo por resultado, Valor gasto, like Ads Manager; decision 8) and the balance of each
// linked account. Loaded after the page draws; never blocks it.
async function loadClientMeta(c) {
  const box = $("#clientmeta");
  if (!box || !BOOT.meta?.enabled) return;
  const card = (body) => `<div class="panel clientbox mt"><div class="panel-head"><h3>Meta</h3><a class="linkbtn small" href="#/campanhas">Campanhas</a></div>${body}</div>`;
  let doc;
  try { doc = await api("GET", `/api/clients/${c.id}/meta`); }
  catch (e) {
    if ($("#clientmeta")) box.innerHTML = card(`<p class="warnbox">${esc(e.message)}</p>`);
    return;
  }
  if (!$("#clientmeta") || !doc.connected) return;
  if (doc.error) {  // Meta failed: members get a neutral line, admins the reason
    box.innerHTML = card(`<p class="warnbox">${esc(doc.error)}</p>`);
    return;
  }
  let camps = null;
  try { camps = (await api("GET", `/api/campaigns?client=${c.id}`)).clients.flatMap((x) => x.campaigns); }
  catch { camps = null; }
  if (!$("#clientmeta")) return;
  if (!doc.accounts.length && !camps?.length) {
    box.innerHTML = ME.is_admin ? card(`<p class="muted small">Nenhuma conta da Meta vinculada. <a href="#/configuracoes">Vincule em Configurações → Meta.</a></p>`) : "";
    return;
  }
  const line = (label, value) => `<div class="row"><span class="grow muted">${label}</span><b>${value}</b></div>`;
  const list = camps === null ? `<p class="muted small">não foi possível ler as campanhas</p>`
    : !camps.length ? `<p class="muted small">Nenhuma campanha acompanhada nos últimos 30 dias.</p>`
    : camps.map((k) => `<div class="metaacc kcard" data-id="${k.id}"><a class="row" href="#/campanha/${k.id}"><b class="grow">${esc(k.name)}</b>${stateTag(k)}</a>
      ${line("Resultados", k.results == null ? dash(NO_RESULTS) : `${esc(count(k.results))}<span class="muted small"> ${esc(resultLabel(k.result_indicator))}</span>`)}
      ${line("Custo por resultado", k.results ? esc(centsMoney(k.cost_per_result_cents, k.currency)) : dash(NO_RESULTS))}
      ${line("Valor gasto", esc(centsMoney(k.spend_cents, k.currency)))}</div>`).join("");
  box.innerHTML = card(`<div class="muted small">Campanhas acompanhadas · últimos 30 dias</div>${list}
    ${doc.accounts.length ? `<div class="metaacc balances">${doc.accounts.map((a) => line(`Saldo · ${esc(a.name)}`, a.stale ? `<span class="muted small">não aparece mais na Meta</span>` : metaBalance(a))).join("")}</div>` : ""}`);
}

function metaBalance(a) {
  const b = a.balance || {};
  // refused for permissions: the system user's task changed on Meta's side, and only a fresh
  // connection (Adicionar contas) carries the new one; anything else Meta didn't answer
  if (!b.available) return `<span class="muted" title="${esc(b.reason || "")}">${b.refused ? "sem permissão · reconecte em Adicionar contas" : "—"}</span>`;
  if (b.remaining_cents != null) return `${esc(centsMoney(b.remaining_cents, a.currency))}<span class="muted small">até o limite</span>`;
  return b.funding ? esc(b.funding) : "—";
}

// The QR code library is only for an invite: fetched the first time one is made.
let qrLoading;
function loadQr() {
  qrLoading ||= new Promise((done, failed) => {
    const s = document.createElement("script");
    s.src = BOOT.qrcode;
    s.onload = done;
    s.onerror = () => { qrLoading = null; failed(new Error("o QR code não carregou; tente de novo")); };
    document.head.append(s);
  });
  return qrLoading;
}

async function makeInvite() {
  const box = $("#qrbox");
  const admin = $("#asadmin").checked;
  try {
    const [inv] = await Promise.all([api("POST", "/api/invite", { admin }), loadQr()]);
    const url = location.origin + inv.path;
    const qr = qrcode(0, "M");
    qr.addData(url);
    qr.make();
    const until = new Date(inv.expires * 1000).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
    const msg = `Oi! Este é o seu convite para a Pauta, onde a gente organiza os pedidos dos clientes: ${url}`;
    box.innerHTML = `<div class="qrbox"><div class="qr">${qr.createSvgTag({ cellSize: 6, margin: 0, scalable: true })}</div>
      <div style="flex:1;min-width:240px"><b>Convite para 1 pessoa${admin ? " (administrador)" : ""}</b>
      <div class="muted small">Vale até ${esc(until)}.</div>
      <code class="invlink">${esc(url)}</code>
      <div class="row-gap"><button class="btn" data-copy="${esc(url)}">${icon("link")}Copiar link</button>
      <a class="btn" href="https://wa.me/?text=${encodeURIComponent(msg)}" target="_blank" rel="noopener">${icon("wa")}Enviar no WhatsApp</a></div></div></div>`;
    bindCopy(box);
  } catch (e) { toast(e.message, true); }
}
