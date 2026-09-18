// Cloudflare Worker: Razorpay backend for mrinaliniisin.github.io/pay.
// Deployed separately from the static site (GitHub Pages can't run code, and
// the Razorpay key secret must never reach the browser). See README.md.
//
// Endpoints:
//   POST /order    {amount (whole INR), note?}                 -> {order_id, amount, currency, key_id, name}
//   POST /verify   {razorpay_order_id, razorpay_payment_id,
//                   razorpay_signature}                        -> {ok, payment_id, amount}
//   POST /webhook  Razorpay webhook (X-Razorpay-Signature)     -> {ok}
//   GET  /                                                     -> liveness text
//
// /order and /verify are browser-facing and locked to ALLOW_ORIGINS. /webhook
// is server-to-server from Razorpay and authenticated by its HMAC instead.
//
// Trust model: the browser's /verify call proves the payer saw a signed success
// from Razorpay; the webhook is Razorpay telling us directly. Both write to the
// same "payment:<id>" record in KV, so a payment is recorded even if the
// visitor closed the tab before /verify ran.

const enc = new TextEncoder();
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey(
    "raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
}

// Constant-time compare. timingSafeEqual throws on unequal lengths, and the
// length of a hex HMAC is public anyway, so checking it first leaks nothing.
function safeEqual(a, b) {
  const x = enc.encode(a), y = enc.encode(b);
  return x.byteLength === y.byteLength && crypto.subtle.timingSafeEqual(x, y);
}

const allowedOrigins = env => (env.ALLOW_ORIGINS || "").split(",").map(s => s.trim()).filter(Boolean);

function cors(origin) {
  return origin ? {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  } : {};
}

const json = (status, obj, headers = {}) => new Response(JSON.stringify(obj), {
  status, headers: { "Content-Type": "application/json", ...headers },
});

const log = (route, fields) => console.log(JSON.stringify({ route, ...fields }));

const ORDER_ID = /^order_[A-Za-z0-9]+$/;
const PAYMENT_ID = /^pay_[A-Za-z0-9]+$/;
const HEX_SHA256 = /^[0-9a-f]{64}$/;

// Merge a patch into "payment:<id>" so checkout verification and the webhook
// can each add what they know without clobbering the other.
async function recordPayment(env, id, patch) {
  const existing = await env.PAYMENTS.get("payment:" + id, "json");
  await env.PAYMENTS.put("payment:" + id, JSON.stringify({ ...(existing || {}), ...patch }));
}

async function createOrder(request, env, origin) {
  if (!env.RAZORPAY_KEY_ID || !env.RAZORPAY_KEY_SECRET) {
    return json(503, { error: "payments are not configured yet" }, cors(origin));
  }
  const body = await request.json().catch(() => null);
  const min = Number(env.MIN_AMOUNT_INR), max = Number(env.MAX_AMOUNT_INR);
  const rupees = Number(body?.amount);
  if (!Number.isInteger(rupees) || rupees < min || rupees > max) {
    return json(400, { error: `amount must be a whole number of rupees from ${min} to ${max}` }, cors(origin));
  }
  const note = typeof body?.note === "string" ? body.note.trim().slice(0, 256) : "";

  // receipt: <= 40 ASCII chars, unique per order.
  const receipt = "site-" + crypto.randomUUID().replace(/-/g, "").slice(0, 24);
  const res = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: {
      "Authorization": "Basic " + btoa(env.RAZORPAY_KEY_ID + ":" + env.RAZORPAY_KEY_SECRET),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      amount: rupees * 100,          // paise
      currency: "INR",
      receipt,
      notes: { site: "mrinaliniisin.github.io", ...(note ? { note } : {}) },
    }),
  });
  if (!res.ok) {
    log("order", { level: "error", status: res.status, body: (await res.text()).slice(0, 500) });
    return json(502, { error: "could not create the order" }, cors(origin));
  }
  const order = await res.json();
  await env.PAYMENTS.put("order:" + order.id, JSON.stringify({
    amount: order.amount, currency: order.currency, note, receipt, created_at: order.created_at,
  }), { expirationTtl: 7 * 86400 });   // unpaid orders can age out; payments never do
  log("order", { level: "info", order_id: order.id, amount: order.amount });
  return json(200, {
    order_id: order.id, amount: order.amount, currency: order.currency,
    key_id: env.RAZORPAY_KEY_ID, name: env.SITE_NAME || "",
  }, cors(origin));
}

