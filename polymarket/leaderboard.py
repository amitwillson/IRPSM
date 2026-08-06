"""Leaderboard retrieval."""

from __future__ import annotations

from .client import PolymarketClient
from .config import LEADERBOARD_TIME_PERIODS


def fetch_leaderboard(
    client: PolymarketClient,
    category: str = "OVERALL",
    time_period: str = "ALL",
    limit: int = 100,
    order_by: str = "pnl",
) -> list[dict]:
    """Fetch a single leaderboard page (rank, wallet, username, volume, pnl)."""
    rows = client.leaderboard(category=category, time_period=time_period, limit=limit, order_by=order_by)
    for row in rows:
        row["_category"] = category
        row["_timePeriod"] = time_period
        row["_orderBy"] = order_by
    return rows


def fetch_leaderboard_all_periods(
    client: PolymarketClient,
    category: str = "OVERALL",
    limit: int = 100,
) -> dict[str, list[dict]]:
    """Fetch leaderboard rows for every time period (DAY/WEEK/MONTH/ALL) by both pnl and vol."""
    result: dict[str, list[dict]] = {}
    for period in LEADERBOARD_TIME_PERIODS:
        for order_by in ("pnl", "vol"):
            key = f"{period}_{order_by}"
            result[key] = fetch_leaderboard(client, category=category, time_period=period, limit=limit, order_by=order_by)
    return result


def unique_wallets_from_leaderboards(leaderboards: dict[str, list[dict]]) -> list[str]:
    """Union of distinct wallet addresses seen across a set of leaderboard pages."""
    wallets: set[str] = set()
    for rows in leaderboards.values():
        for row in rows:
            addr = row.get("proxyWallet") or row.get("wallet") or row.get("address")
            if addr:
                wallets.add(addr.lower())
    return sorted(wallets)
