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

## Coverage — whole site

Because the include is an **absolute path** (`/assets/analytics.js`), it resolves
to *this* repo's loader from anywhere on the `mrinaliniisin.github.io` origin —
so one loader covers project pages served at `/jpeterman/`, `/tv-plot-maps/`,
etc. too.

Wired:
- **Main site** — homepage, blog (index + posts), China & HK list + BellaMafia,
  Commonplace (index + all factoid pages), standalone pages. Future posts/pages
  get it automatically via `server.py`'s `POST_TEMPLATE` / `PAGE_TEMPLATE`.
- **tv-plot-maps/**, **theo/** — in-repo, added directly.
- **jpeterman** — separate repo (`~/Desktop/jpeterman`); the include is in its
  `build_pages.py` templates, regenerated across all pages. Commit + push there.
- **hot_or_not_menu_bar_apps** — separate repo (`~/Desktop/MenuBarApps`);
  include added to `index.html` + `stats.html`. Commit + push there.

Not wired:
- `margo/`, `roger/` — no HTML pages (just assets), nothing to track.

> Separate repos (jpeterman, MenuBarApps) each need their own **push** to
> deploy; they all load the single `assets/analytics.js` from this repo.

### Caveat — regenerated pages

The Commonplace pages and `china-hk-trip-2026/bellamafia.html` were produced by
one-off generator scripts. They carry the include now (added directly), but if
they're ever regenerated from scratch the include must be re-added (re-run the
injection, or add it to the generator template).
