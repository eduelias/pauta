"use strict";
// Pauta: Equipe and Configurações, the account menu, moving house, passkeys, the login and join gate.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- team, account, settings ---------------------------------------------------------

// Configurações (up to 1.6 "Equipe"): the team, then each module's settings, admins only
// past the team. What is about the person signed in lives on Perfil (viewProfile).
async function viewSettings(query) {
  const members = await api("GET", "/api/members");
  const o = BOOT.options;
  app.innerHTML = `<div style="max-width:980px">
    <div class="head"><div><h1>Configurações</h1><p>O time, as integrações e as listas da Pauta.</p></div>
      ${ME.is_admin ? `<div class="actions"><button class="btn" id="export">${icon("download")}Exportar dados</button></div>` : ""}</div>
    <a class="profile-link" href="#/perfil" id="toprofile">${avatar(ME.name, "round", ME.avatar)}Seu perfil →</a>
    <section class="panel" id="time">
        <div class="panel-head"><h2>${icon("team")}Time</h2><span class="muted small">${members.filter((m) => !m.disabled).length} pessoas</span></div>
        ${members.length ? members.map((m) => `<div class="member ${m.disabled ? "off" : ""}">${avatar(m.name, "md round", m.avatar)}
          <div class="who"><b>${esc(m.name)}${m.is_admin ? ` <span class="tag accent">Admin</span>` : ""}${m.disabled ? ` <span class="tag">Desativado</span>` : ""}</b>
          <span>${m.passkeys} passkey${m.passkeys === 1 ? "" : "s"}${m.last_seen ? ` · visto ${esc(ago(m.last_seen))}` : ""}${ME.move && !m.disabled ? (m.domains.includes(ME.move.to) ? ` · já em ${esc(ME.move.to)}` : " · ainda não mudou") : ""}</span></div>
          ${ME.is_admin && m.id !== ME.account ? `<div class="row-gap">
            ${ME.auth && !m.disabled ? (ME.move && !m.domains.includes(ME.move.to)
              ? `<button class="btn small" data-mv="${m.id}" data-name="${esc(m.name)}">${icon("link")}Link para mudar</button>`
              : `<button class="btn small" data-mv="${m.id}" data-name="${esc(m.name)}" data-new="1">${icon("key")}Link de nova passkey</button>`) : ""}
            <button class="btn ghost small" data-m="${m.id}" data-admin="${m.is_admin ? 0 : 1}">${m.is_admin ? "Tirar admin" : "Tornar admin"}</button>
            <button class="btn ghost small ${m.disabled ? "" : "danger"}" data-m="${m.id}" data-dis="${m.disabled ? 0 : 1}">${m.disabled ? "Reativar" : "Desativar"}</button></div>` : ""}
        </div><div id="mv-${m.id}"></div>`).join("") : `<div class="empty">Ninguém ainda.</div>`}
        ${ME.is_admin && ME.auth ? `<div class="invite mt" id="invitebox"><h3>Convidar alguém</h3>
          <p class="muted small" style="margin-top:4px">A pessoa abre o link (ou aponta a câmera para o QR), digita o nome e cria uma passkey. Sem senha, sem cadastro.</p>
          <div class="row-gap"><label class="toggle"><input type="checkbox" id="asadmin">Como administrador</label>
            <button class="btn primary" id="invite">${icon("plus")}Gerar convite</button></div>
          <div id="qrbox"></div></div>` : ""}
      </section>
    ${ME.is_admin && BOOT.meta?.enabled ? `<section class="panel mt" id="meta"><div class="panel-head"><h2>${icon("target")}Meta</h2><span class="muted small">Números das campanhas</span></div>
      <div id="metabody">${spinner()}</div></section>` : ""}
    ${ME.is_admin ? financeSettingsPanel(BOOT.finance) : ""}
    ${ME.is_admin ? `<section class="panel mt" id="lists"><div class="panel-head"><h2>${icon("list")}Listas</h2><span class="muted small">Um item por linha</span></div>
      <div class="grid3">${[["kind", "Tipos de pedido"], ["goal", "Objetivos"], ["segment", "Segmentos"]].map(([k, t]) => `<div class="field"><label>${t}</label>
        <textarea class="input" data-list="${k}" rows="9">${esc(o[k].join("\n"))}</textarea></div>`).join("")}</div>
      <div class="mt"><button class="btn" id="savelists">${icon("check")}Salvar listas</button></div></section>` : ""}
    ${ME.is_admin ? `<section class="panel mt" id="drive"><div class="panel-head"><h2>${icon("cloud")}Arquivos</h2><span class="muted small">O OneDrive dos pedidos</span></div>
      <div id="drivebody">${spinner()}</div></section>` : ""}
    <p class="muted small mt" id="version">Pauta ${esc(BOOT.version || "")}</p>
  </div>`;
  if (ME.is_admin) loadDrive();
  if (ME.is_admin && BOOT.meta?.enabled) loadMeta();
  const back = query?.get("meta");  // the way back from Meta's login (/api/meta/callback)
  if (back) {
    history.replaceState(null, "", "#/configuracoes");
    if (back === "conectado") toast("Meta conectada");
    else toast(META_ERRORS[query.get("motivo")] || "Não foi possível conectar à Meta; tente de novo", true);
  }
  $$("[data-m]").forEach((b) => b.addEventListener("click", async () => {
    const body = b.dataset.admin !== undefined ? { is_admin: b.dataset.admin === "1" } : { disabled: b.dataset.dis === "1" };
    try { await api("PATCH", `/api/members/${b.dataset.m}`, body); track("settings_changed", { section: "equipe" }); viewSettings(); } catch (e) { toast(e.message, true); }
  }));
  $("#invite")?.addEventListener("click", makeInvite);
  $$("[data-mv]").forEach((b) => b.addEventListener("click", () => makeMoveLink(b.dataset.mv, b.dataset.name, !!b.dataset.new)));
  $("#savefin")?.addEventListener("click", async () => {
    const body = {};
    for (const el of $$("[data-fin]")) body[el.dataset.fin] = el.type === "checkbox" ? el.checked : el.value;
    try {
      await api("PATCH", "/api/finance/settings", body);
      track("settings_changed", { section: "financeiro" });
      BOOT = await api("GET", "/api/boot");
      renderShell();
      toast("Financeiro salvo");
    } catch (e) { toast(e.message, true); }
  });
  $("#savelists")?.addEventListener("click", async () => {
    try {
      for (const t of $$("[data-list]")) {
        BOOT.options = await api("PUT", `/api/options/${t.dataset.list}`, { values: t.value.split("\n") });
      }
      track("settings_changed", { section: "listas" });
      toast("Listas salvas");
    } catch (e) { toast(e.message, true); }
  });
  $("#export")?.addEventListener("click", async () => {
    const doc = await api("GET", "/api/export");
    const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pauta-${todayISO()}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}

// ---------- moving to a new address (decision 4) ----------------------------------------------

// On the old address: a bar on every screen until this person has a passkey on the new one
function addMoveBar() {
  const mv = ME?.move;
  if (!mv || mv.here || $("#movebar")) return;
  app.insertAdjacentHTML("afterbegin", `<div class="movebar" id="movebar">
    <div><b>A Pauta mudou para ${esc(mv.to)}</b>
      <span>${mv.done ? "Você já tem passkey lá. A partir de agora, abra a Pauta pelo endereço novo." : "Leve sua conta em um minuto: é só criar uma passkey no endereço novo. Tudo continua igual."}</span></div>
    ${mv.done ? `<a class="btn primary" href="${esc(mv.url)}/">Abrir ${esc(mv.to)}</a>` : `<button class="btn primary" id="moveme">Mudar para ${esc(mv.to)}</button>`}</div>`);
  $("#moveme")?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    try { location.href = (await api("POST", "/api/move", {})).url; }
    catch (err) { toast(err.message, true); e.currentTarget.disabled = false; }
  });
}

