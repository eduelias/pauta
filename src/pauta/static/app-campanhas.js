"use strict";
// Pauta: Campanhas (decision 8).
// Shares app.js's globals; index.html loads it after app.js.

// ---------- campanhas (decision 8) ----------------------------------------------------------

// The period picker means what Ads Manager means: "últimos N dias" run from yesterday back
// and never include today (today's numbers are still moving); "este mês" is the 1st to today.
// The default is Ads Manager's own, "Últimos 30 dias". Dates are computed here, in the
// browser's local date, and sent as since/until (the server's own default, when a caller
// sends none, is the same 30 days in the ad account's time zone).
const PERIODS = [
  ["today", "Hoje"], ["yesterday", "Ontem"], ["last_7", "Últimos 7 dias"], ["last_30", "Últimos 30 dias"],
  ["this_month", "Este mês"], ["last_month", "Mês passado"], ["custom", "Personalizado"],
];
const MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
const isISO = (d) => /^\d{4}-\d{2}-\d{2}$/.test(d || "");

function periodDates(p, custom = {}) {
  const t = todayISO();
  const first = t.slice(0, 8) + "01";
  switch (p) {
    case "today": return [t, t];
    case "yesterday": return [addDays(t, -1), addDays(t, -1)];
    case "last_7": return [addDays(t, -7), addDays(t, -1)];
    case "last_30": return [addDays(t, -30), addDays(t, -1)];
    case "last_month": { const end = addDays(first, -1); return [end.slice(0, 8) + "01", end]; }
    case "custom": {
      const a = isISO(custom.since) ? custom.since : first, b = isISO(custom.until) ? custom.until : t;
      return a <= b ? [a, b] : [b, a];
    }
    default: return [first, t];
  }
}
// "3 out", "25 out 2025": the year only when it isn't this one
const shortDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]}${y !== new Date().getFullYear() ? ` ${y}` : ""}`; };
// "1 nov – 1 nov", "25 out – 31 out"
const periodLabel = (since, until) => `${shortDay(since)} – ${shortDay(until)}`;
// the hash query wins (a reload keeps it), then the last choice on this browser, then the last 30 days
function readPeriod(query) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("pauta.period") || "{}") || {}; } catch { saved = {}; }
  const known = (k) => PERIODS.some(([key]) => key === k);
  let p = query.get("p") || "", since = query.get("since") || "", until = query.get("until") || "";
  if (isISO(since) && isISO(until)) p = "custom";
  else if (!known(p) || p === "custom") {
    p = known(saved.p) ? saved.p : "last_30";
    since = saved.since || "";
    until = saved.until || "";
    if (p === "custom" && !(isISO(since) && isISO(until))) p = "last_30";
  }
  return { p, since, until };
}
// The usage log's "period" row. A Personalizado range adds its shape, never its dates:
// `days` long, ending `ago` days back (0 = today), so the usage log can say which quick
// period the picker lacks ("14 days up to yesterday", say).
function trackPeriod(st) {
  if (st.p !== "custom") { track("period", { p: st.p }); return; }
  const [since, until] = periodDates(st.p, st);
  track("period", { p: st.p, days: 1 - daysUntil(since) + daysUntil(until), ago: -daysUntil(until) });
}
const periodQuery = (st) => st.p === "custom" ? `since=${st.since}&until=${st.until}` : `p=${st.p}`;
function savePeriod(st) {
  try { localStorage.setItem("pauta.period", JSON.stringify(st.p === "custom" ? st : { p: st.p })); } catch { /* private mode: not remembered */ }
}
function periodPicker(st) {
  const [since, until] = periodDates(st.p, st);
  const t = todayISO();
  return `<div class="period" id="period">
    <div class="seg">${PERIODS.map(([k, label]) => `<button type="button" data-p="${k}" class="${k === st.p ? "on" : ""}">${label}</button>`).join("")}</div>
    <div class="period-custom" ${st.p === "custom" ? "" : "hidden"}><input class="input" type="date" id="psince" aria-label="Início" value="${since}" max="${t}"><span class="muted">até</span><input class="input" type="date" id="puntil" aria-label="Fim" value="${until}" max="${t}"></div>
    <div class="period-dates"><b id="pdates">${esc(periodLabel(since, until))}</b>${until >= t ? `<span class="tag" id="ptoday" title="os números de hoje ainda mudam">hoje incluso</span>` : ""}</div>
  </div>`;
}
function bindPeriod(st, onChange) {
  $("#period .seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-p]");
    if (!b || b.dataset.p === st.p) return;
    const [since, until] = periodDates(st.p, st);  // Personalizado starts from the range shown
    st.p = b.dataset.p;
    if (st.p === "custom") { st.since = since; st.until = until; }
    onChange();
  });
  const custom = () => {
    const a = $("#psince").value, b = $("#puntil").value;
    if (!isISO(a) || !isISO(b)) return;
    [st.since, st.until] = a <= b ? [a, b] : [b, a];
    st.p = "custom";
    onChange();
  };
  $("#psince").addEventListener("change", custom);
  $("#puntil").addEventListener("change", custom);
}
const syncLine = (last) => last ? `Dados da Meta de ${esc(ago(last))}` : "A Meta ainda não foi lida; os números chegam na primeira sincronização.";
const SYNC_POLL_MS = 3000, SYNC_POLL_MAX = 40; // every 3 s for up to ~2 min
const SYNC_LOST = "lost";  // nothing syncing and nothing new: the pass never ended
const SYNC_LEFT = "left";  // the person is on another screen: nothing to say there
const SYNC_UNFINISHED = "A sincronização não terminou; tente de novo";
async function waitForSync(previous, since, until) {
  // After Atualizar agora: GET /api/campaigns until the pass ends (a newer `last_sync`);
  // the "Dados da Meta" line follows. SYNC_LOST when nothing is syncing and `last_sync`
  // is still the previous one with no error: the server restarted mid-pass (the lock is
  // fresh, `last_sync` comes back from the database), so nothing was synced. SYNC_LEFT
  // when the person has left the screen; null when it is still running after the last poll.
  const here = () => onScreen("#/campanhas") && $("#syncline");  // Visão geral has that line too
  for (let i = 0; i < SYNC_POLL_MAX; i++) {
    await new Promise((r) => setTimeout(r, i ? SYNC_POLL_MS : 1000));
    if (!here()) return SYNC_LEFT;
    const doc = await api("GET", `/api/campaigns?since=${since}&until=${until}`);
    if (!here()) return SYNC_LEFT;
    if (doc.syncing && doc.last_sync === previous) continue;
    $("#syncline").textContent = syncLine(doc.last_sync);
    if (doc.last_sync === previous && !doc.sync_error) return SYNC_LOST;
    return doc;
  }
  return null;
}

// Ativa / Encerrada em dd/mm / Pausada / Ignorada, Meta's own status on hover
function stateTag(k) {
  const [cls, txt] = k.state === "active" ? ["Ativo", "Ativa"]
    : k.state === "paused" ? ["Pausado", "Pausada"]
    : k.state === "skipped" ? ["Encerrado", "Ignorada"]
    : ["Encerrado", `Encerrada${k.ended ? ` em ${fmtDate(k.ended, { day: "2-digit", month: "2-digit" })}` : ""}`];
  return `<span class="state ${cls}" title="${esc(k.effective_status || "")}">${esc(txt)}</span>`;
}

// Ads Manager's own words for what a campaign's Resultados count (the action type Meta names
// in `result_indicator`); a type not here reads as its name with dots and underscores as spaces
const RESULT_LABELS = {
  "onsite_conversion.messaging_conversation_started_7d": "Conversas por mensagem iniciadas",
  lead: "Cadastros", "onsite_conversion.lead_grouped": "Cadastros", link_click: "Cliques no link",
  landing_page_view: "Visualizações da página de destino",
  purchase: "Compras", omni_purchase: "Compras", "onsite_conversion.purchase": "Compras",
  post_engagement: "Engajamentos com a publicação",
  "offsite_conversion.fb_pixel_view_content": "Conteúdo de visualização",
  video_view: "Reproduções de vídeo", thruplay: "ThruPlays", page_engagement: "Engajamentos com a Página",
  "onsite_conversion.messaging_first_reply": "Novas conexões por mensagem",
};
// a type neither list knows reads in Portuguese (approximate, but never a raw key like
// "offsite_search_add_meta_leads" on the screen): known phrases first, then word by word,
// the place ("no site", "no app") last. The chip's tooltip keeps Meta's own name.
const TYPE_PHRASES = Object.entries({
  add_to_cart: "adições ao carrinho", add_to_wishlist: "adições à lista de desejos", add_payment_info: "informações de pagamento",
  initiate_checkout: "finalizações de compra iniciadas", initiated_checkout: "finalizações de compra iniciadas",
  view_content: "visualizações de conteúdo", content_view: "visualizações de conteúdo", landing_page_view: "visualizações da página de destino",
  complete_registration: "cadastros concluídos", video_view: "reproduções de vídeo", video_play: "reproduções de vídeo",
  post_engagement: "engajamentos com a publicação", page_engagement: "engajamentos com a Página", post_interaction: "interações com a publicação",
  post_net_like: "curtidas líquidas na publicação", post_unlike: "descurtidas na publicação", post_save: "salvamentos",
  post_reaction: "reações", link_click: "cliques no link", click_to_call: "ligações", call_placed: "ligações feitas", call_connect: "ligações atendidas",
  message_send: "mensagens enviadas", messaging_conversation_started: "conversas iniciadas", messaging_first_reply: "primeiras respostas",
  total_messaging_connection: "conexões por mensagem", welcome_message_view: "mensagens de boas-vindas vistas", messaging_block: "bloqueios de mensagens",
  app_install: "instalações do app", mobile_app_install: "instalações do app", activate_app: "aberturas do app", app_use: "usos do app",
  start_trial: "avaliações iniciadas", submit_application: "inscrições enviadas", find_location: "buscas por localização",
  customize_product: "produtos personalizados", photo_view: "visualizações de foto", profile_visit: "visitas ao perfil", ig_profile_visit: "visitas ao perfil",
  store_visit: "visitas à loja", lead_grouped: "cadastros", flow_complete: "fluxos concluídos", order_created: "pedidos criados",
}).sort((a, b) => b[0].length - a[0].length);
const TYPE_WORDS = {
  lead: "cadastros", leads: "cadastros", purchase: "compras", purchases: "compras", search: "pesquisas", view: "visualizações", views: "visualizações",
  like: "curtidas", likes: "curtidas", comment: "comentários", share: "compartilhamentos", save: "salvamentos", reaction: "reações",
  engagement: "engajamentos", interaction: "interações", click: "cliques", clicks: "cliques", call: "ligações", visit: "visitas",
  subscribe: "assinaturas", schedule: "agendamentos", contact: "contatos", donate: "doações", rsvp: "respostas a eventos", checkin: "check-ins",
  follow: "seguidores", install: "instalações", use: "usos", play: "reproduções", conversion: "", conversions: "conversões", custom: "personalizadas",
  offline: "offline", net: "líquidas", gross: "brutas", total: "total", grouped: "", meta: "Meta", omni: "", fb: "", pixel: "", to: "", in: "", the: "",
  mobile: "", native: "", user: "", event: "eventos", response: "respostas", message: "mensagem", messaging: "mensagens", conversation: "conversas",
  started: "iniciadas", replied: "respondidas", block: "bloqueios", order: "pedidos", created: "criados", flow: "fluxos", form: "formulário",
  complete: "concluídos", post: "publicação", page: "Página", video: "vídeo", photo: "foto", profile: "perfil", store: "loja", link: "no link",
  cart: "carrinho", checkout: "finalizações de compra", payment: "pagamento", info: "informações", registration: "cadastros", content: "conteúdo",
};
const TYPE_PLACES = { offsite: "no site", onsite: "na Meta", web: "no site", app: "no app" };
function cleanType(type) {
  let t = String(type || "").toLowerCase().replace(/\./g, "_");
  let tail = "";
  if (/_add_meta_leads$/.test(t)) { t = t.replace(/_add_meta_leads$/, ""); tail = " (site + Meta)"; }
  t = t.replace(/messaging_user_depth_(\d+)_message_send/, "conversas com $1 mensagens");
  for (const [k, v] of TYPE_PHRASES) t = t.replace(new RegExp(`(^|_)${k}(?=_|$)`, "g"), `$1${v}`);  // a phrase has spaces, no "_": it survives the split
  const words = t.split("_").filter(Boolean);
  const places = [...new Set(words.filter((w) => TYPE_PLACES[w]).map((w) => TYPE_PLACES[w]))];
  const rest = words.filter((w) => !TYPE_PLACES[w]).map((w) => w in TYPE_WORDS ? TYPE_WORDS[w] : /^\d/.test(w) ? "" : w).filter(Boolean);
  const where = tail ? "" : places.filter((x) => x !== "na Meta" || places.length === 1).join(" e ");  // "no site e no app"
  const out = ([...rest, where].filter(Boolean).join(" ").replace(/\b(\S+) \1\b/g, "$1") + tail).trim()
    || String(type || "").replace(/[._]+/g, " ");
  return out.replace(/^./, (c) => c.toUpperCase());
}
const resultLabel = (type) => RESULT_LABELS[type] || ACTION_LABELS[type] || cleanType(type);
// the campaign's objective, as Ads Manager names it in Portuguese
const OBJECTIVES = {
  OUTCOME_AWARENESS: "Reconhecimento", OUTCOME_TRAFFIC: "Tráfego", OUTCOME_ENGAGEMENT: "Engajamento",
  OUTCOME_LEADS: "Cadastros", OUTCOME_APP_PROMOTION: "Promoção do app", OUTCOME_SALES: "Vendas", OUTCOME_MESSAGES: "Mensagens",
  BRAND_AWARENESS: "Reconhecimento da marca", REACH: "Alcance", LINK_CLICKS: "Tráfego", POST_ENGAGEMENT: "Engajamento com a publicação",
  PAGE_LIKES: "Curtidas na Página", EVENT_RESPONSES: "Respostas a eventos", MESSAGES: "Mensagens", VIDEO_VIEWS: "Visualizações de vídeo",
  LEAD_GENERATION: "Geração de cadastros", CONVERSIONS: "Conversões", PRODUCT_CATALOG_SALES: "Vendas do catálogo",
  STORE_VISITS: "Visitas à loja", APP_INSTALLS: "Instalações do app", LOCAL_AWARENESS: "Reconhecimento local",
};
const objectiveLabel = (o) => OBJECTIVES[o] || String(o || "").replace(/^OUTCOME_/, "").toLowerCase().replace(/_/g, " ");
const NO_RESULTS = "sem resultados registrados para o objetivo da campanha";
const MIXED_RESULTS = "resultados de objetivos diferentes não somam";
const NO_REACH = "a Meta não respondeu";
const SUM_REACH = "alcance não soma entre campanhas: a mesma pessoa pode ver mais de uma";
const NO_BUDGET = "orçamento definido nos conjuntos de anúncios, não na campanha";
const SUM_BUDGET = "o orçamento é de cada campanha";

// the six numbers of a row, Ads Manager's columns in its order; a client's total shows "—"
// for reach (it doesn't add up), for the budget (each campaign's own) and for results when
// its campaigns count different things
const METRIC_COLS = [["results", "Resultados"], ["cpr", "Custo por resultado"], ["spend", "Valor gasto"], ["impressions", "Impressões"], ["reach", "Alcance"], ["budget", "Orçamento"]];
const dash = (title) => `<span class="muted" title="${esc(title)}">—</span>`;
// "R$ 15,00 · diário", "R$ 450,00 · total", "" when the ad sets carry the budget
function budgetText(k) {
  if (k.daily_budget_cents != null) return `${centsMoney(k.daily_budget_cents, k.currency)} · diário`;
  if (k.lifetime_budget_cents != null) return `${centsMoney(k.lifetime_budget_cents, k.currency)} · total`;
  return "";
}
// `reading`: the period's reach is still being read from Meta behind the page (fillReach)
const READING = `<span class="muted reading" title="lendo o alcance na Meta…">…</span>`;
const reachCell = (k, reading = false) => k.reach != null ? esc(count(k.reach)) : reading ? READING : dash(NO_REACH);
function metricCells(k, total = false, reading = false) {
  const label = resultLabel(k.result_indicator);
  const none = total && k.mixed ? MIXED_RESULTS : NO_RESULTS;
  const v = {
    results: k.results == null ? [dash(none)] : [esc(count(k.results)), label],
    cpr: k.results ? [esc(centsMoney(k.cost_per_result_cents, k.currency)), label] : [dash(none)],
    spend: [esc(centsMoney(k.spend_cents, k.currency))],
    impressions: [esc(count(k.impressions))],
    reach: [total ? dash(SUM_REACH) : reachCell(k, reading)],
    budget: [total ? dash(SUM_BUDGET) : budgetText(k) ? esc(budgetText(k)) : dash(NO_BUDGET)],
  };
  return METRIC_COLS.map(([key, label]) => {
    const [main, sub] = v[key];
    return `<div class="km km-${key}"><span class="kl">${label}</span><b>${main}</b>${sub ? `<span class="ksub" title="${esc(sub)}">${esc(sub)}</span>` : ""}</div>`;
  }).join("");
}
// spend ÷ n in whole cents, half up as Ads Manager and the server's db.cents_per round
// (integer arithmetic: floor((2a + b) / 2b) is exact where a float quotient may not be)
const centsPer = (spendCents, n) => n ? Math.floor((2 * spendCents + n) / (2 * n)) : null;
function clientTotals(c) {
  const live = c.campaigns.filter((x) => x.state !== "skipped");
  const t = { spend_cents: 0, link_clicks: 0, impressions: 0, currency: c.campaigns[0]?.currency, results: null, result_indicator: "", cost_per_result_cents: null, mixed: false };
  for (const k of live) { t.spend_cents += k.spend_cents; t.link_clicks += k.link_clicks; t.impressions += k.impressions; }
  t.cpl_cents = centsPer(t.spend_cents, t.link_clicks);
  // results add up only when every campaign counts the same thing
  const kinds = new Set(live.map((k) => k.result_indicator).filter(Boolean));
  const counted = live.filter((k) => k.results != null);
  if (kinds.size === 1 && counted.length) {
    t.result_indicator = [...kinds][0];
    t.results = counted.reduce((a, k) => a + k.results, 0);
    t.cost_per_result_cents = centsPer(t.spend_cents, t.results);
  } else t.mixed = kinds.size > 1;
  return t;
}
// "ativa desde 3 out" next to the name, so a short period isn't read as missing data
const sinceTag = (k) => k.state === "active" && k.started
  ? `<span class="ksince" title="ativa desde ${esc(fmtDate(k.started, { day: "2-digit", month: "2-digit", year: "numeric" }))}: antes disso não há números">ativa desde ${esc(shortDay(k.started))}</span>` : "";

// Configurações → Campanhas (admins, with Meta on): Visão geral's alert thresholds and the
// request kinds that put a campaign on air. `cfg` is BOOT.campaigns, `kinds` the team's Tipos
// de pedido; a kind saved earlier and since renamed stays listed so it can be unticked.
function campaignSettingsPanel(cfg, kinds) {
  const num = (key, label, hint, min, max) => `<div class="field"><label>${label}</label><input class="input" data-camp="${key}" type="number" min="${min}" max="${max}" value="${cfg[key]}"><span class="hint">${hint}</span></div>`;
  const all = [...new Set([...kinds, ...cfg.tracking_kinds])];
  return `<section class="panel mt" id="campsettings"><div class="panel-head"><h2>${icon("chart")}Campanhas</h2><span class="muted small">Os alertas da Visão geral</span></div>
    <div class="form-grid">
      ${num("rise_pct", "Custo subindo: avisar a partir de (%)", "custo por resultado, ou por clique", 5, 500)}
      ${num("drop_pct", "Volume caindo: avisar a partir de (%)", "resultados, ou cliques", 5, 100)}
      ${num("same_spend_pct", "“Mesmo investimento” é variar até (%)", "acima disso, menos volume é só menos verba", 0, 100)}
      ${num("min_spend", "Só avisar com este gasto por semana", "na moeda da conta; abaixo disso os números oscilam demais", 0, 100000)}
      ${num("min_count", "…e com pelo menos estes cliques ou resultados", "na semana anterior", 1, 1000)}
      ${num("low_balance_days", "Saldo acabando: avisar com menos de (dias)", "0 desliga o alerta", 0, 60)}
      ${num("unseen_days", "Sem análise: avisar depois de (dias)", "sem Visto hoje; 0 desliga o alerta", 0, 60)}
      <div class="field wide"><label>Pedidos que colocam uma campanha no ar</label>
        <div class="row-gap" id="campkinds">${all.map((k) => `<label class="toggle small"><input type="checkbox" data-campkind="${esc(k)}" ${cfg.tracking_kinds.includes(k) ? "checked" : ""}>${esc(k)}</label>`).join("")}</div>
        <span class="hint">Ao concluir um pedido destes tipos, a Pauta pergunta qual campanha ele criou e liga os dois.</span></div>
    </div>
    <p class="muted small mt">Os alertas comparam os últimos 7 dias com os 7 anteriores, sem contar hoje. Valem para todo o time.</p>
    <div class="mt"><button class="btn" id="savecamp">${icon("check")}Salvar campanhas</button></div></section>`;
}
async function saveCampaignSettings() {
  const ticked = [...document.querySelectorAll("[data-campkind]")].filter((el) => el.checked);
  const body = { tracking_kinds: ticked.map((el) => el.dataset.campkind) };
  for (const el of document.querySelectorAll("[data-camp]")) body[el.dataset.camp] = el.value;
  try {
    await api("PATCH", "/api/campaigns/settings", body);
    track("settings_changed", { section: "campanhas" });
    BOOT = await api("GET", "/api/boot");
    toast("Campanhas salvo");
  } catch (e) { toast(e.message, true); }
}

// Campanhas' two views of the same numbers: client by client, or every client on one row
const campTabs = (st, on) => `<nav class="ctabs" aria-label="Visões de Campanhas">${[["", "Por cliente"], ["/geral", "Visão geral"]].map(([path, label]) => `<a href="#/campanhas${path}?${periodQuery(st)}" class="${path === on ? "on" : ""}"${path === on ? ` aria-current="page"` : ""}>${label}</a>`).join("")}</nav>`;

// ---------- visão geral (docs/campaign-overview-spec.md) -------------------------------------
// Every client on one row, the ones that need a look first. The server did the arithmetic
// (GET /api/campaigns/overview): the flags are its rules over the last 7 full days against
// the 7 before, whatever period the columns show.

// what the small line on each row draws, one point per day of the last 14
const TRENDS = {
  spend: ["Valor gasto", (d) => d.spend_cents],
  clicks: ["Cliques no link", (d) => d.link_clicks],
  cpc: ["Custo por clique", (d) => centsPer(d.spend_cents, d.link_clicks)],
  results: ["Resultados", (d) => d.results],
};
const ovState = { flagged: false, segment: "", trend: "spend" };  // for the session

// a line through the days that have a value (a day without one breaks it), scaled to its own top
function trendLine(values, label) {
  const W = 120, H = 30, pad = 3, n = values.length;
  const max = Math.max(0, ...values.map((v) => v ?? 0));
  if (!max) return dash("sem números nos últimos 14 dias");
  let line = "", area = "", from = null, last = 0;
  const close = () => { if (from != null) area += `L${last.toFixed(1)} ${H}L${from.toFixed(1)} ${H}Z`; from = null; };
  values.forEach((v, i) => {
    if (v == null) { close(); return; }
    const x = n > 1 ? i * W / (n - 1) : W / 2, y = H - pad - v / max * (H - 2 * pad);
    const step = `${from == null ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    line += step;
    area += step;
    if (from == null) from = x;
    last = x;
  });
  close();
  return `<svg class="otrend" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="${esc(label)} por dia, últimos 14 dias"><path class="area" d="${area}"/><path class="line" d="${line}"/></svg>`;
}
// "▲ 42%" in red when that direction is bad news (cost up, volume down), green when good,
// plain under 10%: a wobble isn't a trend
function delta(pct, what, upIsBad) {
  if (pct == null) return "";
  const cls = Math.abs(pct) < 10 ? "" : (pct > 0) === upIsBad ? "bad" : "good";
  return `<span class="odelta ${cls}">${pct > 0 ? "▲" : pct < 0 ? "▼" : "="} ${Math.abs(pct) > 999 ? "mais de 999" : Math.abs(pct)}% <span>${what}</span></span>`;
}
// Avisar o cliente: the messages a row writes for the client's WhatsApp, as drafts. The link
// opens the conversation with the text in the box; the person reads it, changes what they
// want and sends it themselves. Without a number on the client WhatsApp asks which
// conversation. Amounts with a plain space: Intl's no-break one shows as a box in some chats.
const plainMoney = (cents, cur) => centsMoney(cents, cur).replace(/\u00a0/g, " ");
const clientHello = (c) => { const who = firstName(c.contact); return `Olá${who ? `, ${who}` : ""}!`; };
// "saldo para 2 dias", said to the one who puts the credit in; a balance already at zero is
// said as it is (the row says "saldo acabou"), never as "acaba hoje (restam R$ 0,00)"
function balanceText(c) {
  if (!c.balance.remaining_cents) return `${clientHello(c)} O saldo dos seus anúncios acabou, e sem saldo as campanhas ficam paradas. Para voltarem a rodar, é só colocar crédito. Qualquer dúvida, é só me chamar.`;
  const left = c.balance.days_left, money = plainMoney(c.balance.remaining_cents, c.currency);
  const lasts = left > 0 ? `dura mais ${left} ${left === 1 ? "dia" : "dias"} no ritmo atual (restam ${money})` : `acaba hoje (restam ${money})`;
  const when = left > 1 ? "nos próximos dias" : left === 1 ? "até amanhã" : "ainda hoje";
  return `${clientHello(c)} O saldo dos seus anúncios ${lasts}. Para as campanhas não pararem, vale colocar crédito ${when}. Qualquer dúvida, é só me chamar.`;
}
// the period's numbers as the row shows them: what was invested, the clicks, and the
// results when the campaigns count the same thing (clicks counted as the result say it once)
function summaryText(c, since, until) {
  const p = c.period;
  const lines = [`• Investimento: ${plainMoney(p.spend_cents, c.currency)}`];
  if (p.link_clicks) lines.push(`• Cliques no link: ${count(p.link_clicks)}`);
  if (p.results && p.result_indicator !== "link_click") lines.push(`• ${resultLabel(p.result_indicator)}: ${count(p.results)}${p.cost_per_result_cents != null ? ` (${plainMoney(p.cost_per_result_cents, c.currency)} cada)` : ""}`);
  return `${clientHello(c)} Resumo ${c.campaigns === 1 ? "da sua campanha" : "das suas campanhas"} (${since === until ? shortDay(since) : periodLabel(since, until)}):\n${lines.join("\n")}\nQualquer dúvida, é só me chamar.`;
}
// one draft as a link; `kind` is what the usage log counts
function messageLink(c, kind, label, glyph, text) {
  const to = waUrl(c.whatsapp);
  return `<a class="oact" data-act="${kind}" href="${esc(`${to || "https://wa.me/"}?text=${encodeURIComponent(text)}`)}" target="_blank" rel="noopener" title="${to ? `Abre a conversa com ${esc(c.contact || c.name)} com a mensagem escrita: você lê e envia` : "O cliente não tem WhatsApp cadastrado: o WhatsApp pergunta para quem enviar"}">${icon(glyph)}${label}</a>`;
}
const balanceFlag = (c) => c.balance ? c.flags.find((f) => f.key === "balance") : undefined;
// "Avisar do saldo": only with the balance alert, on Visão geral's row and the Painel's card
const balanceMessage = (c) => balanceFlag(c) ? messageLink(c, "balance", "Avisar do saldo", "wa", balanceText(c)) : "";
function clientMessages(c, doc) {
  const out = [balanceMessage(c)];
  if (c.period.spend_cents > 0) out.push(messageLink(c, "summary", "Enviar resumo", "send", summaryText(c, doc.since, doc.until)));
  return out.some(Boolean) ? `<div class="oacts">${out.join("")}</div>` : "";
}
// The Painel's card "Saldo acabando": the clients Visão geral flags for their balance (at
// zero, or lasting less than the team's days in Configurações → Campanhas), the ones with
// the least time first, each with the draft that warns the client. From the same overview
// document, so the card and the row never disagree. Nobody flagged: no card.
function lowBalanceCard(doc) {
  const low = doc.clients.filter(balanceFlag).sort((a, b) => (a.balance.remaining_cents > 0) - (b.balance.remaining_cents > 0)
    || (a.balance.days_left ?? 0) - (b.balance.days_left ?? 0)
    || a.balance.remaining_cents - b.balance.remaining_cents || a.name.localeCompare(b.name, "pt-BR"));
  if (!low.length) return "";
  return `<section class="panel lowbal" id="lowbalance">
    <div class="panel-head"><h2>Saldo acabando</h2><span class="muted small" title="${low.length === 1 ? "1 cliente" : `${low.length} clientes`}">${low.length}</span><a class="btn ghost small" href="#/campanhas/geral">Ver visão geral</a></div>
    ${low.map((c) => `<div class="lowrow" data-client="${c.id}">
      <a class="lowname" href="#/cliente/${c.id}">${avatar(c.name)}<b>${esc(c.name)}</b></a>
      <b class="lowleft">${esc(centsMoney(c.balance.remaining_cents, c.currency))}</b>
      <span class="oflag l${balanceFlag(c).level}" data-flag="balance">${esc(balanceFlag(c).text)}</span>
      ${balanceMessage(c)}</div>`).join("")}
  </section>`;
}
// Put under the Painel's counters when the overview answers, if that Painel is still the
// one on screen: it never waits for the balances. A failed read leaves the Painel as it was.
function showLowBalance(pending, root) {
  pending.then((doc) => {
    const html = root.isConnected ? lowBalanceCard(doc) : "";
    if (!html) return;
    $(".stats", root).insertAdjacentHTML("afterend", html);
    $("#lowbalance", root).addEventListener("click", (e) => { const a = e.target.closest("a[data-act]"); if (a) track("client_message", { kind: a.dataset.act }); });
  }).catch(() => {});
}
// under the amount: "acabou" at zero, "menos de um dia" when it won't cover one, else the days
function balanceLasts(b) {
  const text = !b.remaining_cents ? "acabou" : b.days_left == null ? "" : b.days_left === 0 ? "menos de um dia" : `para ${b.days_left} ${b.days_left === 1 ? "dia" : "dias"}`;
  return text ? `<span class="ksub">${text}</span>` : "";
}
function overviewRow(c, doc) {
  const p = c.period, ch = c.change, byResult = ch.kind === "result";
  const none = ch.partial ? "as campanhas começaram há pouco: ainda não há um período anterior inteiro para comparar" : "sem números no período anterior para comparar";
  const results = p.results == null
    ? dash(p.mixed ? "as campanhas contam coisas diferentes: os resultados não se somam" : "sem resultados no período")
    : `<b>${esc(count(p.results))}</b><span class="ksub">${esc(resultLabel(p.result_indicator))}${p.cost_per_result_cents != null ? ` · ${esc(centsMoney(p.cost_per_result_cents, c.currency))} cada` : ""}</span>`;
  const change = [delta(ch.cost_pct, byResult ? "custo por resultado" : "custo por clique", true), delta(ch.volume_pct, byResult ? "resultados" : "cliques", false)].join("") || dash(none);
  const balance = c.balance
    ? `<b>${esc(centsMoney(c.balance.remaining_cents, c.currency))}</b>${balanceLasts(c.balance)}`
    : dash("a Meta não informa o saldo desta conta");
  const seen = c.seen_today
    ? `<span class="oseen">${icon("check")}hoje${c.seen_today.by ? `, ${esc(firstName(c.seen_today.by))}` : ""}</span>`
    : c.last_seen ? `<span class="muted small" title="o último Visto hoje">${esc(shortDay(c.last_seen))}</span>` : dash("ainda sem Visto hoje");
  const [trendLabel, trendOf] = TRENDS[ovState.trend];
  return `<div class="orow${c.flags.length ? " flagged" : ""}" data-client="${c.id}">
    <div class="oname"><a href="#/cliente/${c.id}">${avatar(c.name)}<b>${esc(c.name)}</b></a>
      <span class="muted small">${c.active} de ${c.campaigns} ${c.campaigns === 1 ? "campanha ativa" : "campanhas ativas"}${c.segment ? ` · ${esc(c.segment)}` : ""}</span>
      ${c.flags.length ? `<div class="oflags">${c.flags.map((f) => `<span class="oflag l${f.level}" data-flag="${esc(f.key)}">${esc(f.text)}</span>`).join("")}</div>` : ""}
      ${clientMessages(c, doc)}</div>
    <div class="om om-spend"><span class="kl">Valor gasto</span><b>${esc(centsMoney(p.spend_cents, c.currency))}</b></div>
    <div class="om om-clicks"><span class="kl">Cliques no link</span><b>${esc(count(p.link_clicks))}</b>${p.cpl_cents != null ? `<span class="ksub">${esc(centsMoney(p.cpl_cents, c.currency))} cada</span>` : ""}</div>
    <div class="om om-results"><span class="kl">Resultados</span>${results}</div>
    <div class="om om-change"><span class="kl">Contra o período anterior</span>${change}</div>
    <div class="om om-trend"><span class="kl">${esc(trendLabel)}, 14 dias</span>${trendLine(c.days.map(trendOf), trendLabel)}</div>
    <div class="om om-balance"><span class="kl">Saldo</span>${balance}</div>
    <div class="om om-seen"><span class="kl">Visto</span>${seen}</div>
  </div>`;
}
async function viewOverview(query) {
  if (!metaVisible()) { location.hash = "#/"; return; }
  const st = readPeriod(query);
  const [since, until] = periodDates(st.p, st);
  const doc = await api("GET", `/api/campaigns/overview?since=${since}&until=${until}`);
  if (!onScreen("#/campanhas/geral")) return;
  savePeriod(st);
  trackPeriod(st);
  keepHash(`#/campanhas/geral?${periodQuery(st)}`);
  const segments = [...new Set(doc.clients.map((c) => c.segment).filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  if (!segments.includes(ovState.segment)) ovState.segment = "";
  const n = doc.clients.length;
  const head = `<div class="orow ohead" aria-hidden="true"><div class="oname">Cliente</div>${["Valor gasto", "Cliques no link", "Resultados", "Contra o período anterior", "Tendência, 14 dias", "Saldo", "Visto"].map((l) => `<div class="om">${l}</div>`).join("")}</div>`;
  app.innerHTML = `<div>
    <div class="head"><div><h1>Campanhas</h1><p id="ovsummary">${n} ${n === 1 ? "cliente" : "clientes"} com campanhas acompanhadas${doc.flagged ? `, <b>${doc.flagged} ${doc.flagged === 1 ? "pede" : "pedem"} atenção</b>` : n ? ", nenhum alerta" : ""}.</p></div></div>
    ${campTabs(st, "/geral")}
    ${periodPicker(st)}
    <p class="synced"><span class="muted small" id="syncline">${syncLine(doc.last_sync)}</span><span class="muted small">Os alertas comparam os últimos 7 dias com os 7 anteriores, sem contar hoje.</span></p>
    <div class="otools">
      <label class="toggle small"><input type="checkbox" id="onlyflagged" ${ovState.flagged ? "checked" : ""}>só com alerta</label>
      ${segments.length > 1 ? `<label class="pick">Segmento<select class="input" id="ovsegment"><option value="">Todos</option>${segments.map((s) => `<option${s === ovState.segment ? " selected" : ""}>${esc(s)}</option>`).join("")}</select></label>` : ""}
      <label class="pick">Tendência<select class="input" id="ovtrend">${Object.entries(TRENDS).map(([k, [label]]) => `<option value="${k}"${k === ovState.trend ? " selected" : ""}>${label}</option>`).join("")}</select></label>
    </div>
    <section class="panel" id="overview"></section>
  </div>`;
  const draw = () => {
    const shown = doc.clients.filter((c) => (!ovState.flagged || c.flags.length) && (!ovState.segment || c.segment === ovState.segment));
    $("#overview").innerHTML = shown.length ? `<div class="orows">${head}${shown.map((c) => overviewRow(c, doc)).join("")}</div>`
      : `<div class="empty"><span class="big">${n ? "✅" : "📣"}</span>${n ? "Nenhum cliente com alerta neste filtro." : "Nenhum cliente com campanha acompanhada ainda."}</div>`;
  };
  draw();
  bindPeriod(st, () => viewOverview(new URLSearchParams(periodQuery(st))));
  // the drafts are plain links; the log counts which kind was opened, never to whom
  $("#overview").addEventListener("click", (e) => { const a = e.target.closest("a[data-act]"); if (a) track("client_message", { kind: a.dataset.act }); });
  $("#onlyflagged").addEventListener("change", (e) => { ovState.flagged = e.target.checked; draw(); });
  $("#ovsegment")?.addEventListener("change", (e) => { ovState.segment = e.target.value; draw(); });
  $("#ovtrend").addEventListener("change", (e) => { ovState.trend = e.target.value; draw(); });
}

// A period Pauta hadn't read from Meta yet (a Personalizado range, mostly): the list came
// at once from the stored numbers with `reach_pending` on and "…" in the reach cells.
// Ask again until the read behind the page has landed, then put each number in its cell.
// The page is not redrawn: someone may be halfway through a click. Still pending after
// the last ask, or the ask failing, leaves the dash a failed reach always had.
const REACH_POLL_MS = 1500, REACH_POLL_MAX = 20; // every 1.5 s for up to 30 s
async function fillReach(url) {
  const list = $("#cblocks");
  let doc = null;
  for (let i = 0; i < REACH_POLL_MAX; i++) {
    await new Promise((r) => setTimeout(r, REACH_POLL_MS));
    if (!document.contains(list)) return;  // another screen, or this one drawn again
    try { doc = await api("GET", url); } catch { doc = null; break; }
    if (!document.contains(list)) return;
    if (!doc.reach_pending) break;
  }
  const reach = new Map((doc?.clients || []).flatMap((c) => c.campaigns.map((k) => [String(k.id), k])));
  list.querySelectorAll(".krow[data-id]").forEach((row) => {
    const cell = row.querySelector(".km-reach b");
    if (cell?.querySelector(".reading")) cell.innerHTML = reachCell(reach.get(row.dataset.id) || {});
  });
}

const campState = { skipped: false };  // "ver ignoradas", for the session
async function viewCampaigns(query) {
  if (!metaVisible()) { location.hash = "#/"; return; }
  const st = readPeriod(query);
  const [since, until] = periodDates(st.p, st);
  const url = `/api/campaigns?since=${since}&until=${until}${campState.skipped && ME.is_admin ? "&include_skipped=1" : ""}`;
  const doc = await api("GET", url);
  if (!onScreen("#/campanhas")) return;
  savePeriod(st);
  trackPeriod(st);  // after the call: an api_slow row sits next to the period that cost it
  keepHash(`#/campanhas?${periodQuery(st)}`);
  const n = doc.clients.reduce((a, c) => a + c.campaigns.filter((k) => k.state !== "skipped").length, 0);
  // a campaign younger than the period has numbers only from its "ativa desde" on
  const late = doc.clients.some((c) => c.campaigns.some((k) => k.state !== "skipped" && k.started && k.started > since));
  // the daily check (Visto hoje): clients still to see first, the seen ones sink; a client
  // whose linked accounts hold no campaign (nothing to check) comes last, so a portfolio
  // just connected shows up instead of looking like a failed connection
  const checkable = doc.clients.filter((c) => c.campaigns.length);
  const clients = [...checkable.filter((c) => !c.seen_today), ...checkable.filter((c) => c.seen_today), ...doc.clients.filter((c) => !c.campaigns.length)];
  const seen = doc.seen || { done: 0, total: checkable.length };
  // "Visto hoje: todos" while a client with a live campaign is still to see today
  const toSee = checkable.filter((c) => !c.seen_today && c.campaigns.some((k) => k.state === "active"));
  const seenBox = (c) => c.seen_today
    ? `<span class="seen" title="${esc(c.seen_today.at ? `às ${stamp(c.seen_today.at).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}` : "")}">${icon("check")}visto hoje${c.seen_today.by ? ` por ${esc(firstName(c.seen_today.by))}` : ""}</span>`
    : `<span class="row-gap"><button class="btn small" data-seen="${c.id}" data-name="${esc(c.name)}">${icon("check")}Visto hoje</button><button class="btn ghost small icon-only" data-seen="${c.id}" data-name="${esc(c.name)}" data-note="1" title="Visto hoje, com uma nota" aria-label="Visto hoje, com uma nota">${icon("msg")}</button></span>`;
  const head = `<div class="krow khead" aria-hidden="true"><div class="kname">Campanha</div>${METRIC_COLS.map(([key, label]) => `<div class="km km-${key}"><span>${label}</span></div>`).join("")}${ME.is_admin ? `<div class="kact"></div>` : ""}</div>`;
  // "Saldo da conta: R$ 1.000,00 até o limite", one per linked account (named when there
  // are several), the Saldo the decision promised next to the campaigns
  const balances = (c) => (c.accounts || []).length
    ? `<div class="kbals">${c.accounts.map((a) => `<span class="kbal" data-account="${esc(a.id)}">Saldo da conta${c.accounts.length > 1 ? ` ${esc(a.name)}` : ""}: <b>${metaBalance(a)}</b></span>`).join("")}</div>` : "";
  const noCampaigns = (c) => `<section class="panel cblock nocamp" data-client="${c.id}">
    <div class="panel-head"><h2><a href="#/cliente/${c.id}">${avatar(c.name)}${esc(c.name)}</a><span class="muted small">sem campanhas</span></h2></div>
    <p class="muted nocamp-line">sem campanhas ativas na(s) conta(s) vinculada(s): ${(c.accounts || []).map((a) => `<b>${esc(a.name)}</b>`).join(", ")}</p>
    ${balances(c)}</section>`;
  const block = (c) => !c.campaigns.length ? noCampaigns(c) : `<section class="panel cblock" data-client="${c.id}">
    <div class="panel-head"><h2><a href="#/cliente/${c.id}">${avatar(c.name)}${esc(c.name)}</a><span class="muted small">${c.campaigns.length} ${c.campaigns.length === 1 ? "campanha" : "campanhas"}</span></h2>${seenBox(c)}</div>
    ${balances(c)}
    <div class="krows">${head}
      <div class="krow ktotal"><div class="kname"><b>Total do cliente</b></div>${metricCells(clientTotals(c), true)}${ME.is_admin ? `<div class="kact"></div>` : ""}</div>
      ${c.campaigns.map((k) => `<div class="krow ${k.state === "skipped" ? "skipped" : ""}" data-id="${k.id}">
        <div class="kname"><a href="#/campanha/${k.id}"><b>${esc(k.name)}</b></a>${stateTag(k)}${sinceTag(k)}</div>
        ${metricCells(k, false, doc.reach_pending)}
        ${ME.is_admin ? `<div class="kact">${k.state === "skipped"
          ? `<button class="btn small" data-follow="${k.id}" data-name="${esc(k.name)}">${icon("check")}Acompanhar</button>`
          : `<button class="btn ghost small" data-skip="${k.id}" data-name="${esc(k.name)}" title="Tirar da lista; a Meta não é alterada">Não acompanhar</button>`}</div>` : ""}
      </div>`).join("")}
    </div></section>`;
  const empty = `<div class="panel empty"><span class="big">📣</span>Nenhuma campanha ativa nas contas vinculadas.${ME.is_admin ? ` Vincule contas em <a href="#/configuracoes">Configurações → Meta</a>.` : ""}</div>`;
  app.innerHTML = `<div>
    <div class="head"><div><h1>Campanhas</h1><p>${n} ${n === 1 ? "campanha acompanhada" : "campanhas acompanhadas"} de ${checkable.length} ${checkable.length === 1 ? "cliente" : "clientes"}.</p></div>
      ${ME.is_admin ? `<div class="actions"><label class="toggle small"><input type="checkbox" id="showskipped" ${campState.skipped ? "checked" : ""}>ver ignoradas</label>
        <button class="btn" id="syncnow">${icon("swap")}Atualizar agora</button></div>` : ""}</div>
    ${campTabs(st, "")}
    ${periodPicker(st)}
    <p class="synced" id="synced"><span class="muted small" id="syncline">${syncLine(doc.last_sync)}</span>${clients.length ? `<b id="seenline" class="${seen.done >= seen.total ? "alldone" : ""}">Hoje: ${seen.done} de ${seen.total} ${seen.total === 1 ? "cliente visto" : "clientes vistos"}</b>` : ""}${toSee.length ? `<button class="btn small" id="seenall" title="Marca visto hoje em todos os clientes com campanha ativa que ainda não foram vistos">${icon("check")}Visto hoje: todos</button>` : ""}${late ? `<span class="muted small" id="latenote">Campanha que começou depois de ${esc(shortDay(since))} só tem números a partir de "ativa desde".</span>` : ""}</p>
    <div id="cblocks">${clients.length ? clients.map(block).join("") : empty}</div>
  </div>`;
  const redraw = () => viewCampaigns(new URLSearchParams(periodQuery(st)));
  bindPeriod(st, redraw);
  if (doc.reach_pending) fillReach(url);
  $("#showskipped")?.addEventListener("change", (e) => { campState.skipped = e.target.checked; redraw(); });
  $("#syncnow")?.addEventListener("click", async (e) => {
    // the server answers 202 at once and syncs on its own thread: poll the list until the
    // pass ends, keeping the "Dados da Meta" line honest meanwhile. 409 "busy" means one
    // is already running (another admin's tap, the hourly one): wait for that one instead
    const btn = e.currentTarget, line = $("#syncline");
    btn.disabled = true;
    try {
      let previous = doc.last_sync;
      try {
        previous = (await api("POST", "/api/meta/sync", {})).last_sync;
      } catch (err) {
        if (err.reason !== "busy") throw err;
      }
      line.textContent = previous ? `Sincronizando com a Meta… (dados de ${ago(previous)})` : "Sincronizando com a Meta…";
      const done = await waitForSync(previous, since, until);
      if (done === SYNC_LEFT) return;
      if (!done) { toast("A sincronização ainda não terminou; os números aparecem quando acabar.", true); btn.disabled = false; return; }
      if (done === SYNC_LOST) { toast(SYNC_UNFINISHED, true); btn.disabled = false; return; }
      toast(done.sync_error ? `Sincronização com problema: ${done.sync_error}` : "Dados da Meta atualizados", Boolean(done.sync_error));
      redraw();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
  $("#seenall")?.addEventListener("click", async (e) => {
    // every client with a live campaign not yet seen today, in one request; the per-client
    // button and its note stay for the day someone has something to say about one client
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const out = await api("POST", "/api/reviews/today", {});
      track("seen_today", { n: out.clients });
      toast(out.clients ? `${out.clients} ${out.clients === 1 ? "cliente visto" : "clientes vistos"} hoje` : "Todos já estavam vistos hoje");
      redraw();
    } catch (err) { toast(err.message, true); btn.disabled = false; }
  });
  $$("[data-seen]").forEach((b) => b.addEventListener("click", async () => {
    let note = "";
    if (b.dataset.note) {
      note = prompt(`Nota de hoje sobre ${b.dataset.name} (opcional)`, "");
      if (note === null) return;
    }
    b.disabled = true;
    try {
      await api("POST", `/api/clients/${b.dataset.seen}/reviews`, { note });
      track("seen_today", { n: (doc.clients || []).find((c) => String(c.id) === b.dataset.seen)?.campaigns?.length || 0 });
      toast(`${b.dataset.name}: visto hoje`);
      redraw();
    } catch (err) { toast(err.message, true); b.disabled = false; }
  }));
  $$("[data-skip]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm(`Não acompanhar "${b.dataset.name}"? Ela sai desta lista (a Meta não muda). Dá para voltar em "ver ignoradas".`)) return;
    try { await api("PATCH", `/api/campaigns/${b.dataset.skip}`, { state: "skipped" }); toast("Campanha ignorada"); redraw(); }
    catch (err) { toast(err.message, true); }
  }));
  $$("[data-follow]").forEach((b) => b.addEventListener("click", async () => {
    try { await api("PATCH", `/api/campaigns/${b.dataset.follow}`, { state: "active" }); toast(`${b.dataset.name} de volta à lista`); redraw(); }
    catch (err) { toast(err.message, true); }
  }));
}

// A "Criar campanha" request just marked Concluído: which campaign did it produce? The
// chooser lists the client's campaigns that started in the last 7 days and have no request
// yet, "Nenhuma" first (the default: a done request isn't always a new campaign). Choosing
// one sets `campaign.request` (admins; the API refuses the rest), so the campaign page says
// "Pedido #n" and the request's timeline says which campaign. Nothing shows when there is
// no candidate. The kinds are the team's (Configurações → Campanhas). `onLinked` runs after
// a link is made (the request page redraws its timeline).
const trackingKinds = () => BOOT?.campaigns?.tracking_kinds || [];
const LINK_DAYS_BACK = 7;
async function offerCampaignLink(r, onLinked) {
  if (!metaVisible() || !ME.is_admin || !trackingKinds().includes(r.kind)) return;
  const t = todayISO(), floor = addDays(t, -LINK_DAYS_BACK);
  let doc;
  try { doc = await api("GET", `/api/campaigns?client=${r.client}&since=${floor}&until=${t}`); }
  catch { return; }  // Meta down, or nothing to list: the link can wait for the sync
  const candidates = (doc.clients[0]?.campaigns || []).filter((k) => !k.request && k.state !== "skipped" && k.started && k.started >= floor);
  if (!candidates.length) return;
  const m = $("#modal");
  m.innerHTML = `<form class="panel" id="linkcamp"><h2>Qual campanha o pedido #${r.id} criou?</h2>
    <p class="muted small" style="margin:-8px 0 14px">Campanhas de <b>${esc(r.client_name || "")}</b> que começaram nos últimos ${LINK_DAYS_BACK} dias e ainda não têm pedido. A campanha passa a mostrar "Pedido #${r.id}".</p>
    <div class="field"><label>Campanha</label><select class="input" name="campaign"><option value="">Nenhuma</option>${candidates.map((k) => `<option value="${k.id}">${esc(k.name)} · ativa desde ${esc(shortDay(k.started))}</option>`).join("")}</select></div>
    <div class="actions"><button type="button" class="btn ghost" data-a="cancel">Agora não</button><button class="btn primary" data-a="ok">Vincular</button></div></form>`;
  m.hidden = false;
  const close = () => { m.hidden = true; m.innerHTML = ""; };
  const f = $("#linkcamp");
  f.campaign.focus();
  m.onclick = (e) => { if (e.target === m || e.target.dataset.a === "cancel") close(); };
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const id = f.campaign.value;
    if (!id) { close(); return; }
    try {
      const k = await api("PATCH", `/api/campaigns/${id}`, { request: r.id });
      close();
      toast(`${k.name}: vinculada ao pedido #${r.id}`);
      if (onLinked) onLinked(k);
    } catch (err) { toast(err.message, true); }
  });
}

