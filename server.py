#!/usr/bin/env python3
"""Local save server for the blog.

Serves the static site AND backs editor.html with two endpoints:

  POST /api/save   {title, date, markdown, html}  -> writes blog/<slug>.html
                                                      and updates blog/index.html
  GET  /api/load?p=<slug>                          -> {title, date, markdown}

Posts are pre-rendered: editor.html renders markdown -> HTML with marked.js at
save time and POSTs both; this server just writes files. The markdown source is
preserved inside each post as an <!--EDIT:post:b64:...--> comment, so the editor
can reload and re-save a post. Publishing is a normal `git push` afterwards.

Run from the repo root:  python3 server.py [port]   (default 5666)

5666 is the port the always-on runit service uses, so the default matches it.
"""

import base64
import hmac
import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.getcwd()
BLOG = os.path.join(ROOT, "blog")
INDEX = os.path.join(BLOG, "index.html")
IMAGES = os.path.join(BLOG, "images")
INDEX_HTML = os.path.join(ROOT, "index.html")

# Local, git-ignored file holding the homepage edit-mode key (one line). Absent =
# edit mode disabled. The browser sends the key; the server validates it HERE, so
# it's a real server-side check — not a bypassable client-side "if key===" that
# would ship in the public page.
EDIT_KEY_FILE = os.path.join(ROOT, ".edit-key")

# Hand-built standalone pages that page-editor.html may open and overwrite as
# raw HTML. The allowlist — not a path check — is the security boundary: the
# save endpoint refuses anything not in this list, so it can't traverse out of
# the repo. Deliberately ABSENT: blog posts (edit via editor.html) and
# generated pages — commonplace/* and the JPeterman build — whose HTML is
# rebuilt from data, so a hand-edit would be lost on the next regenerate.
EDITABLE_PAGES = [
    "index.html",
]

# Clipboard images arrive as a MIME type, not a filename, so map it to a suffix.
IMAGE_EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/gif": "gif", "image/webp": "webp", "image/svg+xml": "svg",
}

POST_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_attr} · Mrinalini S</title>
  <meta name="post-title" content="{title_attr}">
  <meta name="post-date" content="{date_iso}">
  <link rel="stylesheet" href="/assets/blog.css">
</head>
<body>
  <main class="wrap">
    <a class="back" href="/blog/">← All posts</a>
    <article>
      <h1 class="post-title">{title_html}</h1>
      <p class="post-meta">{date_human}</p>
<!--EDIT:post:b64:{b64}-->
      <div class="post-body" data-edit-id="post" data-edit-file="blog/{slug}.html">
{body_html}
      </div>
<!--/EDIT:post-->
    </article>
  </main>
  <footer>&copy; 2026 Mrinalini S · Code licensed under MIT</footer>
  <script src="/assets/analytics.js" defer></script>
</body>
</html>
"""

# A standalone "page": same markdown round-trip as a
# post, but it lives at the repo root, links Home instead of "All posts", carries
# no date, and is NOT added to the blog index. The page-kind meta marks it so the
# editor can tell a markdown page apart from a post or hand-built HTML.
PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title_attr} · Mrinalini S</title>
  <meta name="page-title" content="{title_attr}">
  <meta name="page-kind" content="standalone">
  <link rel="stylesheet" href="/assets/blog.css">
</head>
<body>
  <main class="wrap">
    <a class="back" href="/">← Home</a>
    <article>
      <h1 class="post-title">{title_html}</h1>
<!--EDIT:post:b64:{b64}-->
      <div class="post-body" data-edit-id="post" data-edit-file="{slug}.html">
{body_html}
      </div>
<!--/EDIT:post-->
    </article>
  </main>
  <footer>&copy; 2026 Mrinalini S · Code licensed under MIT</footer>
  <script src="/assets/analytics.js" defer></script>
</body>
</html>
"""


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "post"


def human_date(iso):
    try:
        d = datetime.strptime(iso, "%Y-%m-%d")
        return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")
    except ValueError:
        return iso


