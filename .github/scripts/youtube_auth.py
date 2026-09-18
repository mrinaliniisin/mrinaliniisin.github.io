#!/usr/bin/env python3
"""One-time, run locally: mint the YouTube refresh token that the weekly
likes sync (sync_youtube_likes.py, via youtube-likes.yml) uses to read your
"Liked videos" as you.

The liked list is private on YouTube, so the Action has to authenticate as
your Google account. Google's OAuth "installed app" flow does that with a
single browser consent: this script opens the consent page, catches the
redirect on a loopback port, swaps the code for tokens, and offers to
save the credentials to youtube-likes/auth.local.json (git-ignored) for the
local editor server, which runs the weekly sync. It also prints the three
values in case you want the GitHub Action fallback (see youtube-likes/README.md).

Before running: in Google Cloud, enable "YouTube Data API v3" and create an
OAuth client of type "Desktop app". Set the consent screen's publishing
status to "In production" — while it's "Testing", Google expires every
refresh token after 7 days and the weekly job would break on its second run.

Usage:
  python3 .github/scripts/youtube_auth.py
  (prompts for the client id and secret; or export YT_CLIENT_ID /
   YT_CLIENT_SECRET first)
"""
import getpass
import http.server
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


class Catch(http.server.BaseHTTPRequestHandler):
    """Receives Google's redirect (one request) and stashes its query."""

    def do_GET(self):
        self.server.query = urllib.parse.parse_qs(
            urllib.parse.urlparse(self.path).query)
        ok = "code" in self.server.query
        body = ("Done — you can close this tab and go back to the terminal."
                if ok else "No code in the redirect; check the terminal.")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_):  # keep the terminal to our own output
        pass


def main():
    client_id = os.environ.get("YT_CLIENT_ID") or input("OAuth client ID: ").strip()
    client_secret = (os.environ.get("YT_CLIENT_SECRET")
                     or getpass.getpass("OAuth client secret: ").strip())
    if not client_id or not client_secret:
        sys.exit("Both the client id and secret are needed.")

    # Port 0 = let the OS pick a free one. Desktop-app clients may redirect
    # to any http://127.0.0.1:<port> without registering it first.
    server = http.server.HTTPServer(("127.0.0.1", 0), Catch)
    server.query = {}
    redirect = "http://127.0.0.1:%d" % server.server_address[1]
    state = secrets.token_urlsafe(16)

    # access_type=offline + prompt=consent is what makes Google include a
    # refresh_token (it only does so on a fresh consent).
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    print("\nOpening Google's consent page in your browser.")
    print("If it doesn't open, paste this URL yourself:\n\n  %s\n" % url)
    webbrowser.open(url)
    print("Waiting for Google to redirect back to %s ..." % redirect)
    server.handle_request()  # exactly one request, then we're done listening

    q = server.query
    if q.get("state", [None])[0] != state:
        sys.exit("State mismatch on the redirect — try again.")
    if "code" not in q:
        sys.exit("Google returned no code (error=%s)." % q.get("error", ["?"])[0])

    body = urllib.parse.urlencode({
        "code": q["code"][0],
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body)) as r:
            tok = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("Token exchange failed: %s %s" % (e.code, e.read().decode()))

    refresh = tok.get("refresh_token")
    if not refresh:
        sys.exit("No refresh_token in the response — revoke the app at "
                 "https://myaccount.google.com/permissions and run this again.")

    # The local editor server (server.py on :5666) is what normally runs the
    # weekly sync; it reads this git-ignored file.
    auth_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "..", "..", "youtube-likes", "auth.local.json")
    auth_path = os.path.normpath(auth_path)
    ans = input("\nSave to %s for the local server? [Y/n] " % os.path.relpath(auth_path)).strip().lower()
    if ans in ("", "y", "yes"):
        with open(auth_path, "w", encoding="utf-8") as f:
            json.dump({"client_id": client_id, "client_secret": client_secret,
                       "refresh_token": refresh, "auto_push": False}, f, indent=1)
            f.write("\n")
        os.chmod(auth_path, 0o600)
        print("Saved. Restart the server (pkill -f 'server.py 5666'; runit respawns it) "
              "and use 'Sync now' on the editor dashboard.")

    print("\nFor the manual GitHub Action instead/as well, add these repository "
          "secrets (Settings → Secrets and variables → Actions):\n")
    print("  YT_CLIENT_ID      = %s" % client_id)
    print("  YT_CLIENT_SECRET  = %s" % client_secret)
    print("  YT_REFRESH_TOKEN  = %s" % refresh)


if __name__ == "__main__":
    main()