// One campaign: the period's cards and daily charts for the metrics picked. `period` gives the
// period value from the campaign's sums, `day` one day's from an insight row; a metric
// without `day` (frequency: impressions ÷ reach, and reach only comes per period) has no chart;
// `sub` names what Resultados count, under the value, as Ads Manager does; `explain` is the
// one plain line under each number on the client's report (what is being measured).
const METRICS = {
  results: { label: "Resultados", fmt: "count", period: (k) => k.results, day: (d) => d.results, sub: (k) => resultLabel(k.result_indicator), note: "o que o objetivo da campanha conta", explain: "Quantas vezes a campanha entregou o que ela busca no período." },
  cpr: { label: "Custo por resultado", fmt: "money", period: (k) => k.cost_per_result_cents, day: (d) => centsPer(d.spend_cents, d.results), sub: (k) => resultLabel(k.result_indicator), explain: "Quanto custou, em média, cada resultado." },
  spend: { label: "Valor gasto", fmt: "money", period: (k) => k.spend_cents, day: (d) => d.spend_cents, explain: "Quanto foi investido em anúncios no período." },
  leads: { label: "Cliques no link", fmt: "count", period: (k) => k.link_clicks, day: (d) => d.link_clicks, explain: "Quantas vezes alguém clicou no link do anúncio." },
  cpl: { label: "Custo por clique no link", fmt: "money", period: (k) => k.cpl_cents, day: (d) => centsPer(d.spend_cents, d.link_clicks), explain: "Quanto custou, em média, cada clique no link." },
  reach: { label: "Alcance", fmt: "count", period: (k) => k.reach, day: (d) => d.reach, note: "no período, pessoas diferentes (da Meta); por dia, as de cada dia", explain: "Quantas pessoas diferentes viram o anúncio pelo menos uma vez." },
  impressions: { label: "Impressões", fmt: "count", period: (k) => k.impressions, day: (d) => d.impressions, explain: "Quantas vezes o anúncio apareceu na tela; a mesma pessoa pode contar mais de uma vez." },
  ctr: { label: "Taxa de cliques (CTR)", fmt: "pct", period: (k) => k.impressions ? k.link_clicks / k.impressions : null, day: (d) => d.impressions ? d.link_clicks / d.impressions : null, note: "cliques no link ÷ impressões", explain: "De cada 100 vezes que o anúncio apareceu, quantas viraram um clique no link." },
  cpm: { label: "Custo por mil impressões (CPM)", fmt: "money", period: (k) => k.impressions ? k.spend_cents / k.impressions * 1000 : null, day: (d) => d.impressions ? d.spend_cents / d.impressions * 1000 : null, note: "valor gasto ÷ impressões × 1.000", explain: "Quanto custou para o anúncio aparecer mil vezes." },
  freq: { label: "Frequência", fmt: "dec", period: (k) => k.reach ? k.impressions / k.reach : null, note: "impressões ÷ alcance, só no período", explain: "Quantas vezes, em média, cada pessoa viu o anúncio." },
};
// the action chips: Ads Manager's words, told apart where two types would read the same
const ACTION_LABELS = {
  ...RESULT_LABELS, "onsite_conversion.lead_grouped": "Cadastros (Meta, agrupados)", omni_purchase: "Compras (todas)",
  "onsite_conversion.purchase": "Compras (loja da Meta)", comment: "Comentários", like: "Curtidas",
  post_reaction: "Reações", post: "Compartilhamentos", "onsite_conversion.post_save": "Salvamentos", add_to_cart: "Adições ao carrinho",
  initiate_checkout: "Finalizações de compra iniciadas",
  // the ones on the team's campaigns (2026-11-04)
  "onsite_conversion.lead": "Cadastros na Meta", onsite_web_lead: "Cadastros no site",
  offsite_complete_registration_add_meta_leads: "Cadastros concluídos (site + Meta)",
  offsite_content_view_add_meta_leads: "Visualizações de conteúdo (site + Meta)",
  offsite_search_add_meta_leads: "Pesquisas (site + Meta)",
  onsite_app_purchase: "Compras no app", onsite_web_purchase: "Compras no site (dados da Meta)",
  onsite_web_app_purchase: "Compras no site e no app",
  "onsite_conversion.post_net_like": "Curtidas na publicação (líquidas)", "onsite_conversion.post_unlike": "Descurtidas na publicação",
  post_interaction_gross: "Interações com a publicação (brutas)", post_interaction_net: "Interações com a publicação (líquidas)",
  // messaging
  "onsite_conversion.total_messaging_connection": "Conexões por mensagem",
  "onsite_conversion.messaging_user_depth_2_message_send": "Conversas com 2 mensagens",
  "onsite_conversion.messaging_user_depth_3_message_send": "Conversas com 3 mensagens",
  "onsite_conversion.messaging_block": "Bloqueios de mensagens",
  "onsite_conversion.messaging_welcome_message_view": "Mensagens de boas-vindas vistas",
  "onsite_conversion.messaging_order_created": "Pedidos criados por mensagem",
  // leads and forms
  "offsite_conversion.fb_pixel_lead": "Cadastros no site (pixel)",
  leadgen_grouped: "Cadastros (formulários)", "onsite_conversion.flow_complete": "Fluxos concluídos",
  "onsite_conversion.lead_form_grouped": "Cadastros (formulário instantâneo)",
  // site events (pixel)
  "offsite_conversion.fb_pixel_purchase": "Compras (no site)", "offsite_conversion.fb_pixel_add_to_cart": "Adições ao carrinho (no site)",
  omni_add_to_cart: "Adições ao carrinho (todas)", "offsite_conversion.fb_pixel_initiate_checkout": "Finalizações de compra iniciadas (no site)",
  omni_initiated_checkout: "Finalizações de compra iniciadas (todas)", view_content: "Visualizações de conteúdo",
  omni_view_content: "Visualizações de conteúdo (todas)", complete_registration: "Cadastros concluídos",
  "offsite_conversion.fb_pixel_complete_registration": "Cadastros concluídos (no site)", omni_complete_registration: "Cadastros concluídos (todos)",
  search: "Pesquisas", "offsite_conversion.fb_pixel_search": "Pesquisas (no site)", omni_search: "Pesquisas (todas)",
  add_payment_info: "Informações de pagamento adicionadas", "offsite_conversion.fb_pixel_add_payment_info": "Informações de pagamento adicionadas (no site)",
  add_to_wishlist: "Adições à lista de desejos", "offsite_conversion.fb_pixel_add_to_wishlist": "Adições à lista de desejos (no site)",
  contact: "Contatos", schedule: "Agendamentos", submit_application: "Inscrições enviadas", subscribe: "Assinaturas",
  start_trial: "Avaliações iniciadas", donate: "Doações", find_location: "Buscas por localização", customize_product: "Produtos personalizados",
  "offsite_conversion.fb_pixel_custom": "Conversões personalizadas", "offsite_conversion.custom": "Conversões personalizadas",
  offsite_conversion: "Conversões no site", offline_conversion: "Conversões offline",
  // page, post and video
  photo_view: "Visualizações de foto", "onsite_conversion.ig_profile_visit": "Visitas ao perfil",
  rsvp: "Respostas a eventos", checkin: "Check-ins", video_play: "Reproduções de vídeo",
  // calls and app
  click_to_call_call_confirm: "Ligações confirmadas", click_to_call_native_call_placed: "Ligações feitas",
  app_install: "Instalações do app", omni_app_install: "Instalações do app (todas)", mobile_app_install: "Instalações do app (celular)",
  app_use: "Usos do app", app_custom_event: "Eventos no app", omni_activate_app: "Aberturas do app",
};
const DEFAULT_METRICS = ["results", "cpr", "spend"];
const ACTION_EXPLAIN = "Quantas vezes essa ação aconteceu por causa do anúncio.";
function metricDefs(k) {
  const defs = { ...METRICS };
  for (const type of Object.keys(k.actions || {}).sort()) {
    if (type === "link_click") continue;  // Cliques no link is already a metric above
    defs[`act:${type}`] = { label: ACTION_LABELS[type] || cleanType(type), fmt: "count", period: (c) => c.actions?.[type] ?? 0, day: (d) => d.actions?.[type] ?? 0, note: `o que a Meta chama de ${type}` };
  }
  return defs;
}
function fmtMetric(v, fmt, cur) {
  if (v == null || Number.isNaN(v)) return "—";
  if (fmt === "money") return centsMoney(Math.round(v), cur);
  if (fmt === "pct") return `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}%`;
  if (fmt === "dec") return v.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
  return count(Math.round(v));
}
function readMetrics() {
  try {
    const got = JSON.parse(localStorage.getItem("pauta.metrics") || "null");
    if (Array.isArray(got) && got.every((x) => typeof x === "string")) {
      // the link_click action chip is gone (it is Cliques no link): a choice from before keeps the card
      const keys = got.map((x) => x === "act:link_click" ? "leads" : x);
      return keys.filter((x, i) => keys.indexOf(x) === i);
    }
  } catch { /* fall through */ }
  return [...DEFAULT_METRICS];
}

