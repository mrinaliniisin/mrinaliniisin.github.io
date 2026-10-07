#!/usr/bin/env python3
"""Mirror the Anytype "My Commonplace Book" collection onto /commonplace.

server.py (the local editor on :5666) imports this and runs `sync()` on a
weekly timer and from the editor's "Sync now" button, with settings read from
commonplace/auth.local.json (git-ignored):

  {"api_key": "...", "space_id": "...", "list_id": "...", "auto_push": false}

Anytype's API only listens on this machine (127.0.0.1:31009, and images come
from its gateway on :47800), so unlike YouTube Likes there is no GitHub Action
fallback: the desktop app has to be open for a sync to work.

What gets written in commonplace/:

  factoids.json  — one row per factoid, in the collection's order: its Anytype
                   id, the page slug, title, search text and last-modified
                   time. This is the memory of which Anytype object owns which
                   URL, so a retitled factoid keeps its address.
  index.html     — only the cards between <!-- factoids:start --> and
                   <!-- factoids:end -->, plus the search box's count.
  <slug>.html    — one page per factoid.
  images/        — screenshots copied out of Anytype for factoid pages.

Anytype is the source of truth: every row is "managed": true and follows
later edits there. (The 62 June 2026 imports were hand-tidied and frozen as
"managed": false until October 2026, when their site-only content was copied
back into Anytype.) A "managed": false row is still never rewritten. Removing
a factoid from the collection removes its card and page.

Script mode:
  python3 .github/scripts/sync_commonplace.py            sync now
  python3 .github/scripts/sync_commonplace.py --seed     build factoids.json
        from the current index.html + Anytype (one-time; existing rows are
        adopted as unmanaged), then sync
  python3 .github/scripts/sync_commonplace.py --rerender redraw pages and
        cards from factoids.json + Anytype without adding/removing anything
"""
import datetime as dt
import html
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT_DIR = os.path.join(ROOT, "commonplace")
DATA_PATH = os.path.join(OUT_DIR, "factoids.json")
INDEX_PATH = os.path.join(OUT_DIR, "index.html")
AUTH_PATH = os.path.join(OUT_DIR, "auth.local.json")
IMG_DIR = os.path.join(OUT_DIR, "images")

API = "http://127.0.0.1:31009/v1"
API_VERSION = "2025-11-08"
START, END = "<!-- factoids:start -->", "<!-- factoids:end -->"
# A sync that would delete more than this many factoids at once is refused —
# far more likely a wrong list id or a half-synced Anytype than a real purge.
MAX_REMOVALS = 5


class SyncError(Exception):
    pass


# ---------------------------------------------------------------------------
# Anytype API

class Anytype:
    def __init__(self, auth):
        for k in ("api_key", "space_id", "list_id"):
            if not auth.get(k):
                raise SyncError("commonplace/auth.local.json is missing %r" % k)
        self.auth = auth
        self.headers = {"Authorization": "Bearer " + auth["api_key"],
                        "Anytype-Version": API_VERSION}

    def get(self, path):
        req = urllib.request.Request(API + path, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            if e.code == 401:
                raise SyncError("Anytype rejected the API key (401) — make a new one "
                                "in Anytype → Settings → API keys")
            raise SyncError("Anytype API %s: HTTP %s %s" % (path.split("?")[0], e.code, body))
        except urllib.error.URLError as e:
            raise SyncError("Can't reach Anytype on 127.0.0.1:31009 — is the desktop app "
                            "open? (%s)" % e.reason)

    def factoids(self):
        """Every object in the collection, in its (first) view's order."""
        s, l = self.auth["space_id"], self.auth["list_id"]
        views = self.get("/spaces/%s/lists/%s/views" % (s, l))["data"]
        if not views:
            raise SyncError("The Commonplace collection has no views")
        out, offset = [], 0
        while True:
            page = self.get("/spaces/%s/lists/%s/views/%s/objects?limit=100&offset=%d"
                            % (s, l, views[0]["id"], offset))
            out += page["data"]
            if not page["pagination"]["has_more"]:
                break
            offset += 100
        return [o for o in out if not o.get("archived")]

    def body(self, obj_id):
        o = self.get("/spaces/%s/objects/%s?format=md" % (self.auth["space_id"], obj_id))
        return o["object"].get("markdown") or ""


def prop(obj, key):
    for p in obj.get("properties") or []:
        if p.get("key") == key:
            return p.get(p.get("format"))
    return None


# ---------------------------------------------------------------------------
# Markdown -> HTML (just what Anytype's export produces; stdlib only, so the
# runit service needs nothing installed)

IMG_RE = re.compile(r"!\[([^\]]*)\]\((http://127\.0\.0\.1:\d+/image/([A-Za-z0-9]+))\)")


def fetch_image(url, cid):
    """Copy an Anytype image into commonplace/images/ once; returns its site path."""
    os.makedirs(IMG_DIR, exist_ok=True)
    for name in os.listdir(IMG_DIR):
        if name.split(".")[0] == cid:
            return "/commonplace/images/" + name
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                   "image/webp": "webp"}.get(r.headers.get_content_type(), "png")
            data = r.read()
    except urllib.error.URLError as e:
        raise SyncError("Couldn't download an image from Anytype (%s)" % e)
    name = "%s.%s" % (cid, ext)
    with open(os.path.join(IMG_DIR, name), "wb") as f:
        f.write(data)
    return "/commonplace/images/" + name