// An admin's link for someone who hasn't moved: sent on WhatsApp, it's one tap and Face ID
// The same one-time link serves a domain move and a new (or lost) phone; only the words differ
async function makeMoveLink(id, name, fresh = false) {
  const box = $(`#mv-${id}`);
  const mine = id === "me";  // Perfil: the same link, made by the person for themselves
  try {
    const mv = await api("POST", mine ? "/api/me/move" : `/api/members/${id}/move`, {});
    // the person's own link is tapped right away (10 minutes); an admin's is sent and waited for
    const until = mine ? "por 10 minutos" : "até " + new Date(mv.expires * 1000).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
    const msg = mine
      ? `Meu link para criar uma passkey nova na Pauta (celular novo ou perdido). Abrir no aparelho novo, confirmar com o Face ID (ou a digital) e pronto: é a mesma conta, com tudo. ${mv.url}`
      : fresh
        ? `Oi, ${firstName(name)}! Este é o seu link para criar uma passkey nova na Pauta (celular novo ou perdido). Toque no link, confirme com o Face ID (ou a digital) e pronto: é a mesma conta, com tudo. ${mv.url}`
        : `Oi, ${firstName(name)}! A Pauta mudou para ${mv.to}. Toque no link, confirme com o Face ID (ou a digital) e pronto: é a mesma conta, com tudo. Depois adicione o endereço novo à tela de início. ${mv.url}`;
    const title = mine ? "Seu link de nova passkey" : fresh ? `Link de nova passkey de ${esc(firstName(name))}` : `Link de ${esc(firstName(name))} para ${esc(mv.to)}`;
    const who = mine ? "Só para você" : `Só para ${esc(firstName(name))}`;
    box.innerHTML = `<div class="qrbox"><div style="flex:1;min-width:240px"><b>${title}</b>
      <div class="muted small">${who}: quem tiver o link entra na conta. Vale uma vez, ${esc(until)}.</div>
      <code class="invlink">${esc(mv.url)}</code>
      <div class="row-gap"><button class="btn" data-copy="${esc(mv.url)}">${icon("link")}Copiar link</button>
      <a class="btn primary" href="https://wa.me/?text=${encodeURIComponent(msg)}" target="_blank" rel="noopener">${icon("wa")}Enviar no WhatsApp</a></div></div></div>`;
    bindCopy(box);
  } catch (e) { toast(e.message, true); }
}