// A plain SVG bar chart, one bar per day of the period (no library: CSP stays 'self'). The
// labels (the max above, the first and last day below) are HTML around the SVG, so they
// keep their size however narrow the card is; each bar carries a <title>.
function chart(points, fmt, cur) {
  const W = 600, H = 140, n = points.length, bw = W / n;
  const max = Math.max(0, ...points.map((p) => p.v ?? 0)) || 1;
  const bars = points.map((p, i) => {
    if (p.v == null) return "";
    const h = Math.max(p.v > 0 ? 1.5 : 0, p.v / max * (H - 2));
    const x = i * bw + bw * 0.15, w = Math.max(1, bw * 0.7);
    return `<rect x="${x.toFixed(1)}" y="${(H - h).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}"><title>${esc(fmtDate(p.day))}: ${esc(fmtMetric(p.v, fmt, cur))}</title></rect>`;
  }).join("");
  return `<div class="chartbox">
    <div class="chart-y"><span>máx. por dia</span> ${esc(fmtMetric(max, fmt, cur))}</div>
    <svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Por dia, de ${esc(fmtDate(points[0].day))} a ${esc(fmtDate(points[n - 1].day))}">${bars}<line class="axis" x1="0" x2="${W}" y1="${H - 0.5}" y2="${H - 0.5}"/></svg>
    <div class="chart-x"><span>${esc(fmtDate(points[0].day))}</span><span>${esc(fmtDate(points[n - 1].day))}</span></div>
  </div>`;
}
function dayPoints(k, since, until, metric) {
  const byDay = Object.fromEntries((k.days || []).map((d) => [d.day, d]));
  const out = [];
  for (let day = since; day <= until && out.length < 800; day = addDays(day, 1)) {
    const row = byDay[day];
    out.push({ day, v: row ? metric.day(row) : null });
  }
  return out;
}