def _inline(text, alt):
    """Escape one line and turn Markdown links/emphasis into HTML."""
    keep = []

    def stash(s):
        keep.append(s)
        return "\x00%d\x00" % (len(keep) - 1)

    text = re.sub(r"`([^`]+)`", lambda m: stash("<code>%s</code>" % html.escape(m.group(1))), text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: stash(
        '<a href="%s" target="_blank" rel="noopener">%s</a>'
        % (html.escape(m.group(2).replace("\\_", "_")), html.escape(_unescape(m.group(1))))), text)
    text = re.sub(r"https?://[^\s<>)\]]+", lambda m: stash(
        '<a href="%s" target="_blank" rel="noopener">%s</a>'
        % (html.escape(m.group(0)), html.escape(m.group(0)))), text)
    text = html.escape(_unescape(text), quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], text)


def _unescape(s):
    return re.sub(r"\\([\\`*_{}\[\]()#+\-.!>|&~])", r"\1", s)


def _kind(line):
    s = line.strip()
    if s.startswith("\x01"):
        return "img"
    if re.match(r"#{1,6} ", s):
        return "h"
    if re.match(r"[-*+] ", s):
        return "ul"
    if re.match(r"\d+[.)] ", s):
        return "ol"
    if s.startswith(">"):
        return "quote"
    if s.startswith("|"):
        return "table"
    return "p"


def _cells(line):
    return [re.sub(r"\s*<br>\s*$", "", c).strip() for c in line.strip().strip("|").split("|")]


def _table(lines, title):
    rows = [_cells(l) for l in lines if not re.fullmatch(r"\|?[\s:|-]+\|?", l.strip())]
    head, body = rows[0], rows[1:]
    th = "".join("<th>%s</th>" % _inline(c, title) for c in head)
    trs = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % _inline(c, title) for c in r)
                  for r in body)
    return ('<div class="table-scroll"><table><thead><tr>%s</tr></thead>'
            '<tbody>%s</tbody></table></div>' % (th, trs))


def md_to_html(md, title):
    """Anytype's export puts each block on its own line (blank lines are just
    empty blocks), so this works line by line: runs of list items, quote lines
    or table rows group together, and every other line is its own paragraph.
    A closing "Source: …" paragraph is set small, like the Reference link."""
    md = re.sub(r"</?details>", "", md)
    md = re.sub(r"<summary>(.*?)</summary>", r"\1\n", md, flags=re.S)
    md = IMG_RE.sub(lambda m: "\n\x01%s\x01\n" % fetch_image(m.group(2), m.group(3)), md)
    groups = []  # [kind, [lines]]
    for line in md.split("\n"):
        if not line.strip():
            groups.append(["blank", []])
            continue
        kind = _kind(line)
        if groups and groups[-1][0] == kind and kind in ("ul", "ol", "quote", "table"):
            groups[-1][1].append(line.strip())
        else:
            groups.append([kind, [line.strip()]])
    out = []
    for kind, lines in groups:
        if kind == "blank":
            continue
        if kind == "img":
            src = lines[0].strip("\x01")
            out.append('<p><img src="%s" alt="%s" loading="lazy" style="max-width:100%%;'
                       'height:auto;border-radius:8px"></p>' % (src, html.escape(title)))
        elif kind == "h":
            level = 2 if len(lines[0]) - len(lines[0].lstrip("#")) <= 2 else 3
            out.append("<h%d>%s</h%d>" % (level, _inline(lines[0].lstrip("#").strip(), title), level))
        elif kind in ("ul", "ol"):
            out.append("<%s>%s</%s>" % (kind, "".join(
                "<li>%s</li>" % _inline(re.sub(r"^([-*+]|\d+[.)]) ", "", l), title)
                for l in lines), kind))
        elif kind == "quote":
            out.append("<blockquote><p>%s</p></blockquote>" % "<br>".join(
                _inline(l[1:].strip(), title) for l in lines))
        elif kind == "table":
            out.append(_table(lines, title))
        else:
            out.append("<p>%s</p>" % _inline(lines[0], title))
    if out and groups and [g for g in groups if g[0] != "blank"][-1][0] == "p" \
            and out[-1].startswith("<p>Source:"):
        out[-1] = '<p class="post-meta" style="margin-top:28px">' + out[-1][3:]
    return out


