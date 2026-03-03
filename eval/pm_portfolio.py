"""
PM portfolio tracker — tracks the PM agent's active portfolio against benchmarks.

Supports multiple portfolio profiles (e.g. "pm", "pm_nodebate", "pm_noanalysts")
so the ablation experiment can track each condition independently.

Maintains two CSVs per profile:
  - {profile}_trades.csv:     append-only trade ledger (BUY/SELL with prices)
  - {profile}_daily_nav.csv:  daily mark-to-market portfolio value

Usage:
    python eval/pm_portfolio.py --init '{"NVDA": 400, "TSM": 400, "ASML": 200}'
    python eval/pm_portfolio.py --init '{"NVDA": 400, "TSM": 300}' --profile pm_nodebate
    python eval/pm_portfolio.py --update
    python eval/pm_portfolio.py --update --profile pm_nodebate
    python eval/pm_portfolio.py --rebalance '{"NVDA": 300, "TSM": 300, "ASML": 200, "CDNS": 100, "CRWV": 100}'
    python eval/pm_portfolio.py --status
    python eval/pm_portfolio.py --status --profile pm_nodebate
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# ── Paths ─────────────────────────────────────────────────────────────────────
BENCHMARK_DIR = Path(config.DATA_DIR) / "benchmarks"
TICKERS = list(config.COMPANIES.keys())
INITIAL_INVESTMENT = 1000.0

# Profile name → CSV path mapping
PROFILES = ["pm", "pm_nodebate", "pm_noanalysts"]


def _trades_path(profile: str = "pm") -> Path:
    return BENCHMARK_DIR / f"{profile}_trades.csv"


def _nav_path(profile: str = "pm") -> Path:
    return BENCHMARK_DIR / f"{profile}_daily_nav.csv"


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch latest closing prices for tickers."""
    prices = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period="5d")
            if not hist.empty:
                prices[t] = float(hist["Close"].iloc[-1])
        except Exception:
            pass
    return prices


def _load_trades(profile: str = "pm") -> pd.DataFrame:
    """Load the trade ledger."""
    path = _trades_path(profile)
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=["date", "ticker", "action", "shares", "price", "dollars"])


def _save_trades(df: pd.DataFrame, profile: str = "pm") -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_trades_path(profile), index=False)


def _load_nav(profile: str = "pm") -> pd.DataFrame:
    """Load the daily NAV history."""
    path = _nav_path(profile)
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def _save_nav(df: pd.DataFrame, profile: str = "pm") -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(_nav_path(profile), index=False)


def _current_holdings(profile: str = "pm") -> dict[str, float]:
    """Compute current share holdings from the trade ledger."""
    trades = _load_trades(profile)
    if trades.empty:
        return {}
    holdings: dict[str, float] = {}
    for _, row in trades.iterrows():
        t = row["ticker"]
        s = float(row["shares"])
        if row["action"] == "BUY":
            holdings[t] = holdings.get(t, 0.0) + s
        elif row["action"] == "SELL":
            holdings[t] = holdings.get(t, 0.0) - s
    # Clean up near-zero positions
    return {t: round(s, 8) for t, s in holdings.items() if abs(s) > 1e-9}


def _current_cash(profile: str = "pm") -> float:
    """Compute current cash from the trade ledger.

    Cash decreases on BUY, increases on SELL.
    Initial cash = INITIAL_INVESTMENT, then adjusted by trades.
    """
    trades = _load_trades(profile)
    if trades.empty:
        return INITIAL_INVESTMENT
    cash = INITIAL_INVESTMENT
    for _, row in trades.iterrows():
        if row["action"] == "BUY":
            cash -= float(row["dollars"])
        elif row["action"] == "SELL":
            cash += float(row["dollars"])
    return round(cash, 2)


