// Generic subscribe/unsubscribe UI for push-notification bells. Any element
// matching [data-bell-topic] is wired up independently: its own service
// worker registration (bell-sw.js, parameterized by topic via query string),
// its own scope, its own subscribers — so several bells can live on one page
// (e.g. secret.html's per-card bells) without cross-notifying each other.
//
// Required:
//   data-bell-topic   e.g. "commonplace"
// Optional:
//   data-bell-scope   service worker scope, default "/"
//   data-bell-url     fallback notification target if a push arrives before
//                      /latest has ever been broadcast, default "/"
//   data-bell-label   default (not-subscribed) title/aria-label text
(() => {
  const WORKER = "https://mrinaliniisin-push.mustardseed.workers.dev";
  // VAPID public key (safe to expose). Must match the Worker's VAPID_PUBLIC.
  const VAPID_PUBLIC = "BBl7CjwTobyvrKM1fgcfhH5YujNqIR_5dA6EwNRI7LnFJyAmP9_ja2wdy0fSgFTPWSl2MX1K7yxqfmTfaPT2-XY";

  const buttons = document.querySelectorAll("[data-bell-topic]");
  if (!buttons.length) return;

  // Push needs a secure context + service workers + the Push API.
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !window.isSecureContext) {
    buttons.forEach(btn => { btn.hidden = true; });
    return;
  }

  const urlB64ToBytes = b64 => {
    const pad = "=".repeat((4 - (b64.length % 4)) % 4);
    const s = (b64 + pad).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(atob(s), c => c.charCodeAt(0));
  };

  buttons.forEach(initBell);

  function initBell(btn) {
    const topic = btn.dataset.bellTopic;
    const scope = btn.dataset.bellScope || "/";
    const url = btn.dataset.bellUrl || "/";
    const label = btn.dataset.bellLabel || "Notify me of new posts";
    const swUrl = "/bell-sw.js?topic=" + encodeURIComponent(topic) + "&url=" + encodeURIComponent(url);

    const setState = on => {
      btn.dataset.on = on ? "1" : "";
      const text = on ? "Subscribed — click to stop notifications" : label;
      btn.title = text;
      btn.setAttribute("aria-label", text);   // keep the SVG intact, stay accessible
    };

    let reg;
    const ready = navigator.serviceWorker.register(swUrl, { scope }).then(async r => {
      reg = r;
      setState(!!(await reg.pushManager.getSubscription()));
      btn.disabled = false;
    }).catch(() => { btn.hidden = true; });

    btn.addEventListener("click", async () => {
      await ready;
      btn.disabled = true;
      try {
        const existing = await reg.pushManager.getSubscription();
        if (existing) {
          await fetch(WORKER + "/unsubscribe", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ endpoint: existing.endpoint, topic }),
          }).catch(() => {});
          await existing.unsubscribe();
          setState(false);
          return;
        }
        if ((await Notification.requestPermission()) !== "granted") { setState(false); return; }
        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlB64ToBytes(VAPID_PUBLIC),
        });
        const res = await fetch(WORKER + "/subscribe", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(Object.assign(sub.toJSON(), { topic })),
        });
        setState(res.ok);
        if (!res.ok) await sub.unsubscribe().catch(() => {});
      } catch (e) {
        setState(false);
      } finally {
        btn.disabled = false;
      }
    });
  }
})();