def search_text(title, md):
    """The card's data-text: title + body as plain lowercase text."""
    body = IMG_RE.sub("", md)
    body = re.sub(r"</?(details|summary)>", "", body)
    body = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1", body)
    body = re.sub(r"(?<!\\)(\*\*|\*|`)", "", body)
    body = re.sub(r"(?m)^\s*(#{1,6}|>|[-+]|\d+[.)])\s+", "", body)
    body = re.sub(r"(?m)^\|?[\s:|-]+\|?$", "", body)  # table separator rows
    body = re.sub(r"\s*<br>\s*|\s*\|\s*", " ", body)
    body = re.sub(r"\\([\\`*_{}\[\]()#+\-.!>|&~])", r"\1", body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return ("%s %s" % (title, _unescape(body))).lower()


# ---------------------------------------------------------------------------
# Pages

def _footer():
    with open(INDEX_PATH, encoding="utf-8") as f:
        m = re.search(r"  <footer>.*?</footer>", f.read(), re.S)
    return m.group(0) if m else ""


PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} · My Commonplace Book</title>
  <link rel="stylesheet" href="/assets/blog.css">
</head>
<body>
  <main class="wrap">
    <a class="back" href="/commonplace/">← My Commonplace Book</a>
    <article>
      <h1 class="post-title">{title}</h1>
      <div class="post-body">
{body}
      </div>
    </article>
  </main>
{footer}
  <script src="/commonplace/another.js" defer></script>
  <script src="/assets/analytics.js" defer></script>