def init_portfolio(allocation: dict[str, float], profile: str = "pm") -> None:
    """Initialize a portfolio with an allocation_dollars dict."""
    trades_path = _trades_path(profile)
    nav_path = _nav_path(profile)
    if trades_path.exists():
        print(f"  ERROR: Portfolio '{profile}' already initialized. Use --rebalance to change allocation.")
        print(f"  To start fresh, delete {trades_path} and {nav_path}")
        sys.exit(1)

    total_allocated = sum(allocation.values())
    if total_allocated > INITIAL_INVESTMENT + 0.01:
        print(f"  ERROR: Allocation ${total_allocated:.2f} exceeds budget ${INITIAL_INVESTMENT:.2f}")
        sys.exit(1)

    tickers_needed = [t for t, v in allocation.items() if v > 0]
    print(f"  [{profile}] Fetching prices for {', '.join(tickers_needed)}...")
    prices = _fetch_prices(tickers_needed)

    missing = [t for t in tickers_needed if t not in prices]
    if missing:
        print(f"  ERROR: Could not fetch prices for: {missing}")
        sys.exit(1)

    today = date.today().isoformat()
    trades = []
    for t, dollars in allocation.items():
        if dollars <= 0:
            continue
        price = prices[t]
        shares = dollars / price
        trades.append({
            "date": today,
            "ticker": t,
            "action": "BUY",
            "shares": round(shares, 8),
            "price": round(price, 2),
            "dollars": round(dollars, 2),
        })
        print(f"  [{profile}] BUY {t}: ${dollars:.2f} → {shares:.4f} shares @ ${price:.2f}")

    cash = INITIAL_INVESTMENT - total_allocated
    if cash > 0.01:
        print(f"  [{profile}] Cash remaining: ${cash:.2f}")

    trades_df = pd.DataFrame(trades)
    _save_trades(trades_df, profile)
    print(f"  [{profile}] Trades saved to {_trades_path(profile)}")

    # Record initial NAV
    _record_nav(profile=profile, prices_override=prices)


def _record_nav(profile: str = "pm", prices_override: dict[str, float] | None = None) -> None:
    """Compute and append today's NAV row."""
    holdings = _current_holdings(profile)
    cash = _current_cash(profile)

    if not holdings:
        print(f"  [{profile}] No holdings to mark to market.")
        return

    tickers_held = list(holdings.keys())
    if prices_override:
        prices = prices_override
    else:
        print(f"  [{profile}] Fetching prices for {', '.join(tickers_held)}...")
        prices = _fetch_prices(tickers_held)

    today = date.today().isoformat()

    # Check if we already have a row for today
    nav = _load_nav(profile)
    if not nav.empty and today in nav["date"].values:
        # Update existing row
        nav = nav[nav["date"] != today]

    row: dict = {"date": today, "cash": cash}
    portfolio_value = cash
    for t in TICKERS:
        shares = holdings.get(t, 0.0)
        price = prices.get(t)
        if shares > 0 and price:
            value = shares * price
            portfolio_value += value
            row[f"{t}_shares"] = round(shares, 8)
            row[f"{t}_value"] = round(value, 2)
        else:
            row[f"{t}_shares"] = 0.0
            row[f"{t}_value"] = 0.0

    row["portfolio_value"] = round(portfolio_value, 2)
    row["pm_return_pct"] = round((portfolio_value / INITIAL_INVESTMENT - 1) * 100, 4)

    nav = pd.concat([nav, pd.DataFrame([row])], ignore_index=True)
    _save_nav(nav, profile)
    nav_path = _nav_path(profile)
    print(f"  [{profile}] NAV: ${portfolio_value:.2f} ({row['pm_return_pct']:+.2f}%) — saved to {nav_path}")


def update_nav(profile: str = "pm") -> None:
    """Mark portfolio to market with today's closing prices."""
    if not _trades_path(profile).exists():
        print(f"  ERROR: No portfolio '{profile}' initialized. Run --init first.")
        sys.exit(1)
    _record_nav(profile=profile)


