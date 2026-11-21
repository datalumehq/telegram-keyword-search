"""MCP server for Telegram keyword search.

Three tools:
  search_telegram_channels   free, no API key: search channels you name for a keyword
                             (Telegram's in-channel search, exact matches only by default)
  start_keyword_search       needs an Apify token: finds the channels that talk about a
                             keyword, searches them all and returns a run_id at once
  get_keyword_results        needs an Apify token: the posts of that search once it has finished

A hosted search takes from a few seconds to over two minutes, longer than some MCP clients
wait for one tool call, so it is split into "start" and "get results". Posts are paid per
matching post.

Run:  pip install "mcp>=1.2,<2" && python mcp_server.py      (stdio transport)
"""
import json
import os
import re
import urllib.error
import urllib.request

from mcp.server.fastmcp import FastMCP

import telegram_keyword as tk

ACTOR = "datalume~telegram-keyword-search-scraper"
ACTOR_URL = "https://apify.com/datalume/telegram-keyword-search-scraper"
API = "https://api.apify.com/v2"
DONE = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
RUN_ID_RX = re.compile(r"^[A-Za-z0-9]{17}$")
MATCH_MODES = ("phrase", "allWords", "telegram")

mcp = FastMCP("telegram-keyword-search")


def _token():
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set. Create a token at https://console.apify.com/settings/integrations "
                           f"and add it to this server's environment. Actor: {ACTOR_URL}")
    return token


def _call(method, url, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Apify returned HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")


@mcp.tool()
def search_telegram_channels(keyword: str, channels: list[str], include_all: bool = False) -> dict:
    """Search public Telegram channels that you name for a keyword. Free, no API key, no Telegram account.

    Uses Telegram's own in-channel search on the public web preview (t.me/s/<channel>) and
    keeps only posts that contain the keyword as written or as a #hashtag. Returns at most
    the 20 newest search results per channel, up to 10 channels. It does NOT find channels
    for you; use start_keyword_search when you don't know which channels talk about the keyword,
    or need more posts, dates or only new posts.

    Args:
        keyword: word or phrase, e.g. "end-to-end encryption" or "Solana".
        channels: public channel usernames or links, e.g. ["durov", "@telegram", "t.me/s/cointelegraph"].
        include_all: keep every post Telegram's search returns, not only exact matches.

    Returns {"posts": [...], "channels": [{"channel", "status", "returned", "kept"}]}.
    status "notFound" means no public channel with that name or its web preview is off.
    """
    rows, summary = tk.search(keyword, channels or [], keep_all=bool(include_all))
    return {"posts": rows, "channels": summary}


@mcp.tool()
def start_keyword_search(keywords: list[str], channels: list[str] | None = None, discover_channels: bool = True,
                         max_channels_per_keyword: int = 5, match_mode: str = "phrase", max_posts_per_keyword: int = 50,
                         date_from: str = "", only_new_posts: bool = False, max_total_charge_usd: float = 0.25) -> dict:
    """Start a Telegram keyword search that also FINDS the channels talking about each keyword, and return a run_id immediately. Step 1 of 2: then call get_keyword_results(run_id) to get the posts.

    Starts the hosted Apify Actor "datalume/telegram-keyword-search-scraper" with your own
    Apify account. Requires the APIFY_TOKEN environment variable. It is PAID: per matching
    post plus a small fee per keyword when channels are found (current price:
    https://apify.com/datalume/telegram-keyword-search-scraper ); non-matching posts and
    unreadable channels are not charged. Starting a search spends money even if the results
    are never fetched, so start one only when the user wants the posts. The run stops at
    max_posts_per_keyword and at max_total_charge_usd. A run takes from a few seconds to
    about two minutes (15 Nov 2026: 3 keywords, 259 posts from 19 channels in 2 min 15 s).

    Args:
        keywords: words or phrases, e.g. ["Hyperliquid"]. Each keyword is searched separately.
        channels: optional channels that are always searched, e.g. ["durov"].
        discover_channels: find channels for each keyword with Google (site:t.me). Set false to search only `channels`.
        max_channels_per_keyword: found channels searched per keyword, 1-50.
        match_mode: "phrase" (exact phrase or #hashtag), "allWords" or "telegram" (everything Telegram returns).
        max_posts_per_keyword: stop a keyword after this many matching posts. Keep small to control cost.
        date_from: only posts since a date ("2026-11-01") or a period ("7 days", "24 hours"). Empty = any date.
        only_new_posts: return only posts published since the previous run of the same keyword in each channel.
        max_total_charge_usd: hard spending cap for this search, in USD.
    """
    kws = [k.strip() for k in (keywords or []) if k and k.strip()]
    if not kws:
        raise ValueError("give at least one keyword, e.g. 'Hyperliquid'")
    if match_mode not in MATCH_MODES:
        raise ValueError("match_mode must be one of: " + ", ".join(MATCH_MODES))
    chans = [tk.normalize_channel(c) for c in (channels or []) if c and c.strip()]
    if not discover_channels and not chans:
        raise ValueError("with discover_channels false, give at least one channel")
    run_input = {
        "keywords": kws,
        "channels": chans,
        "discoverChannels": bool(discover_channels),
        "maxChannelsPerKeyword": max(1, min(50, int(max_channels_per_keyword))),
        "matchMode": match_mode,
        "maxPostsPerKeyword": max(1, int(max_posts_per_keyword)),
        "onlyNewPosts": bool(only_new_posts),
    }
    if (date_from or "").strip():
        run_input["dateFrom"] = date_from.strip()
    run = _call("POST", f"{API}/acts/{ACTOR}/runs?maxTotalChargeUsd={float(max_total_charge_usd)}", run_input)["data"]
    return {"run_id": run["id"], "status": run.get("status"), "keywords": len(kws),
            "next": f"Call get_keyword_results with run_id {run['id']}. Expect up to about two minutes."}


@mcp.tool()
def get_keyword_results(run_id: str, wait_secs: int = 40) -> dict:
    """Get the posts found by a search started with start_keyword_search. Step 2 of 2. Reading results is free; it never starts a new search.

    Waits up to wait_secs for the search to finish. Returns {"finished", "status", "posts",
    "message"}. If "finished" is false the search is still running and "posts" is empty:
    call get_keyword_results again with the same run_id (do not start a new search).

    Args:
        run_id: the run_id returned by start_keyword_search.
        wait_secs: how long to wait for the search to finish, 0-45 seconds.
    """
    run_id = (run_id or "").strip()
    if not RUN_ID_RX.match(run_id):
        raise ValueError("run_id does not look like an Apify run ID (17 letters and digits)")
    wait = max(0, min(45, int(wait_secs)))
    run = _call("GET", f"{API}/actor-runs/{run_id}?waitForFinish={wait}", timeout=wait + 30)["data"]
    status = run["status"]
    if status not in DONE:
        return {"finished": False, "status": status, "posts": [],
                "message": "Still running. Call get_keyword_results again with the same run_id."}
    posts = _call("GET", f"{API}/datasets/{run['defaultDatasetId']}/items?clean=true&format=json")
    msg = run.get("statusMessage") or ""
    if status == "SUCCEEDED":
        msg = f"{len(posts)} posts. {msg}".strip()
    else:
        msg = (f"The run ended with status {status}; {len(posts)} posts were saved before that. "
               f"Details: https://console.apify.com/actors/runs/{run_id}")
    return {"finished": True, "status": status, "posts": posts, "message": msg}


if __name__ == "__main__":
    mcp.run()