</body>
</html>
"""


def render_page(row, md, reference):
    title = html.escape(row["name"])
    parts = md_to_html(md, row["name"]) or \
        ['<p class="post-meta">No further notes &mdash; just the title.</p>']
    if reference:
        parts.append('<p class="post-meta" style="margin-top:28px"><a href="%s" target="_blank" '
                     'rel="noopener">Source &#8599;</a></p>' % html.escape(reference))
    body = "\n".join("      " + p for p in parts)
    return PAGE.format(title=title, body=body, footer=_footer())


def render_cards(rows):
    return "\n".join(
        '      <a class="cpb-card" href="/commonplace/%s.html" data-text="%s"><h2>%s</h2></a>'
        % (r["slug"], html.escape(r["text"]), html.escape(r["name"])) for r in rows)


def write_index(rows):
    with open(INDEX_PATH, encoding="utf-8") as f:
        page = f.read()
    if START not in page or END not in page:
        raise SyncError("commonplace/index.html has lost its %s / %s markers" % (START, END))
    head, rest = page.split(START, 1)
    tail = rest.split(END, 1)[1]
    page = head + START + "\n" + render_cards(rows) + "\n      " + END + tail
    page = re.sub(r'placeholder="Search \d+ factoids…"',
                  'placeholder="Search %d factoids…"' % len(rows), page)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(page)


# ---------------------------------------------------------------------------
# Sync

def slugify(text, taken):
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "factoid"
    slug, n = base, 2
    while slug in taken or os.path.exists(os.path.join(OUT_DIR, slug + ".html")):
        slug, n = "%s-%d" % (base, n), n + 1
    return slug


def load_data():
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SyncError("No commonplace/factoids.json yet — run "
                        ".github/scripts/sync_commonplace.py --seed once")


def save_data(data):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")


def _prune_images(rows):
    if not os.path.isdir(IMG_DIR):
        return
    used = set()
    for r in rows:
        if r.get("managed"):
            with open(os.path.join(OUT_DIR, r["slug"] + ".html"), encoding="utf-8") as f:
                used.update(re.findall(r"/commonplace/images/([^\"]+)", f.read()))
    for name in os.listdir(IMG_DIR):
        if name not in used:
            os.remove(os.path.join(IMG_DIR, name))


def sync(auth, today=None, rerender=False):
    """One pass. Returns {changed, count, new, removed, edited, updated}."""
    today = today or dt.date.today().isoformat()
    api = Anytype(auth)
    data = load_data()
    old = {r["id"]: r for r in data["factoids"]}
    objs = api.factoids()
    if not objs:
        raise SyncError("Anytype returned an empty collection — refusing to wipe the page")
    live = {o["id"] for o in objs}
    removed = [r for r in data["factoids"] if r["id"] not in live]
    if len(removed) > MAX_REMOVALS and not rerender:
        raise SyncError("Anytype no longer lists %d factoids (%s…) — refusing to delete that "
                        "many at once" % (len(removed), ", ".join(r["name"] for r in removed[:3])))

    rows, new, edited = [], 0, 0
    taken = {r["slug"] for r in data["factoids"]}
    for o in objs:
        name, modified = o.get("name") or "Untitled", prop(o, "last_modified_date")
        row = old.get(o["id"])
        if row is None:
            if rerender:
                continue
            row = {"id": o["id"], "slug": slugify(name, taken), "managed": True}
            taken.add(row["slug"])
            new += 1
        elif not row.get("managed") or (row.get("modified") == modified and not rerender):
            rows.append(row)
            continue
        else:
            edited += row.get("modified") != modified
        md = api.body(o["id"])
        row.update(name=name, modified=modified, created=prop(o, "created_date"),
                   text=search_text(name, md))
        with open(os.path.join(OUT_DIR, row["slug"] + ".html"), "w", encoding="utf-8") as f:
            f.write(render_page(row, md, prop(o, "reference")))
        rows.append(row)

    order_changed = [r["id"] for r in rows] != [r["id"] for r in data["factoids"]]
    changed = bool(new or edited or removed or order_changed or rerender)
    if not changed:
        return {"changed": False, "count": len(rows), "new": 0, "removed": 0,
                "edited": 0, "updated": data.get("updated")}

    for r in ([] if rerender else removed):
        try:
            os.remove(os.path.join(OUT_DIR, r["slug"] + ".html"))
        except FileNotFoundError:
            pass
    if rerender:
        rows += [r for r in removed]  # --rerender never drops anything
    write_index(rows)
    _prune_images(rows)
    data.update(updated=today, factoids=rows)
    save_data(data)
    return {"changed": True, "count": len(rows), "new": new,
            "removed": 0 if rerender else len(removed), "edited": edited, "updated": today}


def seed(auth):
    """Adopt the hand-made cards already in index.html as unmanaged rows,
    matched to Anytype objects by title (in order, so duplicates pair up)."""
    if os.path.exists(DATA_PATH):
        raise SyncError("commonplace/factoids.json already exists")
    with open(INDEX_PATH, encoding="utf-8") as f:
        page = f.read()
    cards = re.findall(r'<a class="cpb-card" href="/commonplace/([^"]+)\.html" '
                       r'data-text="([^"]*)"><h2>(.*?)</h2></a>', page, re.S)
    pool = {}
    for o in Anytype(auth).factoids():
        pool.setdefault(o.get("name") or "", []).append(o)
    rows = []
    for slug, text, name in cards:
        name = html.unescape(name)
        if not pool.get(name):
            raise SyncError("No Anytype factoid is titled %r (card %s)" % (name, slug))
        o = pool[name].pop(0)
        rows.append({"id": o["id"], "slug": slug, "managed": False, "name": name,
                     "modified": prop(o, "last_modified_date"),
                     "created": prop(o, "created_date"), "text": html.unescape(text)})
    # Put the markers around the grid's cards so later syncs can rewrite them.
    if START not in page:
        page = re.sub(r'(<div class="cpb-grid" id="grid">\n)(.*?)(\n    </div>)',
                      lambda m: m.group(1) + "      " + START + "\n" + m.group(2) +
                      "\n      " + END + m.group(3), page, count=1, flags=re.S)
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            f.write(page)
    save_data({"updated": None, "factoids": rows})
    return len(rows)


def main():
    try:
        with open(AUTH_PATH, encoding="utf-8") as f:
            auth = json.load(f)
    except FileNotFoundError:
        sys.exit("No commonplace/auth.local.json — see commonplace/README.md")
    try:
        if "--seed" in sys.argv:
            print("Adopted %d existing factoids" % seed(auth))
        print(json.dumps(sync(auth, rerender="--rerender" in sys.argv)))
    except SyncError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
