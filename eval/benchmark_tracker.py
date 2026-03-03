"""
Daily benchmark tracker for the Council of Agents evaluation framework.

Tracks two passive benchmarks starting March 2, 2026 with $1000 each:
  A) SPY (S&P 500 ETF)
  B) Market-cap-weighted basket of the 5 covered semiconductor stocks

Also merges NAV data from all PM portfolio profiles (pm, pm_nodebate, pm_noanalysts).

Usage:
    python eval/benchmark_tracker.py          # update and print summary
    python eval/benchmark_tracker.py --csv    # print CSV path only
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

# Ensure project root is on path so config imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

# ── Constants ─────────────────────────────────────────────────────────────────
START_DATE = date(2026, 3, 2)
INITIAL_INVESTMENT = 1000.0
TICKERS = list(config.COMPANIES.keys())  # NVDA, CDNS, CRWV, TSM, ASML
BENCHMARK_DIR = Path(config.DATA_DIR) / "benchmarks"
CSV_PATH = BENCHMARK_DIR / "daily_benchmarks.csv"

# Portfolio profiles to merge
PM_PROFILES = ["pm", "pm_nodebate", "pm_noanalysts"]


def _fetch_history(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Fetch daily closing prices for tickers from start to end (inclusive).

    Returns a DataFrame indexed by date with one column per ticker.
    """
    # yfinance end is exclusive, so add 1 day
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
    )
    if raw.empty:
        return pd.DataFrame()

    # yf.download returns MultiIndex columns when >1 ticker: (Price, Ticker)
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw["Close"]
    else:
        # Single ticker case
        closes = raw[["Close"]].rename(columns={"Close": tickers[0]})

    closes.index = pd.to_datetime(closes.index).date
    return closes.dropna(how="all")


def _fetch_market_caps(tickers: list[str]) -> dict[str, float]:
    """Fetch current market caps for tickers via yfinance."""
    caps = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            cap = info.get("marketCap", 0)
            if cap and cap > 0:
                caps[t] = float(cap)
        except Exception:
            pass
    return caps


def build_benchmarks() -> pd.DataFrame:
    """Build the full benchmark DataFrame from start date through today."""
    today = date.today()
    all_tickers = TICKERS + ["SPY"]

    print(f"  Fetching prices for {', '.join(all_tickers)} from {START_DATE} to {today}...")
    closes = _fetch_history(all_tickers, START_DATE, today)

    if closes.empty or len(closes) < 1:
        print("  ERROR: No price data returned from yfinance.")
        return pd.DataFrame()

    # Ensure all tickers are present
    missing = [t for t in all_tickers if t not in closes.columns]
    if missing:
        print(f"  WARNING: Missing price data for: {missing}")

    # ── Day-0 prices (first trading day on or after START_DATE) ────────────
    day0 = closes.iloc[0]

    # ── Benchmark A: SPY ──────────────────────────────────────────────────
    spy_shares = INITIAL_INVESTMENT / day0["SPY"]

    # ── Benchmark B: Market-cap weighted basket ───────────────────────────
    print("  Fetching market caps for weight computation...")
    market_caps = _fetch_market_caps(TICKERS)
    available = [t for t in TICKERS if t in market_caps and t in closes.columns]

    if not available:
        print("  ERROR: Could not fetch market caps for any ticker.")
        return pd.DataFrame()

    total_cap = sum(market_caps[t] for t in available)
    weights = {t: market_caps[t] / total_cap for t in available}
    shares = {t: (INITIAL_INVESTMENT * weights[t]) / day0[t] for t in available}

    print("  Market-cap weights (day 0):")
    for t in sorted(weights, key=weights.get, reverse=True):
        print(f"    {t}: {weights[t]:.4f} ({weights[t]*100:.1f}%)  "
              f"${INITIAL_INVESTMENT * weights[t]:.2f} → {shares[t]:.4f} shares @ ${day0[t]:.2f}")

    # ── Build daily DataFrame ─────────────────────────────────────────────
    rows = []
    for dt in closes.index:
        row = {"date": dt}

        # SPY benchmark
        spy_close = closes.loc[dt, "SPY"] if "SPY" in closes.columns else None
        if spy_close and pd.notna(spy_close):
            spy_val = spy_shares * spy_close
            row["spy_value"] = round(spy_val, 2)
            row["spy_return_pct"] = round((spy_val / INITIAL_INVESTMENT - 1) * 100, 4)
        else:
            row["spy_value"] = None
            row["spy_return_pct"] = None

        # Market-cap basket
        basket_val = 0.0
        all_valid = True
        for t in available:
            price = closes.loc[dt, t] if t in closes.columns else None
            if price and pd.notna(price):
                row[f"{t}_close"] = round(float(price), 2)
                basket_val += shares[t] * price
            else:
                row[f"{t}_close"] = None
                all_valid = False

        if all_valid:
            row["mcap_basket_value"] = round(basket_val, 2)
            row["mcap_return_pct"] = round((basket_val / INITIAL_INVESTMENT - 1) * 100, 4)
        else:
            row["mcap_basket_value"] = None
            row["mcap_return_pct"] = None

        rows.append(row)

    df = pd.DataFrame(rows)

    # Add fixed weight columns
    for t in available:
        df[f"{t}_weight"] = round(weights[t], 6)

    # ── Merge PM portfolio NAVs (all profiles) ────────────────────────────
    for profile in PM_PROFILES:
        nav_path = BENCHMARK_DIR / f"{profile}_daily_nav.csv"
        if nav_path.exists():
            pm_nav = pd.read_csv(nav_path)
            if not pm_nav.empty and "date" in pm_nav.columns:
                pm_nav["date"] = pm_nav["date"].astype(str)
                df["date"] = df["date"].astype(str)
                # Rename columns to include profile prefix
                val_col = f"{profile}_value"
                ret_col = f"{profile}_return_pct"
                pm_subset = pm_nav[["date", "portfolio_value", "pm_return_pct"]].rename(
                    columns={
                        "portfolio_value": val_col,
                        "pm_return_pct": ret_col,
                    }
                )
                df = df.merge(pm_subset, on="date", how="left")

    return df


