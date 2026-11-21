#!/usr/bin/env python3
"""Search public Telegram channels for a keyword, without logging in.

Standard library only. For each channel you name, it runs Telegram's own in-channel
search on the public web preview (t.me/s/<channel>?q=...) and keeps only the posts
that really contain your keyword (Telegram's search also returns posts where the
words appear separately).

    python telegram_keyword.py "end-to-end encryption" durov telegram
    python telegram_keyword.py bitcoin @whale_alert_io t.me/s/cointelegraph --all
    python telegram_keyword.py Solana solananews --csv solana.csv

One search page per channel (Telegram returns up to 20 results, newest first), up to
10 channels per run. Finding channels for a keyword is not included: see README.
"""
import argparse
import csv
import html as htmllib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "https://t.me/s/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
MAX_CHANNELS = 10   # per run
PAUSE = 1.0         # seconds between channels; be polite
USERNAME_RX = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
COUNT_RX = re.compile(r"^\s*([\d.,]+)\s*([KMB]?)\s*$", re.I)
RESERVED = {"s", "joinchat", "addstickers", "addemoji", "share", "proxy", "socks", "iv", "c", "login",
            "setlanguage", "addtheme", "confirmphone", "invoice", "boost", "contact", "addlist", "giftcode", "nft"}
VOID = {"br", "img", "input", "meta", "link", "hr", "source", "wbr", "area", "base", "col", "embed", "param", "track"}
CSV_FIELDS = ["keyword", "matchType", "channel", "postId", "postUrl", "date", "views", "text"]


def normalize_channel(raw):
    """'durov', '@durov', 't.me/durov', 'https://t.me/s/durov', 'https://t.me/durov/123' -> 'durov'."""
    s = (raw or "").strip()
    if s.startswith("@"):
        s = s[1:]
    if "/" in s or "." in s:
        u = urllib.parse.urlparse(s if "://" in s else "https://" + s)
        if (u.hostname or "").lower() not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me", "telegram.dog"):
            raise ValueError(f"not a Telegram link: {raw}")
        parts = [p for p in u.path.split("/") if p]
        if parts and parts[0] == "s":
            parts = parts[1:]
        s = parts[0] if parts else ""
    if s.startswith("+") or s.lower() in RESERVED:
        raise ValueError(f"private invite links and special links are not supported: {raw}")
    if not USERNAME_RX.match(s):
        raise ValueError(f"not a valid public channel username: {raw}")
    return s


def parse_count(txt):
    """'1.38M' -> 1380000, '9.14K' -> 9140, '843' -> 843."""
    m = COUNT_RX.match(txt or "")
    if not m:
        return None
    num, suf = m.group(1), m.group(2).upper()
    num = num.replace(",", ".") if suf else num.replace(",", "")
    try:
        return int(round(float(num) * {"": 1, "K": 1e3, "M": 1e6, "B": 1e9}[suf]))
    except ValueError:
        return None


class _PageParser(HTMLParser):
    """Collects posts from a t.me/s/ page. Post text skips quoted replies and link previews."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # (tag, set of classes)
        self.posts = []
        self.cur = None          # post being read
        self.cur_depth = None
        self.grab = None         # "text" / "views" while inside such an element
        self.grab_depth = None
        self.has_channel_info = False

    def _inside(self, cls):
        return any(cls in c for _, c in self.stack)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if "tgme_channel_info" in classes:
            self.has_channel_info = True
        if tag == "br" and self.grab == "text":
            self.cur["text"].append("\n")
        if tag in VOID:
            return
        self.stack.append((tag, classes))
        depth = len(self.stack)
        if tag == "div" and "tgme_widget_message" in classes and a.get("data-post") and self.cur is None:
            self.cur = {"post": a["data-post"], "date": None, "views": None, "text": []}
            self.cur_depth = depth
            return
        if self.cur is None or self.grab:
            if self.cur is not None and tag == "time" and a.get("datetime") and self._inside("tgme_widget_message_date"):
                self.cur["date"] = a["datetime"]
            return
        if tag == "time" and a.get("datetime") and self._inside("tgme_widget_message_date"):
            self.cur["date"] = a["datetime"]
        elif "tgme_widget_message_text" in classes and not (
                self._inside("tgme_widget_message_reply") or self._inside("tgme_widget_message_link_preview")):
            if self.cur["text"]:
                self.cur["text"].append(" ")
            self.grab, self.grab_depth = "text", depth
        elif "tgme_widget_message_views" in classes:
            self.grab, self.grab_depth = "views", depth
            self.cur["_views"] = []

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        # pop to the matching tag (tolerates sloppy HTML)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                depth = i + 1
                del self.stack[i:]
                break
        else:
            return
        if self.grab and depth <= self.grab_depth:
            if self.grab == "views":
                self.cur["views"] = parse_count("".join(self.cur.pop("_views", [])).strip())
            self.grab = self.grab_depth = None
        if self.cur is not None and depth <= self.cur_depth:
            self.posts.append(self.cur)
            self.cur = self.cur_depth = None

    def handle_data(self, data):
        if self.grab == "text":
            self.cur["text"].append(data)
        elif self.grab == "views":
            self.cur["_views"].append(data)


def parse_page(page_html):
    """-> {"available": bool, "posts": [{post, date, views, text}]}.
    A channel that does not exist or has its web preview turned off still answers HTTP 200,
    but the page has no channel info block and no posts."""
    p = _PageParser()
    p.feed(page_html)
    p.close()
    posts = []
    for x in p.posts:
        text = re.sub(r"[ \t]+", " ", "".join(x["text"]))
        text = re.sub(r" *\n *", "\n", text).strip()
        posts.append({"post": x["post"], "date": x["date"], "views": x["views"], "text": htmllib.unescape(text)})
    return {"available": p.has_channel_info or bool(posts), "posts": posts}


def match(text, keyword):
    """'phrase' if the keyword appears as written (case-insensitive, whole words),
    'hashtag' for #Keyword / #KeyWord without spaces, else None."""
    t = text or ""
    if re.search(r"(?<![\w#])" + re.escape(keyword) + r"(?!\w)", t, re.I):
        return "phrase"
    if re.search(r"#" + re.escape(keyword.replace(" ", "")) + r"(?!\w)", t, re.I):
        return "hashtag"
    return None