async function verifyCheckout(request, env, origin) {
  if (!env.RAZORPAY_KEY_SECRET) return json(503, { error: "payments are not configured yet" }, cors(origin));
  const body = await request.json().catch(() => ({}));
  const o = body.razorpay_order_id, p = body.razorpay_payment_id, s = body.razorpay_signature;
  if (typeof o !== "string" || typeof p !== "string" || typeof s !== "string"
      || !ORDER_ID.test(o) || !PAYMENT_ID.test(p) || !HEX_SHA256.test(s)) {
    return json(400, { ok: false, error: "malformed verification request" }, cors(origin));
  }
  const expected = await hmacHex(env.RAZORPAY_KEY_SECRET, o + "|" + p);
  if (!safeEqual(expected, s)) {
    log("verify", { level: "warn", order_id: o, payment_id: p, reason: "signature mismatch" });
    return json(400, { ok: false, error: "signature mismatch" }, cors(origin));
  }
  const order = await env.PAYMENTS.get("order:" + o, "json");
  await recordPayment(env, p, {
    order_id: o, amount: order?.amount ?? null, note: order?.note ?? "",
    verified_at: Date.now(),
  });
  log("verify", { level: "info", order_id: o, payment_id: p });
  return json(200, { ok: true, payment_id: p, amount: order?.amount ?? null }, cors(origin));
}

async function webhook(request, env) {
  if (!env.RAZORPAY_WEBHOOK_SECRET) return json(503, { error: "webhook secret not set" });
  // Webhook bodies are a few KB. Cap them so the buffered read below stays bounded.
  if (Number(request.headers.get("Content-Length") || 0) > 65536) return json(413, { error: "too large" });
  const sig = request.headers.get("X-Razorpay-Signature") || "";
  const raw = await request.text();   // signature is over the raw bytes, so no JSON round-trip
  if (!HEX_SHA256.test(sig) || !safeEqual(await hmacHex(env.RAZORPAY_WEBHOOK_SECRET, raw), sig)) {
    log("webhook", { level: "warn", reason: "bad signature" });
    return json(401, { error: "bad signature" });
  }
  // Razorpay retries until it sees a 2xx, so the same event can arrive twice.
  const eventId = request.headers.get("x-razorpay-event-id");
  if (eventId && await env.PAYMENTS.get("event:" + eventId)) return json(200, { ok: true, duplicate: true });

  let evt;
  try { evt = JSON.parse(raw); } catch { return json(400, { error: "not json" }); }
  const payment = evt?.payload?.payment?.entity;
  if (payment?.id && PAYMENT_ID.test(payment.id)) {
    await recordPayment(env, payment.id, {
      order_id: payment.order_id ?? null, amount: payment.amount ?? null,
      currency: payment.currency ?? null, status: payment.status ?? null,
      method: payment.method ?? null, email: payment.email ?? null,
      contact: payment.contact ?? null, notes: payment.notes ?? null,
      last_event: evt.event, webhook_at: Date.now(),
    });
  }
  if (eventId) await env.PAYMENTS.put("event:" + eventId, "1", { expirationTtl: 30 * 86400 });
  log("webhook", { level: "info", event: evt?.event, payment_id: payment?.id ?? null });
  return json(200, { ok: true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const reqOrigin = request.headers.get("Origin");
    const origin = allowedOrigins(env).includes(reqOrigin) ? reqOrigin : null;

    try {
      if (url.pathname === "/webhook") {
        if (request.method !== "POST") return json(405, { error: "method not allowed" });
        return await webhook(request, env);
      }
      if (url.pathname === "/order" || url.pathname === "/verify") {
        if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
        if (!origin) return json(403, { error: "origin not allowed" });
        if (request.method !== "POST") return json(405, { error: "method not allowed" }, cors(origin));
        return url.pathname === "/order"
          ? await createOrder(request, env, origin)
          : await verifyCheckout(request, env, origin);
      }
      if (url.pathname === "/") return new Response("pay worker ok");
      return json(404, { error: "not found" });
    } catch (e) {
      log(url.pathname, { level: "error", error: String(e).slice(0, 300) });
      return json(500, { error: "internal error" }, cors(origin));
    }
  },
};