async function viewCampaign(query, id) {
  if (!metaVisible()) { location.hash = "#/"; return; }
  const st = readPeriod(query);
  const [since, until] = periodDates(st.p, st);
  const doc = await api("GET", `/api/campaigns/${id}?since=${since}&until=${until}`);
  if (!onScreen(`#/campanha/${id}`)) return;
  const k = doc.campaign;
  savePeriod(st);
  trackPeriod(st);
  keepHash(`#/campanha/${id}?${periodQuery(st)}`);
  const defs = metricDefs(k);
  let picked = readMetrics();
  // the metrics are always chips; the actions Meta reports (there can be twenty) sit behind
  // "Mais métricas" unless one is marked, so the row stays short
  let more = false;
  const chips = () => {
    const chip = ([key, m]) => `<button type="button" class="chip ${picked.includes(key) ? "on" : ""}" data-metric="${esc(key)}" aria-pressed="${picked.includes(key)}" ${m.note ? `title="${esc(m.note)}"` : ""}>${esc(m.label)}</button>`;
    const all = Object.entries(defs);
    const actions = all.filter(([key]) => key.startsWith("act:"));
    const hidden = more ? [] : actions.filter(([key]) => !picked.includes(key));
    const toggle = actions.length && !more && hidden.length
      ? `<button type="button" class="chip more" id="morechips" title="As ações que a Meta registra nesta campanha">Mais métricas (${hidden.length})</button>`
      : actions.length && more ? `<button type="button" class="chip more" id="morechips">Menos métricas</button>` : "";
    return all.filter((e) => !hidden.includes(e)).map(chip).join("") + toggle;
  };
  const cards = () => {
    const shown = picked.filter((key) => defs[key]);
    if (!shown.length) return `<div class="panel empty">Escolha uma métrica acima.</div>`;
    return shown.map((key) => {
      const m = defs[key];
      const v = m.period(k), sub = m.sub ? m.sub(k) : "";
      return `<section class="panel mcard" data-card="${esc(key)}">
        <div class="panel-head"><h3>${esc(m.label)}</h3></div>
        <div class="mval" ${m.sub && v == null ? `title="${NO_RESULTS}"` : ""}>${esc(fmtMetric(v, m.fmt, k.currency))}</div>
        ${sub ? `<div class="msub">${esc(sub)}</div>` : ""}
        <p class="mwhy muted small">${esc(m.explain || ACTION_EXPLAIN)}</p>
        ${m.day ? chart(dayPoints(k, since, until, m), m.fmt, k.currency) : `<p class="muted small">Só no período: não há valor por dia.</p>`}
      </section>`;
    }).join("");
  };
  const when = [k.started ? `desde ${esc(fmtDate(k.started, { day: "2-digit", month: "2-digit", year: "numeric" }))}` : "",
    k.ended ? `até ${esc(fmtDate(k.ended, { day: "2-digit", month: "2-digit", year: "numeric" }))}` : ""].filter(Boolean).join(" · ");
  app.innerHTML = `<div>
    <div class="crumb"><a href="#/campanhas">Campanhas</a><span>/</span><span>${esc(k.name)}</span></div>
    <div class="head"><div>
      <div class="row-gap"><a class="cl" href="#/cliente/${k.client}">${avatar(k.client_name || "?", "md")}<span style="font-size:16px">${esc(k.client_name || "—")}</span></a>${stateTag(k)}</div>
      <h1 id="kname">${esc(k.name)}</h1>
      <p>${when}${k.objective ? ` · objetivo: ${esc(objectiveLabel(k.objective))}` : ""}${k.request ? ` · <a href="#/pedido/${k.request}">Pedido #${k.request}</a>` : ""}</p>
    </div><div class="actions"><button class="btn primary" id="mkreport" title="Uma tela limpa, com as métricas marcadas abaixo, para tirar um print e mandar ao cliente">${icon("send")}Gerar relatório</button></div></div>
    ${periodPicker(st)}
    <p class="muted small synced" id="synced">${syncLine(doc.last_sync)}</p>
    <p class="muted small chips-note">As métricas marcadas aqui são as que entram no relatório para o cliente.</p>
    <div class="chips" id="metrics">${chips()}</div>
    <div class="mcards" id="cards">${cards()}</div>
    <section class="panel links" id="links" ${doc.links?.length ? "" : "hidden"}>${linksPanel(doc.links || [])}</section>
  </div>`;
  bindPeriod(st, () => viewCampaign(new URLSearchParams(periodQuery(st)), id));
  // Revogar: the link is a 404 from then on; the row stays in the list as history
  const links = $("#links");  // this campaign's, wherever the person is when Revogar answers
  links.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-revoke]");
    if (!b) return;
    b.disabled = true;
    try {
      const row = await api("DELETE", `/api/campaigns/${id}/links/${b.dataset.revoke}`);
      doc.links = doc.links.map((l) => l.token === row.token ? row : l);
      links.innerHTML = linksPanel(doc.links);
      toast("Link desativado");
    } catch (err) { toast(err.message, true); b.disabled = false; }
  });
  // Gerar relatório: the period and the marked metrics travel in the address, so the report
  // is one screen to print (and to reopen later with the same choices)
  $("#mkreport").addEventListener("click", () => {
    const shown = picked.filter((key) => defs[key]);
    if (!shown.length) { toast("Marque ao menos uma métrica para o relatório", true); return; }
    if (shown.length > REPORT_TILE_MAX) { toast(`O relatório cabe ${REPORT_TILE_MAX} métricas; desmarque ${shown.length - REPORT_TILE_MAX}`, true); return; }
    location.hash = reportHash(id, st, shown);
  });
  $("#metrics").addEventListener("click", (e) => {
    if (e.target.closest("#morechips")) { more = !more; $("#metrics").innerHTML = chips(); return; }
    const b = e.target.closest("[data-metric]");
    if (!b) return;
    const key = b.dataset.metric;
    picked = picked.includes(key) ? picked.filter((x) => x !== key) : [...picked, key];
    if (key.startsWith("act:") && !picked.includes(key)) more = true;  // the chip just unmarked stays in view
    try { localStorage.setItem("pauta.metrics", JSON.stringify(picked)); } catch { /* not remembered */ }
    $("#metrics").innerHTML = chips();
    $("#cards").innerHTML = cards();
  });
}

// The report links made for this campaign (decision 12): the card each one opens (period,
// how many metrics), who made it and when, until when it opens, and Revogar while it does.
function linksPanel(links) {
  const row = (l) => {
    const n = l.metrics.length;
    const state = l.revoked ? `desativado em ${esc(stampDay(l.revoked))}`
      : l.live ? `válido até ${esc(validUntil(l.expires))} · <a href="${esc(l.url)}" target="_blank" rel="noopener">abrir</a>`
      : `expirou em ${esc(validUntil(l.expires))}`;
    return `<li class="linkrow ${l.live ? "" : "off"}" data-token="${esc(l.token)}">
      <div class="grow"><b>${esc(periodLabel(l.since, l.until))}</b> · ${n} ${n === 1 ? "métrica" : "métricas"} · por ${esc(firstName(l.by_name) || "—")} em ${esc(stampDay(l.created))}<br><span class="muted small">${state}</span></div>
      ${l.live ? `<button type="button" class="btn small" data-revoke="${esc(l.token)}">Revogar</button>` : ""}
    </li>`;
  };
  return `<div class="panel-head"><h3>Links do relatório</h3><span class="muted small">abrem sem conta, por 5 dias</span></div>
    <ul class="linklist">${links.map(row).join("")}</ul>`;
}

// ---------- relatório (the client's dashboard) ---------------------------------------------

// One clean screen to screenshot and send to the client on WhatsApp: no app chrome (the
// router hides the shell for #/relatorio/...), the campaign, the client, the period, the
// metrics marked on the campaign page as tiles with one plain line under each number
// (what is being measured), a small bar per day where the metric has days, and the
// Compartilhar com o cliente button that opens WhatsApp on the client's registered number
// with the message ready (the person attaches the print there). The colours are fixed
// (light paper, the accent) whatever the phone's theme, so every client gets the same look.
const reportHash = (id, st, keys) => `#/relatorio/${id}?${periodQuery(st)}&m=${encodeURIComponent(keys.join(","))}`;
const REPORT_TILE_MAX = 12;  // a print is one screen: more than this would not fit a phone
// a compact sparkline, one bar per day, the latest day in full colour
function spark(points) {
  const W = 300, H = 40, n = points.length, bw = W / n;
  const max = Math.max(0, ...points.map((p) => p.v ?? 0)) || 1;
  const bars = points.map((p, i) => {
    if (p.v == null) return "";
    const h = Math.max(p.v > 0 ? 2 : 0, p.v / max * H);
    return `<rect x="${(i * bw + bw * 0.15).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${Math.max(1, bw * 0.7).toFixed(1)}" height="${h.toFixed(1)}" rx="1" class="${i === n - 1 ? "last" : ""}"/>`;
  }).join("");
  return `<svg class="rep-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">${bars}</svg>`;
}
// the WhatsApp message that goes with the print: short, in the client's language
function shareText(k, since, until) {
  const who = firstName(k.client_contact);
  return `Olá${who ? `, ${who}` : ""}! Segue o relatório da campanha "${k.name}" (${periodLabel(since, until)}), com o andamento até agora. Qualquer dúvida, é só me chamar.`;
}
// The card as a PNG, drawn in the browser (no server, no library: the card's own markup
// goes into an SVG <foreignObject> with the stylesheet, the SVG is drawn on a canvas at 3x).
// The logo is inlined (an image in an SVG can't load files). Safari wants a data: URL.
async function cardImage(node, scale = 3) {
  const [css, icon] = await Promise.all([fetch("/style.css").then((r) => r.text()), fetch("/icon.svg").then((r) => r.text())]);
  const style = css.replace(/url\(\/icon\.svg\)/g, `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(icon)}")`);
  if (style.includes("]]>")) throw new Error("estilo inválido para a imagem");
  const w = Math.ceil(node.getBoundingClientRect().width), h = Math.ceil(node.getBoundingClientRect().height);
  const html = new XMLSerializer().serializeToString(node);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}"><foreignObject width="100%" height="100%"><div xmlns="http://www.w3.org/1999/xhtml" class="shot" style="width:${w}px"><style><![CDATA[${style}]]></style>${html}</div></foreignObject></svg>`;
  const img = new Image();
  await new Promise((ok, no) => { img.onload = ok; img.onerror = () => no(new Error("não deu para desenhar a imagem")); img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`; });
  try { await img.decode(); } catch { /* drawn below anyway */ }
  const canvas = document.createElement("canvas");
  canvas.width = w * scale; canvas.height = h * scale;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#ebeaf3";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return new Promise((ok, no) => canvas.toBlob((b) => b ? ok(b) : no(new Error("não deu para gerar a imagem")), "image/png"));
}
const slug = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase().slice(0, 40) || "campanha";
// the clipboard takes one PNG, to paste in the conversation (the phone's share sheet was
// tried first: its own "Copiar" put the file there as two items and WhatsApp pasted two
// photos, so the team asked for this one button); a browser whose clipboard takes no image
// gets the PNG as a download instead
const canCopyImage = () => Boolean(navigator.clipboard?.write && window.ClipboardItem);

// The card itself, shared with the client's public page (app-report.js, decision 12): `keys`
// are the metric keys to tile, `defs` metricDefs(k), `by` the preparer's first name.
function reportCard(k, { since, until, keys, defs, lastSync, by }) {
  const tile = (key, i) => {
    const m = defs[key];
    const v = m.period(k), sub = m.sub ? m.sub(k) : "";
    const explain = m.explain || ACTION_EXPLAIN;
    const points = m.day ? dayPoints(k, since, until, m) : [];
    const text = fmtMetric(v, m.fmt, k.currency);
    // a long value ("R$ 123.456,78") takes the whole row rather than shrinking to nothing
    return `<section class="rep-tile ${i === 0 ? "hero" : text.length > 10 ? "wide" : ""}" data-tile="${esc(key)}">
      <span class="rep-label">${esc(m.label)}</span>
      <b class="rep-val">${esc(text)}</b>
      ${sub ? `<span class="rep-sub">${esc(sub)}</span>` : ""}
      <p class="rep-why">${esc(explain)}</p>
      ${points.length > 1 && points.some((p) => p.v) ? spark(points) : ""}
    </section>`;
  };
  const ended = k.state !== "active" && k.ended ? ` · encerrada em ${esc(fmtDate(k.ended, { day: "2-digit", month: "2-digit", year: "numeric" }))}` : "";
  const today = todayISO();
  return `<article class="rep" id="rep">
      <header class="rep-hero">
        <span class="rep-kicker">Relatório de campanha</span>
        <h1>${esc(k.name)}</h1>
        <div class="rep-client">${avatar(k.client_name || "?", "md")}<span>${esc(k.client_name || "—")}</span></div>
        <p class="rep-period">${esc(since === until ? shortDay(since) : periodLabel(since, until))}${until >= today ? (since === until ? " · hoje" : " · até hoje") : ""}${k.state === "active" ? " · campanha ativa" : k.state === "paused" ? " · campanha pausada" : ended}</p>
      </header>
      <div class="rep-tiles">${keys.map(tile).join("")}</div>
      <footer class="rep-foot">
        <span>${lastSync ? `Dados da Meta de ${esc(stamp(lastSync).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", ""))}` : "Dados da Meta"}${by ? ` · preparado por ${esc(by)}` : ""}</span>
        <span class="rep-brand"><span class="logo" aria-hidden="true"></span>pauta</span>
      </footer>
    </article>`;
}
// "4 de dezembro": when a link stops opening (`expires` is a UTC stamp, shown as the local day)
const validUntil = (expires) => stamp(expires).toLocaleDateString("pt-BR", { day: "numeric", month: "long" });
const stampDay = (s) => stamp(s).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", "");

async function viewReport(query, id) {
  if (!metaVisible()) { location.hash = "#/"; return; }
  const st = readPeriod(query);
  const [since, until] = periodDates(st.p, st);
  const doc = await api("GET", `/api/campaigns/${id}?since=${since}&until=${until}`);
  const k = doc.campaign;
  const defs = metricDefs(k);
  // the metrics from the address (the campaign page's choice), else the ones marked there
  const asked = (query.get("m") || "").split(",").filter((key) => defs[key]);
  const keys = (asked.length ? asked : readMetrics().filter((key) => defs[key])).slice(0, REPORT_TILE_MAX);
  const shown = keys.length ? keys : DEFAULT_METRICS;
  const wa = waUrl(k.client_whatsapp);
  // the public link (decision 12): the one the team already made for this very card (same
  // period, same metrics, still open), else made on the first tap of Copiar link or Abrir
  // conversa. The WhatsApp message carries it once it exists.
  let link = (doc.links || []).find((l) => l.live && l.since === since && l.until === until && l.metrics.join(",") === shown.join(",")) || null;
  const text = () => shareText(k, since, until) + (link ? `\n\nVeja o relatório aqui: ${link.url}` : "");
  const waHref = () => `${wa}?text=${encodeURIComponent(text())}`;
  const linkInfo = () => link ? `Link do relatório válido até ${esc(validUntil(link.expires))}: <span class="linkurl">${esc(link.url)}</span>` : "";
  async function ensureLink() {
    if (!link) {
      link = await api("POST", `/api/campaigns/${id}/links`, { since, until, metrics: shown });
      if (!root.isConnected) return link;
      if (wa) $("#share").href = waHref();
      $("#linkinfo").innerHTML = linkInfo();
    }
    return link;
  }
  const image = `<button class="btn primary" id="copyimg">${icon("image")}Copiar imagem</button>`;
  const copy = `<button class="btn" id="copylink" title="Um endereço do relatório que abre sem conta, por 5 dias">${icon("link")}Copiar link</button>`;
  const share = wa
    ? `<a class="btn" id="share" href="${esc(waHref())}" target="_blank" rel="noopener">${icon("send")}Abrir conversa</a>`
    : `<button class="btn" id="share" disabled title="O cliente não tem WhatsApp cadastrado">${icon("send")}Abrir conversa</button>`;
  // no explanation under the buttons (the team's ask); only the missing number is worth a line,
  // and the link's "válido até" once there is one
  const hint = wa ? "" : `<b>${esc(k.client_name || "O cliente")}</b> não tem WhatsApp cadastrado: ${k.client ? `<a href="#/cliente/${k.client}">cadastre o número</a>` : "cadastre o número"} para abrir a conversa daqui.`;
  app.innerHTML = `<div class="report">
    <div class="report-tools">
      <div class="row-gap"><a class="btn" href="#/campanha/${id}?${periodQuery(st)}">${icon("back")}Voltar à campanha</a>${image}${copy}${share}</div>
      ${hint ? `<p class="muted small" id="sharehint">${hint}</p>` : ""}
      <p class="muted small" id="linkinfo">${linkInfo()}</p>
    </div>
    ${reportCard(k, { since, until, keys: shown, defs, lastSync: doc.last_sync, by: firstName(ME.name) })}
  </div>`;
  const root = app.firstElementChild;  // off the page once the person leaves the report
  // Copiar link: the link is made on the first tap. Safari only writes the clipboard inside
  // the tap, but a ClipboardItem takes a promise, so the address can still be made first.
  $("#copylink").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const made = ensureLink();
    const blob = made.then((l) => new Blob([l.url], { type: "text/plain" }));
    blob.catch(() => {});  // a failure to make the link is reported from `made` below
    try {
      try {
        if (typeof ClipboardItem === "function" && navigator.clipboard?.write) await navigator.clipboard.write([new ClipboardItem({ "text/plain": blob })]);
        else await navigator.clipboard.writeText((await made).url);
        await made;
        toast(`Link copiado · válido até ${validUntil(link.expires)}`);
      } catch (err) {
        await made;  // the link exists: only the copying failed
        toast("Não deu para copiar: selecione o link abaixo", true);
      }
    } catch (err) { toast(err.message, true); }
    btn.disabled = false;
  });
  // Abrir conversa before any link exists: the tab opens now (inside the tap, or Safari
  // blocks it) and goes to WhatsApp once the link is made
  $("#share").addEventListener("click", (e) => {
    if (link || !wa) return;  // the address already carries the link: a plain link
    e.preventDefault();
    const tab = window.open("", "_blank");
    if (tab) tab.opener = null;
    ensureLink()
      .then(() => { const href = waHref(); if (tab) tab.location.replace(href); else location.assign(href); })
      .catch((err) => { tab?.close(); toast(err.message, true); });
  });
  // the image is drawn as soon as the card is on screen, so the tap on Copiar imagem has it
  // ready (Safari takes a clipboard write only right after a tap)
  const name = `relatorio-${slug(k.client_name)}-${slug(k.name)}-${since}-${until}.png`;
  let shot = cardImage($("#rep")).catch((e) => e);
  $("#copyimg").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      // the ClipboardItem takes the promise: Safari wants the write inside the tap itself
      const png = shot.then((b) => { if (b instanceof Error) throw b; return b; });
      if (canCopyImage()) {
        await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
        toast("Imagem copiada: cole na conversa do WhatsApp");
      } else {
        let blob = await shot;
        if (blob instanceof Error) { shot = cardImage($("#rep")); blob = await shot; }  // once more, on the tap
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 60_000);
        toast("Imagem baixada: anexe na conversa");
      }
    } catch (err) { toast(`Não deu para copiar: ${err.message}`, true); }
    btn.disabled = false;
  });
}