def write_post(title, date_iso, markdown, body_html):
    slug = slugify(title)
    # The title comes from the title field and is rendered by the template, so
    # drop a leading <h1> from the body to avoid showing the title twice.
    body_html = re.sub(r"^\s*<h1\b[^>]*>.*?</h1>\s*", "", body_html,
                       count=1, flags=re.S | re.I)
    b64 = base64.b64encode(markdown.encode("utf-8")).decode("ascii")
    page = POST_TEMPLATE.format(
        title_attr=html.escape(title, quote=True),
        title_html=html.escape(title),
        date_iso=date_iso,
        date_human=human_date(date_iso),
        b64=b64,
        slug=slug,
        body_html=body_html,
    )
    with open(os.path.join(BLOG, slug + ".html"), "w", encoding="utf-8") as f:
        f.write(page)
    update_index(slug, title, date_iso)
    return slug


def update_index(slug, title, date_iso):
    with open(INDEX, encoding="utf-8") as f:
        text = f.read()

    href = '/blog/%s.html' % slug
    # Drop any existing card for this slug and the "no posts yet" placeholder,
    # matching the same 6-space-indented <div class="card">...</div> block
    # shape as CARD_RE (see the homepage's reorder_index/remove_card above) —
    # each card spans multiple lines now, so this can't be a per-line filter.
    block_re = re.compile(
        r'      <div class="card( empty)?">\n.*?\n      </div>\n?', re.S)
    text = block_re.sub(
        lambda m: '' if (m.group(1) or _card_href(m.group(0)) == href) else m.group(0),
        text)

    card = ('      <div class="card">\n'
            '        <a class="card-link" href="%s" aria-label="%s"></a>\n'
            '        <h2>%s</h2>\n'
            '        <div class="desc">%s</div>\n'
            '      </div>\n'
            % (href, html.escape(title, quote=True), html.escape(title), human_date(date_iso)))

    # newest first, right under the marker
    text = text.replace("<!--POSTS-->\n", "<!--POSTS-->\n" + card, 1)
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write(text)


def save_image(title, mime, b64):
    ext = IMAGE_EXT.get((mime or "").lower())
    if not ext:
        raise ValueError("unsupported image type: %r" % mime)
    os.makedirs(IMAGES, exist_ok=True)
    # Name images after the post slug so they sort and read sensibly; before a
    # title exists, fall back to a timestamp so the paste still works.
    base = slugify(title) if title.strip() else datetime.now().strftime("img-%Y%m%d-%H%M%S")
    n = 1
    while os.path.exists(os.path.join(IMAGES, "%s-%d.%s" % (base, n, ext))):
        n += 1
    name = "%s-%d.%s" % (base, n, ext)
    with open(os.path.join(IMAGES, name), "wb") as f:
        f.write(base64.b64decode(b64))
    return "/blog/images/" + name


def load_post(slug):
    path = os.path.join(BLOG, slug + ".html")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        src = f.read()
    title = re.search(r'name="post-title" content="([^"]*)"', src)
    date = re.search(r'name="post-date" content="([^"]*)"', src)
    b64 = re.search(r"<!--EDIT:post:b64:(.*?)-->", src, re.S)
    markdown = ""
    if b64:
        markdown = base64.b64decode(b64.group(1)).decode("utf-8")
    return {
        "title": html.unescape(title.group(1)) if title else "",
        "date": date.group(1) if date else "",
        "markdown": markdown,
    }


def write_md_page(title, markdown, body_html, slug=None):
    """Render a standalone markdown page to <slug>.html at the repo root.
    An explicit slug (from the editor when re-saving) keeps the filename — and
    thus the homepage link — stable even if the title changes."""
    slug = slugify(slug or title)
    body_html = re.sub(r"^\s*<h1\b[^>]*>.*?</h1>\s*", "", body_html,
                       count=1, flags=re.S | re.I)
    b64 = base64.b64encode(markdown.encode("utf-8")).decode("ascii")
    page = PAGE_TEMPLATE.format(
        title_attr=html.escape(title, quote=True),
        title_html=html.escape(title),
        b64=b64, slug=slug, body_html=body_html)
    with open(os.path.join(ROOT, slug + ".html"), "w", encoding="utf-8") as f:
        f.write(page)
    return slug


def load_md_page(slug):
    path = os.path.join(ROOT, slugify(slug) + ".html")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if 'name="page-kind"' not in src:   # only round-trip pages this tool authored
        return None
    title = re.search(r'name="page-title" content="([^"]*)"', src)
    b64 = re.search(r"<!--EDIT:post:b64:(.*?)-->", src, re.S)
    return {
        "slug": slugify(slug),
        "title": html.unescape(title.group(1)) if title else "",
        "markdown": base64.b64decode(b64.group(1)).decode("utf-8") if b64 else "",
    }


