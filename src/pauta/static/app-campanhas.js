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
  for (let i = 0; i < SYNC_POLL_MAX; i++) {
    await new Promise((r) => setTimeout(r, i ? SYNC_POLL_MS : 1000));
    if (!document.contains($("#syncline"))) return SYNC_LEFT;
    const doc = await api("GET", `/api/campaigns?since=${since}&until=${until}`);
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
// a type neither list knows reads word by word in Portuguese (approximate, but never a raw
// key like "offsite_search_add_meta_leads" on the screen), Meta's prefixes dropped
const TYPE_WORDS = {
  meta: "Meta", pixel: "", fb: "", conversion: "", conversions: "conversões", custom: "personalizadas", offline: "offline", omni: "todas",
  purchase: "compras", purchases: "compras", lead: "cadastros", leads: "cadastros", registration: "cadastros", complete: "concluídos",
  view: "visualizações", views: "visualizações", content: "de conteúdo", search: "pesquisas", add: "+", cart: "carrinho", wishlist: "lista de desejos",
  checkout: "finalizações de compra", initiate: "iniciadas", initiated: "iniciadas", payment: "pagamento", info: "informações",
  subscribe: "assinaturas", trial: "testes", start: "iniciados", schedule: "agendamentos", contact: "contatos", donate: "doações",
  post: "publicação", like: "curtidas", likes: "curtidas", unlike: "descurtidas", net: "líquidas", gross: "brutas",
  interaction: "interações", interactions: "interações", reaction: "reações", comment: "comentários", share: "compartilhamentos",
  save: "salvamentos", engagement: "engajamentos", page: "Página", photo: "foto", video: "vídeo", play: "reproduções", plays: "reproduções",
  message: "mensagem", messaging: "mensagens", conversation: "conversas", started: "iniciadas", connection: "conexões", total: "total",
  user: "", depth: "com", send: "enviadas", first: "primeira", reply: "resposta", welcome: "boas-vindas", block: "bloqueios",
  order: "pedidos", created: "criados", flow: "fluxos", form: "formulário", grouped: "", landing: "página de destino",
  click: "cliques", clicks: "cliques", link: "no link", call: "ligações", confirm: "confirmadas", placed: "feitas", native: "",
  install: "instalações", installs: "instalações", use: "usos", event: "eventos", response: "respostas", rsvp: "respostas a eventos",
  checkin: "check-ins", visit: "visitas", profile: "ao perfil", follow: "seguidores", ig: "Instagram", d2: "", d7: "", "7d": "", "28d": "",
};
const TYPE_PLACES = { offsite: "no site", onsite: "na Meta", web: "no site", app: "no app" };
function cleanType(type) {
  const words = String(type || "").split(/[._]+/).filter(Boolean);
  const places = [...new Set(words.filter((w) => TYPE_PLACES[w]).map((w) => TYPE_PLACES[w]))];
  const rest = words.filter((w) => !TYPE_PLACES[w]).map((w) => w in TYPE_WORDS ? TYPE_WORDS[w] : /^\d/.test(w) ? "" : w).filter(Boolean);
  const where = places.filter((x) => x !== "na Meta" || places.length === 1).join(" e ");  // "no site e no app"
  return [...rest, where].filter(Boolean).join(" ").replace(/^./, (c) => c.toUpperCase());
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
function metricCells(k, total = false) {
  const label = resultLabel(k.result_indicator);
  const none = total && k.mixed ? MIXED_RESULTS : NO_RESULTS;
  const v = {
    results: k.results == null ? [dash(none)] : [esc(count(k.results)), label],
    cpr: k.results ? [esc(centsMoney(k.cost_per_result_cents, k.currency)), label] : [dash(none)],
    spend: [esc(centsMoney(k.spend_cents, k.currency))],
    impressions: [esc(count(k.impressions))],
    reach: [total ? dash(SUM_REACH) : k.reach == null ? dash(NO_REACH) : esc(count(k.reach))],
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

const campState = { skipped: false };  // "ver ignoradas", for the session
async function viewCampaigns(query) {
  if (!metaVisible()) { location.hash = "#/"; return; }
  const st = readPeriod(query);
  const [since, until] = periodDates(st.p, st);
  const doc = await api("GET", `/api/campaigns?since=${since}&until=${until}${campState.skipped && ME.is_admin ? "&include_skipped=1" : ""}`);
  savePeriod(st);
  history.replaceState(null, "", `#/campanhas?${periodQuery(st)}`);
  const n = doc.clients.reduce((a, c) => a + c.campaigns.filter((k) => k.state !== "skipped").length, 0);
  // a campaign younger than the period has numbers only from its "ativa desde" on
  const late = doc.clients.some((c) => c.campaigns.some((k) => k.state !== "skipped" && k.started && k.started > since));
  // the daily check (Visto hoje): clients still to see first, the seen ones sink; a client
  // whose linked accounts hold no campaign (nothing to check) comes last, so a portfolio
  // just connected shows up instead of looking like a failed connection
  const checkable = doc.clients.filter((c) => c.campaigns.length);
  const clients = [...checkable.filter((c) => !c.seen_today), ...checkable.filter((c) => c.seen_today), ...doc.clients.filter((c) => !c.campaigns.length)];
  const seen = doc.seen || { done: 0, total: checkable.length };
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
        ${metricCells(k)}
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
    ${periodPicker(st)}
    <p class="synced" id="synced"><span class="muted small" id="syncline">${syncLine(doc.last_sync)}</span>${clients.length ? `<b id="seenline" class="${seen.done >= seen.total ? "alldone" : ""}">Hoje: ${seen.done} de ${seen.total} ${seen.total === 1 ? "cliente visto" : "clientes vistos"}</b>` : ""}${late ? `<span class="muted small" id="latenote">Campanha que começou depois de ${esc(shortDay(since))} só tem números a partir de "ativa desde".</span>` : ""}</p>
    <div id="cblocks">${clients.length ? clients.map(block).join("") : empty}</div>
  </div>`;
  const redraw = () => viewCampaigns(new URLSearchParams(periodQuery(st)));
  bindPeriod(st, redraw);
  $("#showskipped")?.addEventListener("change", (e) => { campState.skipped = e.target.checked; redraw(); });
  $("#syncnow")?.addEventListener("click", async (e) => {
    // the server answers 202 at once and syncs on its own thread: poll the list until the
    // pass ends, keeping the "Dados da Meta" line honest meanwhile. 409 "busy" means one
    // is already running (another admin's tap, the hourly one): wait for that one instead
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      let previous = doc.last_sync;
      try {
        previous = (await api("POST", "/api/meta/sync", {})).last_sync;
      } catch (err) {
        if (err.reason !== "busy") throw err;
      }
      const line = $("#syncline");
      if (line) line.textContent = previous ? `Sincronizando com a Meta… (dados de ${ago(previous)})` : "Sincronizando com a Meta…";
      const done = await waitForSync(previous, since, until);
      if (done === SYNC_LEFT) return;
      if (!done) { toast("A sincronização ainda não terminou; os números aparecem quando acabar.", true); btn.disabled = false; return; }
      if (done === SYNC_LOST) { toast(SYNC_UNFINISHED, true); btn.disabled = false; return; }
      toast(done.sync_error ? `Sincronização com problema: ${done.sync_error}` : "Dados da Meta atualizados", Boolean(done.sync_error));
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
    try { await api("POST", `/api/clients/${b.dataset.seen}/reviews`, { note }); toast(`${b.dataset.name}: visto hoje`); redraw(); }
    catch (err) { toast(err.message, true); b.disabled = false; }
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
  ...RESULT_LABELS, "onsite_conversion.lead_grouped": "Cadastros (Meta)", omni_purchase: "Compras (todas)",
  "onsite_conversion.purchase": "Compras (no site)", comment: "Comentários", like: "Curtidas",
  post_reaction: "Reações", post: "Compartilhamentos", "onsite_conversion.post_save": "Salvamentos", add_to_cart: "Adições ao carrinho",
  initiate_checkout: "Finalizações de compra iniciadas",
  // the ones on Piero's campaigns (2026-11-04)
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
    defs[`act:${type}`] = { label: ACTION_LABELS[type] || type, fmt: "count", period: (c) => c.actions?.[type] ?? 0, day: (d) => d.actions?.[type] ?? 0 };
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
  const k = doc.campaign;
  savePeriod(st);
  history.replaceState(null, "", `#/campanha/${id}?${periodQuery(st)}`);
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
  </div>`;
  bindPeriod(st, () => viewCampaign(new URLSearchParams(periodQuery(st)), id));
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
    try { localStorage.setItem("pauta.metrics", JSON.stringify(picked)); } catch { /* not remembered */ }
    $("#metrics").innerHTML = chips();
    $("#cards").innerHTML = cards();
  });
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
  const tile = (key, i) => {
    const m = defs[key];
    const v = m.period(k), sub = m.sub ? m.sub(k) : "";
    const explain = m.explain || ACTION_EXPLAIN;
    const points = m.day ? dayPoints(k, since, until, m) : [];
    return `<section class="rep-tile ${i === 0 ? "hero" : ""}" data-tile="${esc(key)}">
      <span class="rep-label">${esc(m.label)}</span>
      <b class="rep-val">${esc(fmtMetric(v, m.fmt, k.currency))}</b>
      ${sub ? `<span class="rep-sub">${esc(sub)}</span>` : ""}
      <p class="rep-why">${esc(explain)}</p>
      ${points.length > 1 && points.some((p) => p.v) ? spark(points) : ""}
    </section>`;
  };
  const wa = waUrl(k.client_whatsapp);
  const share = wa
    ? `<a class="btn primary" id="share" href="${esc(`${wa}?text=${encodeURIComponent(shareText(k, since, until))}`)}" target="_blank" rel="noopener">${icon("send")}Compartilhar com o cliente</a>`
    : `<button class="btn primary" id="share" disabled title="O cliente não tem WhatsApp cadastrado">${icon("send")}Compartilhar com o cliente</button>`;
  const hint = wa
    ? `Tire um print do cartão abaixo e toque em <b>Compartilhar com o cliente</b>: o WhatsApp abre na conversa com <b>${esc(k.client_name || "o cliente")}</b> com a mensagem pronta; é só anexar o print.`
    : `<b>${esc(k.client_name || "O cliente")}</b> não tem WhatsApp cadastrado. ${k.client ? `<a href="#/cliente/${k.client}">Cadastre o número do cliente</a>` : "Cadastre o número do cliente"} para compartilhar daqui; até lá, tire o print e envie à mão.`;
  const ended = k.state !== "active" && k.ended ? ` · encerrada em ${esc(fmtDate(k.ended, { day: "2-digit", month: "2-digit", year: "numeric" }))}` : "";
  const today = todayISO();
  app.innerHTML = `<div class="report">
    <div class="report-tools">
      <div class="row-gap"><a class="btn" href="#/campanha/${id}?${periodQuery(st)}">${icon("back")}Voltar à campanha</a>${share}</div>
      <p class="muted small" id="sharehint">${hint}</p>
    </div>
    <article class="rep" id="rep">
      <header class="rep-hero">
        <span class="rep-kicker">Relatório de campanha</span>
        <h1>${esc(k.name)}</h1>
        <div class="rep-client">${avatar(k.client_name || "?", "md")}<span>${esc(k.client_name || "—")}</span></div>
        <p class="rep-period">${esc(since === until ? shortDay(since) : periodLabel(since, until))}${until >= today ? (since === until ? " · hoje" : " · até hoje") : ""}${k.state === "active" ? " · campanha ativa" : k.state === "paused" ? " · campanha pausada" : ended}</p>
      </header>
      <div class="rep-tiles">${shown.map(tile).join("")}</div>
      <footer class="rep-foot">
        <span>${doc.last_sync ? `Dados da Meta de ${esc(stamp(doc.last_sync).toLocaleDateString("pt-BR", { day: "numeric", month: "short" }).replace(".", ""))}` : "Dados da Meta"} · preparado por ${esc(firstName(ME.name))}</span>
        <span class="rep-brand"><span class="logo" aria-hidden="true"></span>pauta</span>
      </footer>
    </article>
  </div>`;
}
