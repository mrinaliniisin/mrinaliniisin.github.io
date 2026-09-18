# Payments for mrinaliniisin.github.io

`/pay` takes contributions through Razorpay Standard Checkout. GitHub Pages
can't run code and the Razorpay key secret must never reach a browser, so
the moving parts are:

- **`/pay/index.html`** — the page. Amount chips, a free amount box, an
  optional note. It asks the Worker for an order, opens Razorpay's checkout
  with that order, then asks the Worker to verify the result. Razorpay's
  `checkout.js` is loaded on the first click, not at page load.
- **`pay-worker/`** — this Cloudflare Worker. Holds the secret, creates
  orders, verifies checkout signatures, and receives Razorpay webhooks.
  Records every payment it hears about in the `PAYMENTS` KV namespace.
- **`/refund`, `/contact`, `/privacy`, `/tos`** — the policy pages Razorpay
  asks for at activation. `/privacy` and `/tos` each have a Payments section.

Deployed at **https://mrinaliniisin-pay.mustardseed.workers.dev**.

| Route      | Who calls it            | Auth                                  |
|------------|-------------------------|---------------------------------------|
| `/order`   | the page (browser)      | `Origin` must be in `ALLOW_ORIGINS`   |
| `/verify`  | the page (browser)      | same, plus the checkout HMAC          |
| `/webhook` | Razorpay (server)       | `X-Razorpay-Signature` HMAC           |

Amount limits (`MIN_AMOUNT_INR`, `MAX_AMOUNT_INR`) are enforced in the
Worker, so they hold even if someone calls `/order` by hand.

---

## One-time setup

Wrangler 4 needs Node 22+. The shell defaults to Node 20, so prefix
commands with the Node 25 install:

```sh
cd pay-worker
export PATH=~/.nvm/versions/node/v25.9.0/bin:$PATH
npx wrangler login          # once; a free account is fine
```

### 1. Secrets

From **Razorpay Dashboard → Account & Settings → API Keys**. Use the
`rzp_test_…` pair first, then repeat with the `rzp_live_…` pair when going
live. Each command prompts for the value; nothing is written to the repo.

```sh
npx wrangler secret put RAZORPAY_KEY_ID
npx wrangler secret put RAZORPAY_KEY_SECRET
```

### 2. Deploy

```sh
npx wrangler deploy
```

The KV namespace id in `wrangler.jsonc` was created with
`npx wrangler kv namespace create PAYMENTS`; only redo that on a fresh
Cloudflare account.

### 3. Webhook

**Razorpay Dashboard → Account & Settings → Webhooks → Add New Webhook**:

| Field          | Value                                                        |
|----------------|--------------------------------------------------------------|
| Webhook URL    | `https://mrinaliniisin-pay.mustardseed.workers.dev/webhook` |
| Secret         | any long random string; you'll set the same one below        |
| Active events  | `payment.captured`, `payment.failed`                         |

Then give the Worker the same secret:

```sh
npx wrangler secret put RAZORPAY_WEBHOOK_SECRET
```

Razorpay retries a webhook until it gets a 2xx, and the Worker dedupes on
`x-razorpay-event-id`, so a retry never double-records a payment.

### 4. Try it

With test keys, open https://mrinaliniisin.github.io/pay and pay with one
of Razorpay's test cards or a test UPI id (Dashboard → test mode shows
them). The page should end on "Thank you! Payment pay_… went through."

Then switch the two API-key secrets to the live pair and `deploy` again.

---

## Trying it locally

The page at http://localhost:5666/pay talks to the **live** Worker by
default (its `ALLOW_ORIGINS` includes the editor server), so a real
test-mode checkout can be tried before a push. To exercise the Worker code
itself locally, open http://localhost:5666/pay?worker=local and run:

```sh
npx wrangler dev --port 8787 --local
```

With the fake keys, `/order` fails at Razorpay with a 502 (correct: the
keys are fake). To try the real checkout locally, put a test key pair in
`.dev.vars` instead. Signature paths can be exercised without any real
key: sign `order_id|payment_id` with the `.dev.vars` key secret using
`openssl dgst -sha256 -hmac`.

## Seeing payments

The Razorpay dashboard is the source of truth. The Worker's own record,
useful for matching a note to a payment:

```sh
npx wrangler kv key list --binding PAYMENTS --prefix payment: --remote
npx wrangler kv key get  --binding PAYMENTS --remote "payment:pay_XXXX"
```

Live request logs: **Cloudflare Dashboard → Workers → mrinaliniisin-pay →
Logs**. Every log line is JSON with a `route` field.

## Changing things

- Site origin changes → edit `ALLOW_ORIGINS` in `wrangler.jsonc`, deploy.
- Amount limits → `MIN_AMOUNT_INR` / `MAX_AMOUNT_INR` in `wrangler.jsonc`
  **and** the `min`/`max` on the input plus `MIN`/`MAX` in
  `/pay/index.html`, so the page's own message matches.
- Key rotation → `secret put` the new pair, deploy. In-flight checkouts
  opened with the old key id will fail verification; that window is seconds.
