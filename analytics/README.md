# Analytics for mrinaliniisin.github.io

Privacy-friendly, self-hosted page analytics via
[**Counterscale**](https://github.com/benvinegar/counterscale) — one Cloudflare
Worker that is *both* the collector and the dashboard, storing data in
**Workers Analytics Engine** (no database). GitHub Pages can't run code, so the
collector lives on Cloudflare; the site just loads a small tracker.

## How the site is wired

Every main-site page includes one file:

```html
<script src="/assets/analytics.js" defer></script>
```

[`assets/analytics.js`](../assets/analytics.js) holds the Worker URL and site id
in **one place** and injects Counterscale's `tracker.js`. Until `WORKER` is set
to a real URL it is a **no-op** — nothing is requested, nothing is tracked. So
the site can ship wired-but-dormant and be switched on with a one-line edit.

## Part A — Deploy Counterscale (your part; ~5 min)

Same shape as `push-worker`. Counterscale can't be deployed by the editor tools —
it goes into *your* Cloudflare account.

1. **Enable Analytics Engine**: Cloudflare dashboard → *Storage & Databases →
   Analytics Engine → Enable* (free).
2. **Create an API token** with **Account Analytics** read permission (the
   dashboard queries your pageviews back out through Cloudflare's GraphQL API).
3. **Run the installer** (Node 20+):
   ```sh
   npx wrangler login                      # likely still logged in from push-worker
   npx @counterscale/cli@latest install
   ```
   It prompts for the API token, asks whether to **password-protect the
   dashboard** (say **yes** — the workers.dev URL is public otherwise), and
   deploys. It prints the Worker URL, e.g.
   `https://counterscale.<your-subdomain>.workers.dev`.
4. The dashboard lives at that Worker URL (log in with the password you set).

## Part B — Switch it on (one line)

In [`assets/analytics.js`](../assets/analytics.js), set:

```js
var WORKER = "https://counterscale.<your-subdomain>.workers.dev";
```

Commit + push. That's it — every wired page starts reporting. The site id is
`mrinaliniisin` (change `SITE_ID` if you want a different label in the dashboard).

## Coverage

Wired: the **main site** — homepage, blog (index + posts), the China & HK list +
its BellaMafia page, the Commonplace Book (index + all factoid pages), and
standalone pages. Future blog posts and markdown pages get it automatically
because the include is in `server.py`'s `POST_TEMPLATE` and `PAGE_TEMPLATE`.

**Not wired (by default):** the sub-projects in their own folders/repos —
`tv-plot-maps/`, `theo/`, `jpeterman/` (separate repo), `margo/`, `roger/`,
`hot_or_not_menu_bar_apps/`.

### Caveat — regenerated pages

The Commonplace pages and `china-hk-trip-2026/bellamafia.html` were produced by
one-off generator scripts. They carry the include now (added directly), but if
they're ever regenerated from scratch the include must be re-added (re-run the
injection, or add it to the generator template).
