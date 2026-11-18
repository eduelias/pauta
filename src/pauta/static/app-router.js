"use strict";
// Pauta: the hash router and start-up; loaded last, after every screen it routes to.
// Shares app.js's globals; index.html loads it after app.js.

// ---------- router ------------------------------------------------------------------------

const ROUTES = [
  [/^\/?(?:painel)?$/, viewDash],
  [/^\/quadro$/, viewBoard],
  [/^\/pedidos$/, viewList],
  [/^\/pedido\/(\d+)$/, viewRequest],
  [/^\/novo(?:\/(\d+))?$/, viewNew],
  [/^\/clientes$/, viewClients],
  [/^\/cliente\/novo$/, viewNewClient],
  [/^\/cliente\/(\d+)$/, viewClient],
  [/^\/financeiro$/, viewFinance],
  [/^\/campanhas$/, viewCampaigns],
  [/^\/campanhas\/geral$/, viewOverview],
  [/^\/campanha\/(\d+)$/, viewCampaign],
  [/^\/relatorio\/(\d+)$/, viewReport],
  [/^\/configuracoes$/, viewSettings],
  [/^\/perfil$/, viewProfile],
];

function hashParts() {
  const raw = (location.hash || "#/").slice(1);
  const [path, query] = raw.split("?");
  return { path: path || "/", query: new URLSearchParams(query || "") };
}

// the screen's name for the usage log (decision 11): the first segment, never an id
function screenName(path) {
  if (path === "/") return "painel";
  const [, a, b] = path.split("/");
  return a === "cliente" && b === "novo" ? "cliente_novo" : a;
}

function enterScreen(name) {
  const from = USAGE.screen;
  USAGE.screen = name;
  if (name !== from) track("screen", { from });
}

async function route() {
  const { path, query } = hashParts();
  if (path === "/equipe" || path.startsWith("/equipe/")) {
    // the tab's name up to 1.6: bookmarks, Meta's way back and old links land on the new one
    const q = query.toString();
    history.replaceState(null, "", `#/configuracoes${path.slice(7)}${q ? "?" + q : ""}`);
    return route();
  }
  if (path.startsWith("/entrar/")) { enterScreen("entrar"); return showJoin(path.slice(8)); }
  if (path.startsWith("/mudar/")) { enterScreen("mudar"); return showMove(path.slice(7)); }
  if (ME.auth && !ME.logged_in) { enterScreen("entrar"); return showGate(); }
  // signed in without the boot data, e.g. the page was opened on an invite link: load it first
  if (!BOOT) return enter();
  $("#gate").hidden = true;
  $("#shell").hidden = false;
  $(".menu")?.remove();
  // the client's report is a screen to print: no sidebar, top bar or tab bar around it
  document.body.classList.toggle("report", /^\/relatorio\//.test(path));
  markNav();
  for (const [re, view] of ROUTES) {
    const m = path.match(re);
    if (m) {
      const seq = ++NAV_SEQ;
      enterScreen(screenName(path));
      app.innerHTML = spinner();
      LOADING++;
      try {
        await view(query, ...m.slice(1));
        app.firstElementChild?.classList.add("fadein");
        addMoveBar();
      } catch (e) {
        if (e instanceof Stale || seq !== NAV_SEQ) return;  // a newer screen owns #app now
        document.body.classList.remove("report");  // an error screen keeps its navigation
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

// ---------- start -------------------------------------------------------------------------------

async function enter() {
  BOOT = await api("GET", "/api/boot");
  ME = BOOT.me;
  if (!USAGE.opened) {  // once per page load, when the version is known
    USAGE.opened = true;
    const theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    track("app_open", { version: BOOT.version || "", theme, ...(startScreen() && { start: startScreen() }) });
  }
  // opened without an address of its own: the screen the person chose on Perfil, in place
  // of the Painel (replaceState: Back doesn't return to an address that would come here again)
  if (hashParts().path === "/" && startScreen()) history.replaceState(null, "", `#/${startScreen()}`);
  renderShell();
  await route();
}

async function start() {
  ME = await api("GET", "/api/me");
  USAGE.dev = deviceClass();
  const open = () => /^\/(entrar|mudar)\//.test(hashParts().path);
  window.addEventListener("hashchange", () => (ME.logged_in || open()) ? route() : showGate());
  if (open()) return route();
  if (!ME.logged_in) { enterScreen("entrar"); return showGate(); }
  await enter();
}

start().catch((e) => { document.body.innerHTML = `<p style="padding:40px;font-family:sans-serif">A Pauta não carregou: ${esc(e.message)}</p>`; });
