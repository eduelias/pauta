"use strict";
// Pauta: one small single-page app. Routes are #/..., data comes from /api, nothing else.

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const app = $("#app");
let ME = null;        // /api/me
let BOOT = null;      // {me, options, members, avatars, files, finance, meta}
let REQS = null;      // last /api/requests, for the nav counter

// ---------- small helpers ---------------------------------------------------------------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// Every navigation gets a number. A screen's GET that answers after the user has already
// moved on is dropped (Stale) instead of drawing the old screen over the new one.
let NAV_SEQ = 0, LOADING = 0;
class Stale extends Error {}

async function api(method, path, body) {
  const nav = LOADING && method === "GET" ? NAV_SEQ : null;
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const doc = await res.json().catch(() => ({}));
  if (res.status === 401 && ME?.auth && !path.startsWith("/api/passkey")) {
    ME.logged_in = false;
    showGate();
  }
  if (nav !== null && nav !== NAV_SEQ) throw new Stale(path);
  if (!res.ok) throw new Error(doc.error || res.statusText);
  return doc;
}

let toastTimer;
function toast(msg, err = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (err ? " err" : "");
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, err ? 4200 : 2200);
}

const ICONS = {
  dash: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  board: '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M8 7v7M12 7v4M16 7v9"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  clients: '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2M10 6h4M10 10h4M10 14h4M10 18h4"/>',
  team: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  cal: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
  msg: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  key: '<circle cx="7.5" cy="15.5" r="5.5"/><path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5M21 12H9"/>',
  at: '<circle cx="12" cy="12" r="4"/><path d="M16 8v5a3 3 0 0 0 6 0v-1a10 10 0 1 0-4 8"/>',
  phone: '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
  folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/>',
  hash: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1"/>',
  edit: '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5M12 15V3"/>',
  send: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
  swap: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  target: '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
  pin: '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="3"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  trash: '<path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  ext: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  wa: '<path d="M3 21l1.65-3.8a9 9 0 1 1 3.4 2.9L3 21"/><path d="M9 10a.5.5 0 0 0 1 0V9a.5.5 0 0 0-1 0v1a5 5 0 0 0 5 5h1a.5.5 0 0 0 0-1h-1a.5.5 0 0 0 0 1"/>',
  clip: '<path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5M12 3v12"/>',
  cloud: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
  money: '<rect x="2" y="6" width="20" height="12" rx="2"/><circle cx="12" cy="12" r="3"/><path d="M6 12h.01M18 12h.01"/>',
  sparkle: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
};
const icon = (name, cls = "") => `<svg class="i ${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;

function hue(s) {
  let h = 0;
  for (const c of String(s)) h = (h * 31 + c.codePointAt(0)) % 360;
  return h;
}
function initials(name) {
  const parts = String(name || "?").replace(/[^\p{L}\p{N} ]/gu, " ").trim().split(/\s+/);
  return ((parts[0]?.[0] || "?") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}
// people may have a Gravatar: d=blank returns a transparent image when there is none,
// so the initials underneath show through without any error handling
const avatar = (name, cls = "", grav = "") => `<span class="avatar ${cls}" style="--h:${hue(name)}">${esc(initials(name))}${
  /^[0-9a-f]{64}$/.test(grav || "") ? `<img src="https://gravatar.com/avatar/${grav}?s=112&d=blank" alt="" loading="lazy">` : ""}</span>`;
const personAvatar = (id, name, cls = "round") => avatar(name, cls, BOOT?.avatars?.[id]);
const firstName = (n) => String(n || "").split(" ")[0];

// dates: requests carry plain YYYY-MM-DD; timestamps are UTC "YYYY-MM-DD HH:MM:SS"
function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + n);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const daysUntil = (iso) => Math.round((Date.parse(iso + "T00:00:00Z") - Date.parse(todayISO() + "T00:00:00Z")) / 86400000);
const fmtDate = (iso, opts = { day: "numeric", month: "short" }) => iso ? new Date(iso + "T12:00:00").toLocaleDateString("pt-BR", opts).replace(".", "") : "";
const stamp = (s) => new Date(String(s).replace(" ", "T") + "Z");
function ago(s) {
  const sec = (Date.now() - stamp(s)) / 1000;
  if (sec < 60) return "agora";
  if (sec < 3600) return `há ${Math.floor(sec / 60)} min`;
  if (sec < 86400) return `há ${Math.floor(sec / 3600)} h`;
  const d = Math.floor(sec / 86400);
  if (d < 7) return d === 1 ? "ontem" : `há ${d} dias`;
  return stamp(s).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", "");
}
const money = (n, cur) => n == null || n === "" ? "" : Number(n).toLocaleString("pt-BR", { style: "currency", currency: cur || BOOT?.finance?.currency || "BRL", maximumFractionDigits: Number(n) % 1 ? 2 : 0 });

const isOpen = (r) => ["todo", "doing", "waiting"].includes(r.status);
const isLate = (r) => isOpen(r) && r.due && daysUntil(r.due) < 0;
const STATUS = () => BOOT.options.status;
function statusLabel(r) {
  if (r.status === "waiting") return r.created_by_name ? `Aguardando ${firstName(r.created_by_name)}` : "Aguardando retorno";
  return STATUS()[r.status];
}
const statusBadge = (r) => `<span class="status ${r.status}">${esc(statusLabel(r))}</span>`;
function dueBadge(r) {
  if (!r.due) return "";
  if (!isOpen(r)) return `<span class="due faint">${icon("cal")}${esc(fmtDate(r.due))}</span>`;
  const d = daysUntil(r.due);
  let txt, cls = "";
  if (d < 0) { txt = d === -1 ? "1 dia atrasado" : `${-d} dias atrasado`; cls = "late"; }
  else if (d === 0) { txt = "Hoje"; cls = "soon"; }
  else if (d === 1) { txt = "Amanhã"; cls = "soon"; }
  else if (d < 7) txt = fmtDate(r.due, { weekday: "short" });
  else txt = fmtDate(r.due);
  return `<span class="due ${cls}">${icon("cal")}${esc(txt)}</span>`;
}
const prio = (p) => p && p !== "Baixa" ? `<span class="prio ${esc(p)}">${esc(p)}</span>` : "";

function safeUrl(u) {
  return /^https?:\/\//i.test(u || "") ? u : "";
}
function igUrl(h) {
  if (!h) return "";
  if (/^https?:\/\//i.test(h)) return h;
  const m = h.replace(/^@/, "").match(/^[A-Za-z0-9._]+$/);
  return m ? `https://instagram.com/${m[0]}` : "";
}
function waUrl(n) {
  let d = String(n || "").replace(/\D/g, "");
  if (!d) return "";
  if (d.length <= 11) d = "55" + d;
  return `https://wa.me/${d}`;
}

