"""
APScheduler daemon for the multi-frequency live trading experiment.

Runs the full one-shot LangGraph pipeline on 4 different cadences,
records each run to pm_portfolio CSVs, and syncs to Google Sheets.

Usage:
    python eval/live_scheduler.py               # start daemon (blocking)
    python eval/live_scheduler.py --dry-run     # one pass of all strategies, no portfolio changes
    python eval/live_scheduler.py --once live_1h  # run one strategy once then exit
"""

import argparse
import logging
import sys
import time
from datetime import datetime, date
from pathlib import Path

import yfinance as yf
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.schedulers.background import BackgroundScheduler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from eval.pm_portfolio import (
    init_portfolio, rebalance, update_nav, get_portfolio_status,
    _trades_path,
)
from eval.live_performance_sheets import write_strategy_tab, write_dashboard, get_sheet_url

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  %(levelname)-7s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger('live_scheduler')

TICKERS = list(config.COMPANIES.keys())
SPY_SHARES_PATH = Path(config.DATA_DIR) / 'benchmarks' / 'spy_shares.txt'


# ── SPY tracking ──────────────────────────────────────────────────────────────

def _init_spy() -> None:
    """Buy-and-hold SPY with $1000 on first run; record share count."""
    if SPY_SHARES_PATH.exists():
        return
    try:
        hist = yf.Ticker('SPY').history(period='2d')
        if hist.empty:
            return
        price = float(hist['Close'].iloc[-1])
        shares = 1000.0 / price
        SPY_SHARES_PATH.parent.mkdir(parents=True, exist_ok=True)
        SPY_SHARES_PATH.write_text(f'{shares:.6f}')
        log.info(f'SPY initialized: {shares:.4f} shares @ ${price:.2f}')
    except Exception as e:
        log.warning(f'SPY init failed: {e}')


def _spy_value() -> float:
    """Return current mark-to-market value of the SPY position."""
    if not SPY_SHARES_PATH.exists():
        return 1000.0
    try:
        shares = float(SPY_SHARES_PATH.read_text().strip())
        hist = yf.Ticker('SPY').history(period='2d')
        if hist.empty:
            return 1000.0
        price = float(hist['Close'].iloc[-1])
        return round(shares * price, 2)
    except Exception:
        return 1000.0


# ── Core run function ─────────────────────────────────────────────────────────

def run_and_record(profile: str, lookback_hours: int, dry_run: bool = False) -> dict:
    """
    Execute one pipeline run for a strategy and record the results.

    1. Run LangGraph pipeline (one-shot, $1000 budget)
    2. Init or rebalance the portfolio
    3. Update NAV
    4. Write to Google Sheets
    5. Return result dict
    """
    label = config.LIVE_STRATEGIES[profile]['label']
    log.info(f'[{profile}] Starting {label} run (lookback={lookback_hours}h, dry_run={dry_run})')
    t0 = time.time()

    # ── 1. Run pipeline ────────────────────────────────────────────────────────
    result = {}
    allocation = {}
    rationale = ''
    theses = []
    errors = ''

    try:
        from langgraph_pipeline import graph
        state = {
            'event': '',
            'lookback_hours': lookback_hours,
            'budget': 1000.0,
            'debate_rounds': 0,
            'no_analysts': False,
        }
        out = graph.invoke(state)
        if out.get('error'):
            errors = out['error']
            log.warning(f'[{profile}] Pipeline error: {errors}')
        else:
            result = out.get('result', {})
            allocation = result.get('allocation_dollars', {})
            rationale = result.get('rationale', '')
            # Extract per-company theses from analyst briefs in state
            briefs = out.get('analyst_briefs', [])
            for b in briefs:
                theses.append({
                    'ticker': b.get('ticker', ''),
                    'conviction': b.get('conviction', 0),
                    'st_event_conv': b.get('short_term_event_conviction', 0),
                    'thesis': b.get('thesis', ''),
                    'key_events': ', '.join(
                        e.get('headline', '') for e in b.get('routed_events', [])[:3]
                    ),
                })
    except Exception as e:
        errors = str(e)
        log.error(f'[{profile}] Pipeline exception: {e}')

    elapsed = round(time.time() - t0, 1)

    # ── 2 & 3. Portfolio update ────────────────────────────────────────────────
    prices = {}
    nav_status = {}
    if allocation and not dry_run:
        try:
            if not _trades_path(profile).exists():
                log.info(f'[{profile}] Initializing portfolio: {allocation}')
                init_portfolio(allocation, profile)
            else:
                log.info(f'[{profile}] Rebalancing portfolio: {allocation}')
                rebalance(allocation, profile)
            update_nav(profile)
        except Exception as e:
            log.error(f'[{profile}] Portfolio update failed: {e}')

        try:
            nav_status = get_portfolio_status(profile)
        except Exception as e:
            log.warning(f'[{profile}] Could not read portfolio status: {e}')

        try:
            prices = _fetch_prices(TICKERS)
        except Exception as e:
            log.warning(f'[{profile}] Price fetch failed: {e}')
    elif dry_run and allocation:
        log.info(f'[{profile}] DRY RUN — allocation would be: {allocation}')
        try:
            nav_status = get_portfolio_status(profile) if _trades_path(profile).exists() else {}
        except Exception:
            nav_status = {}
        try:
            prices = _fetch_prices(TICKERS)
        except Exception:
            prices = {}

    # ── 4. Sheets write ────────────────────────────────────────────────────────
    if config.LIVE_PERFORMANCE_SHEET_ID and nav_status:
        try:
            run_number = nav_status.get('trades_count', 1)
            write_strategy_tab(
                profile=profile,
                nav_row=nav_status,
                allocation=allocation,
                theses=theses,
                rationale=rationale,
                prices=prices,
                run_number=run_number,
            )
        except Exception as e:
            log.warning(f'[{profile}] Sheets write failed: {e}')

    log.info(
        f'[{profile}] Done in {elapsed}s | '
        f'NAV=${nav_status.get("portfolio_value", "?"):.2f} | '
        f'Return={nav_status.get("return_pct", 0)*100:+.2f}%'
        if nav_status else f'[{profile}] Done in {elapsed}s (no portfolio data)'
    )
    return {
        'profile': profile,
        'allocation': allocation,
        'nav': nav_status,
        'rationale': rationale,
        'errors': errors,
        'elapsed_s': elapsed,
    }


