"""Quick local check of the three MCP tools without an MCP client.

    pip install "mcp>=1.2,<2"
    python test_mcp_tools.py              # free tool only
    set APIFY_TOKEN=...  then run again   # also tests the paid tools (about $0.03)
"""
import os
import time
import mcp_server as s

r = s.search_telegram_channels("privacy", ["durov", "telegram"])
print("search_telegram_channels:", len(r["posts"]), "posts;", r["channels"])

if os.environ.get("APIFY_TOKEN"):
    t0 = time.time()
    run = s.start_keyword_search(["Hyperliquid"], max_channels_per_keyword=3, max_posts_per_keyword=10,
                                 max_total_charge_usd=0.05)
    print(f"start_keyword_search: {run['run_id']} {run['status']} ({time.time() - t0:.1f}s)")
    for i in range(6):
        t1 = time.time()
        res = s.get_keyword_results(run["run_id"], wait_secs=45)
        print(f"get_keyword_results #{i + 1}: finished={res['finished']} {res['status']} ({time.time() - t1:.1f}s)")
        if res["finished"]:
            print(" ", res["message"])
            for p in res["posts"][:3]:
                print("  ", p.get("date"), p.get("channel"), "|", (p.get("matchedText") or "")[:70])
            break
    print(f"total {time.time() - t0:.0f}s")
else:
    print("APIFY_TOKEN not set: skipped start_keyword_search / get_keyword_results")