function sortOpen(a, b) {
  const da = a.due || "9999", db = b.due || "9999";
  if (da !== db) return da < db ? -1 : 1;
  const p = { Alta: 0, "Média": 1, Baixa: 2 };
  return (p[a.priority] ?? 1) - (p[b.priority] ?? 1) || a.id - b.id;
}

const spinner = () => `<div class="loading"><div class="spinner"></div></div>`;

// ---------- request card (board, dashboard, client page) --------------------------------

function rcard(r, { client = true, drag = false } = {}) {
  return `<a class="rcard" href="#/pedido/${r.id}" data-id="${r.id}" ${drag ? 'draggable="true"' : ""}>
    <div class="top">${client ? `${avatar(r.client_name)}<span class="cname">${esc(r.client_name)}</span>` : `<span class="tag">${esc(r.kind || "Pedido")}</span>`}<span class="num">#${r.id}</span></div>
    ${client && r.kind ? `<div class="row-gap" style="margin-bottom:6px"><span class="tag">${esc(r.kind)}</span></div>` : ""}
    <div class="what">${esc(r.what)}</div>
    ${r.status === "waiting" && r.missing ? `<div class="missing">${esc(r.missing)}</div>` : ""}
    <div class="meta">${dueBadge(r)}${prio(r.priority)}${r.budget != null ? `<span>${esc(money(r.budget))}</span>` : ""}
      ${r.comments ? `<span>${icon("msg")} ${r.comments}</span>` : ""}
      ${!client ? statusBadge(r) : ""}</div>
  </a>`;
}

// ---------- shell: nav, tab bar, account menu --------------------------------------------

const NAV = [
  ["#/", "dash", "Painel"],
  ["#/quadro", "board", "Quadro"],
  ["#/pedidos", "list", "Pedidos"],
  ["#/clientes", "clients", "Clientes"],
  ["#/equipe", "team", "Equipe"],
];

const FIN_NAV = ["#/financeiro", "money", "Financeiro"];
const finVisible = () => Boolean(BOOT?.finance?.visible);

function renderShell() {
  const open = REQS ? REQS.filter(isOpen).length : null;
  // Financeiro sits after Clientes; on the phone it takes Quadro's slot (decision 7)
  const nav = NAV.flatMap((e) => (e[0] === "#/equipe" && finVisible() ? [FIN_NAV, e] : [e]));
  $("#nav").innerHTML = `<a href="#/novo" class="btn primary newbtn">${icon("plus")}Novo pedido</a>` +
    nav.map(([h, i, t]) => `<a href="${h}" data-nav="${h}">${icon(i)}${t}${h === "#/pedidos" && open ? `<span class="count">${open}</span>` : ""}</a>`).join("");
  $("#tabbar").innerHTML = [
    ["#/", "dash", "Painel"], ["#/pedidos", "list", "Pedidos"], ["#/novo", "plus", "Novo"],
    finVisible() ? FIN_NAV : ["#/quadro", "board", "Quadro"], ["#/clientes", "clients", "Clientes"],
  ].map(([h, i, t]) => `<a href="${h}" data-nav="${h}">${icon(i)}${t}</a>`).join("");
  $("#sidefoot").innerHTML = `<button class="me-chip" id="mechip">${avatar(ME.name, "md round", ME.avatar)}<div><b>${esc(ME.name)}</b><span>${ME.is_admin ? "Administrador" : "Membro"}</span></div></button>`;
  const top = $("#topnew");
  top.outerHTML = `<a href="#/equipe" id="topnew" aria-label="Equipe e conta">${avatar(ME.name, "md round", ME.avatar)}</a>`;
  $("#mechip").addEventListener("click", (e) => { e.stopPropagation(); toggleMenu(); });
  // the live release, small, next to the name (sidebar and phone top bar)
  $$(".brand").forEach((b) => {
    b.querySelector(".ver")?.remove();
    if (BOOT?.version) b.insertAdjacentHTML("beforeend", `<span class="ver" title="Versão ${esc(BOOT.version)}">v${esc(BOOT.version)}</span>`);
  });
  markNav();
}

function markNav() {
  const h = location.hash || "#/";
  const base = "#/" + (h.slice(2).split(/[/?]/)[0] || "");
  const map = { "#/pedido": "#/pedidos", "#/cliente": "#/clientes", "#/": "#/" };
  const want = map[base] || base;
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === want));
}

function toggleMenu() {
  const old = $(".menu");
  if (old) { old.remove(); return; }
  const m = document.createElement("div");
  m.className = "menu";
  m.innerHTML = `<a href="#/equipe">${icon("user")}Minha conta e equipe</a>
    ${ME.auth ? `<button data-act="addkey">${icon("key")}Adicionar passkey neste aparelho</button>
    <button data-act="logout">${icon("logout")}Sair</button>` : ""}`;
  $(".side").appendChild(m);
  m.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "logout") logout();
    if (act === "addkey") addPasskey();
    m.remove();
  });
  setTimeout(() => document.addEventListener("click", () => m.remove(), { once: true }));
}

// ---------- router ------------------------------------------------------------------------

const ROUTES = [
  [/^\/?$/, viewDash],
  [/^\/quadro$/, viewBoard],
  [/^\/pedidos$/, viewList],
  [/^\/pedido\/(\d+)$/, viewRequest],
  [/^\/novo(?:\/(\d+))?$/, viewNew],
  [/^\/clientes$/, viewClients],
  [/^\/cliente\/novo$/, viewNewClient],
  [/^\/cliente\/(\d+)$/, viewClient],
  [/^\/financeiro$/, viewFinance],
  [/^\/equipe$/, viewTeam],
];

function hashParts() {
  const raw = (location.hash || "#/").slice(1);
  const [path, query] = raw.split("?");
  return { path: path || "/", query: new URLSearchParams(query || "") };
}

