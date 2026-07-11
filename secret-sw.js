// Service worker for the secret.html "secret" notification topic on
// mrinaliniisin.github.io. Registered at scope /secret.html (see
// secret-push.js) so it's a completely separate registration from sw.js —
// subscribing here never triggers a notification for index.html cards.
// Pushes arrive payload-less (the broadcaster only signs, doesn't encrypt),
// so on each push we fetch the latest card info from the push Worker's /latest.

// ▼ After deploying the Worker, set this to its URL (also set in secret-push.js).
const WORKER = "https://mrinaliniisin-push.mustardseed.workers.dev";
const TOPIC = "secret";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", e => e.waitUntil(self.clients.claim()));

self.addEventListener("push", event => {
  event.waitUntil((async () => {
    let data = { title: "mrinaliniisin.github.io", body: "Something new was posted", url: "/secret.html" };
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
      tag: "mrinaliniisin-secret-new",    // collapse duplicates, distinct from the index topic
      data: { url: data.url || "/secret.html" },
    });
  })());
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/secret.html";
  event.waitUntil((async () => {
    const all = await clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const c of all) {
      if (c.url === url && "focus" in c) return c.focus();
    }
    return clients.openWindow(url);
  })());
});
