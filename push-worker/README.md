# Push notifications for mrinaliniisin.github.io

When a new card is added to `index.html` or `secret.html`, subscribers to that
page's bell icon get a browser push notification. The two pages are
independent notification **topics** ("index" and "secret") — subscribing on
one never notifies you about the other. GitHub Pages can't run code, so the
moving parts are:

- **`/sw.js`** + **`/push.js`** + the `#notify` button on `index.html` — the
  "index" topic: its own service worker registration, its own subscribers.
- **`/secret-sw.js`** + **`/secret-push.js`** + the `#notify` button on
  `secret.html` — the "secret" topic, registered at scope `/secret.html` so
  it's a wholly separate service worker registration from `/sw.js`.
- **`push-worker/`** — a Cloudflare Worker (deployed separately) that stores
  subscriptions in KV (keyed by topic) and sends the pushes.
- **`.github/workflows/notify.yml`** — on every push to `main` that changes
  `index.html` or `secret.html`, diffs that page's cards and calls the
  Worker's `/broadcast` for any new one, tagged with that page's topic.

Pushes are sent **payload-less** (VAPID-signed only). Each service worker
fetches its topic's latest card text from the Worker's `/latest?topic=`.
Works on Chrome, Edge, Firefox, and Android. On iPhone the visitor must
**Add to Home Screen** first (iOS web-push requirement); plain Safari may not
show payload-less pushes.

---

## One-time setup

All the key values you need are in **`push-worker/SECRETS.local.txt`**
(git-ignored — never commit it).

### 1. Deploy the Worker (Cloudflare, free)

```sh
cd push-worker
npm install -g wrangler        # or use: npx wrangler ...
wrangler login                 # opens browser, free account is fine

# Create the KV store, then paste the printed id into wrangler.toml
wrangler kv namespace create SUBS
#   -> copy the id into  [[kv_namespaces]] id = "..."  in wrangler.toml

# Set the two secrets (paste values from SECRETS.local.txt)
wrangler secret put VAPID_PRIVATE
wrangler secret put BROADCAST_SECRET

wrangler deploy
#   -> note the deployed URL, e.g. https://mrinaliniisin-push.<you>.workers.dev
```

### 2. Point the site at the Worker

Set the deployed URL as the `WORKER` constant in **all four**:
- `sw.js`
- `push.js`
- `secret-sw.js`
- `secret-push.js`

(They currently say `https://mrinaliniisin-push.YOUR-SUBDOMAIN.workers.dev`.)

If your site origin ever changes, update `ALLOW_ORIGIN` in `wrangler.toml` and
re-`wrangler deploy`.

### 3. Add the GitHub Action secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Name               | Value                                              |
|--------------------|----------------------------------------------------|
| `PUSH_WORKER_URL`  | the deployed Worker URL (no trailing slash)        |
| `BROADCAST_SECRET` | the same token from `SECRETS.local.txt`            |

### 4. Publish the site

Commit and push `index.html`, `secret.html`, `push.js`, `sw.js`,
`secret-push.js`, `secret-sw.js`, and `.github/`. Then:

1. Open https://mrinaliniisin.github.io, click **🔔 Notify me of new stuff**, allow.
2. Add a new card to `index.html` or `secret.html` and push. The Action runs,
   detects the new card, and subscribers to that page's topic get a notification.

---

## Manual send (optional)

```sh
curl -X POST "$PUSH_WORKER_URL/broadcast" \
  -H "Authorization: Bearer $BROADCAST_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello","body":"Test push","url":"https://mrinaliniisin.github.io","topic":"index"}'
```

`topic` defaults to `"index"` if omitted. Use `"secret"` to notify only
`secret.html` subscribers. `/broadcast` returns `{sent, pruned, failed}` —
`pruned` are dead subscriptions it cleaned up automatically.

## Rotating keys

VAPID keys are generated with:

```sh
openssl ecparam -genkey -name prime256v1 -noout -out priv.pem
openssl pkcs8 -topk8 -nocrypt -in priv.pem -outform DER -out priv.pkcs8.der   # -> VAPID_PRIVATE (base64 of this)
openssl ec -in priv.pem -pubout -outform DER | tail -c 65 | base64            # -> VAPID_PUBLIC (base64url it)
```

If you rotate VAPID keys, every existing subscription is invalidated and users
must re-subscribe.
