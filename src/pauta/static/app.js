"use strict";
// Pauta: one small single-page app. Routes are #/..., data comes from /api, nothing else.
// This file is the shared part (helpers, the shell); the screens are app-<area>.js and the
// router is app-router.js, loaded in that order by index.html (one global scope, no modules).

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
  chart: '<path d="M3 3v18h18"/><path d="m7 15 4-5 4 3 5-7"/>',
  gear: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
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
const stamp = (s) => new Date(/Z$/.test(String(s)) ? String(s) : String(s).replace(" ", "T") + "Z");
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
  ["#/configuracoes", "gear", "Configurações"],
];

const FIN_NAV = ["#/financeiro", "money", "Financeiro"];
const finVisible = () => Boolean(BOOT?.finance?.visible);
// Campanhas (decision 8) sits after Pedidos; members see it too (the clients' numbers the
// team already sees), admins get the extra buttons
const CAMP_NAV = ["#/campanhas", "chart", "Campanhas"];
const metaVisible = () => Boolean(BOOT?.meta?.enabled);

function renderShell() {
  const open = REQS ? REQS.filter(isOpen).length : null;
  // Financeiro sits after Clientes; on the phone it takes Quadro's slot (decision 7), and
  // Campanhas takes that slot over both when Meta is on (Quadro stays a tap from the Painel)
  const nav = NAV.flatMap((e) => (e[0] === "#/configuracoes" && finVisible() ? [FIN_NAV, e]
    : e[0] === "#/pedidos" && metaVisible() ? [e, CAMP_NAV] : [e]));
  $("#nav").innerHTML = `<a href="#/novo" class="btn primary newbtn">${icon("plus")}Novo pedido</a>` +
    nav.map(([h, i, t]) => `<a href="${h}" data-nav="${h}">${icon(i)}${t}${h === "#/pedidos" && open ? `<span class="count">${open}</span>` : ""}</a>`).join("");
  $("#tabbar").innerHTML = [
    ["#/", "dash", "Painel"], ["#/pedidos", "list", "Pedidos"], ["#/novo", "plus", "Novo"],
    metaVisible() ? CAMP_NAV : finVisible() ? FIN_NAV : ["#/quadro", "board", "Quadro"], ["#/clientes", "clients", "Clientes"],
  ].map(([h, i, t]) => `<a href="${h}" data-nav="${h}">${icon(i)}${t}</a>`).join("");
  $("#sidefoot").innerHTML = `<button class="me-chip" id="mechip">${avatar(ME.name, "md round", ME.avatar)}<div><b>${esc(ME.name)}</b><span>${ME.is_admin ? "Administrador" : "Membro"}</span></div></button>`;
  const top = $("#topnew");
  top.outerHTML = `<a href="#/perfil" id="topnew" aria-label="Seu perfil">${avatar(ME.name, "md round", ME.avatar)}</a>`;
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
  const map = { "#/pedido": "#/pedidos", "#/cliente": "#/clientes", "#/campanha": "#/campanhas", "#/": "#/" };
  const want = map[base] || base;
  $$("[data-nav]").forEach((a) => a.classList.toggle("on", a.dataset.nav === want));
}

function toggleMenu() {
  const old = $(".menu");
  if (old) { old.remove(); return; }
  const m = document.createElement("div");
  m.className = "menu";
  m.innerHTML = `<a href="#/perfil">${icon("user")}Meu perfil</a>
    <a href="#/configuracoes">${icon("gear")}Configurações</a>
    ${ME.auth ? `<button data-act="logout">${icon("logout")}Sair</button>` : ""}`;
  $(".side").appendChild(m);
  m.addEventListener("click", (e) => {
    if (e.target.closest("[data-act]")?.dataset.act === "logout") logout();
    m.remove();
  });
  setTimeout(() => document.addEventListener("click", () => m.remove(), { once: true }));
}
