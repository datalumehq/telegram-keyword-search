# Telegram Keyword Search (Python) - search public channels without logging in

A small Python script that searches **public Telegram channels for a keyword** and returns only the posts that really contain it. No Telegram account, no phone number, no API key, no dependencies beyond the standard library.

For each channel you name, it runs Telegram's own in-channel search and gives you the post link, date, views and full text, marked as an exact-phrase or #hashtag match. Export JSON or CSV.

```bash
python telegram_keyword.py "end-to-end encryption" durov telegram
```

Also works as an **MCP server** for Claude, Cursor and other AI clients: a free `search_telegram_channels` tool, plus a hosted search that also finds the channels for you. See [Use it as an MCP server](#use-it-as-an-mcp-server).

## Can you search Telegram without an account?

Telegram's official API needs a Telegram account (phone number) and an `api_id`. But every public channel with the web preview turned on has a page anyone can open, `https://t.me/s/<channel>`, and that page has a search box. This script calls the same URL your browser does:

```
GET https://t.me/s/<channel>?q=<keyword>
```

and reads the posts from the HTML. `telegram_keyword.py` is about 250 lines and you can read all of it in a few minutes.

## Quick start

Requires Python 3.8+. Nothing to install for the script (the MCP server needs `pip install -r requirements.txt`).

```bash
git clone https://github.com/datalumehq/telegram-keyword-search.git
cd telegram-keyword-search
python telegram_keyword.py privacy durov
```

Or download `telegram_keyword.py` on its own and run it.

## Options

| Option | What it does | Example |
|---|---|---|
| `keyword` | Word or phrase to find (required) | `"end-to-end encryption"` |
| `channels` | Public channels: username, `@username` or `t.me` link, up to 10 (required) | `durov @telegram t.me/s/cointelegraph` |
| `--all` | Keep every post Telegram's search returns, not only exact matches | `--all` |
| `--csv FILE` | Write CSV instead of printing JSON | `--csv mentions.csv` |

The script prints one status line per channel to stderr, e.g. `durov: ok, Telegram returned 20, kept 19`. `notFound` means there is no public channel with that name, or its web preview is turned off.

## Output

Real output from 20 November 2026 (`privacy` in `durov`; Telegram returned 20 posts, 19 contained the word; text shortened here):

```json
[
  {
    "keyword": "privacy",
    "matchType": "phrase",
    "channel": "durov",
    "postId": 520,
    "postUrl": "https://t.me/durov/520",
    "date": "2026-05-23T13:26:07+00:00",
    "views": 11700000,
    "text": "🎭 WhatsApp encryption is a giant fraud. ..."
  }
]
```

Posts are newest first. `matchType` is `phrase` (the keyword as written, case-insensitive, whole words), `hashtag` (`#EndToEndEncryption` for "end to end encryption") or `telegram` (only with `--all`: returned by Telegram's search without an exact match).

## Why check the phrase again?

Telegram's channel search matches **words, not phrases**: search for `bitcoin ETF` and you also get posts that mention "bitcoin" in one sentence and "ETF" in another. In a test on 15 November 2026 (three keywords, 19 channels), 211 of 470 search results did not contain the exact phrase. This script keeps only the posts that do, unless you pass `--all`.

One trap if you write your own: on search pages Telegram wraps every matched word in `<mark>`, so `end-to-end` arrives as `<mark>end</mark>-<mark>to</mark>-<mark>end</mark>`. Joining the text with a separator (BeautifulSoup's `get_text(" ")`) breaks the phrase; this script joins text nodes as they are.

## What this script does not do

You have to know the channels. Telegram has no public search across all channels, so the hard part of keyword monitoring is **finding which channels talk about a keyword** in the first place, then searching each of them deeper than one page and only returning what is new since last time.

That part (channel discovery, page-by-page search, date filters, only new posts, retries) is what the hosted version below does. This script stays small on purpose.

## Limits of this script

- One search page per channel: Telegram returns up to 20 results, newest first. Older matches are not fetched.
- Up to 10 channels per run, one request per channel with a 1-second pause.
- Only public channels with the web preview (`t.me/s/...`) turned on. Private channels, groups and comments are not available.
- A channel that does not exist still answers HTTP 200, so the script detects it from the page content (no channel info, no posts) and reports `notFound`.
- The page layout is Telegram's and can change without notice. If the script breaks, please open an issue.

## Hosted version: finds the channels for you

If you don't know which channels to search, need more than 20 results per channel, or want a feed of new mentions, the same approach is available as a maintained Apify Actor: **[Telegram Keyword Search Scraper - Mention Alerts, No Login](https://apify.com/datalume/telegram-keyword-search-scraper)**.

It adds:

- **Finds channels for each keyword** with Google (`site:t.me`); when Google finds only a few, it also searches the channels that matching posts were forwarded from or link to
- **Searches inside every channel page by page**, so it finds recent posts Google hasn't indexed
- Match modes: exact phrase or #hashtag, all words, or everything Telegram returns
- Date range (`7 days`, `2026-11-01`), **only new posts since the last run** for scheduled mention alerts
- Reactions, media, forwards, links and channel info per post
- Pay per matching post; non-matching posts and unreadable channels are not charged (price on the [Actor page](https://apify.com/datalume/telegram-keyword-search-scraper))

From Python (`pip install apify-client`, see `run_apify_actor.py`):

```python
from apify_client import ApifyClient

client = ApifyClient("<YOUR_APIFY_TOKEN>")
run = client.actor("datalume/telegram-keyword-search-scraper").call(run_input={
    "keywords": ["Hyperliquid"],
    "discoverChannels": True,
    "maxChannelsPerKeyword": 10,
    "dateFrom": "7 days",
})
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(item["date"], item["channel"], item["views"], item["matchedText"])
```

The same features are available to AI agents through the MCP server below (`start_keyword_search`).

## Use it as an MCP server

[![Telegram Keyword Search MCP server – quality and maintenance score on Glama](https://glama.ai/mcp/servers/datalumehq/telegram-keyword-search/badges/score.svg)](https://glama.ai/mcp/servers/datalumehq/telegram-keyword-search)

`mcp_server.py` exposes three tools to any MCP client (Claude Desktop, Claude Code, Cursor, VS Code). Requires Python 3.10+.

| Tool | Cost | What it returns |
|---|---|---|
| `search_telegram_channels` | Free, no API key | Exact-phrase matches for a keyword in channels you name: post link, date, views, text. Up to 20 newest search results per channel, 10 channels |
| `start_keyword_search` | Paid per matching post through your Apify account (price on the [Actor page](https://apify.com/datalume/telegram-keyword-search-scraper)) | Starts a search that also finds the channels for each keyword and returns a `run_id` at once. Options: match mode, date range, only new posts. Each search has a spending cap (`max_total_charge_usd`, default $0.25) and a post limit (`max_posts_per_keyword`, default 50) |
| `get_keyword_results` | Free (reads the results of a search you started) | The matching posts once the search has finished. While it is still running it says so and the client calls it again |

Why two steps: a hosted search takes from a few seconds to over two minutes (2 min 15 s for 3 keywords and 19 channels in our 15 November 2026 test), and some MCP clients stop waiting for a single tool call before that. Starting the search and fetching the results separately keeps every call short.

Install:

```bash
git clone https://github.com/datalumehq/telegram-keyword-search.git
cd telegram-keyword-search
pip install -r requirements.txt
```

Claude Desktop (`claude_desktop_config.json`), Cursor (`~/.cursor/mcp.json`) and most other clients use the same block. Use the full path to `mcp_server.py`:

```json
{
  "mcpServers": {
    "telegram-keyword-search": {
      "command": "python",
      "args": ["/path/to/telegram-keyword-search/mcp_server.py"],
      "env": { "APIFY_TOKEN": "<optional, only for start_keyword_search and get_keyword_results>" }
    }
  }
}
```

Claude Code:

```bash
claude mcp add telegram-keyword-search -- python /path/to/telegram-keyword-search/mcp_server.py
```

Then ask in plain language, for example:

- "Did @durov post anything about privacy recently? Give me the links" (free)
- "Find Telegram channels talking about Hyperliquid in the last 7 days and show the most viewed posts" (uses `start_keyword_search`)

Without `APIFY_TOKEN` the free tool works and the other two return a message explaining how to add a token. Get a token at [console.apify.com/settings/integrations](https://console.apify.com/settings/integrations).

Prefer not to run anything locally? Apify's hosted MCP endpoint serves the same Actor: `https://mcp.apify.com?tools=datalume/telegram-keyword-search-scraper` (sign in with Apify on first use).

## FAQ

**Do I need a Telegram account or API key?**
No. The script reads the public web preview pages that anyone can open without logging in.

**Can it search all of Telegram?**
No tool without an account can. This script searches the channels you give it; the hosted version first finds channels that talk about your keyword.

**Is it allowed?**
The pages are public and served to anyone without logging in. This script reads them the way a browser does, one request per channel with a pause. Use it responsibly and check the terms that apply to you.

**Why do I get fewer posts than I expected?**
Only the first search page (up to 20 results) per channel is read, and posts without the exact phrase are dropped. Try `--all` to see what Telegram returned.

**Does it work for private channels or groups?**
No. Only public channels with the web preview turned on.

## More

- Tutorial: [How to Search Telegram for a Keyword Without Logging In (and Why Google Misses Most Posts)](https://dev.to/datalume/how-to-search-telegram-for-a-keyword-without-logging-in-and-why-google-misses-most-posts-2oe9)
- Every post from specific channels: [Telegram Channel Scraper](https://apify.com/datalume/telegram-channel-scraper)
- Other scrapers by datalume: [apify.com/datalume](https://apify.com/datalume)

## License

MIT. Built with AI assistance; numbers come from real runs on the dates shown.

*Not affiliated with, endorsed by or sponsored by Telegram or Google. "Telegram" is a trademark of Telegram FZ-LLC. This project only reads publicly available channel posts.*
