"""Endpoint and constant configuration for the Polymarket extraction toolkit.

All endpoints are Polymarket's public, unauthenticated read APIs:

- Gamma API   (market/event metadata)         https://gamma-api.polymarket.com
- Data API    (positions/trades/activity/lb)  https://data-api.polymarket.com
- CLOB API    (orderbook/prices)              https://clob.polymarket.com
"""

from __future__ import annotations

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"

# The 7 crypto assets Polymarket runs recurring 5-minute Up/Down markets for.
# Slugs follow the pattern: "{ticker}-updown-5m-{window_start_unix_ts}" where
# window_start_unix_ts is a Unix timestamp divisible by 300 (5 minutes).
FIVE_MIN_UPDOWN_ASSETS: dict[str, str] = {
    "BTC": "btc",
    "ETH": "eth",
    "SOL": "sol",
    "XRP": "xrp",
    "DOGE": "doge",
    "HYPE": "hype",
    "BNB": "bnb",
}

FIVE_MIN_WINDOW_SECONDS = 300

LEADERBOARD_CATEGORIES = [
    "OVERALL",
    "POLITICS",
    "SPORTS",
    "ESPORTS",
    "CRYPTO",
    "CULTURE",
    "MENTIONS",
    "WEATHER",
    "ECONOMICS",
    "TECH",
    "FINANCE",
]

LEADERBOARD_TIME_PERIODS = ["DAY", "WEEK", "MONTH", "ALL"]

DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RETRIES = 4
DEFAULT_BACKOFF_SECONDS = 1.5

# Data API applies stricter rate limits on /positions (~150 req/10s at the
# platform level); we stay well under that with a small fixed delay between
# calls when doing bulk wallet extraction.
DEFAULT_REQUEST_DELAY_SECONDS = 0.15
