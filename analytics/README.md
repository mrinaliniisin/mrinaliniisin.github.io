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
in **one place** and injects Counterscale's `tracker.js`. If `WORKER` is ever reset to the placeholder it becomes a **no-op** — nothing is
requested, nothing is tracked — so the tracker can be switched off with a
one-line edit.

## Part A — Deploy Counterscale (done 2026-09-18)

Same shape as `push-worker`: the collector lives in *your* Cloudflare account.
Worker name `counterscale`, URL **https://counterscale.mustardseed.workers.dev**,
site id `mrinaliniisin`. Dashboard at that URL (password-protected).

> **Don't use `npx @counterscale/cli install`.** As of CLI 3.4.1 with Wrangler
> 4.110+, it dies with `Worker "counterscale" not found` before prompting for
> anything: it probes the Worker by listing its secrets and only tolerates the
> not-found error when Wrangler tags it `[code: 10007]`, which newer Wrangler
> no longer does. Its bundled config also binds an R2 bucket that R2-less
> accounts can't satisfy. R2 is only used by a nightly rollup cron, gated by
> the `CF_STORAGE_ENABLED` secret, so the dashboard doesn't need it.

How it was actually deployed (repeat to upgrade):

1. **Enable Analytics Engine** in the dashboard (free): Storage & Databases →
   Analytics Engine. The deploy fails with `[code: 10089]` until this is done.
2. Use **Node 22+** (`nvm use 25`); Wrangler 4.110 refuses Node 20. `npx
   wrangler login` if needed.
3. Let npx fetch the packages, then stage a config: copy
   `@counterscale/server/wrangler.json` (from the npx cache, e.g.
   `~/.npm/_npx/*/node_modules/@counterscale/server/`), make `main` and
   `assets.directory` absolute, add `account_id`, and delete `r2_buckets` and
   `triggers`.
4. From the server package dir:
   `npx wrangler deploy --config <staged.json> --var VERSION:<server version>`
5. Secrets (all via `wrangler secret put <NAME> --config <staged.json>`):
   `CF_ACCOUNT_ID`, `CF_STORAGE_ENABLED=false`, plus the credential ones set
   interactively:
   ```sh
   npx @counterscale/cli@latest auth enable    # dashboard password
   npx @counterscale/cli@latest env token      # Analytics API token
   ```
   The token needs **Account Analytics: Read** (My Profile → API Tokens); the
   dashboard uses it to read pageviews back out through Cloudflare's GraphQL API.

## Part B — Switch it on (done)

[`assets/analytics.js`](../assets/analytics.js) has `WORKER` set to the URL
above. Every wired page loads the tracker. Change `SITE_ID` if you want a
different label in the dashboard.

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
