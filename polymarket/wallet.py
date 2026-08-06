"""Per-wallet extraction: positions, ledger, capital deployed, win/loss, lifetime P&L."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from .client import PolymarketBadRequestError, PolymarketClient

logger = logging.getLogger(__name__)

DATA_API_ACTIVITY_PAGE_SIZE = 500
# Docs advertise offset up to 10000, but in practice the API has started
# returning 400s well before that for some wallets (observed as low as
# ~5500). We treat that as a real "no more pages" signal rather than an
# error - see the PolymarketBadRequestError handling in fetch_full_activity.
DATA_API_MAX_OFFSET = 10000


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


def _fetch_activity_window(
    client: PolymarketClient,
    address: str,
    start_ts: int,
    end_ts: int,
    event_types: str,
) -> list[dict]:
    """Offset-paginate a single [start_ts, end_ts) time window until exhausted or the offset ceiling hits."""
    events: list[dict] = []
    offset = 0

    while True:
        try:
            page = client.activity(
                address,
                type=event_types,
                start=start_ts,
                end=end_ts,
                limit=DATA_API_ACTIVITY_PAGE_SIZE,
                offset=offset,
                sortBy="TIMESTAMP",
                sortDirection="DESC",
            )
        except PolymarketBadRequestError as exc:
            if offset == 0:
                raise  # first page failing is a real error (bad address, etc.)
            logger.warning(
                "%s: Data API rejected offset=%d within window [%d, %d) (%s); "
                "that window's history is truncated at this point (still trading heavily "
                "within a single %d-day chunk — narrow --chunk-days to fix).",
                address,
                offset,
                start_ts,
                end_ts,
                exc,
                (end_ts - start_ts) // 86400 or 1,
            )
            break

        if not page:
            break

        events.extend(page)
        if len(page) < DATA_API_ACTIVITY_PAGE_SIZE:
            break  # last page in this window
        offset += DATA_API_ACTIVITY_PAGE_SIZE
        if offset > DATA_API_MAX_OFFSET:
            logger.warning(
                "%s: hit Data API offset ceiling (%d) within window [%d, %d); "
                "that window's older history is unavailable",
                address,
                DATA_API_MAX_OFFSET,
                start_ts,
                end_ts,
            )
            break

    return events


def fetch_full_activity(
    client: PolymarketClient,
    address: str,
    days: int = 180,
    event_types: str = "TRADE,SPLIT,MERGE,REDEEM,REWARD,CONVERSION",
    chunk_days: int = 7,
) -> list[dict]:
    """Pull a wallet's complete activity history for the last `days` days.

    The Data API's /activity offset pagination has a ceiling well below its
    documented 10000 for very active wallets (observed 400s as low as
    offset~5500 in practice) — a single unbounded pull can silently truncate
    a heavy 5-min-market trader's history to a couple of weeks instead of 6
    months. To avoid that, we split the requested range into `chunk_days`
    windows (via the API's start/end filters) and offset-paginate each
    window independently, so each individual pull only needs to cover a few
    hundred to a few thousand events rather than the whole history at once.
    """
    now = int(time.time())
    cutoff_ts = now - days * 86400
    chunk_seconds = chunk_days * 86400

    all_events: list[dict] = []
    window_end = now
    while window_end > cutoff_ts:
        window_start = max(window_end - chunk_seconds, cutoff_ts)
        all_events.extend(_fetch_activity_window(client, address, window_start, window_end, event_types))
        window_end = window_start

    # De-dupe in case of overlapping boundary events, then keep only the requested range.
    seen: set[str] = set()
    deduped = []
    for e in all_events:
        key = e.get("transactionHash", "") + str(e.get("timestamp")) + str(e.get("asset", ""))
        if key in seen:
            continue
        seen.add(key)
        if int(e.get("timestamp") or 0) >= cutoff_ts:
            deduped.append(e)

    return deduped


_FIVE_MIN_TITLE_RE = re.compile(r"\bUp or Down\b.*\d{1,2}:\d{2}\s*(AM|PM)\s*-\s*\d{1,2}:\d{2}\s*(AM|PM)", re.I)


def build_round_ledger(activity: list[dict], open_condition_ids: set[str] | None = None) -> list[dict]:
    """Collapse a raw activity ledger into one row per market ("round") traded.

    Realized P&L per market is computed as a full cash-flow net: BUY costs
    and SPLIT costs are cash out; SELL proceeds, REDEEM payouts and MERGE
    payouts are cash in. This is the only way to get a correct number for
    wallets that exit positions by selling before resolution, or that hold
    both outcome tokens of the same market (common in these markets — the
    losing side simply expires worthless with no on-chain event, so relying
    on the presence of a REDEEM event alone undercounts wins and misreports
    open/exited positions as losses).

    A round is only marked WIN/LOSS once we know it's actually closed: either
    a REDEEM/MERGE event was seen, or (if `open_condition_ids` — the wallet's
    *currently* open positions, from /positions — is supplied) the market is
    absent from that set. Anything still genuinely open is left as `None`
    (OPEN) rather than being counted as a loss.
    """
    open_condition_ids = open_condition_ids or set()
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
                "first_trade_ts": None,
                "last_event_ts": None,
                "trade_count": 0,
                "net_cash": 0.0,  # negative = spent, positive = received
                "shares_by_asset": {},  # asset -> net remaining shares (signed; used to detect a flat/closed position)
                "assets_entered": set(),  # asset -> ever bought here (used to report which side was taken)
                "saw_redeem_or_merge": False,
            },
        )
        bucket["title"] = bucket["title"] or evt.get("title")
        ts = int(evt.get("timestamp") or 0)
        bucket["last_event_ts"] = ts

        etype = evt.get("type")
        asset = evt.get("asset")
        cash_amount = float(evt.get("usdcSize") or 0) or float(evt.get("price") or 0) * float(evt.get("size") or 0)
        size = float(evt.get("size") or 0)

        if etype == "TRADE":
            if bucket["first_trade_ts"] is None:
                bucket["first_trade_ts"] = ts
            bucket["trade_count"] += 1
            if evt.get("side") == "BUY":
                bucket["net_cash"] -= abs(cash_amount)
                bucket["shares_by_asset"][asset] = bucket["shares_by_asset"].get(asset, 0.0) + size
                if asset:
                    bucket["assets_entered"].add(asset)
            else:  # SELL
                bucket["net_cash"] += abs(cash_amount)
                bucket["shares_by_asset"][asset] = bucket["shares_by_asset"].get(asset, 0.0) - size
        elif etype == "REDEEM":
            bucket["net_cash"] += abs(cash_amount)
            bucket["saw_redeem_or_merge"] = True
            if asset:
                bucket["shares_by_asset"][asset] = bucket["shares_by_asset"].get(asset, 0.0) - size
        elif etype == "MERGE":
            bucket["net_cash"] += abs(cash_amount)
            bucket["saw_redeem_or_merge"] = True
        elif etype == "SPLIT":
            bucket["net_cash"] -= abs(cash_amount)

    rounds = []
    for cid, b in by_market.items():
        assets_entered = sorted(b["assets_entered"])
        side_taken = assets_entered[0] if len(assets_entered) == 1 else ("MIXED" if len(assets_entered) > 1 else None)

        is_flat = all(abs(qty) < 1e-6 for qty in b["shares_by_asset"].values())
        is_closed = b["saw_redeem_or_merge"] or is_flat or (cid not in open_condition_ids and open_condition_ids)

        pnl = b["net_cash"] if is_closed else None
        rounds.append(
            {
                "conditionId": cid,
                "title": b["title"],
                "is_5min_crypto_updown": bool(_FIVE_MIN_TITLE_RE.search(b["title"] or "")),
                "side_taken": side_taken,
                "first_trade_ts": b["first_trade_ts"],
                "last_event_ts": b["last_event_ts"],
                "trade_count": b["trade_count"],
                "net_cash_flow": round(b["net_cash"], 4),
                "status": "CLOSED" if is_closed else "OPEN",
                "realized_pnl": round(pnl, 4) if pnl is not None else None,
                "result": (
                    None if pnl is None else ("WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN"))
                ),
            }
        )

    rounds.sort(key=lambda r: r["first_trade_ts"] or 0)
    return rounds