def list_md_pages():
    """Every standalone markdown page at the repo root (for the editor picker)."""
    out = []
    for n in sorted(os.listdir(ROOT)):
        path = os.path.join(ROOT, n)
        if not n.endswith(".html") or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            src = f.read()
        if 'name="page-kind" content="standalone"' not in src:
            continue
        title = re.search(r'name="page-title" content="([^"]*)"', src)
        out.append({"slug": n[:-5],
                    "title": html.unescape(title.group(1)) if title else n[:-5]})
    return out


def post_files():
    """Every published post HTML file (skips the listing index)."""
    if not os.path.isdir(BLOG):
        return []
    return [os.path.join(BLOG, n) for n in sorted(os.listdir(BLOG))
            if n.endswith(".html") and n != "index.html"]


def list_posts():
    """Slug + title + date for every post, newest first (for the editor picker)."""
    out = []
    for path in post_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        title = re.search(r'name="post-title" content="([^"]*)"', src)
        date = re.search(r'name="post-date" content="([^"]*)"', src)
        out.append({
            "slug": os.path.basename(path)[:-5],
            "title": html.unescape(title.group(1)) if title else os.path.basename(path)[:-5],
            "date": date.group(1) if date else "",
        })
    out.sort(key=lambda p: (p["date"], p["slug"]), reverse=True)
    return out