async function route() {
  const { path, query } = hashParts();
  if (path.startsWith("/entrar/")) return showJoin(path.slice(8));
  if (path.startsWith("/mudar/")) return showMove(path.slice(7));
  if (ME.auth && !ME.logged_in) return showGate();
  // signed in without the boot data, e.g. the page was opened on an invite link: load it first
  if (!BOOT) return enter();
  $("#gate").hidden = true;
  $("#shell").hidden = false;
  $(".menu")?.remove();
  markNav();
  for (const [re, view] of ROUTES) {
    const m = path.match(re);
    if (m) {
      const seq = ++NAV_SEQ;
      app.innerHTML = spinner();
      LOADING++;
      try {
        await view(query, ...m.slice(1));
        app.firstElementChild?.classList.add("fadein");
        addMoveBar();
      } catch (e) {
        if (e instanceof Stale || seq !== NAV_SEQ) return;  // a newer screen owns #app now
        app.innerHTML = `<div class="empty"><span class="big">😕</span>${esc(e.message)}</div>`;
      } finally { LOADING--; }
      if (seq === NAV_SEQ) window.scrollTo(0, 0);
      return;
    }
  }
  location.hash = "#/";
}

async function loadReqs() {
  REQS = await api("GET", "/api/requests");
  renderShell();
  return REQS;
}

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
        <div class="panel-head"><h2>Para fazer agora</h2><a class="btn ghost small" href="#/quadro">Ver quadro</a></div>
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
  $("#q").addEventListener("input", (e) => { q = e.target.value; draw(); });
  $("#cl").addEventListener("change", (e) => { client = e.target.value; draw(); });
  $("#filters").addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]");
    if (!b) return;
    f = b.dataset.f;
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
  const who = (e) => `<b>${esc(e.account_name || (ME.auth ? "Alguém" : "Você"))}</b>`;
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
      ? `Conecte o OneDrive em <a href="#/equipe">Equipe</a> para anexar arquivos aos pedidos.`
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
      if (x.status >= 200 && x.status < 300) resolve(doc);
      else reject(new Error(doc.error || `erro ${x.status}`));
    });
    x.addEventListener("error", () => reject(new Error("a conexão caiu; tente de novo")));
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
      if (!file.size) { toast(`${file.name} está vazio`, true); continue; }
      if (file.size > max) { toast(`${file.name} passa de ${BOOT.files.max_mb} MB`, true); continue; }
      const row = document.createElement("div");
      row.className = "upl";
      row.innerHTML = `<span>${esc(file.name)}</span><progress max="1" value="0"></progress>`;
      $("#uploads").append(row);
      try {
        set(await sendFile(get().id, file, (f) => { $("progress", row).value = f; }));
        redraw();
        toast(`${file.name} enviado`);
      } catch (e) { toast(`${file.name}: ${e.message}`, true); }
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
    } catch (e) { toast(e.message, true); }
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
    save({ [f]: b.dataset.v });
  }));
  const autosize = (t) => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
  $$("textarea.input").forEach((t) => { autosize(t); t.addEventListener("input", () => autosize(t)); });
  const send = async () => {
    const t = $("#comment");
    if (!t.value.trim()) return;
    try {
      r = await api("POST", `/api/requests/${r.id}/comments`, { text: t.value });
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
      try { done(await api("POST", "/api/clients", Object.fromEntries(new FormData(e.target)))); }
      catch (err) { toast(err.message, true); }
    });
  });
}

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

// ---------- financeiro (decision 7) ---------------------------------------------------------

const FIN_LABEL = {
  late: "Em atraso", due: "Vencendo", due_soon: "Vence em breve",
  awaiting_first: "Aguardando 1º pagamento", paid: "Em dia",
};
const FIN_ORDER = ["late", "due", "due_soon", "awaiting_first", "paid"];
const CADENCE_UNIT = { monthly: ["mês", "meses", "º"], weekly: ["semana", "semanas", "ª"], yearly: ["ano", "anos", "º"] };
const PAY_METHODS = ["Pix", "Cartão", "Transferência", "Dinheiro", "Outro"];

// "4º mês" / "2ª semana": the current period of the cycle
function activeLabel(b, cadence) {
  if (!b || !b.months_active) return "";
  const [unit, , ord] = CADENCE_UNIT[cadence || BOOT.finance.cadence] || CADENCE_UNIT.monthly;
  return `${b.months_active}${ord} ${unit}`;
}
const finBadge = (st) => `<span class="fstatus ${esc(st)}">${esc(FIN_LABEL[st] || st)}</span>`;
function dueLine(b) {
  if (!b || !b.next_due) return "";
  const d = daysUntil(b.next_due);
  const when = d === 0 ? "hoje" : d === 1 ? "amanhã" : d === -1 ? "ontem" : d < 0 ? `há ${-d} dias` : fmtDate(b.next_due);
  const verb = b.status === "late" ? "venceu" : "vence";
  return `<span class="due ${b.status === "late" ? "late" : b.status === "due" || b.status === "due_soon" ? "soon" : "faint"}">${icon("cal")}${verb} ${esc(when)}</span>`;
}

// The tiles are filters: one at a time, click again to clear. "received" shows the month's
// payments with a month picker instead of the client groups.
const FIN_FILTER = { late: ["late"], week: ["due", "due_soon"], awaiting_first: ["awaiting_first"], paid: ["paid"] };
const finState = { filter: null, month: null };
const monthName = (m, year = false) => new Date(m + "-15T12:00:00").toLocaleDateString("pt-BR", year ? { month: "long", year: "numeric" } : { month: "long" });

