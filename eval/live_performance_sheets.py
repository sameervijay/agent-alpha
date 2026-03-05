"""
Google Sheets writer for the live performance tracking experiment.

Manages a single "Agent Alpha — Live Performance" Sheet with:
  - Dashboard tab: side-by-side summary of all strategies + SPY
  - Per-strategy tabs (live_1h, live_4h, live_24h, live_7d):
      Section A — Current Portfolio
      Section B — NAV History (append-only)
      Section C — Latest Agent Theses (overwritten each run)
      Section D — Run Log (append-only)

Usage:
    from eval.live_performance_sheets import create_performance_sheet, write_strategy_tab, write_dashboard
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import gspread
from gspread.exceptions import APIError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config
from sheets_client import get_gspread_client, _with_retry

# ── Layout constants ───────────────────────────────────────────────────────────
TICKERS = ['NVDA', 'CDNS', 'CRWV', 'TSM', 'ASML']

_DASHBOARD_HEADER = [
    'Strategy', 'Label', 'Lookback (h)', 'Start Value ($)',
    'Current Value ($)', 'Return (%)', '# Runs', 'Last Run',
]
_DASHBOARD_TIMESERIES_HEADER_ROW = 10  # row where the time-series table starts
_TIMESERIES_COLS = ['Date', 'SPY ($)', 'live_1h ($)', 'live_4h ($)', 'live_24h ($)', 'live_7d ($)']

_PORTFOLIO_HEADER = ['Ticker', 'Shares', 'Price ($)', 'Value ($)', 'Weight (%)']
_NAV_HEADER = ['Timestamp', 'NVDA_val', 'CDNS_val', 'CRWV_val', 'TSM_val', 'ASML_val',
               'Cash ($)', 'Portfolio Value ($)', 'Return (%)']
_THESIS_HEADER = ['Company', 'Conviction', 'ST Event Conv', 'Thesis (excerpt)', 'Key Events']
_RUNLOG_HEADER = ['Run #', 'Timestamp', 'NVDA ($)', 'CDNS ($)', 'CRWV ($)', 'TSM ($)', 'ASML ($)', 'Rationale (excerpt)']

# Row anchors for each section within a strategy tab
_SEC_A_ROW = 1   # Current Portfolio
_SEC_B_ROW = 10  # NAV History
_SEC_C_ROW = 30  # Agent Theses
_SEC_D_ROW = 40  # Run Log


# ── Sheet creation ─────────────────────────────────────────────────────────────

def scaffold_existing_sheet(sheet_id: str) -> str:
    """
    Scaffold tabs on an already-created Sheet (use when Drive quota prevents gc.create()).
    The Sheet must already be shared with the service account (editor access).
    Returns the sheet_id unchanged.
    """
    gc = get_gspread_client()
    sh = _with_retry(lambda: gc.open_by_key(sheet_id), 'open_existing_sheet')

    # Rename first sheet to Dashboard if it isn't already
    existing_titles = [ws.title for ws in sh.worksheets()]
    if 'Dashboard' not in existing_titles:
        first = sh.sheet1
        _with_retry(lambda: first.update_title('Dashboard'), 'rename_to_dashboard')
        _scaffold_dashboard(first)
    else:
        _scaffold_dashboard(sh.worksheet('Dashboard'))

    for profile, cfg in config.LIVE_STRATEGIES.items():
        if profile not in existing_titles:
            tab = _with_retry(
                lambda p=profile: sh.add_worksheet(title=p, rows=500, cols=20),
                f'create_tab_{profile}',
            )
        else:
            tab = sh.worksheet(profile)
        _scaffold_strategy_tab(tab, profile, cfg['label'])

    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}'
    print(f'  [live_sheets] Scaffolded existing sheet: {url}')
    return sheet_id


def create_performance_sheet() -> str:
    """
    Create a new 'Agent Alpha — Live Performance' Google Sheet,
    scaffold all tabs with headers, and return the sheet ID.

    The caller is responsible for saving the returned ID to config /
    LIVE_PERFORMANCE_SHEET_ID env var.
    """
    gc = get_gspread_client()
    sh = _with_retry(lambda: gc.create('Agent Alpha — Live Performance'),
                     'create_performance_sheet')

    # Share with the service account's own email so it can always access it
    # (gspread.create() already gives the SA owner access)

    # Rename default "Sheet1" to "Dashboard"
    ws = sh.sheet1
    _with_retry(lambda: ws.update_title('Dashboard'), 'rename_to_dashboard')
    _scaffold_dashboard(ws)

    # Create per-strategy tabs
    for profile, cfg in config.LIVE_STRATEGIES.items():
        tab = _with_retry(lambda p=profile: sh.add_worksheet(title=p, rows=500, cols=20),
                          f'create_tab_{profile}')
        _scaffold_strategy_tab(tab, profile, cfg['label'])

    sheet_id = sh.id
    url = f'https://docs.google.com/spreadsheets/d/{sheet_id}'
    print(f'  [live_sheets] Created: {url}')
    return sheet_id


def _scaffold_dashboard(ws: gspread.Worksheet) -> None:
    """Write Dashboard tab headers and static rows using a single batch_update call."""
    ws.clear()
    summary_rows = [['SPY', 'Buy & Hold', '—', 1000, '', '', '—', '']]
    for profile, cfg in config.LIVE_STRATEGIES.items():
        summary_rows.append([profile, cfg['label'], cfg['lookback_hours'], 1000, '', '', 0, ''])

    ws.batch_update([
        {'range': 'A1', 'values': [['Agent Alpha — Live Performance']]},
        {'range': 'A2', 'values': [['Last updated:', '']]},
        {'range': 'J2', 'values': [['SPY Base ($)', '']]},  # col J=base price, K=value
        {'range': 'A4', 'values': [_DASHBOARD_HEADER]},
        {'range': 'A5', 'values': summary_rows},
        {'range': f'A{_DASHBOARD_TIMESERIES_HEADER_ROW}', 'values': [_TIMESERIES_COLS]},
    ])


def _scaffold_strategy_tab(ws: gspread.Worksheet, profile: str, label: str) -> None:
    """Write section headers for a strategy tab using a single batch_update call."""
    ws.clear()
    ws.batch_update([
        {'range': 'A1', 'values': [[f'{label} ({profile})']]},
        {'range': 'A2', 'values': [['Section A — Current Portfolio']]},
        {'range': 'A3', 'values': [_PORTFOLIO_HEADER]},
        {'range': f'A{_SEC_B_ROW}',     'values': [['Section B — NAV History']]},
        {'range': f'A{_SEC_B_ROW + 1}', 'values': [_NAV_HEADER]},
        {'range': f'A{_SEC_C_ROW}',     'values': [['Section C — Latest Agent Theses']]},
        {'range': f'A{_SEC_C_ROW + 1}', 'values': [_THESIS_HEADER]},
        {'range': f'A{_SEC_D_ROW}',     'values': [['Section D — Run Log']]},
        {'range': f'A{_SEC_D_ROW + 1}', 'values': [_RUNLOG_HEADER]},
    ])


# ── Per-run write ──────────────────────────────────────────────────────────────

def write_strategy_tab(
    profile: str,
    nav_row: dict,
    allocation: dict,
    theses: list[dict],
    rationale: str,
    prices: dict,
    run_number: int,
) -> None:
    """
    Update a strategy tab after a pipeline run.

    Args:
        profile:     e.g. 'live_1h'
        nav_row:     dict from pm_portfolio.get_portfolio_status() — includes
                     portfolio_value, return_pct, holdings {ticker: shares}
        allocation:  dict[ticker -> dollars] from pipeline result
        theses:      list of dicts, one per company: {ticker, conviction,
                     st_event_conv, thesis, key_events}
        rationale:   PM rationale string
        prices:      dict[ticker -> float] current prices
        run_number:  sequential run counter
    """
    if not config.LIVE_PERFORMANCE_SHEET_ID:
        print(f'  [live_sheets] No LIVE_PERFORMANCE_SHEET_ID set — skipping Sheets write for {profile}')
        return

    gc = get_gspread_client()
    sh = _with_retry(lambda: gc.open_by_key(config.LIVE_PERFORMANCE_SHEET_ID),
                     f'open_perf_sheet_{profile}')

    try:
        ws = sh.worksheet(profile)
    except gspread.WorksheetNotFound:
        label = config.LIVE_STRATEGIES.get(profile, {}).get('label', profile)
        ws = _with_retry(lambda: sh.add_worksheet(title=profile, rows=500, cols=20),
                         f'create_tab_{profile}')
        _scaffold_strategy_tab(ws, profile, label)

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    # holdings may be list[dict] (from get_portfolio_status) or dict[ticker->shares]
    holdings_raw = nav_row.get('holdings', {})
    if isinstance(holdings_raw, list):
        holdings = {h['ticker']: h['shares'] for h in holdings_raw}
    else:
        holdings = holdings_raw
    portfolio_value = nav_row.get('portfolio_value', 1000.0)
    return_pct = nav_row.get('return_pct', 0.0)
    cash = nav_row.get('cash', 0.0)

    # ── Section A: overwrite current portfolio (rows 4-8) ─────────────────────
    port_rows = []
    total_val = portfolio_value if portfolio_value else 1.0
    for ticker in TICKERS:
        shares = holdings.get(ticker, 0.0)
        price = prices.get(ticker, 0.0)
        value = shares * price
        weight = (value / total_val * 100) if total_val else 0.0
        port_rows.append([ticker, round(shares, 4), round(price, 2),
                          round(value, 2), round(weight, 2)])
    _with_retry(lambda: ws.update('A4', port_rows), f'write_portfolio_{profile}')

    # ── Section B: append NAV row ──────────────────────────────────────────────
    # Read from first data row (skip header at _SEC_B_ROW+1) so nav_data[i] == sheet row _SEC_B_ROW+2+i
    nav_data = _get_all_values(ws, f'A{_SEC_B_ROW + 2}', 500)
    next_nav_row = _SEC_B_ROW + 2
    for i, row in enumerate(nav_data):
        if not any(cell for cell in row):
            next_nav_row = _SEC_B_ROW + 2 + i
            break
    else:
        next_nav_row = _SEC_B_ROW + 2 + len(nav_data)

    nav_entry = [
        now_str,
        round(holdings.get('NVDA', 0) * prices.get('NVDA', 0), 2),
        round(holdings.get('CDNS', 0) * prices.get('CDNS', 0), 2),
        round(holdings.get('CRWV', 0) * prices.get('CRWV', 0), 2),
        round(holdings.get('TSM', 0) * prices.get('TSM', 0), 2),
        round(holdings.get('ASML', 0) * prices.get('ASML', 0), 2),
        round(cash, 2),
        round(portfolio_value, 2),
        round(return_pct, 4),
    ]
    _with_retry(lambda: ws.update(f'A{next_nav_row}', [nav_entry]), f'append_nav_{profile}')

    # ── Section C: overwrite agent theses (rows SEC_C_ROW+2 to +8) ────────────
    thesis_rows = []
    for t in theses:
        thesis_rows.append([
            t.get('ticker', ''),
            round(t.get('conviction', 0), 2),
            round(t.get('st_event_conv', 0), 2),
            str(t.get('thesis', ''))[:200],
            str(t.get('key_events', ''))[:200],
        ])
    if thesis_rows:
        _with_retry(lambda: ws.update(f'A{_SEC_C_ROW + 2}', thesis_rows),
                    f'write_theses_{profile}')

    # ── Section D: append run log row ─────────────────────────────────────────
    # Read from first data row (skip header at _SEC_D_ROW+1) so run_data[i] == sheet row _SEC_D_ROW+2+i
    run_data = _get_all_values(ws, f'A{_SEC_D_ROW + 2}', 200)
    next_run_row = _SEC_D_ROW + 2
    for i, row in enumerate(run_data):
        if not any(cell for cell in row):
            next_run_row = _SEC_D_ROW + 2 + i
            break
    else:
        next_run_row = _SEC_D_ROW + 2 + len(run_data)

    run_entry = [
        run_number,
        now_str,
        allocation.get('NVDA', 0),
        allocation.get('CDNS', 0),
        allocation.get('CRWV', 0),
        allocation.get('TSM', 0),
        allocation.get('ASML', 0),
        str(rationale)[:300],
    ]
    _with_retry(lambda: ws.update(f'A{next_run_row}', [run_entry]), f'append_runlog_{profile}')

    print(f'  [live_sheets] Updated {profile} tab (run #{run_number}, NAV=${portfolio_value:.2f})')


def write_dashboard(all_nav: dict, spy_value: Optional[float] = None) -> None:
    """
    Refresh the Dashboard tab summary rows and append a time-series row.

    Args:
        all_nav:   dict[profile -> dict] from get_portfolio_status() for each profile
        spy_value: current SPY portfolio value (mark-to-market from $1000 start)
    """
    if not config.LIVE_PERFORMANCE_SHEET_ID:
        return

    gc = get_gspread_client()
    sh = _with_retry(lambda: gc.open_by_key(config.LIVE_PERFORMANCE_SHEET_ID),
                     'open_perf_sheet_dashboard')
    ws = sh.worksheet('Dashboard')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Update "Last updated" cell
    _with_retry(lambda: ws.update('B2', [[now_str]]), 'dashboard_timestamp')

    # ── SPY: compute $1000-scaled portfolio value ─────────────────────────────
    # K2 stores the base SPY price recorded at experiment start.
    # spy_value here is the raw current SPY price (from yfinance).
    spy_portfolio_value: Optional[float] = None
    spy_ret: float | str = ''
    if spy_value:
        try:
            raw_k2 = ws.acell('K2').value
            base = float(str(raw_k2).replace(',', '.')) if raw_k2 else None
        except Exception:
            base = None

        if not base:
            # First run — record current price as base; return = 0%
            base = spy_value
            _with_retry(lambda: ws.update('K2', [[round(base, 4)]]), 'set_spy_base')

        spy_portfolio_value = round((spy_value / base) * 1000, 2)
        spy_ret = round((spy_portfolio_value / 1000 - 1) * 100, 4)

    # Update summary rows (A5 = SPY, A6-A9 = live strategies)
    spy_row_vals = [['SPY', 'Buy & Hold', '—', 1000,
                     spy_portfolio_value if spy_portfolio_value is not None else '',
                     spy_ret, '—', now_str]]
    _with_retry(lambda: ws.update('A5', spy_row_vals), 'dashboard_spy_row')

    strategy_rows = []
    for i, (profile, cfg) in enumerate(config.LIVE_STRATEGIES.items()):
        nav = all_nav.get(profile, {})
        cur_val = nav.get('portfolio_value', '')
        ret_pct = nav.get('return_pct', '')
        n_runs = nav.get('trades_count', 0)
        last_run = nav.get('last_date', '')
        strategy_rows.append([
            profile, cfg['label'], cfg['lookback_hours'], 1000,
            round(cur_val, 2) if cur_val else '',
            round(ret_pct * 100, 4) if ret_pct else '',
            n_runs,
            str(last_run),
        ])
    _with_retry(lambda: ws.update('A6', strategy_rows), 'dashboard_strategy_rows')

    # Append time-series row
    ts_data = _get_all_values(ws, f'A{_DASHBOARD_TIMESERIES_HEADER_ROW + 1}', 500)
    next_ts_row = _DASHBOARD_TIMESERIES_HEADER_ROW + 1
    for i, row in enumerate(ts_data):
        if not any(cell for cell in row):
            next_ts_row = _DASHBOARD_TIMESERIES_HEADER_ROW + 1 + i
            break
    else:
        next_ts_row = _DASHBOARD_TIMESERIES_HEADER_ROW + 1 + len(ts_data)

    ts_entry = [
        now_str,
        spy_portfolio_value if spy_portfolio_value is not None else '',
    ] + [
        round(all_nav.get(p, {}).get('portfolio_value', ''), 2)
        if all_nav.get(p, {}).get('portfolio_value') else ''
        for p in config.LIVE_STRATEGIES
    ]
    _with_retry(lambda: ws.update(f'A{next_ts_row}', [ts_entry]), 'dashboard_timeseries')
    print(f'  [live_sheets] Dashboard updated')


# ── Live state reader (for cloud/LangGraph Platform runs) ─────────────────────

def read_current_holdings(profile: str) -> dict:
    """
    Read current portfolio state from Section A of a strategy tab.

    Returns dict with keys:
        holdings: dict[ticker -> shares]
        portfolio_value: float (mark-to-market from Section A values)
        run_count: int (number of rows in Section D run log)
    """
    if not config.LIVE_PERFORMANCE_SHEET_ID:
        return {'holdings': {}, 'portfolio_value': 0.0, 'run_count': 0}

    try:
        gc = get_gspread_client()
        sh = _with_retry(lambda: gc.open_by_key(config.LIVE_PERFORMANCE_SHEET_ID),
                         f'read_holdings_{profile}')
        ws = sh.worksheet(profile)

        # Section A rows 4-8: Ticker | Shares | Price | Value | Weight
        port_data = _get_all_values(ws, 'A4', 10)
        holdings = {}
        portfolio_value = 0.0
        for row in port_data:
            if not row or not row[0]:
                continue
            ticker = str(row[0]).strip()
            if ticker not in TICKERS:
                continue
            shares = float(row[1]) if len(row) > 1 and row[1] else 0.0
            value = float(row[3]) if len(row) > 3 and row[3] else 0.0
            holdings[ticker] = shares
            portfolio_value += value

        # Count run log rows for run_count
        run_data = _get_all_values(ws, f'A{_SEC_D_ROW + 2}', 200)
        run_count = sum(1 for r in run_data if any(cell for cell in r))

        return {'holdings': holdings, 'portfolio_value': portfolio_value, 'run_count': run_count}

    except Exception as e:
        print(f'  [live_sheets] read_current_holdings({profile}) failed: {e}')
        return {'holdings': {}, 'portfolio_value': 0.0, 'run_count': 0}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_all_values(ws: gspread.Worksheet, start: str, max_rows: int) -> list:
    """Read a block of cells starting at `start` for up to max_rows rows."""
    try:
        return ws.get(start) or []
    except Exception:
        return []


def get_sheet_url() -> str:
    """Return the URL of the performance sheet, or empty string if not configured."""
    sid = config.LIVE_PERFORMANCE_SHEET_ID
    if not sid:
        return ''
    return f'https://docs.google.com/spreadsheets/d/{sid}'