def uncommitted_posts():
    """Root-relative hrefs of blog posts that exist on disk but aren't in the
    current HEAD commit. GitHub Pages only ever serves what's been pushed, so
    these are exactly the posts whose blog/index.html card would 404 live —
    blog/index.html itself is generated together with the post file (see
    update_index), so this only diverges when a post got committed/pushed
    without also committing its file, or hasn't been committed at all yet.
    Used so the local editor can preview the "coming soon" fallback
    (assets/blog-availability.js) without needing to actually push."""
    out = []
    for path in post_files():
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        r = subprocess.run(["git", "cat-file", "-e", "HEAD:" + rel],
                            cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            out.append("/" + rel)
    return out


def page_title(src, rel):
    """A human label for the page picker: <title>, else <h1>, else the path."""
    m = re.search(r"<title>(.*?)</title>", src, re.S | re.I)
    if m:
        return html.unescape(re.sub(r"\s+", " ", m.group(1)).strip())
    m = re.search(r"<h1[^>]*>(.*?)</h1>", src, re.S | re.I)
    if m:
        return html.unescape(re.sub(r"<[^>]+>", "", m.group(1)).strip())
    return rel


def editable_path(rel):
    """Absolute path for an allowlisted standalone page, or None if not allowed.
    Membership in EDITABLE_PAGES is what confines writes to known files; the
    normpath round-trip is a belt-and-suspenders guard against odd input."""
    rel = (rel or "").lstrip("/")
    if rel not in EDITABLE_PAGES:
        return None
    path = os.path.normpath(os.path.join(ROOT, rel))
    return path if path == os.path.join(ROOT, rel) else None


def list_pages():
    """Allowlisted standalone pages with a display title (for the page picker)."""
    out = []
    for rel in EDITABLE_PAGES:
        path = os.path.join(ROOT, rel)
        exists = os.path.isfile(path)
        title = rel
        if exists:
            with open(path, encoding="utf-8") as f:
                title = page_title(f.read(), rel)
        out.append({"path": rel, "title": title, "exists": exists})
    return out


def load_page(rel):
    path = editable_path(rel)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return {"path": rel.lstrip("/"), "html": f.read()}


def save_page(rel, content):
    path = editable_path(rel)
    if not path:
        raise ValueError("not an editable page: %r" % rel)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    rel = rel.lstrip("/")
    return {"path": rel, "url": "/" + rel}


def list_images():
    if not os.path.isdir(IMAGES):
        return []
    names = sorted(n for n in os.listdir(IMAGES)
                   if os.path.isfile(os.path.join(IMAGES, n)) and not n.startswith("."))
    # Map each image to the post slugs that reference it, by scanning the
    # rendered HTML (the human-readable /blog/images/<name> in each post body).
    usage = {n: [] for n in names}
    for path in post_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        slug = os.path.basename(path)[:-5]
        for n in names:
            if "/blog/images/" + n in src:
                usage[n].append(slug)
    out = []
    for n in names:
        st = os.stat(os.path.join(IMAGES, n))
        out.append({"name": n, "size": st.st_size,
                    "url": "/blog/images/" + n, "used_in": usage[n]})
    return out


def update_image_refs(old_name, new_name):
    """Repoint every reference to old_name at new_name, in both the rendered
    body HTML and the base64 Markdown source preserved in each post. Returns
    the number of posts changed."""
    old_ref = "/blog/images/" + old_name
    new_ref = "/blog/images/" + new_name
    count = 0
    for path in post_files():
        with open(path, encoding="utf-8") as f:
            src = f.read()
        changed = [old_ref in src]  # list so the nested repl can flip it
        src = src.replace(old_ref, new_ref)  # rendered <img src> occurrences

        def repl(m):  # the base64-encoded Markdown isn't touched by the replace above
            md = base64.b64decode(m.group(1)).decode("utf-8")
            if old_ref not in md:
                return m.group(0)
            changed[0] = True
            md = md.replace(old_ref, new_ref)
            return "<!--EDIT:post:b64:" + base64.b64encode(
                md.encode("utf-8")).decode("ascii") + "-->"

        src = re.sub(r"<!--EDIT:post:b64:(.*?)-->", repl, src, flags=re.S)
        if changed[0]:
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
            count += 1
    return count


def rename_image(old, new):
    old = os.path.basename(old or "")
    src_path = os.path.join(IMAGES, old)
    if not old or not os.path.isfile(src_path):
        raise ValueError("no such image: %r" % old)
    ext = os.path.splitext(old)[1].lower()             # keep the original format
    stem = slugify(os.path.splitext(os.path.basename(new or ""))[0])
    if not stem:
        raise ValueError("invalid new name")
    new_name = stem + ext
    if new_name == old:
        return {"name": old, "updated": 0}
    if os.path.exists(os.path.join(IMAGES, new_name)):
        raise ValueError("an image named %s already exists" % new_name)
    os.rename(src_path, os.path.join(IMAGES, new_name))
    return {"name": new_name, "updated": update_image_refs(old, new_name)}


def delete_image(name):
    name = os.path.basename(name or "")
    path = os.path.join(IMAGES, name)
    if not name or not os.path.isfile(path):
        raise ValueError("no such image: %r" % name)
    os.remove(path)
    return {"name": name}


# --- Homepage edit mode (key-gated drag-to-reorder) ---------------------------
# A card block is `      <div class="card"> ... \n      </div>` (6-space indent).
# Inner tags (desc/credit/gh) close inline or at deeper indent, so the first
# bare 6-space </div> after a card open is always that card's close.
CARD_RE = re.compile(r'      <div class="card">\n.*?\n      </div>', re.S)
GRID_RE = re.compile(r'(    <div class="grid">\n)(.*?)(\n    </div>)', re.S)


def _edit_key():
    try:
        with open(EDIT_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def key_ok(provided):
    k = _edit_key()
    return bool(k) and hmac.compare_digest(provided or "", k)


def _card_href(block):
    m = re.search(r'card-link" href="([^"]+)"', block)
    return m.group(1) if m else ""


def reorder_index(order):
    """Reorder the homepage cards to match `order` (a list of card-link hrefs).
    Cards not named in `order` are kept, in their original relative order."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    m = GRID_RE.search(src)
    if not m:
        raise ValueError("could not locate the card grid in index.html")
    blocks = CARD_RE.findall(m.group(2))
    by_href = {}
    for b in blocks:
        by_href.setdefault(_card_href(b), b)
    seen, new_blocks = set(), []
    for h in order:
        if h in by_href and h not in seen:
            new_blocks.append(by_href[h]); seen.add(h)
    for b in blocks:  # keep any unmentioned cards, in original order
        h = _card_href(b)
        if h not in seen:
            new_blocks.append(b); seen.add(h)
    new_grid = m.group(1) + "\n".join(new_blocks) + m.group(3)
    src = src[:m.start()] + new_grid + src[m.end():]
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(src)
    return [_card_href(b) for b in new_blocks]


def remove_card(href):
    """Drop the card whose card-link href matches, keeping the rest in order."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        src = f.read()
    m = GRID_RE.search(src)
    if not m:
        raise ValueError("could not locate the card grid in index.html")
    blocks = CARD_RE.findall(m.group(2))
    keep = [b for b in blocks if _card_href(b) != href]
    if len(keep) == len(blocks):
        raise ValueError("no card links to %r" % href)
    new_grid = m.group(1) + "\n".join(keep) + m.group(3)
    src = src[:m.start()] + new_grid + src[m.end():]
    with open(INDEX_HTML, "w", encoding="utf-8") as f:
        f.write(src)
    return len(keep)


def _repo_rel(href):
    """Repo-relative path a card href points at, or None if it leaves the site."""
    if re.match(r"^[a-z][a-z0-9+.-]*:", href, re.I) or href.startswith("//"):
        return None                                   # http:, mailto:, //cdn…
    rel = href.split("#")[0].split("?")[0].lstrip("/")
    if not rel:
        return None
    if os.path.normpath(os.path.join(ROOT, rel)).startswith(ROOT + os.sep):
        return rel
    return None                                       # traversal guard


def _site_html():
    skip = {".git", "node_modules", "__pycache__"}
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
        for n in filenames:
            if n.endswith(".html"):
                out.append(os.path.relpath(os.path.join(dirpath, n), ROOT))
    return sorted(out)


def _href_variants(rel):
    return (rel, "/" + rel, "./" + rel)


def inbound_links(rel):
    """HTML files containing an <a href> pointing at rel (excluding rel itself)."""
    hits = []
    for f in _site_html():
        if f == rel:
            continue
        with open(os.path.join(ROOT, f), encoding="utf-8", errors="ignore") as fh:
            src = fh.read()
        if any(('href="%s"' % v) in src for v in _href_variants(rel)):
            hits.append(f)
    return hits


def strip_inbound_links(rel):
    """Unwrap <a href="rel">text</a> -> text, so prose survives but the dead link goes."""
    changed = []
    for f in inbound_links(rel):
        p = os.path.join(ROOT, f)
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        new = src
        for v in _href_variants(rel):
            new = re.sub(r'<a\b[^>]*href="%s"[^>]*>(.*?)</a>' % re.escape(v),
                         lambda m: m.group(1), new, flags=re.S | re.I)
        if new != src:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(new)
            changed.append(f)
    return changed


def delete_plan(href):
    """Dry run: what dragging this card to the trash would do.

    kind == "file"     -> a standalone page; delete it and strip inbound links
    kind == "folder"   -> a directory or a subdirectory's index.html (a section):
                          card-only removal, files untouched
    kind == "external" -> off-site link; card-only removal
    kind == "missing"  -> nothing on disk (e.g. a separate repo); card-only removal
    """
    rel = _repo_rel(href)
    if rel is None:
        return {"href": href, "kind": "external", "target": None, "inbound": []}
    parts = rel.split("/")
    section_index = len(parts) > 1 and parts[-1] == "index.html"
    if href.endswith("/") or rel.endswith("/") or os.path.isdir(os.path.join(ROOT, rel)) or section_index:
        return {"href": href, "kind": "folder", "target": rel, "inbound": []}
    if not os.path.isfile(os.path.join(ROOT, rel)):
        return {"href": href, "kind": "missing", "target": rel, "inbound": []}
    # index.html's link to it IS the card, which remove_card() handles — don't
    # list it as a separate inbound link in the confirmation dialog.
    inbound = [f for f in inbound_links(rel) if f != "index.html"]
    return {"href": href, "kind": "file", "target": rel, "inbound": inbound}


def delete_card(href):
    """Remove the card; delete the page + strip inbound links only for kind=="file"."""
    plan = delete_plan(href)
    remove_card(href)                     # the card always goes
    deleted, unlinked = [], []
    if plan["kind"] == "file":
        p = os.path.join(ROOT, plan["target"])
        if os.path.isfile(p):
            os.remove(p)
            deleted.append(plan["target"])
        # Only now that the page is gone do links to it become dead.
        unlinked = strip_inbound_links(plan["target"])
    return {"kind": plan["kind"], "target": plan["target"],
            "deleted": deleted, "unlinked": unlinked}


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Local dev only (never runs on GitHub Pages, which serves the
        # deployed static files through its own CDN/cache headers): plain
        # SimpleHTTPRequestHandler sends no Cache-Control, so Chrome's
        # heuristic caching can keep serving a stale JS/CSS file for minutes
        # after editing it — very confusing mid-edit. Disable caching
        # entirely here since freshness matters far more than speed for a
        # single local editor.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path.startswith("/api/load"):
            slug = slugify(self.path.split("p=", 1)[1]) if "p=" in self.path else ""
            post = load_post(slug) if slug else None
            return self._json(200 if post else 404, post or {"error": "not found"})
        if self.path == "/api/images":
            return self._json(200, {"images": list_images()})
        if self.path == "/api/posts":
            return self._json(200, {"posts": list_posts()})
        if self.path == "/api/blog-status":
            return self._json(200, {"uncommitted": uncommitted_posts()})
        if self.path == "/api/md-pages":
            return self._json(200, {"pages": list_md_pages()})
        if self.path.startswith("/api/md-page?"):
            slug = parse_qs(urlparse(self.path).query).get("p", [""])[0]
            page = load_md_page(slug) if slug else None
            return self._json(200 if page else 404, page or {"error": "not found"})
        if self.path == "/api/pages":
            return self._json(200, {"pages": list_pages()})
        if self.path.startswith("/api/page?"):
            rel = parse_qs(urlparse(self.path).query).get("p", [""])[0]
            page = load_page(rel)
            return self._json(200 if page else 404, page or {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        try:
            if self.path == "/api/upload":
                d = self._body()
                url = save_image(d.get("title", ""), d.get("mime", ""), d.get("b64", ""))
                return self._json(200, {"ok": True, "url": url})
            if self.path == "/api/image/rename":
                d = self._body()
                return self._json(200, {"ok": True, **rename_image(d.get("old"), d.get("new"))})
            if self.path == "/api/image/delete":
                d = self._body()
                return self._json(200, {"ok": True, **delete_image(d.get("name"))})
            if self.path == "/api/save":
                d = self._body()
                title = (d.get("title") or "").strip()
                if not title:
                    return self._json(400, {"error": "title is required"})
                date_iso = (d.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
                slug = write_post(title, date_iso, d.get("markdown", ""), d.get("html", ""))
                return self._json(200, {"ok": True, "slug": slug,
                                        "url": "/blog/%s.html" % slug})
            if self.path == "/api/save-page":
                d = self._body()
                title = (d.get("title") or "").strip()
                if not title:
                    return self._json(400, {"error": "title is required"})
                slug = write_md_page(title, d.get("markdown", ""), d.get("html", ""),
                                     slug=(d.get("slug") or "").strip() or None)
                return self._json(200, {"ok": True, "slug": slug,
                                        "url": "/%s.html" % slug})
            if self.path == "/api/edit/auth":
                return self._json(200, {"ok": key_ok(self._body().get("key"))})
            if self.path == "/api/edit/reorder":
                d = self._body()
                if not key_ok(d.get("key")):
                    return self._json(403, {"error": "bad key"})
                return self._json(200, {"ok": True, "order": reorder_index(d.get("order") or [])})
            if self.path == "/api/edit/delete-plan":
                d = self._body()
                if not key_ok(d.get("key")):
                    return self._json(403, {"error": "bad key"})
                return self._json(200, delete_plan(d.get("href") or ""))
            if self.path == "/api/edit/delete":
                d = self._body()
                if not key_ok(d.get("key")):
                    return self._json(403, {"error": "bad key"})
                return self._json(200, {"ok": True, **delete_card(d.get("href") or "")})
            if self.path == "/api/page/save":
                d = self._body()
                return self._json(200, {"ok": True,
                                        **save_page(d.get("path"), d.get("html", ""))})
            return self._json(404, {"error": "unknown endpoint"})
        except Exception as e:  # surface the error to the editor/gallery UI
            return self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5666
    print("Blog save server on http://localhost:%d" % port)
    print("  editor:  http://localhost:%d/editor.html" % port)
    print("  gallery: http://localhost:%d/gallery.html" % port)
    print("  blog:    http://localhost:%d/blog/" % port)
    ThreadingHTTPServer(("", port), Handler).serve_forever()
