"""Hosted version: finds the channels for a keyword, more posts, dates and only new posts.

    pip install apify-client
    python run_apify_actor.py
"""
from apify_client import ApifyClient

client = ApifyClient("<YOUR_APIFY_TOKEN>")
run = client.actor("datalume/telegram-keyword-search-scraper").call(run_input={
    "keywords": ["Hyperliquid"],
    "discoverChannels": True,
    "maxChannelsPerKeyword": 10,
    "matchMode": "phrase",
    "maxPostsPerKeyword": 100,
    "dateFrom": "7 days",
})
for item in client.dataset(run["defaultDatasetId"]).iterate_items():
    print(item["date"], item["channel"], item["views"], item["matchedText"])