def rebalance(new_allocation: dict[str, float], profile: str = "pm") -> None:
    """Rebalance the portfolio to match a new allocation_dollars dict."""
    if not _trades_path(profile).exists():
        print(f"  ERROR: No portfolio '{profile}' initialized. Run --init first.")
        sys.exit(1)

    holdings = _current_holdings(profile)
    cash = _current_cash(profile)

    # Fetch current prices for all relevant tickers
    all_tickers = list(set(list(holdings.keys()) + [t for t, v in new_allocation.items() if v > 0]))
    print(f"  [{profile}] Fetching prices for {', '.join(all_tickers)}...")
    prices = _fetch_prices(all_tickers)

    # Current portfolio value
    portfolio_value = cash
    for t, shares in holdings.items():
        if t in prices:
            portfolio_value += shares * prices[t]

    print(f"  [{profile}] Current portfolio value: ${portfolio_value:.2f}")

    # Normalize new allocation to current portfolio value (not initial investment)
    alloc_total = sum(new_allocation.values())
    if alloc_total <= 0:
        print(f"  [{profile}] ERROR: New allocation sums to $0")
        sys.exit(1)
    scale = portfolio_value / alloc_total
    target = {t: v * scale for t, v in new_allocation.items()}

    # Compute current dollar positions
    current_positions = {t: holdings.get(t, 0) * prices.get(t, 0) for t in all_tickers}

    # Generate trades
    today = date.today().isoformat()
    new_trades = []

    # Sells first (free up cash)
    for t in all_tickers:
        current_val = current_positions.get(t, 0)
        target_val = target.get(t, 0)
        delta = target_val - current_val
        if delta < -0.01:  # SELL
            sell_dollars = abs(delta)
            sell_shares = sell_dollars / prices[t]
            new_trades.append({
                "date": today, "ticker": t, "action": "SELL",
                "shares": round(sell_shares, 8),
                "price": round(prices[t], 2),
                "dollars": round(sell_dollars, 2),
            })
            print(f"  [{profile}] SELL {t}: ${sell_dollars:.2f} ({sell_shares:.4f} shares @ ${prices[t]:.2f})")

    # Then buys
    for t in set(list(new_allocation.keys()) + all_tickers):
        current_val = current_positions.get(t, 0)
        target_val = target.get(t, 0)
        delta = target_val - current_val
        if delta > 0.01:  # BUY
            if t not in prices:
                print(f"  [{profile}] WARNING: No price for {t}, skipping")
                continue
            buy_shares = delta / prices[t]
            new_trades.append({
                "date": today, "ticker": t, "action": "BUY",
                "shares": round(buy_shares, 8),
                "price": round(prices[t], 2),
                "dollars": round(delta, 2),
            })
            print(f"  [{profile}] BUY  {t}: ${delta:.2f} ({buy_shares:.4f} shares @ ${prices[t]:.2f})")

    if not new_trades:
        print(f"  [{profile}] No trades needed — allocation already matches.")
        return

    # Append trades
    trades = _load_trades(profile)
    trades = pd.concat([trades, pd.DataFrame(new_trades)], ignore_index=True)
    _save_trades(trades, profile)
    print(f"  [{profile}] {len(new_trades)} trade(s) recorded.")

    # Update NAV
    _record_nav(profile=profile, prices_override=prices)


def get_portfolio_status(profile: str = "pm") -> dict:
    """Return portfolio status as a structured dict (for Slack or other consumers).

    Returns dict with keys: initialized, profile, holdings, cash, portfolio_value,
    return_pct, trades_count, nav_days, last_date.
    """
    if not _trades_path(profile).exists():
        return {"initialized": False, "profile": profile}

    holdings = _current_holdings(profile)
    cash = _current_cash(profile)
    prices = _fetch_prices(list(holdings.keys())) if holdings else {}
    nav = _load_nav(profile)
    trades = _load_trades(profile)

    portfolio_value = cash
    holding_details = []
    for t in TICKERS:
        shares = holdings.get(t, 0)
        price = prices.get(t, 0)
        value = shares * price
        portfolio_value += value
        if shares > 0:
            weight = value / portfolio_value if portfolio_value > 0 else 0
            holding_details.append({
                "ticker": t,
                "shares": round(shares, 4),
                "price": round(price, 2),
                "value": round(value, 2),
                "weight": round(weight, 4),
            })

    return {
        "initialized": True,
        "profile": profile,
        "holdings": holding_details,
        "cash": round(cash, 2),
        "portfolio_value": round(portfolio_value, 2),
        "return_pct": round((portfolio_value / INITIAL_INVESTMENT - 1) * 100, 2),
        "trades_count": len(trades),
        "nav_days": len(nav),
        "last_date": str(nav.iloc[-1]["date"]) if not nav.empty else None,
    }


