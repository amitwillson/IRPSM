"""Per-wallet extraction: positions, ledger, capital deployed, win/loss, lifetime P&L."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .client import PolymarketClient

logger = logging.getLogger(__name__)

DATA_API_ACTIVITY_PAGE_SIZE = 500
DATA_API_MAX_OFFSET = 10000  # hard ceiling enforced by data-api.polymarket.com


@dataclass
class WalletProfile:
    address: str
    username: str | None = None

    leaderboard_rank: dict | None = None  # {"category": ..., "timePeriod": ..., "rank": ..., "pnl": ..., "vol": ...}

    positions: list[dict] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)

    open_positions_value: float = 0.0
    capital_deployed: float = 0.0  # sum of initialValue across all open positions
    unrealized_pnl: float = 0.0

    realized_wins: int = 0
    realized_losses: int = 0
    resolved_markets_count: int = 0

    total_volume_traded: float = 0.0
    portfolio_value: float | None = None

    def to_summary_row(self) -> dict:
        win_rate = None
        total_resolved = self.realized_wins + self.realized_losses
        if total_resolved:
            win_rate = round(self.realized_wins / total_resolved, 4)

        return {
            "wallet": self.address,
            "username": self.username,
            "leaderboard_rank": (self.leaderboard_rank or {}).get("rank"),
            "leaderboard_category": (self.leaderboard_rank or {}).get("category"),
            "leaderboard_period": (self.leaderboard_rank or {}).get("timePeriod"),
            "lifetime_pnl": (self.leaderboard_rank or {}).get("pnl"),
            "lifetime_volume": (self.leaderboard_rank or {}).get("vol"),
            "open_positions_count": len(self.positions),
            "capital_deployed": round(self.capital_deployed, 2),
            "open_positions_value": round(self.open_positions_value, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "realized_wins": self.realized_wins,
            "realized_losses": self.realized_losses,
            "win_rate": win_rate,
            "total_volume_traded": round(self.total_volume_traded, 2),
            "portfolio_value": self.portfolio_value,
            "activity_events": len(self.activity),
        }


def _extract_wallets_pnl_and_volume(rows: list[dict], address: str) -> dict | None:
    address = address.lower()
    for row in rows:
        addr = (row.get("proxyWallet") or row.get("wallet") or row.get("address") or "").lower()
        if addr == address:
            return {
                "rank": row.get("rank"),
                "category": row.get("_category"),
                "timePeriod": row.get("_timePeriod"),
                "pnl": row.get("pnl"),
                "vol": row.get("vol"),
            }
    return None


def build_wallet_profile(
    client: PolymarketClient,
    address: str,
    username: str | None = None,
    leaderboards: dict[str, list[dict]] | None = None,
) -> WalletProfile:
    """Pull everything the public APIs expose for a single wallet address."""
    profile = WalletProfile(address=address, username=username)

    if leaderboards:
        # Prefer ALL-time pnl ranking as the "lifetime profit" figure.
        for key in ("ALL_pnl", "ALL_vol"):
            hit = _extract_wallets_pnl_and_volume(leaderboards.get(key, []), address)
            if hit:
                profile.leaderboard_rank = hit
                break

    positions = client.positions(address)
    profile.positions = positions
    for pos in positions:
        profile.capital_deployed += float(pos.get("initialValue") or 0)
        profile.open_positions_value += float(pos.get("currentValue") or 0)
        profile.unrealized_pnl += float(pos.get("cashPnl") or 0)

    activity = client.activity(address, type="TRADE,REDEEM,MERGE,SPLIT,REWARD,CONVERSION")
    profile.activity = activity

    total_volume = 0.0
    redeem_pnl_by_market: dict[str, float] = {}
    for evt in activity:
        if evt.get("type") == "TRADE":
            total_volume += abs(float(evt.get("usdcSize") or evt.get("size", 0) or 0)) or abs(
                float(evt.get("price") or 0) * float(evt.get("size") or 0)
            )
        if evt.get("type") == "REDEEM":
            cid = evt.get("conditionId") or evt.get("market")
            payout = float(evt.get("usdcSize") or evt.get("size") or 0)
            if cid:
                redeem_pnl_by_market[cid] = redeem_pnl_by_market.get(cid, 0.0) + payout

    profile.total_volume_traded = total_volume
    profile.resolved_markets_count = len(redeem_pnl_by_market)

    for pnl in redeem_pnl_by_market.values():
        if pnl > 0:
            profile.realized_wins += 1
        else:
            profile.realized_losses += 1

    try:
        value_resp = client.portfolio_value(address)
        if isinstance(value_resp, list) and value_resp:
            profile.portfolio_value = float(value_resp[0].get("value") or 0)
        elif isinstance(value_resp, dict):
            profile.portfolio_value = float(value_resp.get("value") or 0)
    except Exception:
        profile.portfolio_value = None

    return profile


def filter_positions_by_condition_ids(positions: list[dict], condition_ids: set[str]) -> list[dict]:
    return [p for p in positions if p.get("conditionId") in condition_ids]


def fetch_full_activity(
    client: PolymarketClient,
    address: str,
    days: int = 180,
    event_types: str = "TRADE,SPLIT,MERGE,REDEEM,REWARD,CONVERSION",
) -> list[dict]:
    """Page through /activity to pull a wallet's complete history for the last `days` days.

    The Data API paginates with limit/offset (limit<=500, offset<=10000), and
    returns events newest-first. We page until either a short page tells us
    we've exhausted history, the offset ceiling is hit, or every event on a
    page is already older than the cutoff.
    """
    cutoff_ts = int(time.time()) - days * 86400
    all_events: list[dict] = []
    offset = 0

    while True:
        page = client.activity(
            address,
            type=event_types,
            limit=DATA_API_ACTIVITY_PAGE_SIZE,
            offset=offset,
            sortBy="TIMESTAMP",
            sortDirection="DESC",
        )
        if not page:
            break

        all_events.extend(page)
        oldest_ts_on_page = min(int(e.get("timestamp") or 0) for e in page)

        if len(page) < DATA_API_ACTIVITY_PAGE_SIZE:
            break  # last page
        if oldest_ts_on_page < cutoff_ts:
            break  # we've paged past the window we care about
        offset += DATA_API_ACTIVITY_PAGE_SIZE
        if offset > DATA_API_MAX_OFFSET:
            logger.warning(
                "%s: hit Data API offset ceiling (%d) before reaching %d days back; "
                "history is truncated to the most recent ~%d events",
                address,
                DATA_API_MAX_OFFSET,
                days,
                offset,
            )
            break

    return [e for e in all_events if int(e.get("timestamp") or 0) >= cutoff_ts]


def build_round_ledger(activity: list[dict]) -> list[dict]:
    """Collapse a raw activity ledger into one row per market ("round") traded.

    Groups TRADE/REDEEM/MERGE events by conditionId and produces, per market:
    entry side(s), avg entry price, total cost basis, number of fills, redeem
    payout, realized P&L, win/loss, first-trade and last-event timestamps.
    This is the shape you want for strategy backtesting/decoding — one row
    per decision the wallet made, in chronological order.
    """
    by_market: dict[str, dict] = {}

    for evt in sorted(activity, key=lambda e: int(e.get("timestamp") or 0)):
        cid = evt.get("conditionId") or evt.get("market")
        if not cid:
            continue
        bucket = by_market.setdefault(
            cid,
            {
                "conditionId": cid,
                "title": evt.get("title"),
                "outcome": None,
                "first_trade_ts": None,
                "last_event_ts": None,
                "trade_count": 0,
                "cost_basis": 0.0,
                "shares_bought": 0.0,
                "redeem_payout": 0.0,
                "realized": False,
            }
        )
        bucket["title"] = bucket["title"] or evt.get("title")
        ts = int(evt.get("timestamp") or 0)
        bucket["last_event_ts"] = ts
        if bucket["first_trade_ts"] is None and evt.get("type") == "TRADE":
            bucket["first_trade_ts"] = ts
            bucket["outcome"] = evt.get("outcome")

        if evt.get("type") == "TRADE" and evt.get("side") == "BUY":
            price = float(evt.get("price") or 0)
            size = float(evt.get("size") or 0)
            bucket["cost_basis"] += price * size
            bucket["shares_bought"] += size
            bucket["trade_count"] += 1
        elif evt.get("type") == "TRADE":
            bucket["trade_count"] += 1
        elif evt.get("type") == "REDEEM":
            bucket["redeem_payout"] += float(evt.get("usdcSize") or evt.get("size") or 0)
            bucket["realized"] = True

    rounds = []
    for cid, b in by_market.items():
        pnl = b["redeem_payout"] - b["cost_basis"] if b["realized"] else None
        avg_entry_price = (b["cost_basis"] / b["shares_bought"]) if b["shares_bought"] else None
        rounds.append(
            {
                "conditionId": cid,
                "title": b["title"],
                "side_taken": b["outcome"],
                "first_trade_ts": b["first_trade_ts"],
                "last_event_ts": b["last_event_ts"],
                "trade_count": b["trade_count"],
                "avg_entry_price": round(avg_entry_price, 4) if avg_entry_price is not None else None,
                "cost_basis": round(b["cost_basis"], 4),
                "redeem_payout": round(b["redeem_payout"], 4) if b["realized"] else None,
                "realized_pnl": round(pnl, 4) if pnl is not None else None,
                "result": (None if pnl is None else ("WIN" if pnl > 0 else "LOSS")),
            }
        )

    rounds.sort(key=lambda r: r["first_trade_ts"] or 0)
    return rounds