// On the new address: make a passkey for the same account, then in
async function showMove(token) {
  const to = ME.move?.to || location.hostname;
  if (ME.logged_in && ME.auth) {
    gate(`<h1>Tudo certo</h1><p>Você já está na Pauta em ${esc(to)}, ${esc(firstName(ME.name))}.</p><a class="btn primary big" href="#/">Abrir a Pauta</a>`);
    return;
  }
  let info;
  try { info = await api("GET", `/api/move/${encodeURIComponent(token)}`); }
  catch (e) {
    gate(`<h1>Link expirado</h1><p>${esc(e.message)}. Peça um link novo a quem administra a Pauta${ME.move ? `, ou abra a Pauta no endereço antigo e toque em "Mudar" de novo` : ""}.</p><a class="btn big" href="#/">Ir para o login</a>`);
    return;
  }
  const g = gate(ME.move ? `<h1>Olá, ${esc(firstName(info.name))}!</h1>
    <p>A Pauta agora mora em <b>${esc(info.to)}</b>. Crie sua passkey aqui para continuar: é a mesma conta, com tudo o que você já fez.</p>
    <button class="btn primary big" id="moveok">${icon("key")}Criar passkey em ${esc(info.to)}</button>
    <p class="fine">Depois, adicione este endereço à tela de início do celular de novo: o ícone antigo abre o endereço antigo.</p>`
    : `<h1>Olá, ${esc(firstName(info.name))}!</h1>
    <p>Crie uma passkey neste aparelho para entrar na Pauta: é a mesma conta, com tudo o que você já fez.</p>
    <button class="btn primary big" id="moveok">${icon("key")}Criar passkey neste aparelho</button>
    <p class="fine">Dica: adicione a Pauta à tela de início do celular para abrir com um toque.</p>`);
  $("#moveok", g).addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      ME = await passkeyRegister({ move: token });
      track("login", { ok: true, method: "link" });
      toast(`Pronto, ${firstName(ME.name)}! Você está em ${info.to}.`);
      location.hash = "#/";
      await enter();
    } catch (err) {
      track("login", { ok: false, method: "link" });
      if (err.name !== "NotAllowedError") toast(err.message, true);
    } finally { btn.disabled = false; }
  });
}

// ---------- passkeys --------------------------------------------------------------------------

const b64u = {
  toBuf: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
  fromBuf: (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
};
function creationOptions(o) {
  return { ...o, challenge: b64u.toBuf(o.challenge), user: { ...o.user, id: b64u.toBuf(o.user.id) },
    excludeCredentials: (o.excludeCredentials || []).map((c) => ({ ...c, id: b64u.toBuf(c.id) })) };
}
function requestOptions(o) {
  return { ...o, challenge: b64u.toBuf(o.challenge),
    allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: b64u.toBuf(c.id) })) };
}
function credentialJSON(c) {
  const r = c.response;
  const response = { clientDataJSON: b64u.fromBuf(r.clientDataJSON) };
  if (r.attestationObject) {
    response.attestationObject = b64u.fromBuf(r.attestationObject);
    response.transports = r.getTransports ? r.getTransports() : [];
  } else {
    response.authenticatorData = b64u.fromBuf(r.authenticatorData);
    response.signature = b64u.fromBuf(r.signature);
    if (r.userHandle) response.userHandle = b64u.fromBuf(r.userHandle);
  }
  return { id: c.id, rawId: b64u.fromBuf(c.rawId), type: c.type, response,
    clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {} };
}