async function viewFinance() {
  if (!finVisible()) { location.hash = "#/"; return; }
  const f = await api("GET", `/api/finance${finState.month ? `?month=${finState.month}` : ""}`);
  finState.month = f.month;
  const cur = f.currency;
  const on = finState.filter;
  const stat = (key, n, t, c, hot) => `<button type="button" class="stat ${hot ? "hot" : ""} ${on === key ? "on" : ""}" data-filter="${key}" style="--c:${c}" aria-pressed="${on === key}"><div class="n">${n}</div><div class="t">${t}</div></button>`;
  const week = f.counts.due + f.counts.due_soon;
  const group = (st) => {
    const rows = f.clients.filter((c) => c.status === st);
    if (!rows.length) return "";
    return `<section class="panel"><div class="panel-head"><h2>${finBadge(st)}</h2><span class="muted small">${rows.length}</span></div>
      <div class="finrows">${rows.map((c) => `<div class="finrow" data-id="${c.id}">
        ${avatar(c.name)}<div class="who"><a href="#/cliente/${c.id}"><b>${esc(c.name)}</b></a>
          <span>${esc(activeLabel(c, f.cadence))}${c.segment ? ` · ${esc(c.segment)}` : ""}${c.owed ? ` · deve ${esc(money(c.owed, cur))}` : ""}</span></div>
        <div class="when">${dueLine(c)}<span class="muted small">${c.last_payment ? `último ${esc(fmtDate(c.last_payment.paid_on))} · ${esc(money(c.last_payment.amount, cur))}` : "nenhum pagamento"}</span></div>
        <button class="btn small" data-pay="${c.id}" data-name="${esc(c.name)}" data-amount="${c.amount}">${icon("plus")}Registrar</button>
      </div>`).join("")}</div></section>`;
  };
  const clear = `<button type="button" class="btn ghost small" id="finclear">Mostrar todos</button>`;
  let body;
  if (on === "received") {
    body = `<section class="panel" id="finmonthpanel"><div class="panel-head"><h2>Recebimentos</h2>
        <select class="input" id="finmonth" aria-label="Mês">${f.months.map((m) => `<option value="${m.month}" ${m.month === f.month ? "selected" : ""}>${esc(monthName(m.month, true))}${m.payments ? ` · ${esc(money(m.received, cur))}` : ""}</option>`).join("")}</select></div>
      ${f.payments.length ? `<div class="paylist">${f.payments.map((p) => `<div class="pay">
          <span class="d">${esc(fmtDate(p.paid_on, { day: "2-digit", month: "2-digit", year: "2-digit" }))}</span>
          <span class="v">${esc(money(p.amount, cur))}</span>
          <span class="m"><a href="#/cliente/${p.client}">${esc(p.name)}</a><span class="muted small"> · ${esc(p.method || "")}${p.note ? ` · ${esc(p.note)}` : ""}</span></span>
        </div>`).join("")}</div>
        <div class="paytotal"><span class="muted small">${f.payments.length} ${f.payments.length === 1 ? "pagamento" : "pagamentos"} em ${esc(monthName(f.month))}</span><b>${esc(money(f.received_month, cur))}</b></div>`
        : `<p class="muted small mt">Nenhum pagamento em ${esc(monthName(f.month, true))}.</p>`}
    </section>`;
  } else if (!f.clients.length) {
    body = `<div class="panel empty"><span class="big">💸</span>Nenhum cliente ativo cobrado. Os clientes <b>Ativos</b> aparecem aqui; pausados e encerrados não.</div>`;
  } else {
    const shown = on ? FIN_ORDER.filter((st) => FIN_FILTER[on].includes(st)) : FIN_ORDER;
    body = shown.map(group).join("") || `<div class="panel empty"><span class="big">✨</span>Nenhum cliente aqui. ${clear}</div>`;
  }
  app.innerHTML = `<div>
    <div class="head"><div><h1>Financeiro</h1><p>${f.clients.length} ${f.clients.length === 1 ? "cliente cobrado" : "clientes cobrados"} · ${esc(money(f.received_total, cur))} recebidos no total.</p></div>${on ? clear : ""}</div>
    <div class="stats fin">
      ${stat("received", esc(money(f.received_month, cur)), `Recebido em ${esc(monthName(f.month))}`, "var(--s-done)")}
      ${stat("late", f.counts.late, `Em atraso${f.owed ? ` · ${esc(money(f.owed, cur))}` : ""}`, "var(--danger)", f.counts.late > 0)}
      ${stat("week", week, "Vencem esta semana", "var(--s-waiting)")}
      ${stat("awaiting_first", f.counts.awaiting_first, "Aguardando 1º pagamento", "var(--s-todo)")}
      ${stat("paid", f.counts.paid, "Em dia", "var(--accent)")}
    </div>
    ${body}
  </div>`;
  $$("[data-filter]").forEach((b) => b.addEventListener("click", () => {
    finState.filter = finState.filter === b.dataset.filter ? null : b.dataset.filter;
    viewFinance();
  }));
  $$("#finclear").forEach((b) => b.addEventListener("click", () => { finState.filter = null; viewFinance(); }));
  const sel = $("#finmonth");
  if (sel) sel.addEventListener("change", () => { finState.month = sel.value; viewFinance(); });
  $$("[data-pay]").forEach((b) => b.addEventListener("click", () => payModal(
    { id: Number(b.dataset.pay), name: b.dataset.name }, Number(b.dataset.amount), cur, viewFinance)));
}