def _refresh_dashboard(dry_run: bool = False) -> None:
    """Collect all strategy NAVs and update Dashboard + SPY."""
    if not config.LIVE_PERFORMANCE_SHEET_ID:
        return
    all_nav = {}
    for profile in config.LIVE_STRATEGIES:
        try:
            if _trades_path(profile).exists():
                all_nav[profile] = get_portfolio_status(profile)
        except Exception:
            pass
    spy_val = _spy_value()
    if not dry_run:
        try:
            write_dashboard(all_nav, spy_value=spy_val)
        except Exception as e:
            log.warning(f'Dashboard write failed: {e}')


def _fetch_prices(tickers: list) -> dict:
    prices = {}
    for t in tickers:
        try:
            hist = yf.Ticker(t).history(period='2d')
            if not hist.empty:
                prices[t] = float(hist['Close'].iloc[-1])
        except Exception:
            pass
    return prices


# ── Scheduler setup ───────────────────────────────────────────────────────────

def build_scheduler(dry_run: bool = False) -> BlockingScheduler:
    """Build and return the APScheduler with all 4 strategy jobs."""
    scheduler = BlockingScheduler(timezone='America/New_York')

    for profile, cfg in config.LIVE_STRATEGIES.items():
        lh = cfg['lookback_hours']

        def _make_job(p=profile, l=lh):
            def job():
                run_and_record(p, l, dry_run=dry_run)
                _refresh_dashboard(dry_run=dry_run)
            return job

        if 'interval_weeks' in cfg:
            scheduler.add_job(
                _make_job(),
                trigger='interval',
                weeks=cfg['interval_weeks'],
                id=profile,
                next_run_time=datetime.now(),  # fire immediately on start
                misfire_grace_time=3600,
            )
        else:
            scheduler.add_job(
                _make_job(),
                trigger='interval',
                hours=cfg['interval_hours'],
                id=profile,
                next_run_time=datetime.now(),  # fire immediately on start
                misfire_grace_time=3600,
            )
        log.info(f'Registered job: {profile} every '
                 f'{cfg.get("interval_hours", cfg.get("interval_weeks", "?"))} '
                 f'{"hour(s)" if "interval_hours" in cfg else "week(s)"}')

    return scheduler


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Agent Alpha live trading scheduler')
    parser.add_argument('--dry-run', action='store_true',
                        help='Run all strategies once without modifying portfolios')
    parser.add_argument('--once', metavar='PROFILE',
                        help='Run a single strategy once then exit (e.g. live_1h)')
    args = parser.parse_args()

    _init_spy()

    if args.once:
        profile = args.once
        if profile not in config.LIVE_STRATEGIES:
            print(f'Unknown profile "{profile}". Choose from: {list(config.LIVE_STRATEGIES)}')
            sys.exit(1)
        cfg = config.LIVE_STRATEGIES[profile]
        result = run_and_record(profile, cfg['lookback_hours'], dry_run=args.dry_run)
        _refresh_dashboard(dry_run=args.dry_run)
        print(f'\nAllocation: {result["allocation"]}')
        print(f'Rationale:  {result["rationale"][:300]}')
        if result['errors']:
            print(f'Errors:     {result["errors"]}')
        return

    if args.dry_run:
        log.info('DRY RUN — running all strategies once (no portfolio changes)')
        for profile, cfg in config.LIVE_STRATEGIES.items():
            run_and_record(profile, cfg['lookback_hours'], dry_run=True)
        _refresh_dashboard(dry_run=True)
        log.info('Dry run complete.')
        return

    # Normal daemon mode
    sheet_url = get_sheet_url()
    log.info('=' * 60)
    log.info('  Agent Alpha — Live Trading Scheduler')
    log.info(f'  Strategies: {list(config.LIVE_STRATEGIES.keys())}')
    if sheet_url:
        log.info(f'  Sheets: {sheet_url}')
    else:
        log.warning('  LIVE_PERFORMANCE_SHEET_ID not set — Sheets writes disabled')
    log.info('  All strategies fire immediately on start, then on schedule.')
    log.info('  Press Ctrl+C to stop.')
    log.info('=' * 60)

    scheduler = build_scheduler(dry_run=False)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info('Scheduler stopped.')


if __name__ == '__main__':
    main()
