# IRPSM
IRPSM PROJECT REPORT

## Polymarket Wallet & Market Data Extraction Toolkit

A Python toolkit for pulling wallet/trader data from [Polymarket](https://polymarket.com)
using its public, unauthenticated read APIs (Gamma API, Data API, CLOB API — the
same endpoints the polymarket.com frontend itself calls). No login, API key, or
wallet signature is required for any of this: it's all public market data.

### What it extracts

- **Leaderboard**: top traders by lifetime P&L and by volume, across DAY/WEEK/MONTH/ALL
  time windows and category (OVERALL, CRYPTO, SPORTS, POLITICS, ...).
- **5-minute crypto Up/Down markets**: the recurring markets for all 7 assets Polymarket
  runs them on — BTC, ETH, SOL, XRP, DOGE, HYPE, BNB — including current prices,
  volume, liquidity, and outcome token IDs.
- **Per-wallet detail**: open positions (size, avg price, current value, unrealized
  P&L), full onchain activity ledger (trades/splits/merges/redeems/rewards),
  capital deployed, realized win/loss count from resolved markets, lifetime P&L
  and volume (from the leaderboard), and total portfolio value.

### Install

```bash
pip install -r requirements.txt
```

### Usage

```bash
# Top 50 lifetime-profit wallets in the crypto category
python cli.py leaderboard --category CRYPTO --period ALL --limit 50

# Currently open 5-min Up/Down markets for all 7 assets
python cli.py markets

# Last 12 windows (1 hour) of 5-min Up/Down markets per asset
python cli.py markets --recent --lookback 12

# Full detail (positions, ledger, P&L, win/loss) for one wallet
python cli.py wallet 0xYOURWALLETADDRESS --with-leaderboard-rank

# Full pipeline: leaderboard + 5-min markets + every wallet's positions/ledger,
# exported as CSV + JSON into ./output
python cli.py extract --out output --limit 100

# Same, but keep only wallets currently holding a position in a live
# 5-minute crypto Up/Down market
python cli.py extract --out output --limit 100 --only-active-5min
```

`extract` writes:

| File | Contents |
|---|---|
| `leaderboard_<category>_<period>_<pnl|vol>.csv/json` | Raw leaderboard pages |
| `five_min_updown_markets.csv/json` | Discovered 5-min crypto markets |
| `wallet_summary.csv/json` | One row per wallet: capital deployed, win/loss, win rate, lifetime P&L/volume, portfolio value |
| `wallet_positions.csv/json` | Every open position for every wallet |
| `wallet_ledger.csv/json` | Full onchain activity (trade-by-trade ledger) for every wallet |

### Notes / limitations

- The leaderboard endpoint returns each wallet's **lifetime P&L and volume**
  directly; per-market realized win/loss is derived from `REDEEM` activity
  events (a positive payout on a resolved market counts as a win), since the
  positions endpoint only reports currently-open positions, not full trade
  history.
- 5-minute markets are discovered deterministically via their slug pattern
  (`{asset}-updown-5m-{window_start_unix_ts}`, window divisible by 300
  seconds) rather than by scanning all markets, so no market gets missed.
- Polymarket's Gamma API rate-limits aggressively above ~30 req/s; the client
  in `polymarket/client.py` retries with exponential backoff on 429s and paces
  requests by default. For large wallet counts, `extract` can take a while —
  use `--max-wallets` to cap it while testing.
- This code was written and reviewed without live network access to
  polymarket.com (this sandbox's egress policy doesn't allow it), based on
  Polymarket's public API documentation and known response shapes. Run it
  from an environment with normal internet access, and open an issue/PR if
  any field names have since changed upstream.
