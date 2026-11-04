"use strict";
// The client's copy of a campaign report (decision 12): /r/<token>, no account, no shell.
// report.html loads this after app.js and app-campanhas.js, whose reportCard draws the same
// card the team sees, from GET /api/r/<token> (which carries only what the card shows).

async function showPublicReport() {
  const token = decodeURIComponent(location.pathname.split("/r/")[1] || "");
  let doc;
  try {
    doc = await api("GET", `/api/r/${encodeURIComponent(token)}`);
  } catch (e) {
    // the link ended between the page and its data (or the network failed): the same words
    // the server's own page uses
    app.innerHTML = `<div class="report"><article class="rep rep-gone">
      <span class="rep-brand"><span class="logo" aria-hidden="true"></span>pauta</span>
      <h1>${e.status === 404 ? "Este relatório não está mais disponível" : "O relatório não carregou"}</h1>
      <p>${e.status === 404 ? "O link expirou ou foi desativado. Peça um link novo a quem enviou o relatório." : esc(e.message)}</p>
    </article></div>`;
    return;
  }
  const k = doc.campaign;
  const ends = validUntil(doc.expires);
  app.innerHTML = `<div class="report">
    ${reportCard(k, { since: doc.since, until: doc.until, keys: doc.metrics, defs: metricDefs(k), lastSync: doc.last_sync, by: doc.prepared_by })}
    <p class="public-note">Relatório preparado na Pauta. Este link vale até ${esc(ends)}.</p>
  </div>`;
}

showPublicReport();
