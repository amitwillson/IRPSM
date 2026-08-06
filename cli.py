#!/usr/bin/env python3
"""CLI entrypoint for the Polymarket wallet/leaderboard/market data extractor.

Examples:
    python cli.py leaderboard --category CRYPTO --limit 50
    python cli.py markets
    python cli.py wallet 0xabc123...
    python cli.py extract --out output --limit 100 --only-active-5min
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from polymarket import export
from polymarket.client import PolymarketClient
from polymarket.config import LEADERBOARD_CATEGORIES, LEADERBOARD_TIME_PERIODS
from polymarket.leaderboard import fetch_leaderboard, fetch_leaderboard_all_periods
from polymarket.markets import fetch_current_updown_markets, fetch_recent_updown_markets
from polymarket.pipeline import run_full_extraction
from polymarket.wallet import build_round_ledger, build_wallet_profile, fetch_full_activity


def cmd_leaderboard(args: argparse.Namespace) -> None:
    client = PolymarketClient()
    rows = fetch_leaderboard(
        client, category=args.category, time_period=args.period, limit=args.limit, order_by=args.order_by
    )
    if args.out:
        export.write_json(rows, args.out)
        export.write_csv(rows, args.out.rsplit(".", 1)[0] + ".csv")
    print(json.dumps(rows, indent=2, default=str))


def cmd_markets(args: argparse.Namespace) -> None:
    client = PolymarketClient()
    if args.recent:
        markets = fetch_recent_updown_markets(client, lookback_windows=args.lookback)
    else:
        markets = fetch_current_updown_markets(client)
    rows = [m.__dict__ for m in markets]
    for r in rows:
        r.pop("raw_event", None)
    if args.out:
        export.write_json(rows, args.out)
    print(json.dumps(rows, indent=2, default=str))


def cmd_wallet(args: argparse.Namespace) -> None:
    client = PolymarketClient()
    leaderboards = None
    if args.with_leaderboard_rank:
        leaderboards = fetch_leaderboard_all_periods(client, category="OVERALL", limit=500)
    profile = build_wallet_profile(client, args.address, leaderboards=leaderboards)
    result = {
        "summary": profile.to_summary_row(),
        "positions": profile.positions,
        "activity": profile.activity,
    }
    if args.out:
        export.write_json(result, args.out)
    print(json.dumps(result, indent=2, default=str))


def cmd_history(args: argparse.Namespace) -> None:
    client = PolymarketClient()
    print(f"Fetching {args.days}-day activity history for {args.address} ...", file=sys.stderr)
    activity = fetch_full_activity(client, args.address, days=args.days)
    rounds = build_round_ledger(activity)

    resolved = [r for r in rounds if r["result"] is not None]
    wins = sum(1 for r in resolved if r["result"] == "WIN")
    total_pnl = sum(r["realized_pnl"] for r in resolved if r["realized_pnl"] is not None)
    print(
        f"{len(activity)} raw events -> {len(rounds)} markets traded "
        f"({len(resolved)} resolved, {wins}/{len(resolved)} wins, net realized P&L ${total_pnl:.2f})",
        file=sys.stderr,
    )

    out_dir = args.out
    export.write_json(activity, f"{out_dir}/{args.address}_activity_{args.days}d.json")
    export.write_csv(activity, f"{out_dir}/{args.address}_activity_{args.days}d.csv")
    export.write_json(rounds, f"{out_dir}/{args.address}_rounds_{args.days}d.json")
    export.write_csv(rounds, f"{out_dir}/{args.address}_rounds_{args.days}d.csv")
    print(f"Wrote {out_dir}/{args.address}_activity_{args.days}d.csv and _rounds_{args.days}d.csv", file=sys.stderr)


def cmd_extract(args: argparse.Namespace) -> None:
    stats = run_full_extraction(
        out_dir=args.out,
        leaderboard_limit=args.limit,
        category=args.category,
        lookback_windows=args.lookback,
        only_active_5min_traders=args.only_active_5min,
        max_wallets=args.max_wallets,
    )
    print(json.dumps(stats, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p_lb = sub.add_parser("leaderboard", help="Fetch a leaderboard page")
    p_lb.add_argument("--category", choices=LEADERBOARD_CATEGORIES, default="OVERALL")
    p_lb.add_argument("--period", choices=LEADERBOARD_TIME_PERIODS, default="ALL")
    p_lb.add_argument("--order-by", choices=["pnl", "vol"], default="pnl")
    p_lb.add_argument("--limit", type=int, default=100)
    p_lb.add_argument("--out", help="Write JSON+CSV to this path")
    p_lb.set_defaults(func=cmd_leaderboard)

    p_mk = sub.add_parser("markets", help="Discover 5-minute crypto Up/Down markets (7 assets)")
    p_mk.add_argument("--recent", action="store_true", help="Include recent past windows, not just current")
    p_mk.add_argument("--lookback", type=int, default=12, help="Number of trailing 5-min windows when --recent")
    p_mk.add_argument("--out", help="Write JSON to this path")
    p_mk.set_defaults(func=cmd_markets)

    p_wal = sub.add_parser("wallet", help="Full extraction for a single wallet address")
    p_wal.add_argument("address")
    p_wal.add_argument("--with-leaderboard-rank", action="store_true")
    p_wal.add_argument("--out", help="Write JSON to this path")
    p_wal.set_defaults(func=cmd_wallet)

    p_hist = sub.add_parser(
        "history", help="Full N-day activity history + decoded round-by-round ledger for one wallet"
    )
    p_hist.add_argument("address")
    p_hist.add_argument("--days", type=int, default=180, help="How many days back to pull (default 180 = 6 months)")
    p_hist.add_argument("--out", default="output", help="Output directory")
    p_hist.set_defaults(func=cmd_history)

    p_ex = sub.add_parser("extract", help="Full pipeline: leaderboard + markets + all wallet ledgers -> CSV/JSON")
    p_ex.add_argument("--out", default="output")
    p_ex.add_argument("--category", choices=LEADERBOARD_CATEGORIES, default="OVERALL")
    p_ex.add_argument("--limit", type=int, default=100, help="Leaderboard page size per period/order")
    p_ex.add_argument("--lookback", type=int, default=12, help="Trailing 5-min windows per asset")
    p_ex.add_argument("--max-wallets", type=int, default=None, help="Cap number of wallets processed")
    p_ex.add_argument(
        "--only-active-5min",
        action="store_true",
        help="Keep only wallets currently holding a position in one of the 5-min crypto markets",
    )
    p_ex.set_defaults(func=cmd_extract)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