def save_and_print(df: pd.DataFrame) -> Path:
    """Save DataFrame to CSV and print summary."""
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False)
    print(f"\n  Saved to: {CSV_PATH}")
    print(f"  Trading days tracked: {len(df)}")

    if len(df) >= 1:
        first = df.iloc[0]
        last = df.iloc[-1]
        print(f"\n  {'─' * 60}")
        print(f"  BENCHMARK SUMMARY  ({first['date']} → {last['date']})")
        print(f"  {'─' * 60}")
        print(f"  SPY (S&P 500):        ${last.get('spy_value', 'N/A'):>10}  "
              f"({last.get('spy_return_pct', 'N/A'):>+7}%)")
        print(f"  Semis (mcap-weighted): ${last.get('mcap_basket_value', 'N/A'):>10}  "
              f"({last.get('mcap_return_pct', 'N/A'):>+7}%)")

        # Print all PM profiles
        for profile in PM_PROFILES:
            val_col = f"{profile}_value"
            ret_col = f"{profile}_return_pct"
            if val_col in df.columns and pd.notna(last.get(val_col)):
                label = {
                    "pm": "PM (full debate)",
                    "pm_nodebate": "PM (no debate)",
                    "pm_noanalysts": "PM (no analysts)",
                }.get(profile, profile)
                print(f"  {label + ':':<24} ${last.get(val_col, 'N/A'):>10}  "
                      f"({last.get(ret_col, 'N/A'):>+7}%)")

        print(f"  {'─' * 60}")

        # Per-stock breakdown
        weight_cols = [c for c in df.columns if c.endswith("_weight")]
        if weight_cols:
            print(f"\n  {'Ticker':<8} {'Weight':>8} {'Day-0':>10} {'Latest':>10} {'Return':>10}")
            for wc in weight_cols:
                t = wc.replace("_weight", "")
                w = last[wc]
                close_col = f"{t}_close"
                if close_col in df.columns:
                    d0 = first.get(close_col, 0)
                    dl = last.get(close_col, 0)
                    ret = ((dl / d0) - 1) * 100 if d0 else 0
                    print(f"  {t:<8} {w:>7.1%} {d0:>10.2f} {dl:>10.2f} {ret:>+9.2f}%")

    return CSV_PATH


def main():
    df = build_benchmarks()
    if df.empty:
        print("  No data to save.")
        sys.exit(1)

    path = save_and_print(df)

    if "--csv" in sys.argv:
        print(path)


if __name__ == "__main__":
    main()
