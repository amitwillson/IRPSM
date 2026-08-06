"""Discovery of the recurring 5-minute crypto Up/Down markets.

Polymarket runs these as deterministic, timestamp-keyed markets rather than
ad-hoc ones: for asset ticker `t` and a window start `ws` (a Unix timestamp
divisible by 300), the market slug is `{t}-updown-5m-{ws}`. This lets us
compute the currently-open (and recent/past) windows for all 7 assets
without having to page through the full market list.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .client import PolymarketClient
from .config import FIVE_MIN_UPDOWN_ASSETS, FIVE_MIN_WINDOW_SECONDS


@dataclass
class UpDownMarket:
    asset: str
    slug: str
    window_start: int
    window_end: int
    condition_id: str | None
    question: str | None
    up_token_id: str | None
    down_token_id: str | None
    up_price: float | None
    down_price: float | None
    volume: float | None
    liquidity: float | None
    closed: bool | None
    raw_event: dict


def _current_window_start(now: float | None = None) -> int:
    now = int(now if now is not None else time.time())
    return now - (now % FIVE_MIN_WINDOW_SECONDS)


def slug_for_window(asset_ticker: str, window_start: int) -> str:
    return f"{asset_ticker}-updown-5m-{window_start}"


def _parse_event_to_market(asset: str, slug: str, window_start: int, event: dict | None) -> UpDownMarket:
    window_end = window_start + FIVE_MIN_WINDOW_SECONDS
    if not event:
        return UpDownMarket(
            asset=asset,
            slug=slug,
            window_start=window_start,
            window_end=window_end,
            condition_id=None,
            question=None,
            up_token_id=None,
            down_token_id=None,
            up_price=None,
            down_price=None,
            volume=None,
            liquidity=None,
            closed=None,
            raw_event={},
        )

    markets = event.get("markets") or []
    market = markets[0] if markets else {}

    token_ids: list[str] = []
    raw_tokens = market.get("clobTokenIds")
    if isinstance(raw_tokens, str):
        import json

        try:
            token_ids = json.loads(raw_tokens)
        except (ValueError, TypeError):
            token_ids = []
    elif isinstance(raw_tokens, list):
        token_ids = raw_tokens

    prices: list[float] = []
    raw_prices = market.get("outcomePrices")
    if isinstance(raw_prices, str):
        import json

        try:
            prices = [float(p) for p in json.loads(raw_prices)]
        except (ValueError, TypeError):
            prices = []
    elif isinstance(raw_prices, list):
        prices = [float(p) for p in raw_prices]

    up_token = token_ids[0] if len(token_ids) > 0 else None
    down_token = token_ids[1] if len(token_ids) > 1 else None
    up_price = prices[0] if len(prices) > 0 else None
    down_price = prices[1] if len(prices) > 1 else None

    return UpDownMarket(
        asset=asset,
        slug=slug,
        window_start=window_start,
        window_end=window_end,
        condition_id=market.get("conditionId"),
        question=market.get("question") or event.get("title"),
        up_token_id=up_token,
        down_token_id=down_token,
        up_price=up_price,
        down_price=down_price,
        volume=float(market.get("volume") or 0) or None,
        liquidity=float(market.get("liquidity") or 0) or None,
        closed=market.get("closed"),
        raw_event=event,
    )


def fetch_current_updown_markets(
    client: PolymarketClient,
    assets: dict[str, str] | None = None,
) -> list[UpDownMarket]:
    """Fetch the currently-open 5-minute Up/Down market for each asset."""
    assets = assets or FIVE_MIN_UPDOWN_ASSETS
    window_start = _current_window_start()
    results = []
    for name, ticker in assets.items():
        slug = slug_for_window(ticker, window_start)
        event = client.gamma_event_by_slug(slug)
        results.append(_parse_event_to_market(name, slug, window_start, event))
    return results


def fetch_recent_updown_markets(
    client: PolymarketClient,
    lookback_windows: int = 12,
    assets: dict[str, str] | None = None,
) -> list[UpDownMarket]:
    """Fetch the last `lookback_windows` 5-minute windows (including current) per asset.

    Useful for building a short trailing ledger of recently-resolved rounds
    to compute short-horizon win/loss stats per asset.
    """
    assets = assets or FIVE_MIN_UPDOWN_ASSETS
    current = _current_window_start()
    results = []
    for name, ticker in assets.items():
        for i in range(lookback_windows):
            window_start = current - i * FIVE_MIN_WINDOW_SECONDS
            slug = slug_for_window(ticker, window_start)
            event = client.gamma_event_by_slug(slug)
            results.append(_parse_event_to_market(name, slug, window_start, event))
    return results


def condition_ids_for_markets(markets: list[UpDownMarket]) -> set[str]:
    return {m.condition_id for m in markets if m.condition_id}
