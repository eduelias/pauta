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
const resultLabel = (type) => RESULT_LABELS[type] || String(type || "").replace(/[._]+/g, " ");
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
function clientTotals(c) {
  const live = c.campaigns.filter((x) => x.state !== "skipped");
  const t = { spend_cents: 0, link_clicks: 0, impressions: 0, currency: c.campaigns[0]?.currency, results: null, result_indicator: "", cost_per_result_cents: null, mixed: false };
  for (const k of live) { t.spend_cents += k.spend_cents; t.link_clicks += k.link_clicks; t.impressions += k.impressions; }
  t.cpl_cents = t.link_clicks ? Math.round(t.spend_cents / t.link_clicks) : null;
  // results add up only when every campaign counts the same thing
  const kinds = new Set(live.map((k) => k.result_indicator).filter(Boolean));
  const counted = live.filter((k) => k.results != null);
  if (kinds.size === 1 && counted.length) {
    t.result_indicator = [...kinds][0];
    t.results = counted.reduce((a, k) => a + k.results, 0);
    t.cost_per_result_cents = t.results ? Math.round(t.spend_cents / t.results) : null;
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
    <p class="synced" id="synced"><span class="muted small">${syncLine(doc.last_sync)}</span>${clients.length ? `<b id="seenline" class="${seen.done >= seen.total ? "alldone" : ""}">Hoje: ${seen.done} de ${seen.total} ${seen.total === 1 ? "cliente visto" : "clientes vistos"}</b>` : ""}${late ? `<span class="muted small" id="latenote">Campanha que começou depois de ${esc(shortDay(since))} só tem números a partir de "ativa desde".</span>` : ""}</p>
    <div id="cblocks">${clients.length ? clients.map(block).join("") : empty}</div>
  </div>`;
  const redraw = () => viewCampaigns(new URLSearchParams(periodQuery(st)));
  bindPeriod(st, redraw);
  $("#showskipped")?.addEventListener("change", (e) => { campState.skipped = e.target.checked; redraw(); });
  $("#syncnow")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const out = await api("POST", "/api/meta/sync", {});
      toast(`${out.accounts} ${out.accounts === 1 ? "conta lida" : "contas lidas"}, ${out.campaigns_new} ${out.campaigns_new === 1 ? "campanha nova" : "campanhas novas"}, ${out.insight_rows} ${out.insight_rows === 1 ? "dia atualizado" : "dias atualizados"}${out.errors?.length ? ` · ${out.errors.length} com erro` : ""}`, Boolean(out.errors?.length));
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
// `sub` names what Resultados count, under the value, as Ads Manager does.
const METRICS = {
  results: { label: "Resultados", fmt: "count", period: (k) => k.results, day: (d) => d.results, sub: (k) => resultLabel(k.result_indicator), note: "o que o objetivo da campanha conta" },
  cpr: { label: "Custo por resultado", fmt: "money", period: (k) => k.cost_per_result_cents, day: (d) => d.results ? d.spend_cents / d.results : null, sub: (k) => resultLabel(k.result_indicator) },
  spend: { label: "Valor gasto", fmt: "money", period: (k) => k.spend_cents, day: (d) => d.spend_cents },
  leads: { label: "Leads (cliques)", fmt: "count", period: (k) => k.link_clicks, day: (d) => d.link_clicks },
  cpl: { label: "Custo por lead", fmt: "money", period: (k) => k.cpl_cents, day: (d) => d.link_clicks ? d.spend_cents / d.link_clicks : null },
  reach: { label: "Alcance", fmt: "count", period: (k) => k.reach, day: (d) => d.reach, note: "no período, pessoas diferentes (da Meta); por dia, as de cada dia" },
  impressions: { label: "Impressões", fmt: "count", period: (k) => k.impressions, day: (d) => d.impressions },
  ctr: { label: "CTR", fmt: "pct", period: (k) => k.impressions ? k.link_clicks / k.impressions : null, day: (d) => d.impressions ? d.link_clicks / d.impressions : null, note: "cliques no link ÷ impressões" },
  cpm: { label: "CPM", fmt: "money", period: (k) => k.impressions ? k.spend_cents / k.impressions * 1000 : null, day: (d) => d.impressions ? d.spend_cents / d.impressions * 1000 : null, note: "custo por mil impressões" },
  freq: { label: "Frequência", fmt: "dec", period: (k) => k.reach ? k.impressions / k.reach : null, note: "impressões ÷ alcance, só no período" },
};
// the action chips: Ads Manager's words, told apart where two types would read the same
const ACTION_LABELS = {
  ...RESULT_LABELS, "onsite_conversion.lead_grouped": "Cadastros (Meta)", omni_purchase: "Compras (todas)",
  "onsite_conversion.purchase": "Compras (no site)", comment: "Comentários", like: "Curtidas",
  post_reaction: "Reações", post: "Compartilhamentos", "onsite_conversion.post_save": "Salvamentos", add_to_cart: "Adições ao carrinho",
  initiate_checkout: "Finalizações iniciadas",
};
const DEFAULT_METRICS = ["results", "cpr", "spend"];
function metricDefs(k) {
  const defs = { ...METRICS };
  for (const type of Object.keys(k.actions || {}).sort()) {
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
    if (Array.isArray(got) && got.every((x) => typeof x === "string")) return got;
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
    <div class="chart-y">${esc(fmtMetric(max, fmt, cur))}</div>
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
  const chips = () => Object.entries(defs).map(([key, m]) => `<button type="button" class="chip ${picked.includes(key) ? "on" : ""}" data-metric="${esc(key)}" aria-pressed="${picked.includes(key)}" ${m.note ? `title="${esc(m.note)}"` : ""}>${esc(m.label)}</button>`).join("");
  const cards = () => {
    const shown = picked.filter((key) => defs[key]);
    if (!shown.length) return `<div class="panel empty">Escolha uma métrica acima.</div>`;
    return shown.map((key) => {
      const m = defs[key];
      const v = m.period(k), sub = m.sub ? m.sub(k) : "";
      return `<section class="panel mcard" data-card="${esc(key)}">
        <div class="panel-head"><h3>${esc(m.label)}</h3>${m.note ? `<span class="muted small">${esc(m.note)}</span>` : ""}</div>
        <div class="mval" ${m.sub && v == null ? `title="${NO_RESULTS}"` : ""}>${esc(fmtMetric(v, m.fmt, k.currency))}</div>
        ${sub ? `<div class="msub muted small">${esc(sub)}</div>` : ""}
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
      <p>${when}${k.objective ? ` · ${esc(k.objective.replace(/^OUTCOME_/, "").toLowerCase())}` : ""}${k.request ? ` · <a href="#/pedido/${k.request}">Pedido #${k.request}</a>` : ""}</p>
    </div></div>
    ${periodPicker(st)}
    <p class="muted small synced" id="synced">${syncLine(doc.last_sync)}</p>
    <div class="chips" id="metrics">${chips()}</div>
    <div class="mcards" id="cards">${cards()}</div>
  </div>`;
  bindPeriod(st, () => viewCampaign(new URLSearchParams(periodQuery(st)), id));
  $("#metrics").addEventListener("click", (e) => {
    const b = e.target.closest("[data-metric]");
    if (!b) return;
    const key = b.dataset.metric;
    picked = picked.includes(key) ? picked.filter((x) => x !== key) : [...picked, key];
    try { localStorage.setItem("pauta.metrics", JSON.stringify(picked)); } catch { /* not remembered */ }
    $("#metrics").innerHTML = chips();
    $("#cards").innerHTML = cards();
  });
}