def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def search_channel(channel, keyword, keep_all=False, fetch_page=None):
    """One channel, one search page. -> {"channel", "status", "returned", "rows"}.
    status: "ok", "notFound" (no such public channel or web preview off) or "error: ...".
    """
    url = BASE + urllib.parse.quote(channel) + "?" + urllib.parse.urlencode({"q": keyword})
    try:
        page = parse_page((fetch_page or fetch)(url))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return {"channel": channel, "status": f"error: {e}", "returned": 0, "rows": []}
    if not page["available"]:
        return {"channel": channel, "status": "notFound", "returned": 0, "rows": []}
    rows = []
    for p in page["posts"]:
        mtype = match(p["text"], keyword) or ("telegram" if keep_all else None)
        if not mtype:
            continue
        ch, _, pid = p["post"].partition("/")
        rows.append({"keyword": keyword, "matchType": mtype, "channel": ch,
                     "postId": int(pid) if pid.isdigit() else pid, "postUrl": f"https://t.me/{p['post']}",
                     "date": p["date"], "views": p["views"], "text": p["text"]})
    rows.reverse()  # newest first
    return {"channel": channel, "status": "ok", "returned": len(page["posts"]), "rows": rows}


def search(keyword, channels, keep_all=False, pause=None, fetch_page=None):
    """Search up to MAX_CHANNELS channels. -> (rows, per-channel summary)."""
    keyword = re.sub(r"\s+", " ", (keyword or "")).strip().strip('"').strip()
    if not keyword:
        raise ValueError("keyword is empty")
    names = []
    for c in channels:
        n = normalize_channel(c)
        if n.lower() not in {x.lower() for x in names}:
            names.append(n)
    if not names:
        raise ValueError("give at least one public channel, e.g. durov")
    if len(names) > MAX_CHANNELS:
        raise ValueError(f"this script searches at most {MAX_CHANNELS} channels per run")
    rows, summary = [], []
    for i, ch in enumerate(names):
        if i:
            time.sleep(PAUSE if pause is None else pause)
        r = search_channel(ch, keyword, keep_all, fetch_page)
        rows += r["rows"]
        summary.append({"channel": ch, "status": r["status"], "returned": r["returned"], "kept": len(r["rows"])})
    return rows, summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Search public Telegram channels for a keyword (no login, no API key).")
    p.add_argument("keyword", help='word or phrase, e.g. "end-to-end encryption"')
    p.add_argument("channels", nargs="+", help=f"public channels: durov, @durov or t.me links (max {MAX_CHANNELS})")
    p.add_argument("--all", action="store_true", help="keep every post Telegram's search returns, not only exact matches")
    p.add_argument("--csv", metavar="FILE", help="write CSV instead of printing JSON")
    a = p.parse_args(argv)
    # Windows consoles default to a legacy code page (e.g. cp949, cp1252) that cannot print emoji
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        rows, summary = search(a.keyword, a.channels, keep_all=a.all)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for s in summary:
        print(f"{s['channel']}: {s['status']}, Telegram returned {s['returned']}, kept {s['kept']}", file=sys.stderr)
    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            w.writerows(rows)
        print(f"{len(rows)} posts -> {a.csv}", file=sys.stderr)
    else:
        json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
        print()
        print(f"{len(rows)} posts", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