// Registrar pagamento: the date defaults to today and the amount to the client's fee
function payModal(c, amount, cur, done) {
  const m = $("#modal");
  m.innerHTML = `<form class="panel" id="payf"><h2>Pagamento de ${esc(c.name)}</h2>
    <div class="form-grid">
      <div class="field"><label>Data</label><input class="input" type="date" name="paid_on" required value="${todayISO()}" max="${todayISO()}"></div>
      <div class="field"><label>Valor (${esc(cur)})</label><input class="input" name="amount" inputmode="decimal" required value="${esc(String(amount ?? ""))}"></div>
      <div class="field"><label>Forma</label><select class="input" name="method">${PAY_METHODS.map((v) => `<option>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Observação <span class="muted">(opcional)</span></label><input class="input" name="note" maxlength="200"></div>
    </div>
    <div class="actions"><button type="button" class="btn ghost" data-a="cancel">Cancelar</button><button class="btn primary">${icon("check")}Registrar</button></div></form>`;
  m.hidden = false;
  const f = $("#payf");
  const close = () => { m.hidden = true; m.innerHTML = ""; };
  m.onclick = (e) => { if (e.target === m || e.target.dataset.a === "cancel") close(); };
  f.amount.focus();
  f.amount.select();
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const go = $("button.primary", f);
    go.disabled = true;
    try {
      const fresh = await api("POST", `/api/clients/${c.id}/payments`, Object.fromEntries(new FormData(f)));
      close();
      toast("Pagamento registrado");
      done(fresh);
    } catch (err) { toast(err.message, true); go.disabled = false; }
  });
}

// The Pagamentos card on the client page: the fee, where the client stands, the ledger.
function payBox(c) {
  if (!finVisible()) return "";
  const b = c.billing, cur = b?.currency || BOOT.finance.currency;
  const live = (c.payments || []).filter((p) => !p.voided_at);
  const total = live.reduce((n, p) => n + p.amount, 0);
  const canVoid = (p) => ME.is_admin || (ME.account && p.recorded_by === ME.account);
  const head = `<div class="panel-head"><h3>${icon("money")}Pagamentos</h3>${b && b.months_active ? `<span class="tag accent">${esc(activeLabel(b))}</span>` : ""}</div>`;
  let standing;
  if (b) {
    standing = `<div class="paystand">${finBadge(b.status)}${dueLine(b)}</div>
      <div class="payfee"><label>Valor por ${esc((CADENCE_UNIT[BOOT.finance.cadence] || CADENCE_UNIT.monthly)[0])}</label>
        <input class="input" id="payfee" inputmode="decimal" value="${esc(String(b.amount))}"> <span class="muted small">${esc(cur)}</span></div>
      <button class="btn primary" id="paynew" style="width:100%">${icon("plus")}Registrar pagamento</button>`;
  } else if (!c.billed) {
    standing = `<p class="muted small">Este cliente não é cobrado.</p>`;
  } else {
    standing = `<p class="muted small">Sem cobrança enquanto ${esc(c.state.toLowerCase())}. Ao voltar a Ativo, a contagem recomeça no próximo pagamento.</p>`;
  }
  const billedToggle = c.state === "Ativo" ? `<label class="toggle small mt"><input type="checkbox" id="paybilled" ${c.billed ? "checked" : ""}>Cobrado</label>` : "";
  const list = (c.payments || []).length ? `<div class="paylist">${c.payments.map((p) => `<div class="pay ${p.voided_at ? "void" : ""}" title="${p.voided_at ? `Anulado por ${esc(p.voided_by_name || "")}` : `Registrado por ${esc(p.recorded_by_name || "")}`}">
      <span class="d">${esc(fmtDate(p.paid_on, { day: "2-digit", month: "2-digit", year: "2-digit" }))}</span>
      <span class="v">${esc(money(p.amount, cur))}</span>
      <span class="m muted small">${esc(p.method || "")}${p.note ? ` · ${esc(p.note)}` : ""}</span>
      ${!p.voided_at && canVoid(p) ? `<button class="copy" data-void="${p.id}" title="Anular este pagamento">Anular</button>` : ""}
    </div>`).join("")}</div>
    <div class="paytotal"><span class="muted small">${live.length} ${live.length === 1 ? "pagamento" : "pagamentos"}</span><b>${esc(money(total, cur))}</b></div>` : `<p class="muted small mt">Nenhum pagamento registrado.</p>`;
  return `<div class="panel mt paybox">${head}${standing}${billedToggle}${list}</div>`;
}

function bindPayBox(c, done) {
  const box = $("#paybox");
  if (!box || !finVisible()) return;
  const cur = c.billing?.currency || BOOT.finance.currency;
  $("#paynew", box)?.addEventListener("click", () => payModal(c, c.billing?.amount, cur, done));
  $("#payfee", box)?.addEventListener("change", async (e) => {
    try { done(await api("PATCH", `/api/clients/${c.id}/billing`, { amount: e.target.value })); toast("Salvo"); }
    catch (err) { toast(err.message, true); }
  });
  $("#paybilled", box)?.addEventListener("change", async (e) => {
    try { done(await api("PATCH", `/api/clients/${c.id}/billing`, { billed: e.target.checked })); toast("Salvo"); }
    catch (err) { toast(err.message, true); }
  });
  $$("[data-void]", box).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Anular este pagamento? Ele continua na lista, riscado.")) return;
    try { done(await api("DELETE", `/api/payments/${b.dataset.void}`)); toast("Pagamento anulado"); }
    catch (err) { toast(err.message, true); }
  }));
}

// Equipe → Financeiro: the team's conventions (admins)
function financeSettingsPanel(fin) {
  const opt = (values, labels, cur) => values.map((v) => `<option value="${v}" ${v === cur ? "selected" : ""}>${labels[v]}</option>`).join("");
  return `<section class="panel mt" id="finsettings"><div class="panel-head"><h2>${icon("money")}Financeiro</h2><span class="muted small">Como o time cobra</span></div>
    <div class="form-grid">
      <div class="field wide"><label class="toggle"><input type="checkbox" data-fin="enabled" ${fin.enabled ? "checked" : ""}>Usar o Financeiro</label></div>
      <div class="field"><label>Valor padrão por cliente</label><input class="input" data-fin="amount" inputmode="decimal" value="${esc(String(fin.amount))}"></div>
      <div class="field"><label>Moeda</label><select class="input" data-fin="currency">${opt(["BRL", "USD", "EUR"], { BRL: "Real (R$)", USD: "Dólar (US$)", EUR: "Euro (€)" }, fin.currency)}</select></div>
      <div class="field"><label>Cobrança</label><select class="input" data-fin="cadence">${opt(["monthly", "weekly", "yearly"], { monthly: "Mensal", weekly: "Semanal", yearly: "Anual" }, fin.cadence)}</select></div>
      <div class="field"><label>O mês do cliente começa</label><select class="input" data-fin="anchor">${opt(["first_payment", "client_since", "fixed_day"], { first_payment: "No primeiro pagamento", client_since: "Na data “cliente desde”", fixed_day: "Num dia fixo do mês" }, fin.anchor)}</select></div>
      <div class="field"><label>Dia fixo <span class="muted">(se for o caso)</span></label><input class="input" data-fin="fixed_day" type="number" min="1" max="28" value="${fin.fixed_day}"></div>
      <div class="field"><label>Avisar com antecedência (dias)</label><input class="input" data-fin="due_soon_days" type="number" min="0" max="60" value="${fin.due_soon_days}"></div>
      <div class="field"><label>Tolerância antes de atrasar (dias)</label><input class="input" data-fin="grace_days" type="number" min="0" max="60" value="${fin.grace_days}"></div>
      <div class="field"><label>Quem vê o financeiro</label><select class="input" data-fin="visibility">${opt(["all", "admins"], { all: "Todo o time", admins: "Só administradores" }, fin.visibility)}</select></div>
      <div class="field wide"><label class="toggle"><input type="checkbox" data-fin="bill_new_clients" ${fin.bill_new_clients ? "checked" : ""}>Cobrar clientes novos por padrão</label></div>
    </div>
    <p class="muted small mt">Clientes <b>Ativos</b> entram no painel; pausados e encerrados saem, e ao voltar a contagem recomeça. Pagamentos nunca são apagados, só anulados.</p>
    <div class="mt"><button class="btn" id="savefin">${icon("check")}Salvar financeiro</button></div></section>`;
}

// ---------- team, account, settings ---------------------------------------------------------

async function viewTeam(query) {
  const members = await api("GET", "/api/members");
  const o = BOOT.options;
  app.innerHTML = `<div style="max-width:980px">
    <div class="head"><div><h1>Equipe</h1><p>Quem usa a Pauta, convites e listas.</p></div>
      ${ME.is_admin ? `<div class="actions"><button class="btn" id="export">${icon("download")}Exportar dados</button></div>` : ""}</div>
    <div class="grid2">
      <section class="panel">
        <div class="panel-head"><h2>Você</h2></div>
        <div class="member">${avatar(ME.name, "md round", ME.avatar)}<div class="who"><b>${esc(ME.name)}${ME.is_admin ? ` <span class="tag accent">${icon("shield")}Admin</span>` : ""}</b>
          <span>${ME.auth ? "Entra com passkey: Face ID, digital ou PIN do aparelho." : "Modo local, sem contas."}</span></div></div>
        ${ME.auth ? `<div class="field mt"><label>Seu nome</label><input class="input" id="myname" value="${esc(ME.name)}"></div>
        <div class="field mt"><label>E-mail <span class="muted">(opcional)</span></label><input class="input" id="myemail" type="email" inputmode="email" autocomplete="email" placeholder="voce@exemplo.com" value="${esc(ME.email || "")}">
          <span class="muted small">Só para mostrar sua foto do <a href="https://gravatar.com" target="_blank" rel="noopener">Gravatar</a>. O endereço não aparece para o time, mas quem já souber seu e-mail consegue confirmar que é ele.</span></div>
        <div class="mt"><button class="btn" id="rename">${icon("check")}Salvar</button></div>
        <div class="row-gap mt"><button class="btn" id="addkey">${icon("key")}Adicionar passkey neste aparelho</button><button class="btn ghost" id="logout">${icon("logout")}Sair em todos os aparelhos</button></div>` : ""}
      </section>
      <section class="panel">
        <div class="panel-head"><h2>Time</h2><span class="muted small">${members.filter((m) => !m.disabled).length} pessoas</span></div>
        ${members.length ? members.map((m) => `<div class="member ${m.disabled ? "off" : ""}">${avatar(m.name, "md round", m.avatar)}
          <div class="who"><b>${esc(m.name)}${m.is_admin ? ` <span class="tag accent">Admin</span>` : ""}${m.disabled ? ` <span class="tag">Desativado</span>` : ""}</b>
          <span>${m.passkeys} passkey${m.passkeys === 1 ? "" : "s"}${m.last_seen ? ` · visto ${esc(ago(m.last_seen))}` : ""}${ME.move && !m.disabled ? (m.domains.includes(ME.move.to) ? ` · já em ${esc(ME.move.to)}` : " · ainda não mudou") : ""}</span></div>
          ${ME.is_admin && m.id !== ME.account ? `<div class="row-gap">
            ${ME.move && !m.disabled && !m.domains.includes(ME.move.to) ? `<button class="btn small" data-mv="${m.id}" data-name="${esc(m.name)}">${icon("link")}Link para mudar</button>` : ""}
            <button class="btn ghost small" data-m="${m.id}" data-admin="${m.is_admin ? 0 : 1}">${m.is_admin ? "Tirar admin" : "Tornar admin"}</button>
            <button class="btn ghost small ${m.disabled ? "" : "danger"}" data-m="${m.id}" data-dis="${m.disabled ? 0 : 1}">${m.disabled ? "Reativar" : "Desativar"}</button></div>` : ""}
        </div><div id="mv-${m.id}"></div>`).join("") : `<div class="empty">Ninguém ainda.</div>`}
      </section>
    </div>
    ${ME.is_admin && ME.auth ? `<section class="panel mt">
      <div class="panel-head"><h2>Convidar alguém</h2></div>
      <p class="muted" style="margin-top:-6px">A pessoa abre o link (ou aponta a câmera para o QR), digita o nome e cria uma passkey. Sem senha, sem cadastro.</p>
      <div class="row-gap"><label class="toggle"><input type="checkbox" id="asadmin">Como administrador</label>
        <button class="btn primary" id="invite">${icon("plus")}Gerar convite</button></div>
      <div id="qrbox"></div></section>` : ""}
    ${ME.is_admin ? `<section class="panel mt" id="drive"><div class="panel-head"><h2>${icon("cloud")}OneDrive</h2><span class="muted small">Arquivos dos pedidos</span></div>
      <div id="drivebody">${spinner()}</div></section>` : ""}
    ${ME.is_admin && BOOT.meta?.enabled ? `<section class="panel mt" id="meta"><div class="panel-head"><h2>${icon("target")}Meta</h2><span class="muted small">Números das campanhas</span></div>
      <div id="metabody">${spinner()}</div></section>` : ""}
    ${ME.is_admin ? financeSettingsPanel(BOOT.finance) : ""}
    ${ME.is_admin ? `<section class="panel mt"><div class="panel-head"><h2>Listas</h2><span class="muted small">Um item por linha</span></div>
      <div class="grid3">${[["kind", "Tipos de pedido"], ["goal", "Objetivos"], ["segment", "Segmentos"]].map(([k, t]) => `<div class="field"><label>${t}</label>
        <textarea class="input" data-list="${k}" rows="9">${esc(o[k].join("\n"))}</textarea></div>`).join("")}</div>
      <div class="mt"><button class="btn" id="savelists">${icon("check")}Salvar listas</button></div></section>` : ""}
    <p class="muted small mt" id="version">Pauta ${esc(BOOT.version || "")}</p>
  </div>`;
  $("#logout")?.addEventListener("click", logout);
  $("#addkey")?.addEventListener("click", addPasskey);
  if (ME.is_admin) loadDrive();
  if (ME.is_admin && BOOT.meta?.enabled) loadMeta();
  const back = query?.get("meta");  // the way back from Meta's login (/api/meta/callback)
  if (back) {
    history.replaceState(null, "", "#/equipe");
    if (back === "conectado") toast("Meta conectada");
    else toast(META_ERRORS[query.get("motivo")] || "Não foi possível conectar à Meta; tente de novo", true);
  }
  $("#rename")?.addEventListener("click", async () => {
    try {
      ME = { ...ME, ...(await api("PATCH", "/api/me", { name: $("#myname").value, email: $("#myemail").value })) };
      BOOT = await api("GET", "/api/boot");
      renderShell();
      toast("Salvo");
      viewTeam();
    } catch (e) { toast(e.message, true); }
  });
  $$("[data-m]").forEach((b) => b.addEventListener("click", async () => {
    const body = b.dataset.admin !== undefined ? { is_admin: b.dataset.admin === "1" } : { disabled: b.dataset.dis === "1" };
    try { await api("PATCH", `/api/members/${b.dataset.m}`, body); viewTeam(); } catch (e) { toast(e.message, true); }
  }));
  $("#invite")?.addEventListener("click", makeInvite);
  $$("[data-mv]").forEach((b) => b.addEventListener("click", () => makeMoveLink(b.dataset.mv, b.dataset.name)));
  $("#savefin")?.addEventListener("click", async () => {
    const body = {};
    for (const el of $$("[data-fin]")) body[el.dataset.fin] = el.type === "checkbox" ? el.checked : el.value;
    try {
      await api("PATCH", "/api/finance/settings", body);
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
    try { loadDrive(await api("POST", "/api/onedrive/connect")); } catch (e) { toast(e.message, true); }
  });
  $("#drivecancel")?.addEventListener("click", async () => {
    loadDrive(await api("DELETE", "/api/onedrive"));
    await refreshBoot();
  });
  $("#driveoff")?.addEventListener("click", async () => {
    if (!confirm("Desconectar o OneDrive? Os arquivos continuam lá, mas a Pauta deixa de enviar e abrir arquivos até alguém reconectar.")) return;
    loadDrive(await api("DELETE", "/api/onedrive"));
    await refreshBoot();
    toast("OneDrive desconectado");
  });
  if (doc.state === "pending") DRIVE_TIMER = setTimeout(() => loadDrive(), Math.max(1000, (doc.pending?.interval || 5) * 1000));
  if (doc.state === "connected") { toast("OneDrive conectado"); await refreshBoot(); }
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
const centsMoney = (c, cur) => c == null ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: cur || "BRL" }).format(c / 100);
const count = (n) => new Intl.NumberFormat("pt-BR").format(n || 0);

async function loadMeta(refresh = false) {
  if (!$("#metabody")) return;
  let doc, clients = [], error = "";
  try { [doc, clients] = await Promise.all([api("GET", `/api/meta${refresh ? "?refresh=1" : ""}`), api("GET", "/api/clients")]); }
  catch (e) { error = e.message; }
  const box = $("#metabody");
  if (!box) return;  // left the page while waiting
  box.innerHTML = error
    ? `<p class="warnbox">${esc(error)}</p>
      <div class="row-gap mt"><button class="btn primary" data-metaconnect>${icon("target")}Conectar de novo</button>
        <button class="btn ghost danger" id="metaoff">Desconectar</button></div>`
    : metaBody(doc, clients);
  // the Cliente column: picking saves at once; a suggestion is only a suggestion until picked
  $$("select[data-link]").forEach((sel) => sel.addEventListener("change", async (e) => {
    const el = e.currentTarget, value = el.value;
    el.disabled = true;
    try {
      const row = await api("PATCH", `/api/meta/accounts/${el.dataset.link}`, { client: value ? Number(value) : null });
      toast(row.client ? `Conta vinculada a ${row.client.name}` : "Conta desvinculada");
      loadMeta();
    } catch (err) { toast(err.message, true); el.disabled = false; }
  }));
  // Conectar, Conectar de novo and Adicionar contas are the same trip through Meta's login
  $$("[data-metaconnect]").forEach((b) => b.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    if (btn.dataset.metaconnect === "add" && !confirm("Na Meta, marque todas as contas de anúncios que a Pauta deve ler: as que já estão aqui e as novas. Uma conta que ficar desmarcada pode sair da lista.")) return;
    btn.disabled = true;
    try { location.href = (await api("POST", "/api/meta/connect")).url; }
    catch (err) { toast(err.message, true); btn.disabled = false; }
  }));
  $("#metarefresh")?.addEventListener("click", (e) => { e.currentTarget.disabled = true; loadMeta(true); });
  $("#metaoff")?.addEventListener("click", async () => {
    if (!confirm("Desconectar a Meta? A Pauta esquece o acesso e para de ler os números. Para tirar o acesso também do lado da Meta, remova o app Pauta nas Configurações do negócio (Integrações → Apps conectados).")) return;
    try { await api("DELETE", "/api/meta"); toast("Meta desconectada"); loadMeta(); }
    catch (err) { toast(err.message, true); }
  });
}

function metaBody(d, clients = []) {
  if (!d.connected) {
    return `<p class="muted">Conecte o portfólio empresarial da agência para a Pauta ler os números das campanhas. A Pauta só lê; não altera nada na Meta.</p>
      <button class="btn primary" data-metaconnect>${icon("target")}Conectar Meta</button>`;
  }
  const since = d.connected_at ? new Date(d.connected_at).toLocaleDateString("pt-BR") : "";
  const accs = d.accounts || [];
  // Ativo clients first, then the rest, each group as /api/clients orders them
  const sorted = [...clients.filter((c) => c.state === "Ativo"), ...clients.filter((c) => c.state !== "Ativo")];
  const pick = (a) => {
    const cur = a.client?.id, sug = !cur && a.suggested ? a.suggested.id : null;
    return `<select class="input small" data-link="${esc(a.id)}" aria-label="Cliente da conta ${esc(a.name)}"><option value="">— sem cliente —</option>
      ${sorted.map((c) => `<option value="${c.id}" ${c.id === cur ? "selected" : ""}>${esc(c.name)}${c.id === sug ? " (sugestão)" : ""}</option>`).join("")}</select>
      ${sug ? `<span class="muted small hint">Sugestão: ${esc(a.suggested.name)}</span>` : ""}`;
  };
  const rows = accs.map((a) => `<tr${a.stale ? ' class="stale"' : ""}><td><b>${esc(a.name)}</b><span class="muted small">${esc(a.id)}${a.status !== 1 && a.status_label ? ` · ${esc(a.status_label)}` : ""}</span></td>
      <td class="pick">${pick(a)}</td>
      ${a.stale ? `<td colspan="6" class="muted">não aparece mais na Meta</td>`
    : `<td class="r">${esc(centsMoney(a.spend_cents, a.currency))}</td>
      <td class="r">${esc(count(a.reach))}</td>
      <td class="r">${esc(count(a.impressions))}</td>
      <td class="r">${esc(count(a.link_clicks))}</td>
      <td class="r">${esc(centsMoney(a.cpc_cents, a.currency))}</td>
      <td class="r">${metaBalance(a)}</td>`}</tr>`).join("");
  return `${d.error ? `<p class="warnbox">${esc(d.error)}</p>` : ""}
    <div class="member"><div class="who"><b>Conectado: ${esc(d.business_name || "portfólio")}${since ? ` desde ${esc(since)}` : ""}</b>
      <span>Números deste mês. A Pauta guarda por 10 minutos; Atualizar busca de novo.</span></div>
      <div class="row-gap">${d.error ? `<button class="btn primary small" data-metaconnect>${icon("target")}Conectar de novo</button>`
        : `<button class="btn primary small" data-metaconnect="add">${icon("plus")}Adicionar contas</button>`}
        <button class="btn small" id="metarefresh">${icon("swap")}Atualizar</button>
        <button class="btn ghost small danger" id="metaoff">Desconectar</button></div></div>
    ${accs.length ? `<div class="scrollx"><table class="mtable" id="metaaccounts"><thead><tr><th>Conta</th><th>Cliente</th><th class="r">Investido este mês</th><th class="r">Alcance</th><th class="r">Impressões</th><th class="r">Cliques no link</th><th class="r">Custo por clique</th><th class="r">Saldo</th></tr></thead>
      <tbody>${rows}</tbody></table></div>`
    : `<div class="empty small">Nenhuma conta de anúncios liberada para a Pauta neste portfólio.</div>`}
    <p class="muted small mt">Cliente novo? Toque em <b>Adicionar contas</b> e marque, na Meta, todas as contas que a Pauta deve ler. Ou, nas Configurações do negócio da Meta (Integrações → Apps conectados → Pauta), adicione a conta e toque em Atualizar. Na coluna <b>Cliente</b>, diga de quem é cada conta: os números aparecem na página do cliente.</p>`;
}

// The Meta card on a client's page: this month's numbers of the accounts linked to it
// (Equipe → Meta). Loaded after the page draws; never blocks it.
async function loadClientMeta(c) {
  const box = $("#clientmeta");
  if (!box || !BOOT.meta?.enabled) return;
  let doc;
  try { doc = await api("GET", `/api/clients/${c.id}/meta`); }
  catch (e) {
    if ($("#clientmeta")) box.innerHTML = `<div class="panel clientbox mt"><div class="panel-head"><h3>Meta</h3></div><p class="warnbox">${esc(e.message)}</p></div>`;
    return;
  }
  if (!$("#clientmeta") || !doc.connected) return;
  if (!doc.accounts.length) {
    box.innerHTML = ME.is_admin ? `<div class="panel clientbox mt"><div class="panel-head"><h3>Meta</h3></div>
      <p class="muted small">Nenhuma conta da Meta vinculada. <a href="#/equipe">Vincule em Equipe → Meta.</a></p></div>` : "";
    return;
  }
  const line = (label, value) => `<div class="row"><span class="grow muted">${label}</span><b>${value}</b></div>`;
  box.innerHTML = `<div class="panel clientbox mt"><div class="panel-head"><h3>Meta</h3><span class="muted small">este mês</span></div>
    ${doc.accounts.map((a) => `<div class="metaacc"><div class="row"><b class="grow">${esc(a.name)}</b><span class="muted small">${esc(a.id)}</span></div>
      ${a.stale ? `<p class="muted small">não aparece mais na Meta</p>`
      : line("Investido este mês", esc(centsMoney(a.spend_cents, a.currency)))
        + line("Alcance", esc(count(a.reach)))
        + line("Cliques no link", esc(count(a.link_clicks)))
        + line("Custo por clique", esc(centsMoney(a.cpc_cents, a.currency)))
        + line("Saldo", metaBalance(a))}</div>`).join("")}</div>`;
}

function metaBalance(a) {
  const b = a.balance || {};
  if (!b.available) return `<span class="muted" title="${esc(b.reason || "")}">sem permissão</span>`;
  if (b.remaining_cents != null) return `${esc(centsMoney(b.remaining_cents, a.currency))}<span class="muted small">até o limite</span>`;
  return b.funding ? esc(b.funding) : "—";
}

async function makeInvite() {
  const box = $("#qrbox");
  const admin = $("#asadmin").checked;
  try {
    const inv = await api("POST", "/api/invite", { admin });
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
async function makeMoveLink(id, name) {
  const box = $(`#mv-${id}`);
  try {
    const mv = await api("POST", `/api/members/${id}/move`, {});
    const until = new Date(mv.expires * 1000).toLocaleDateString("pt-BR", { weekday: "long", day: "numeric", month: "long" });
    const msg = `Oi, ${firstName(name)}! A Pauta mudou para ${mv.to}. Toque no link, confirme com o Face ID (ou a digital) e pronto: é a mesma conta, com tudo. Depois adicione o endereço novo à tela de início. ${mv.url}`;
    box.innerHTML = `<div class="qrbox"><div style="flex:1;min-width:240px"><b>Link de ${esc(firstName(name))} para ${esc(mv.to)}</b>
      <div class="muted small">Só para ${esc(firstName(name))}: quem tiver o link entra na conta. Vale uma vez, até ${esc(until)}.</div>
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
    gate(`<h1>Link expirado</h1><p>${esc(e.message)}. Peça um link novo a quem administra a Pauta, ou abra a Pauta no endereço antigo e toque em "Mudar" de novo.</p><a class="btn big" href="#/">Ir para o login</a>`);
    return;
  }
  const g = gate(`<h1>Olá, ${esc(firstName(info.name))}!</h1>
    <p>A Pauta agora mora em <b>${esc(info.to)}</b>. Crie sua passkey aqui para continuar: é a mesma conta, com tudo o que você já fez.</p>
    <button class="btn primary big" id="moveok">${icon("key")}Criar passkey em ${esc(info.to)}</button>
    <p class="fine">Depois, adicione este endereço à tela de início do celular de novo: o ícone antigo abre o endereço antigo.</p>`);
  $("#moveok", g).addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      ME = await passkeyRegister({ move: token });
      toast(`Pronto, ${firstName(ME.name)}! Você está em ${info.to}.`);
      location.hash = "#/";
      await enter();
    } catch (err) {
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
    await enter();
  } catch (e) {
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
  } catch (e) {
    if (e.name === "InvalidStateError") toast("Este aparelho já tem uma passkey sua.");
    else if (e.name !== "NotAllowedError") toast(e.message, true);
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
      toast(`Bem-vindo, ${firstName(ME.name)}!`);
      location.hash = "#/";
      await enter();
    } catch (err) {
      if (err.name !== "NotAllowedError") toast(err.message, true);
    } finally { btn.disabled = false; }
  });
}

// ---------- start -------------------------------------------------------------------------------

async function enter() {
  BOOT = await api("GET", "/api/boot");
  ME = BOOT.me;
  renderShell();
  await route();
}

async function start() {
  ME = await api("GET", "/api/me");
  const open = () => /^\/(entrar|mudar)\//.test(hashParts().path);
  window.addEventListener("hashchange", () => (ME.logged_in || open()) ? route() : showGate());
  if (open()) return route();
  if (!ME.logged_in) return showGate();
  await enter();
}

start().catch((e) => { document.body.innerHTML = `<p style="padding:40px;font-family:sans-serif">A Pauta não carregou: ${esc(e.message)}</p>`; });
