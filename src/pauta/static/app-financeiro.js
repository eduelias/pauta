"use strict";
// Pauta: Financeiro (decision 7).
// Shares app.js's globals; index.html loads it after app.js.

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
  if (!onScreen("#/financeiro")) return;  // asked again by itself, answered on another screen
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
      track("finance_entry", { kind: "payment" });
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
    try { done(await api("PATCH", `/api/clients/${c.id}/billing`, { amount: e.target.value })); track("finance_entry", { kind: "cycle" }); toast("Salvo"); }
    catch (err) { toast(err.message, true); }
  });
  $("#paybilled", box)?.addEventListener("change", async (e) => {
    try { done(await api("PATCH", `/api/clients/${c.id}/billing`, { billed: e.target.checked })); track("finance_entry", { kind: "cycle" }); toast("Salvo"); }
    catch (err) { toast(err.message, true); }
  });
  $$("[data-void]", box).forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Anular este pagamento? Ele continua na lista, riscado.")) return;
    try { done(await api("DELETE", `/api/payments/${b.dataset.void}`)); track("finance_entry", { kind: "void" }); toast("Pagamento anulado"); }
    catch (err) { toast(err.message, true); }
  }));
}

// Configurações → Financeiro: the team's conventions (admins)
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
