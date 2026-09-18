# YouTube likes → /youtube-likes

The account's private **Liked videos** list is mirrored onto
[`/youtube-likes`](https://mrinaliniisin.github.io/youtube-likes) once a
week. The local editor server (`server.py` on :5666, the always-on runit
service) does the fetching: it reads the liked list from the YouTube Data
API and rewrites the page in place. Publishing is then a normal `git push`,
like every other edit — or flip `auto_push` (below) to have it commit and
push by itself.

| File                          | What                                                                 |
|-------------------------------|----------------------------------------------------------------------|
| `index.html`                  | The page. Only the part between `<!-- likes:start -->` / `<!-- likes:end -->` is machine-written; edit the rest freely. |
| `likes.json`                  | The data (appears after the first sync). Also remembers when each video was first seen, since YouTube doesn't expose like times. |
| `auth.local.json`             | Your OAuth credentials, written by `youtube_auth.py`. **Git-ignored.** Without it the feature is dormant. |
| `sync-state.local.json`       | Last run, result, error — so a restart doesn't reset the week. Git-ignored. |

Moving parts:

- `server.py` (section "YouTube likes") — the weekly timer (7 days from the
  last run, checked hourly, first run ~30 s after the server starts), plus
  `GET /api/youtube-likes` (status) and `POST /api/youtube-likes/sync` (run
  now). The editor dashboard shows both as a **YouTube Likes** card under
  *Feeds*, with a **Sync now** button.
- `.github/scripts/sync_youtube_likes.py` — the fetch + render, imported by
  the server. Runnable on its own with the credentials in env.
- `.github/scripts/youtube_auth.py` — one-time helper that mints the
  refresh token and writes `auth.local.json`.
- `.github/workflows/youtube-likes.yml` — **manual-only** fallback ("Run
  workflow" in the Actions tab) for when this machine is off. Not on a cron
  on purpose: two schedulers committing the same files from different clones
  would race into merge conflicts. `git pull` locally after using it.

## One-time setup (~10 minutes)

1. **Google Cloud** → <https://console.cloud.google.com/> → create a project
   (any name). Under *APIs & Services → Library*, enable **YouTube Data API v3**.
2. *APIs & Services → OAuth consent screen*: user type **External**, fill in
   the app name and your email, add the scope
   `https://www.googleapis.com/auth/youtube.readonly`. Then set
   **Publishing status → In production**. (Leave it in *Testing* and Google
   expires the refresh token after 7 days, so the second weekly run fails.
   You'll see an "unverified app" warning during consent — expand *Advanced*
   and continue; that's expected for a personal app.)
3. *APIs & Services → Credentials → Create credentials → OAuth client ID*,
   application type **Desktop app**. Note the client id and secret.
4. Locally, from the repo root, mint the refresh token (opens a browser for
   consent, then offers to write `youtube-likes/auth.local.json`):

   ```sh
   python3 .github/scripts/youtube_auth.py
   ```

5. Restart the server so it picks the file up (runit respawns it):

   ```sh
   pkill -f "server.py 5666"
   ```

   It syncs on its own about 30 seconds later; or open
   <http://localhost:5666/editor.html> and press **Sync now** on the YouTube
   Likes card. The first run files everything under "Earlier"; each later
   like lands under the month the sync caught it.
6. `git push` to publish (or see *auto_push*).

### GitHub Action fallback (optional)

Add the same three values as repository secrets — *Settings → Secrets and
variables → Actions*: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN`
(the auth script prints them). Then *Actions → Sync YouTube likes → Run
workflow* whenever you want a sync without this machine.

## Options

- **`auto_push`** in `auth.local.json` (default `false`): when a sync
  changes something, commit just `index.html` + `likes.json` from this
  folder and `git push`. Anything else uncommitted in the tree is left alone.
- How often: `YT_EVERY` in `server.py` (default 7 days).
- How many likes to mirror: `MAX_VIDEOS` in `sync_youtube_likes.py`
  (default 300, newest first; `YT_MAX_VIDEOS` env in script mode).
- If the card shows **Last sync failed** with `invalid_grant`, the token was
  revoked or expired (usually the *Testing* status above): fix that, re-run
  `youtube_auth.py`, restart the server.
