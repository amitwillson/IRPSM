"""Thin HTTP client with retries/backoff for Polymarket's public REST APIs."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from . import config

logger = logging.getLogger(__name__)


class PolymarketAPIError(RuntimeError):
    """Raised when a Polymarket API request fails after all retries."""


class PolymarketClient:
    """Read-only client for the Gamma, Data and CLOB public APIs.

    No authentication is required or used: every endpoint wrapped here is
    part of Polymarket's public market-data surface (the same data a
    browser loads when you visit polymarket.com).
    """

    def __init__(
        self,
        timeout: int = config.DEFAULT_TIMEOUT,
        max_retries: int = config.DEFAULT_MAX_RETRIES,
        backoff_seconds: float = config.DEFAULT_BACKOFF_SECONDS,
        request_delay: float = config.DEFAULT_REQUEST_DELAY_SECONDS,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.request_delay = request_delay
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "irpsm-polymarket-extractor/0.1 (+read-only research tool)",
                "Accept": "application/json",
            }
        )

    def _get(self, base: str, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{base}{path}"
        params = {k: v for k, v in (params or {}).items() if v is not None}

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429:
                    wait = self.backoff_seconds * (2 ** (attempt - 1))
                    logger.warning("429 rate limited on %s, backing off %.1fs", url, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                if self.request_delay:
                    time.sleep(self.request_delay)
                return resp.json()
            except requests.RequestException as exc:
                last_exc = exc
                wait = self.backoff_seconds * (2 ** (attempt - 1))
                logger.warning(
                    "Request to %s failed (attempt %d/%d): %s; retrying in %.1fs",
                    url,
                    attempt,
                    self.max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        raise PolymarketAPIError(f"GET {url} failed after {self.max_retries} attempts: {last_exc}")

    # ---- Gamma API (market/event metadata) --------------------------------

    def gamma_markets(self, **params: Any) -> list[dict]:
        return self._get(config.GAMMA_API_BASE, "/markets", params)

    def gamma_events(self, **params: Any) -> list[dict]:
        return self._get(config.GAMMA_API_BASE, "/events", params)

    def gamma_event_by_slug(self, slug: str) -> dict | None:
        events = self.gamma_events(slug=slug)
        return events[0] if events else None

    # ---- CLOB API (orderbook / prices) -------------------------------------

    def clob_price(self, token_id: str, side: str = "buy") -> dict:
        return self._get(config.CLOB_API_BASE, "/price", {"token_id": token_id, "side": side})

    def clob_book(self, token_id: str) -> dict:
        return self._get(config.CLOB_API_BASE, "/book", {"token_id": token_id})

    def clob_midpoint(self, token_id: str) -> dict:
        return self._get(config.CLOB_API_BASE, "/midpoint", {"token_id": token_id})

    # ---- Data API (positions / trades / activity / leaderboard) -----------

    def leaderboard(
        self,
        category: str = "OVERALL",
        time_period: str = "ALL",
        limit: int = 100,
        offset: int = 0,
        order_by: str = "pnl",
    ) -> list[dict]:
        return self._get(
            config.DATA_API_BASE,
            "/v1/leaderboard",
            {
                "category": category,
                "timePeriod": time_period,
                "limit": limit,
                "offset": offset,
                "orderBy": order_by,
            },
        )

    def positions(self, user: str, **params: Any) -> list[dict]:
        params.setdefault("limit", 500)
        params.setdefault("sizeThreshold", 0)
        return self._get(config.DATA_API_BASE, "/positions", {"user": user, **params})

    def trades(self, user: str | None = None, market: str | None = None, **params: Any) -> list[dict]:
        params.setdefault("limit", 500)
        return self._get(config.DATA_API_BASE, "/trades", {"user": user, "market": market, **params})

    def activity(self, user: str, **params: Any) -> list[dict]:
        params.setdefault("limit", 500)
        return self._get(config.DATA_API_BASE, "/activity", {"user": user, **params})

    def holders(self, market: str, limit: int = 100) -> list[dict]:
        return self._get(config.DATA_API_BASE, "/holders", {"market": market, "limit": limit})

    def portfolio_value(self, user: str, market: str | None = None) -> Any:
        return self._get(config.DATA_API_BASE, "/value", {"user": user, "market": market})