async function passkeyLogin(btn) {
  btn.disabled = true;
  try {
    const { flow, options } = await api("POST", "/api/passkey/login/options", {});
    const cred = await navigator.credentials.get({ publicKey: requestOptions(options) });
    ME = await api("POST", "/api/passkey/login/verify", { flow, credential: credentialJSON(cred) });
    track("login", { ok: true, method: "passkey" });
    await enter();
  } catch (e) {
    track("login", { ok: false, method: "passkey" });
    if (e.name !== "NotAllowedError") toast(`Não deu para entrar: ${e.message}`, true);
  } finally { btn.disabled = false; }
}

async function passkeyRegister(body) {
  const { flow, options } = await api("POST", "/api/passkey/register/options", body);
  const cred = await navigator.credentials.create({ publicKey: creationOptions(options) });
  return api("POST", "/api/passkey/register/verify", { flow, credential: credentialJSON(cred) });
}

async function addPasskey() {
  try {
    await passkeyRegister({});
    toast("Passkey adicionada neste aparelho");
    return true;
  } catch (e) {
    if (e.name === "InvalidStateError") toast("Este aparelho já tem uma passkey sua.");
    else if (e.name !== "NotAllowedError") toast(e.message, true);
    return false;
  }
}

async function logout() {
  await api("POST", "/api/logout", {});
  ME = await api("GET", "/api/me");
  location.hash = "#/";
  showGate();
}

// ---------- gate: login and join ----------------------------------------------------------------

function gate(html) {
  $("#shell").hidden = true;
  const g = $("#gate");
  g.hidden = false;
  g.innerHTML = `<div class="gate-card fadein"><span class="logo"></span>${html}</div>`;
  return g;
}

function showGate() {
  const g = gate(`<h1>pauta</h1><p>Os pedidos do time, num lugar só.</p>
    <button class="btn primary big" id="login">${icon("key")}Entrar com passkey</button>
    <p class="fine">Ainda não tem acesso? Peça um convite a quem administra a Pauta.</p>
    ${ME.move && !ME.move.here ? `<p class="fine">A Pauta mudou para <a href="${esc(ME.move.url)}/">${esc(ME.move.to)}</a>. Entre aqui para levar sua conta, ou direto lá se você já mudou.</p>` : ""}`);
  $("#login", g).addEventListener("click", (e) => passkeyLogin(e.currentTarget));
}

async function showJoin(token) {
  if (ME.logged_in && ME.auth) {
    gate(`<h1>Você já entrou</h1><p>Você já tem uma conta aqui, ${esc(firstName(ME.name))}.</p><a class="btn primary big" href="#/">Abrir a Pauta</a>`);
    return;
  }
  let info;
  try { info = await api("GET", `/api/invite/${encodeURIComponent(token)}`); }
  catch (e) {
    gate(`<h1>Convite inválido</h1><p>${esc(e.message)}</p><a class="btn big" href="#/">Ir para o login</a>`);
    return;
  }
  const g = gate(`<h1>Bem-vindo à pauta</h1>
    <p>${info.invited_by ? `${esc(firstName(info.invited_by))} convidou você` : "Você foi convidado"} para organizar os pedidos do time${info.admin ? ", como administrador" : ""}.</p>
    <form id="join"><div class="field"><label>Seu nome</label><input class="input" name="name" required autocomplete="name" placeholder="Como o time te chama"></div>
    <button class="btn primary big">${icon("key")}Criar passkey e entrar</button></form>
    <p class="fine">A passkey usa o Face ID, a digital ou o PIN deste aparelho. Não tem senha para lembrar, e ninguém consegue entrar no seu lugar.</p>`);
  $("#join", g).name.focus();
  $("#join", g).addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = $("button", e.target);
    btn.disabled = true;
    try {
      ME = await passkeyRegister({ invite: token, name: e.target.name.value });
      track("login", { ok: true, method: "link" });
      toast(`Bem-vindo, ${firstName(ME.name)}!`);
      location.hash = "#/";
      await enter();
    } catch (err) {
      track("login", { ok: false, method: "link" });
      if (err.name !== "NotAllowedError") toast(err.message, true);
    } finally { btn.disabled = false; }
  });
}
