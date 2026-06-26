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

Run from the repo root:  python3 server.py [port]   (default 8000)
"""

import base64
import html
import json
import os
import re
import sys
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.getcwd()
BLOG = os.path.join(ROOT, "blog")
INDEX = os.path.join(BLOG, "index.html")

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
        lines = f.read().splitlines()

    href = '/blog/%s.html' % slug
    # Drop any existing entry for this slug and the "no posts" placeholder.
    lines = [ln for ln in lines
             if href not in ln and "empty-placeholder" not in ln]

    li = ('      <li><a href="%s"><span class="t">%s</span>'
          '<span class="post-meta">%s</span></a></li>'
          % (href, html.escape(title), human_date(date_iso)))

    out = []
    for ln in lines:
        out.append(ln)
        if "<!--POSTS-->" in ln:
            out.append(li)  # newest first, right under the marker
    with open(INDEX, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


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


class Handler(SimpleHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/load"):
            slug = slugify(self.path.split("p=", 1)[1]) if "p=" in self.path else ""
            post = load_post(slug) if slug else None
            return self._json(200 if post else 404, post or {"error": "not found"})
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/save":
            return self._json(404, {"error": "unknown endpoint"})
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            title = (data.get("title") or "").strip()
            if not title:
                return self._json(400, {"error": "title is required"})
            date_iso = (data.get("date") or datetime.now().strftime("%Y-%m-%d")).strip()
            slug = write_post(title, date_iso, data.get("markdown", ""),
                              data.get("html", ""))
            return self._json(200, {"ok": True, "slug": slug,
                                    "url": "/blog/%s.html" % slug})
        except Exception as e:  # surface the error to the editor UI
            return self._json(500, {"error": str(e)})

    def log_message(self, *a):
        pass  # quiet


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    print("Blog save server on http://localhost:%d" % port)
    print("  editor:  http://localhost:%d/editor.html" % port)
    print("  blog:    http://localhost:%d/blog/" % port)
    ThreadingHTTPServer(("", port), Handler).serve_forever()
