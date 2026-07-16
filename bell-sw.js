// Generic service worker for mrinaliniisin.github.io's per-topic push bells.
// One script serves every topic — it's registered per-bell with the topic
// (and a fallback notification url) passed as a query string, e.g.
// /bell-sw.js?topic=commonplace&url=/commonplace/. The *scope* given at
// registration time (see bell.js) is what actually keeps each topic's
// registration independent, so subscribing to one bell never notifies you
// about another.
// Pushes arrive payload-less (the broadcaster only signs, doesn't encrypt),
// so on each push we fetch the latest card info from the push Worker's /latest.

const WORKER = "https://mrinaliniisin-push.mustardseed.workers.dev";
const params = new URLSearchParams(self.location.search);
const TOPIC = params.get("topic") || "index";
const DEFAULT_URL = params.get("url") || "/";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", event => {
  event.waitUntil((async () => {
    let data = { title: "mrinaliniisin.github.io", body: "Something new was posted", url: DEFAULT_URL };
    try {
      if (event.data) {
        data = { ...data, ...event.data.json() };          // if a payload is ever sent
      } else {
        const r = await fetch(WORKER + "/latest?topic=" + TOPIC, { cache: "no-store" });
        if (r.ok) {
          const j = await r.json();
          if (j && j.title) data = { ...data, ...j };
        }
      }
    } catch (_) { /* fall back to the generic message */ }

    await self.registration.showNotification(data.title, {
      body: data.body,
      tag: "mrinaliniisin-" + TOPIC + "-new",   // collapse duplicates, distinct per topic
      data: { url: data.url || DEFAULT_URL },
    });
  })());
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || DEFAULT_URL;
  event.waitUntil((async () => {
    const all = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (c.url === url && "focus" in c) return c.focus();
    }
    return clients.openWindow(url);
  })());
});