def format_status_for_slack(status: dict | None = None, profile: str = "pm") -> str:
    """Format portfolio status as Slack mrkdwn text.

    If status is None, fetches it via get_portfolio_status().
    """
    if status is None:
        status = get_portfolio_status(profile)

    profile_label = status.get("profile", profile)
    if not status.get("initialized"):
        return f"_No portfolio '{profile_label}' initialized yet. Run the pipeline with `--init` first._"

    lines = [
        f"*{profile_label.upper()} Portfolio Status* ({status.get('last_date', 'N/A')})",
        f"*Total Value:* ${status['portfolio_value']:,.2f}  |  *Return:* {status['return_pct']:+.2f}%",
        "",
        "```",
        f"{'Ticker':<7} {'Shares':>8} {'Price':>9} {'Value':>10} {'Weight':>7}",
        f"{'-' * 45}",
    ]
    for h in status["holdings"]:
        lines.append(
            f"{h['ticker']:<7} {h['shares']:>8.2f} {h['price']:>9.2f} "
            f"{h['value']:>10.2f} {h['weight']:>6.1%}"
        )
    if status["cash"] > 0.01:
        lines.append(
            f"{'Cash':<7} {'':>8} {'':>9} {status['cash']:>10.2f} "
            f"{status['cash'] / status['portfolio_value']:>6.1%}"
        )
    lines.append(f"{'-' * 45}")
    lines.append(f"{'TOTAL':<7} {'':>8} {'':>9} {status['portfolio_value']:>10.2f}")
    lines.append("```")
    lines.append(f"_Trades: {status['trades_count']} | NAV days: {status['nav_days']}_")

    return "\n".join(lines)


def show_status(profile: str = "pm") -> None:
    """Print current portfolio status."""
    if not _trades_path(profile).exists():
        print(f"  No portfolio '{profile}' initialized. Run --init first.")
        return

    holdings = _current_holdings(profile)
    cash = _current_cash(profile)
    prices = _fetch_prices(list(holdings.keys())) if holdings else {}

    nav = _load_nav(profile)
    trades = _load_trades(profile)

    print(f"\n  {'═' * 60}")
    print(f"  {profile.upper()} PORTFOLIO STATUS")
    print(f"  {'═' * 60}")

    # Compute total portfolio value first for weight calculation
    portfolio_value = cash
    for t in TICKERS:
        shares = holdings.get(t, 0)
        price = prices.get(t, 0)
        portfolio_value += shares * price

    print(f"\n  {'Ticker':<8} {'Shares':>10} {'Price':>10} {'Value':>10} {'Weight':>8}")
    print(f"  {'─' * 56}")
    for t in TICKERS:
        shares = holdings.get(t, 0)
        price = prices.get(t, 0)
        value = shares * price
        if shares > 0:
            weight = value / portfolio_value if portfolio_value > 0 else 0
            print(f"  {t:<8} {shares:>10.4f} {price:>10.2f} {value:>10.2f} {weight:>7.1%}")

    if cash > 0.01:
        print(f"  {'Cash':<8} {'':>10} {'':>10} {cash:>10.2f} {cash/portfolio_value:>7.1%}")
    print(f"  {'─' * 56}")
    print(f"  {'TOTAL':<8} {'':>10} {'':>10} {portfolio_value:>10.2f}")

    ret = (portfolio_value / INITIAL_INVESTMENT - 1) * 100
    print(f"\n  Return: {ret:+.2f}% (from ${INITIAL_INVESTMENT:.0f} initial)")
    print(f"  Trades executed: {len(trades)}")

    if not nav.empty:
        print(f"  NAV history: {len(nav)} day(s) tracked")
        print(f"  First: {nav.iloc[0]['date']}  Last: {nav.iloc[-1]['date']}")

    print(f"  {'═' * 60}\n")


def main():
    parser = argparse.ArgumentParser(description="PM Portfolio Tracker")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", type=str, help='Initialize with allocation JSON, e.g. \'{"NVDA": 400, "TSM": 300}\'')
    group.add_argument("--update", action="store_true", help="Mark portfolio to market with today's prices")
    group.add_argument("--rebalance", type=str, help='Rebalance to new allocation JSON')
    group.add_argument("--status", action="store_true", help="Print current portfolio status")
    parser.add_argument("--profile", type=str, default="pm",
                        help='Portfolio profile name (default: "pm"). E.g. pm_nodebate, pm_noanalysts')
    args = parser.parse_args()

    if args.init:
        allocation = json.loads(args.init)
        init_portfolio(allocation, profile=args.profile)
    elif args.update:
        update_nav(profile=args.profile)
    elif args.rebalance:
        allocation = json.loads(args.rebalance)
        rebalance(allocation, profile=args.profile)
    elif args.status:
        show_status(profile=args.profile)


if __name__ == "__main__":
    main()
