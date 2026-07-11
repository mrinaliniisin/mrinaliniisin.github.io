#!/usr/bin/env python3
"""Broadcast a push notification for each card newly added to index.html or
secret.html.

Run by .github/workflows/notify.yml after a push to main. For each of the two
pages, compares its cards against the previous commit (HEAD~1); for every card
whose href is new, POSTs {title, body, url, topic} to the push Worker's
/broadcast — index.html's cards go out under topic "index", secret.html's
under "secret", so each page's bell only notifies subscribers to that page.

Env:
  PUSH_WORKER_URL   e.g. https://mrinaliniisin-push.<sub>.workers.dev
  BROADCAST_SECRET  shared bearer token (matches the Worker secret)
  SITE_ORIGIN       optional, default https://mrinaliniisin.github.io
"""
import html
import json
import os
import re
import subprocess
import sys
import urllib.request

PAGES = [("index.html", "index"), ("secret.html", "secret")]

# href, title, desc — robust to whatever follows inside the card.
CARD_RE = re.compile(
    r'<a class="card-link" href="([^"]+)"[^>]*></a>\s*'
    r'<h2>(.*?)</h2>\s*<div class="desc">(.*?)</div>', re.S)


def cards(src):
    out = {}
    for href, title, desc in CARD_RE.findall(src or ""):
        clean = lambda s: html.unescape(re.sub(r"\s+", " ", s).strip())
        out[href] = (clean(title), clean(desc))
    return out


def prev_version(path):
    r = subprocess.run(["git", "show", "HEAD~1:" + path],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def broadcast(worker, secret, origin, topic, href, title, desc):
    url = href if href.startswith("http") else origin + "/" + href.lstrip("/")
    payload = json.dumps({
        "title": "New on Mrinalini S: " + title,
        "body": desc, "url": url, "topic": topic,
    }).encode()
    req = urllib.request.Request(
        worker + "/broadcast", data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + secret,
                 # Cloudflare's edge 403s the default Python-urllib UA as a bot.
                 "User-Agent": "mrinaliniisin-notify/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        print("notified %r (%s) -> %s %s" % (title, topic, resp.status, resp.read().decode()))


def main():
    worker = os.environ["PUSH_WORKER_URL"].rstrip("/")
    secret = os.environ["BROADCAST_SECRET"]
    origin = os.environ.get("SITE_ORIGIN", "https://mrinaliniisin.github.io").rstrip("/")

    any_added = False
    for path, topic in PAGES:
        if not os.path.exists(path):
            continue
        new = cards(open(path, encoding="utf-8").read())
        old = cards(prev_version(path))
        added = [h for h in new if h not in old]
        for href in added:
            any_added = True
            title, desc = new[href]
            try:
                broadcast(worker, secret, origin, topic, href, title, desc)
            except Exception as e:
                print("FAILED to notify %r: %s" % (title, e), file=sys.stderr)
                sys.exit(1)

    if not any_added:
        print("No new cards; nothing to notify.")


if __name__ == "__main__":
    main()
