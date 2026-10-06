# Anytype → /commonplace

The **My Commonplace Book** collection in Anytype is mirrored onto
[`/commonplace`](https://mrinaliniisin.github.io/commonplace/) once a week,
the same way `/youtube-likes` is: the local editor server (`server.py` on
:5666, the always-on runit service) reads the collection from Anytype's local
API and rewrites the page. Publishing is then a normal `git push` — or flip
`auto_push` (below) to have it commit and push by itself.

Anytype's API only listens on this Mac, so **the Anytype desktop app has to be
open** for a sync to work. If it's closed, the sync fails quietly and tries
again 6 hours later (rather than waiting another week). There is no GitHub
Action fallback, for the same reason.

| File                    | What                                                                 |
|-------------------------|----------------------------------------------------------------------|
| `index.html`            | The page. Only the cards between `<!-- factoids:start -->` / `<!-- factoids:end -->` and the "Search N factoids…" count are machine-written; edit the rest freely. |
| `<slug>.html`           | One page per factoid.                                                |
| `another.js`            | "Another from the book": a random other factoid (with ↻ shuffle) under each page, read from `factoids.json`. |
| `images/`               | Screenshots copied out of Anytype for factoid pages.                 |
| `factoids.json`         | Which Anytype object owns which page, in the collection's order. A factoid keeps its URL when retitled. |
| `auth.local.json`       | `api_key`, `space_id`, `list_id`, `auto_push`. **Git-ignored.** Without it the feed is dormant. |
| `sync-state.local.json` | Last run, result, error. Git-ignored.                                |

## What a sync does

- **New factoid in the collection** → new card at its place in the grid, plus
  a page. Text, lists and links are rendered from Anytype's Markdown;
  screenshots are copied in as images; a title with no body gets "just the
  title"; a *Reference* property becomes a "Source ↗" link.
- **Edited factoid** → its page is re-rendered — *only* for factoids the sync
  added. The original 62 (June 2026 import) were tidied by hand, so their pages
  are frozen (`"managed": false` in `factoids.json`). To let the sync take one
  over, set its `managed` to `true` and run with `--rerender`.
- **Removed from the collection** → card and page are deleted. A sync that
  would remove more than 5 at once is refused, in case Anytype is mid-sync
  or the list id is wrong.
- Nothing changed → nothing is written.

New cards also trigger the usual push notification for the `commonplace`
bell (see `.github/workflows/notify.yml`) once pushed.

## Moving parts

- `.github/scripts/sync_commonplace.py` — fetch + render. Runnable on its own:
  `python3 .github/scripts/sync_commonplace.py` (`--rerender` redraws managed
  pages without adding or removing anything).
- `server.py` (section "Feeds") — the weekly timer, plus
  `GET /api/feed/commonplace` (status) and `POST /api/feed/commonplace/sync`
  (run now). The editor dashboard shows it as a **My Commonplace Book** card
  under *Feeds*, with a **Sync now** button.

## If the key stops working

The card shows **Last sync failed** with "rejected the API key": make a new key
in Anytype → *Settings → API keys* and put it in `auth.local.json` as
`api_key`. No restart needed — the file is read on every sync.

## Options

- **`auto_push`** in `auth.local.json` (default `false`): when a sync changes
  something, commit just the `commonplace/` folder and `git push`.
