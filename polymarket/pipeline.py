"""End-to-end orchestration: leaderboard -> wallets -> 5-min crypto markets -> export."""

from __future__ import annotations

import logging
from pathlib import Path

from . import export
from .client import PolymarketClient
from .config import FIVE_MIN_UPDOWN_ASSETS
from .leaderboard import fetch_leaderboard_all_periods, unique_wallets_from_leaderboards
from .markets import condition_ids_for_markets, fetch_recent_updown_markets
from .wallet import build_wallet_profile, filter_positions_by_condition_ids

logger = logging.getLogger(__name__)


def run_full_extraction(
    out_dir: str = "output",
    leaderboard_limit: int = 100,
    category: str = "OVERALL",
    lookback_windows: int = 12,
    only_active_5min_traders: bool = False,
    max_wallets: int | None = None,
) -> dict:
    """Run the full pipeline and write CSV/JSON artifacts to `out_dir`.

    Steps:
      1. Pull the leaderboard (all time periods, by pnl and by volume).
      2. Discover the currently-open + recent 5-minute Up/Down markets for
         all 7 crypto assets.
      3. For every wallet on the leaderboard, pull positions/activity and
         compute capital deployed, win/loss, lifetime P&L, ledger.
      4. Optionally restrict the wallet set to ones currently holding a
         position in one of the 5-minute crypto markets.
      5. Export everything to CSV + JSON.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    client = PolymarketClient()

    logger.info("Fetching leaderboard (%s)...", category)
    leaderboards = fetch_leaderboard_all_periods(client, category=category, limit=leaderboard_limit)
    for key, rows in leaderboards.items():
        export.write_json(rows, out / f"leaderboard_{category}_{key}.json")
        export.write_csv(rows, out / f"leaderboard_{category}_{key}.csv")

    logger.info("Discovering 5-minute crypto Up/Down markets for %d assets...", len(FIVE_MIN_UPDOWN_ASSETS))
    updown_markets = fetch_recent_updown_markets(client, lookback_windows=lookback_windows)
    updown_rows = [
        {
            "asset": m.asset,
            "slug": m.slug,
            "window_start": m.window_start,
            "window_end": m.window_end,
            "condition_id": m.condition_id,
            "question": m.question,
            "up_price": m.up_price,
            "down_price": m.down_price,
            "volume": m.volume,
            "liquidity": m.liquidity,
            "closed": m.closed,
        }
        for m in updown_markets
    ]
    export.write_json(updown_rows, out / "five_min_updown_markets.json")
    export.write_csv(updown_rows, out / "five_min_updown_markets.csv")
    active_condition_ids = condition_ids_for_markets(updown_markets)

    wallets = unique_wallets_from_leaderboards(leaderboards)
    if max_wallets:
        wallets = wallets[:max_wallets]
    logger.info("Extracting %d wallet profiles...", len(wallets))

    summary_rows = []
    all_positions_rows = []
    all_ledger_rows = []

    for i, addr in enumerate(wallets, 1):
        logger.info("[%d/%d] wallet %s", i, len(wallets), addr)
        try:
            profile = build_wallet_profile(client, addr, leaderboards=leaderboards)
        except Exception as exc:
            logger.warning("Failed to extract wallet %s: %s", addr, exc)
            continue

        if only_active_5min_traders:
            active_positions = filter_positions_by_condition_ids(profile.positions, active_condition_ids)
            if not active_positions:
                continue

        summary_rows.append(profile.to_summary_row())

        for pos in profile.positions:
            row = dict(pos)
            row["wallet"] = addr
            all_positions_rows.append(row)

        for evt in profile.activity:
            row = dict(evt)
            row["wallet"] = addr
            all_ledger_rows.append(row)

    export.write_json(summary_rows, out / "wallet_summary.json")
    export.write_csv(summary_rows, out / "wallet_summary.csv")
    export.write_json(all_positions_rows, out / "wallet_positions.json")
    export.write_csv(all_positions_rows, out / "wallet_positions.csv")
    export.write_json(all_ledger_rows, out / "wallet_ledger.json")
    export.write_csv(all_ledger_rows, out / "wallet_ledger.csv")

    logger.info("Done. Wrote artifacts to %s", out.resolve())
    return {
        "wallets_extracted": len(summary_rows),
        "five_min_markets_found": sum(1 for m in updown_markets if m.condition_id),
        "out_dir": str(out.resolve()),
    }
