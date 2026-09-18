#!/usr/bin/env python3
"""Mirror the signed-in account's YouTube "Liked videos" onto /youtube-likes.

Two callers share this module:

  * server.py (the local editor on :5666) imports it and runs `sync()` on a
    weekly timer and from the editor's "Sync now" button, with credentials
    read from youtube-likes/auth.local.json (git-ignored; written by
    youtube_auth.py).
  * .github/workflows/youtube-likes.yml runs it as a script with the same
    three values in env, as a manual fallback from the Actions tab.

Either way it trades the stored refresh token for an access token, pages
through the documented `videos.list?myRating=like` endpoint (most recently
liked first), and writes two things in youtube-likes/:

  likes.json   — the list itself, plus per-video `first_seen` (the date this
                 sync first saw the video liked; YouTube doesn't expose the
                 like time, so we remember it ourselves across runs).
  index.html   — the static page. Only the part between the
                 <!-- likes:start --> / <!-- likes:end --> markers is
                 regenerated, so the surrounding page can be edited by hand.

Videos are grouped by the month they were first seen, newest month first.
Everything from the very first run has no first_seen (there's no honest date
to give it) and lands in a trailing "Earlier" group; from then on each new
like files under the month the sync caught it. Unliking a video drops it —
the page mirrors YouTube, it isn't a log.

Nothing is written when the list is unchanged (the "updated" date on the
page is therefore the last change, not the last run).

Env (script mode):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN   from youtube_auth.py
  YT_MAX_VIDEOS   optional cap on how many likes to mirror (default 300)
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT_DIR = os.path.join(ROOT, "youtube-likes")
DATA_PATH = os.path.join(OUT_DIR, "likes.json")
PAGE_PATH = os.path.join(OUT_DIR, "index.html")

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3/videos"
MAX_VIDEOS = int(os.environ.get("YT_MAX_VIDEOS", "300"))

START, END = "<!-- likes:start -->", "<!-- likes:end -->"
CRED_KEYS = ("client_id", "client_secret", "refresh_token")


class SyncError(Exception):
    """Anything that should stop a run with a message rather than a trace."""


def creds_from_env():
    env = {"client_id": "YT_CLIENT_ID", "client_secret": "YT_CLIENT_SECRET",
           "refresh_token": "YT_REFRESH_TOKEN"}
    missing = [v for v in env.values() if not os.environ.get(v)]
    if missing:
        raise SyncError("Missing env: %s (see youtube-likes/README.md)" % ", ".join(missing))
    return {k: os.environ[v] for k, v in env.items()}


def _http_error(prefix, e):
    try:
        detail = e.read().decode()
    except Exception:
        detail = ""
    return SyncError("%s: %s %s" % (prefix, e.code, detail[:300]))


def access_token(creds):
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
            return json.load(r)["access_token"]
    except urllib.error.HTTPError as e:
        # invalid_grant here almost always means the token expired because the
        # OAuth consent screen is still in "Testing" (7-day tokens) or the
        # grant was revoked — re-run youtube_auth.py after fixing that.
        raise _http_error("Token refresh failed", e)
    except urllib.error.URLError as e:
        raise SyncError("Token refresh failed: %s" % e.reason)


def fetch_likes(token, limit=None):
    limit = limit or MAX_VIDEOS
    items, page = [], None
    while True:
        q = {"part": "snippet", "myRating": "like", "maxResults": "50"}
        if page:
            q["pageToken"] = page
        req = urllib.request.Request(API + "?" + urllib.parse.urlencode(q),
                                     headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
        except urllib.error.HTTPError as e:
            raise _http_error("YouTube API error", e)
        except urllib.error.URLError as e:
            raise SyncError("YouTube API unreachable: %s" % e.reason)
        for v in data.get("items", []):
            sn = v.get("snippet", {})
            items.append({
                "id": v["id"],
                "title": sn.get("title", ""),
                "channel": sn.get("channelTitle", ""),
                "published": (sn.get("publishedAt") or "")[:10],
                "url": "https://www.youtube.com/watch?v=" + v["id"],
            })
            if len(items) >= limit:
                return items
        page = data.get("nextPageToken")
        if not page:
            return items


def load_previous():
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def merge(items, previous, today):
    """Carry each video's first_seen over from the last run. On the very
    first run there is no previous file, so nothing gets a date."""
    seen = {v["id"]: v.get("first_seen", "") for v in (previous or {}).get("videos", [])}
    for v in items:
        v["first_seen"] = seen.get(v["id"], today if previous is not None else "")
    return items


def month_label(first_seen):
    if not first_seen:
        return "Earlier"
    return dt.date.fromisoformat(first_seen).strftime("%B %Y")


def render(videos, updated):
    if not videos:
        return '<p class="likes-empty">No liked videos yet.</p>'
    # Group by first-seen month; dated groups newest first, undated last.
    groups = []
    for v in videos:
        key = v["first_seen"][:7]
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(v)
    groups.sort(key=lambda g: g[0], reverse=True)  # "" sorts last on reverse

    nice_date = dt.date.fromisoformat(updated).strftime("%-d %B %Y")
    out = ['<p class="post-meta">%d videos &middot; updated %s</p>' % (len(videos), nice_date)]
    for key, vids in groups:
        out.append('<section class="likes-group">')
        out.append('  <h2>%s</h2>' % html.escape(month_label(vids[0]["first_seen"])))
        out.append('  <ul class="likes">')
        for v in vids:
            t, ch = html.escape(v["title"]), html.escape(v["channel"])
            out.append(
                '    <li>'
                '<a class="thumb" href="%(u)s" target="_blank" rel="noopener" tabindex="-1" aria-hidden="true">'
                '<img src="https://i.ytimg.com/vi/%(id)s/mqdefault.jpg" alt="" loading="lazy" width="120" height="68"></a>'
                '<div class="what"><a href="%(u)s" target="_blank" rel="noopener">%(t)s</a>'
                '<span class="channel">%(ch)s</span></div>'
                '</li>' % {"u": html.escape(v["url"]), "id": v["id"], "t": t, "ch": ch})
        out.append('  </ul>')
        out.append('</section>')
    return "\n".join(out)


def write_page(fragment):
    with open(PAGE_PATH, encoding="utf-8") as f:
        page = f.read()
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pat.search(page):
        raise SyncError("%s has no %s/%s markers" % (PAGE_PATH, START, END))
    page = pat.sub(lambda _: "%s\n%s\n%s" % (START, fragment, END), page, count=1)
    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(page)


def sync(creds, today=None):
    """Fetch, merge, and write if anything changed. Returns a summary dict;
    raises SyncError on auth/API/page problems."""
    missing = [k for k in CRED_KEYS if not creds.get(k)]
    if missing:
        raise SyncError("Credentials missing: %s" % ", ".join(missing))
    today = today or dt.date.today().isoformat()
    previous = load_previous()
    videos = merge(fetch_likes(access_token(creds)), previous, today)

    if previous is not None and previous.get("videos") == videos:
        return {"changed": False, "count": len(videos), "new": 0, "updated": previous.get("updated")}

    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump({"updated": today, "videos": videos}, f, indent=1, ensure_ascii=False)
        f.write("\n")
    write_page(render(videos, today))
    new = sum(1 for v in videos if v["first_seen"] == today)
    return {"changed": True, "count": len(videos), "new": new, "updated": today}


def main():
    try:
        r = sync(creds_from_env())
    except SyncError as e:
        sys.exit(str(e))
    if r["changed"]:
        print("Wrote %d liked videos (%d new this run)." % (r["count"], r["new"]))
    else:
        print("Unchanged: %d liked videos." % r["count"])


if __name__ == "__main__":
    main()
