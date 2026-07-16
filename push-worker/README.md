# Push notifications for mrinaliniisin.github.io

When a new card/entry is added to a tracked page, subscribers to its bell
icon get a browser push notification. Each destination is an independent
notification **topic** — subscribing to one never notifies you about the
others:

| Topic          | Source page                     | Bell lives on                          |
|----------------|----------------------------------|-----------------------------------------|
| `index`        | `index.html`                     | `index.html`'s own page-level bell      |
| `blog`         | `blog/index.html`                | `blog/index.html`'s own bell **and** a card-bell on `secret.html` (same subscription — see below) |
| `commonplace`  | `commonplace/index.html`         | a card-bell on `secret.html`            |
| `listicles`    | `theo/listicles/index.html`      | a card-bell on `secret.html`            |
| `tvplotmaps`   | `tv-plot-maps/index.html`        | a card-bell on `secret.html`            |

`secret.html` no longer has its own page-wide bell/topic — that was retired
in favor of a bell on each card (except the Poonkuzhali link, which points
off-site and has nothing to subscribe to). GitHub Pages can't run code, so
the moving parts are:

- **`/bell.js`** — generic subscribe/unsubscribe UI. Any element with
  `data-bell-topic="…"` becomes an independent bell: its own service worker
  registration, its own scope, its own subscribers. One script handles every
  bell on the site, including several on the same page (`secret.html` has
  four).
- **`/bell-sw.js`** — generic service worker. One file serves every topic;
  the topic (and a fallback notification URL) are passed in as a query
  string at registration time, e.g. `/bell-sw.js?topic=commonplace&url=/commonplace/`.
  The *scope* given at registration (e.g. `/commonplace/`) is what actually
  keeps two topics' subscriptions from colliding.
- **`/sw.js`** + **`/push.js`** — the one holdover from before `bell.js`
  existed: `index.html`'s own `#notify` button still uses this bespoke pair.
  Left as-is since it works and touching it wasn't in scope.
- The Blog card-bell on `secret.html` registers the *exact same*
  `bell-sw.js` script at the *exact same* scope (`/blog/`) as
  `blog/index.html`'s own bell, so a visitor who subscribes from either page
  ends up with one shared subscription, not two (which would otherwise mean
  duplicate notifications for the same post).
- **`push-worker/`** — a Cloudflare Worker (deployed separately) that stores
  subscriptions in KV (keyed by topic) and sends the pushes.
- **`.github/workflows/notify.yml`** — on every push to `main` that changes
  one of the tracked pages, diffs that page's cards/entries against the
  previous commit and calls the Worker's `/broadcast` for any new one,
  tagged with that page's topic. Each tracked page has its own markup, so
  `.github/scripts/notify_new_cards.py` carries a separate extraction regex
  per page (see `PAGES` in that file).

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
- `bell.js`
- `bell-sw.js`

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

Commit and push `index.html`, `secret.html`, `blog/index.html`, `push.js`,
`sw.js`, `bell.js`, `bell-sw.js`, and `.github/`. Then:

1. Open https://mrinaliniisin.github.io, click **🔔 Notify me of new stuff**, allow.
2. On `secret.html`, click a card's bell (e.g. TV Plot Maps) to subscribe to
   just that section.
3. Add a new card/entry to one of the tracked pages (see the topic table
   above) and push. The Action runs, detects the new item, and subscribers to
   that item's topic get a notification.

---

## Manual send (optional)

```sh
curl -X POST "$PUSH_WORKER_URL/broadcast" \
  -H "Authorization: Bearer $BROADCAST_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello","body":"Test push","url":"https://mrinaliniisin.github.io","topic":"index"}'
```

`topic` defaults to `"index"` if omitted. Use `"blog"`, `"commonplace"`,
`"listicles"`, or `"tvplotmaps"` to notify only that section's subscribers.
`/broadcast` returns `{sent, pruned, failed}` — `pruned` are dead
subscriptions it cleaned up automatically.

## Rotating keys

VAPID keys are generated with:

```sh
openssl ecparam -genkey -name prime256v1 -noout -out priv.pem
openssl pkcs8 -topk8 -nocrypt -in priv.pem -outform DER -out priv.pkcs8.der   # -> VAPID_PRIVATE (base64 of this)
openssl ec -in priv.pem -pubout -outform DER | tail -c 65 | base64            # -> VAPID_PUBLIC (base64url it)
```

If you rotate VAPID keys, every existing subscription is invalidated and users
must re-subscribe.
