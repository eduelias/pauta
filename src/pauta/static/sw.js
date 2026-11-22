"use strict";
// Pauta's service worker: notifications only. No cache and no fetch handler, so pages load
// and reload exactly as without it. It is registered when a person switches notifications
// on (Perfil), on that device.
//
// A push carries no text (pauta/push.py): it wakes this worker, which asks the server what
// to show, as the person signed in here. Signed out or offline it still has to show
// something (browsers take the permission back from a worker that stays silent), so then
// it says only that there is news.
const GENERIC = { title: "Pauta", body: "Há novidades nos pedidos.", url: "/", tag: "pauta" };

async function news() {
  try {
    const sub = await self.registration.pushManager.getSubscription();
    const res = await fetch("/api/push/news", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ endpoint: sub ? sub.endpoint : "" }),
      signal: AbortSignal.timeout(5000),  // a slow answer must not hold the notification back
    });
    const doc = res.ok ? await res.json() : {};
    if (Array.isArray(doc.news) && doc.news.length) return doc.news;
  } catch { /* offline, or too slow: the generic line */ }
  return [GENERIC];
}

self.addEventListener("push", (event) => event.waitUntil((async () => {
  for (const n of await news()) {
    await self.registration.showNotification(n.title, { body: n.body, tag: n.tag, icon: "/icon-192.png", data: { url: n.url } });
  }
})()));

// A tap opens the request: in the Pauta that is already open (the page listens for `go`,
// app-router.js), else in a new one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil((async () => {
    const [tab] = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    if (!tab) return self.clients.openWindow(url);
    tab.postMessage({ go: url.slice(1) });
    return tab.focus();
  })());
});
