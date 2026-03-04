"""
Google Sheets client for the Agent Alpha pipeline.

Provides read/write access to the Agent View and Agent Documentation tabs
on each company's Google Sheet. Replaces local JSON persistence for analyst views.

Usage:
    from sheets_client import load_analyst_view, write_agent_documentation, write_agent_view_multiples
    view = load_analyst_view('NVDA')
    write_agent_documentation('NVDA', updated_view)
    write_agent_view_multiples('NVDA', {'ev_rev_2026': 25.0, ...})
"""

import base64
import json
import os
import random
import re
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Optional

import gspread

import config

# ── Rate Limiting ──────────────────────────────────────────────────────────
# Google Sheets API allows 60 read requests per minute per user.
# With 5 companies × multiple reads, we can hit this easily.

_SHEETS_RETRY_MAX = 3
_SHEETS_RETRY_BASE_DELAY = 5  # seconds


def _with_retry(fn, label: str = "sheets"):
    """Execute a Sheets API call with exponential backoff on 429 errors."""
    for attempt in range(_SHEETS_RETRY_MAX):
        try:
            return fn()
        except gspread.exceptions.APIError as e:
            if '429' in str(e) and attempt < _SHEETS_RETRY_MAX - 1:
                delay = _SHEETS_RETRY_BASE_DELAY * (2 ** attempt) + random.uniform(0, 2)
                print(f"  [sheets_client] Rate limited on {label}, retrying in {delay:.0f}s...")
                time.sleep(delay)
            else:
                raise

# ── Authentication ────────────────────────────────────────────────────────

_gc_cache: Optional[gspread.Client] = None


def get_gspread_client() -> gspread.Client:
    """Return a cached gspread client, authenticating from env or local creds file."""
    global _gc_cache
    if _gc_cache is not None:
        return _gc_cache

    # Try base64-encoded credentials from env first (for LangSmith Cloud)
    b64 = os.getenv('GOOGLE_CREDENTIALS_B64', '')
    if b64:
        creds_dict = json.loads(base64.b64decode(b64))
        _gc_cache = gspread.service_account_from_dict(creds_dict)
        return _gc_cache

    # Fallback to local credentials file
    creds_path = config._PROJECT_ROOT / 'credentials' / 'google_sheets_sa.json'
    if creds_path.exists():
        creds_dict = json.loads(creds_path.read_text())
        _gc_cache = gspread.service_account_from_dict(creds_dict)
        return _gc_cache

    raise RuntimeError(
        "No Google credentials found. Set GOOGLE_CREDENTIALS_B64 env var "
        "or place credentials/google_sheets_sa.json in the project root."
    )


def _get_worksheet(ticker: str, tab_name: str) -> gspread.Worksheet:
    """Open a specific worksheet tab for a ticker."""
    sheet_id = config.GOOGLE_SHEET_IDS.get(ticker)
    if not sheet_id:
        raise ValueError(f"No Google Sheet ID configured for {ticker}")
    gc = get_gspread_client()
    sh = gc.open_by_key(sheet_id)
    return sh.worksheet(tab_name)


# ── Agent View tab row mappings ───────────────────────────────────────────
# Standard layout (NVDA, CDNS, CRWV, ASML):
#   C5=stock price, C6=shares, D11:E11=revenue, D12:E12=ebitda,
#   D13:E13=EPS, D14:E14=net income, C18=debt, C19=cash, C20=net debt,
#   D27:E27=EV/Rev, D28:E28=EV/EBITDA, D29:E29=P/E,
#   D34:E36=implied prices, C40=avg implied, C42=upside
#
# TSM layout (shifted +1 for FX rate row):
#   C5=stock price, C6=shares, C7=FX rate, D12:E12=revenue, D13:E13=ebitda,
#   D14:E14=EPS, D15:E15=net income, C19=debt, C20=cash, C21=net debt,
#   D28:E28=EV/Rev, D29:E29=EV/EBITDA, D30:E30=P/E,
#   D35:E37=implied prices, C41=avg implied, C43=upside

_AGENT_VIEW_LAYOUT = {
    'standard': {
        'stock_price': 'C5', 'shares': 'C6',
        'rev_26': 'D11', 'rev_27': 'E11',
        'ebitda_26': 'D12', 'ebitda_27': 'E12',
        'eps_26': 'D13', 'eps_27': 'E13',
        'ni_26': 'D14', 'ni_27': 'E14',
        'debt': 'C18', 'cash': 'C19', 'net_debt': 'C20',
        'mkt_cap': 'C21', 'ev': 'C22',
        'ev_rev_26': 'D27', 'ev_rev_27': 'E27',
        'ev_ebitda_26': 'D28', 'ev_ebitda_27': 'E28',
        'pe_26': 'D29', 'pe_27': 'E29',
        'implied_ev_rev_26': 'D34', 'implied_ev_rev_27': 'E34',
        'implied_ev_ebitda_26': 'D35', 'implied_ev_ebitda_27': 'E35',
        'implied_pe_26': 'D36', 'implied_pe_27': 'E36',
        'avg_implied': 'C40', 'current_price': 'C41', 'upside': 'C42',
    },
    'tsm': {
        'stock_price': 'C5', 'shares': 'C6', 'fx_rate': 'C7',
        'rev_26': 'D12', 'rev_27': 'E12',
        'ebitda_26': 'D13', 'ebitda_27': 'E13',
        'eps_26': 'D14', 'eps_27': 'E14',
        'ni_26': 'D15', 'ni_27': 'E15',
        'debt': 'C19', 'cash': 'C20', 'net_debt': 'C21',
        'mkt_cap': 'C22', 'ev': 'C23',
        'ev_rev_26': 'D28', 'ev_rev_27': 'E28',
        'ev_ebitda_26': 'D29', 'ev_ebitda_27': 'E29',
        'pe_26': 'D30', 'pe_27': 'E30',
        'implied_ev_rev_26': 'D35', 'implied_ev_rev_27': 'E35',
        'implied_ev_ebitda_26': 'D36', 'implied_ev_ebitda_27': 'E36',
        'implied_pe_26': 'D37', 'implied_pe_27': 'E37',
        'avg_implied': 'C41', 'current_price': 'C42', 'upside': 'C43',
    },
}


# ── Driver-to-Model-tab cell mapping ─────────────────────────────────────
# Maps proposed_driver_deltas keys to Google Sheets Model tab rows + period columns.
# Only companies with Excel-backed driver cells are included.

_DRIVER_MODEL_CONFIGS = {
    'NVDA': {
        'period_columns': OrderedDict([
            ('Q4-26', 'BW'), ('Q1-27', 'BY'), ('Q2-27', 'BZ'),
            ('Q3-27', 'CA'), ('Q4-27', 'CB'),
            ('FY2028', 'CD'), ('FY2029', 'CE'), ('FY2030', 'CF'),
        ]),
        'drivers': OrderedDict([
            ('datacenter_growth', 24),
            ('gaming_growth', 9),
            ('automotive_growth', 28),
            ('proviz_growth', 13),
            ('oem_growth', 32),
            ('gm_improvement_bps', 62),
            ('rd_improvement_bps', 77),
            ('sga_improvement_bps', 92),
        ]),
    },
    'CDNS': {
        'period_columns': OrderedDict([
            ('Q3-26', 'BV'), ('Q4-26', 'BW'),
            ('FY2027', 'BY'), ('FY2028', 'BZ'), ('FY2029', 'CA'),
        ]),
        'drivers': OrderedDict([
            ('core_eda_growth', 14),
            ('system_interconnect_growth', 17),
            ('ip_growth', 19),
            ('gm_improvement_bps', 49),
            ('rd_improvement_bps', 62),
            ('ga_improvement_bps', 75),
            ('sm_improvement_bps', 88),
        ]),
    },
}

# Delta grid layout in Agent Documentation tab
_DELTA_GRID_HEADER_ROW = 65
_DELTA_GRID_PERIOD_ROW = 67
_DELTA_GRID_DATA_START_ROW = 68


def _col_to_index(col_str: str) -> int:
    """Convert column letter(s) to 0-based index. A=0, B=1, ..., Z=25, AA=26."""
    idx = 0
    for c in col_str.upper():
        idx = idx * 26 + (ord(c) - ord('A') + 1)
    return idx - 1


def _layout_for(ticker: str) -> dict:
    return _AGENT_VIEW_LAYOUT['tsm'] if ticker == 'TSM' else _AGENT_VIEW_LAYOUT['standard']


def _safe_float(val, default=0.0, is_pct=False):
    """Parse a cell value to float, handling currency strings, percentages, 'x' suffix, etc."""
    if val is None or val == '' or val == 'N/A':
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    # Detect percentage format
    pct = is_pct or s.endswith('%')
    # Strip common formatting characters
    s = s.replace('$', '').replace(',', '').replace('%', '').replace('x', '').strip()
    try:
        v = float(s)
        return v / 100.0 if pct else v
    except (ValueError, TypeError):
        return default


# ── Reading ───────────────────────────────────────────────────────────────

def read_agent_view(ticker: str) -> Optional[dict]:
    """Read the Agent View tab and return a dict with financials, multiples, and implied prices."""
    try:
        ws = _get_worksheet(ticker, 'Agent View')
        layout = _layout_for(ticker)

        # Batch-read all cells we need (with rate-limit retry)
        cell_refs = list(layout.values())
        results = _with_retry(lambda: ws.batch_get(cell_refs), f"read_agent_view({ticker})")

        vals = {}
        for key, cell_ref in layout.items():
            idx = cell_refs.index(cell_ref)
            raw = results[idx]
            vals[key] = raw[0][0] if raw and raw[0] else None

        return {
            'stock_price': _safe_float(vals.get('stock_price')),
            'shares': _safe_float(vals.get('shares')),
            'model_financials': {
                'rev_2026': _safe_float(vals.get('rev_26')),
                'rev_2027': _safe_float(vals.get('rev_27')),
                'ebitda_2026': _safe_float(vals.get('ebitda_26')),
                'ebitda_2027': _safe_float(vals.get('ebitda_27')),
                'eps_2026': _safe_float(vals.get('eps_26')),
                'eps_2027': _safe_float(vals.get('eps_27')),
            },
            'ev_bridge': {
                'debt': _safe_float(vals.get('debt')),
                'cash': _safe_float(vals.get('cash')),
                'net_debt': _safe_float(vals.get('net_debt')),
                'market_cap': _safe_float(vals.get('mkt_cap')),
                'enterprise_value': _safe_float(vals.get('ev')),
            },
            'suggested_multiples': {
                'ev_rev_2026': _safe_float(vals.get('ev_rev_26')),
                'ev_rev_2027': _safe_float(vals.get('ev_rev_27')),
                'ev_ebitda_2026': _safe_float(vals.get('ev_ebitda_26')),
                'ev_ebitda_2027': _safe_float(vals.get('ev_ebitda_27')),
                'pe_2026': _safe_float(vals.get('pe_26')),
                'pe_2027': _safe_float(vals.get('pe_27')),
            },
            'multiples_implied_prices': {
                'ev_rev_2026': _safe_float(vals.get('implied_ev_rev_26')),
                'ev_rev_2027': _safe_float(vals.get('implied_ev_rev_27')),
                'ev_ebitda_2026': _safe_float(vals.get('implied_ev_ebitda_26')),
                'ev_ebitda_2027': _safe_float(vals.get('implied_ev_ebitda_27')),
                'pe_2026': _safe_float(vals.get('implied_pe_26')),
                'pe_2027': _safe_float(vals.get('implied_pe_27')),
            },
            'avg_implied_price': _safe_float(vals.get('avg_implied')),
            'current_price': _safe_float(vals.get('current_price')),
            'upside': _safe_float(vals.get('upside')),
        }
    except Exception as e:
        print(f"  [sheets_client] read_agent_view({ticker}) failed: {e}")
        return None


def read_agent_documentation(ticker: str) -> Optional[dict]:
    """Read the Agent Documentation tab and return a dict with qualitative data."""
    try:
        ws = _get_worksheet(ticker, 'Agent Documentation')

        # Batch-read all cells (with rate-limit retry)
        ranges = (
            ['C5', 'C6', 'C7', 'C8', 'C9', 'C10']      # thesis & conviction
            + [f'C{r}' for r in range(14, 19)]             # drivers (C14-C18)
            + [f'C{r}' for r in range(22, 27)]             # risks (C22-C26)
            + [f'A{r}' for r in range(31, 41)]             # delta drivers (A31-A40)
            + [f'B{r}' for r in range(31, 41)]             # delta periods (B31-B40)
            + [f'C{r}' for r in range(31, 41)]             # delta values (C31-C40)
            + ['C44']                                       # challenge
            + [f'A{r}' for r in range(48, 63)]             # headlines (A48-A62)
        )
        results = _with_retry(lambda: ws.batch_get(ranges), f"read_agent_documentation({ticker})")

        def _val(idx):
            r = results[idx] if idx < len(results) else []
            return r[0][0] if r and r[0] else ''

        # Parse fields
        last_updated = _val(0)
        conviction = _safe_float(_val(1))
        st_conv = _safe_float(_val(2))
        thesis = _val(3)
        recovery = _val(4)
        rationale = _val(5)

        # Drivers (indices 6-10)
        drivers = [_val(6 + i) for i in range(5) if _val(6 + i)]

        # Risks (indices 11-15)
        risks = [_val(11 + i) for i in range(5) if _val(11 + i)]

        # Driver deltas (indices 16-25=drivers, 26-35=periods, 36-45=values)
        deltas = {}
        for i in range(10):
            drv = _val(16 + i)
            per = _val(26 + i)
            val = _val(36 + i)
            if drv and per and val:
                deltas.setdefault(drv, {})[per] = _safe_float(val)

        # Challenge (index 46)
        challenge = _val(46)

        # Headlines (indices 47-61)
        headlines = [_val(47 + i) for i in range(15) if _val(47 + i)]

        return {
            'ticker': ticker,
            'last_updated': last_updated,
            'summary': thesis,
            'conviction': conviction,
            'short_term_event_conviction': st_conv,
            'recovery_thesis': recovery,
            'rationale_for_deltas': rationale,
            'key_drivers': drivers,
            'key_risks': risks,
            'proposed_driver_deltas': deltas,
            'challenge_to_others': challenge,
            'seen_headlines': headlines,
        }
    except Exception as e:
        print(f"  [sheets_client] read_agent_documentation({ticker}) failed: {e}")
        return None


def load_analyst_view(ticker: str) -> Optional[dict]:
    """Combined read: Agent View + Agent Documentation → single dict.

    Drop-in replacement for dcf_grounding.load_analyst_view().
    """
    doc = read_agent_documentation(ticker)
    av = read_agent_view(ticker)

    if doc is None and av is None:
        return None

    combined = doc or {}
    if av:
        combined['model_financials'] = av.get('model_financials', {})
        combined['suggested_multiples'] = av.get('suggested_multiples', {})
        combined['multiples_implied_prices'] = av.get('multiples_implied_prices', {})
        combined['current_price'] = av.get('current_price', 0)
        combined['avg_implied_price'] = av.get('avg_implied_price', 0)
        combined['upside'] = av.get('upside', 0)
        combined['ev_bridge'] = av.get('ev_bridge', {})

    return combined


# ── Writing ───────────────────────────────────────────────────────────────

def write_agent_documentation(ticker: str, view: dict) -> None:
    """Write qualitative analyst data to the Agent Documentation tab."""
    try:
        ws = _get_worksheet(ticker, 'Agent Documentation')

        now = datetime.now().isoformat()
        drivers = view.get('key_drivers', [])
        risks = view.get('key_risks', [])
        deltas = view.get('proposed_driver_deltas', {})
        headlines = view.get('seen_headlines', [])

        cells = [
            {'range': 'C5', 'values': [[now]]},
            {'range': 'C6', 'values': [[view.get('conviction', '')]]},
            {'range': 'C7', 'values': [[view.get('short_term_event_conviction', '')]]},
            {'range': 'C8', 'values': [[view.get('summary', '')]]},
            {'range': 'C9', 'values': [[view.get('recovery_thesis', '')]]},
            {'range': 'C10', 'values': [[view.get('rationale_for_deltas', '')]]},
        ]

        # Drivers (C14-C18) — clear all then fill
        for i in range(5):
            val = drivers[i] if i < len(drivers) else ''
            cells.append({'range': f'C{14 + i}', 'values': [[val]]})

        # Risks (C22-C26)
        for i in range(5):
            val = risks[i] if i < len(risks) else ''
            cells.append({'range': f'C{22 + i}', 'values': [[val]]})

        # Driver deltas (A31:C40)
        delta_rows = []
        for drv, periods in deltas.items():
            if isinstance(periods, dict):
                for period, value in periods.items():
                    delta_rows.append((drv, period, value))

        for i in range(10):
            row = 31 + i
            if i < len(delta_rows):
                d, p, v = delta_rows[i]
                cells.append({'range': f'A{row}', 'values': [[d]]})
                cells.append({'range': f'B{row}', 'values': [[p]]})
                cells.append({'range': f'C{row}', 'values': [[v]]})
            else:
                cells.append({'range': f'A{row}', 'values': [['']]})
                cells.append({'range': f'B{row}', 'values': [['']]})
                cells.append({'range': f'C{row}', 'values': [['']]})

        # Challenge (C44)
        cells.append({'range': 'C44', 'values': [[view.get('challenge_to_others', '')]]})

        # Headlines (A48-A62)
        for i in range(15):
            val = headlines[i] if i < len(headlines) else ''
            cells.append({'range': f'A{48 + i}', 'values': [[val]]})

        ws.batch_update(cells, value_input_option='USER_ENTERED')
        print(f"  [sheets_client] Updated Agent Documentation for {ticker}")

    except Exception as e:
        print(f"  [sheets_client] write_agent_documentation({ticker}) failed: {e}")


def write_agent_view_multiples(ticker: str, multiples: dict) -> None:
    """Update the target multiples (hardcoded blue inputs) in the Agent View tab.

    Args:
        ticker: Company ticker.
        multiples: Dict with keys ev_rev_2026, ev_rev_2027, ev_ebitda_2026,
                   ev_ebitda_2027, pe_2026, pe_2027.
    """
    try:
        ws = _get_worksheet(ticker, 'Agent View')
        layout = _layout_for(ticker)

        cells = []
        mapping = {
            'ev_rev_2026': 'ev_rev_26',
            'ev_rev_2027': 'ev_rev_27',
            'ev_ebitda_2026': 'ev_ebitda_26',
            'ev_ebitda_2027': 'ev_ebitda_27',
            'pe_2026': 'pe_26',
            'pe_2027': 'pe_27',
        }

        for mult_key, layout_key in mapping.items():
            val = multiples.get(mult_key)
            if val is not None:
                cell_ref = layout.get(layout_key)
                if cell_ref:
                    cells.append({'range': cell_ref, 'values': [[float(val)]]})

        if cells:
            ws.batch_update(cells, value_input_option='USER_ENTERED')
            print(f"  [sheets_client] Updated Agent View multiples for {ticker} ({len(cells)} cells)")

    except Exception as e:
        print(f"  [sheets_client] write_agent_view_multiples({ticker}) failed: {e}")


# ── Model Tab Driver Delta Formulas ──────────────────────────────────────

def write_driver_deltas_to_model(ticker: str, deltas: dict) -> None:
    """Write driver delta formulas to the Model tab.

    For each driver+period delta:
      1. Writes the delta value to a fixed cell in the Agent Documentation tab
         (a structured delta grid starting at row 65).
      2. Writes a formula to the corresponding Model tab cell:
             =<baseline_value> + 'Agent Documentation'!<delta_cell>
         On subsequent runs, only the delta cell is updated; the formula persists.
      3. Formats the Model tab formula cells with green text (cross-tab reference).

    Only supported for companies with Excel-backed driver cells (NVDA, CDNS).
    Other tickers are silently skipped.

    Args:
        ticker: Company ticker (e.g., 'NVDA').
        deltas: Dict of driver_name -> {period: delta_value}.
    """
    ticker = ticker.upper()
    cfg = _DRIVER_MODEL_CONFIGS.get(ticker)
    if not cfg:
        print(f"  [sheets_client] No Model tab driver config for {ticker}, skipping delta formulas")
        return

    sheet_id = config.GOOGLE_SHEET_IDS.get(ticker)
    if not sheet_id:
        return

    gc = get_gspread_client()
    spreadsheet = _with_retry(lambda: gc.open_by_key(sheet_id), f"open_{ticker}")
    doc_ws = _with_retry(lambda: spreadsheet.worksheet('Agent Documentation'), f"doc_ws_{ticker}")
    model_ws = _with_retry(lambda: spreadsheet.worksheet('Model'), f"model_ws_{ticker}")

    drivers = cfg['drivers']           # OrderedDict: driver_name → model_row
    periods = cfg['period_columns']    # OrderedDict: period_label → model_col
    driver_list = list(drivers.keys())
    period_list = list(periods.keys())

    # ── Ensure Agent Documentation tab is large enough for the delta grid ──
    needed_rows = _DELTA_GRID_DATA_START_ROW + len(driver_list)
    needed_cols = 2 + len(period_list) + 1  # A, B, then C..J for periods
    if doc_ws.row_count < needed_rows or doc_ws.col_count < needed_cols:
        new_rows = max(doc_ws.row_count, needed_rows)
        new_cols = max(doc_ws.col_count, needed_cols)
        _with_retry(lambda: doc_ws.resize(rows=new_rows, cols=new_cols), f"resize_doc_{ticker}")

    # ── Step 1: Write delta grid to Agent Documentation tab ──
    doc_cells = []

    # Section header
    doc_cells.append({
        'range': f'A{_DELTA_GRID_HEADER_ROW}',
        'values': [['DRIVER DELTA GRID (Model Tab Links)']],
    })

    # Period headers row: A=Driver, C..=period labels
    header_row = ['Driver', ''] + period_list
    doc_cells.append({
        'range': f'A{_DELTA_GRID_PERIOD_ROW}',
        'values': [header_row],
    })

    # Driver rows with delta values (default to 0 for unspecified periods)
    for i, driver_name in enumerate(driver_list):
        row_num = _DELTA_GRID_DATA_START_ROW + i
        driver_deltas = deltas.get(driver_name, {})
        row_vals = [driver_name, '']
        for period in period_list:
            val = driver_deltas.get(period, 0)
            row_vals.append(val if val else 0)
        doc_cells.append({
            'range': f'A{row_num}',
            'values': [row_vals],
        })

    _with_retry(
        lambda: doc_ws.batch_update(doc_cells, value_input_option='RAW'),
        f"write_delta_grid_{ticker}",
    )

    # ── Step 2: Format delta grid (blue text for agent-written values) ──
    doc_sheet_id = doc_ws.id
    fmt_requests = []

    # Section header: dark blue bold
    fmt_requests.append({
        'repeatCell': {
            'range': {
                'sheetId': doc_sheet_id,
                'startRowIndex': _DELTA_GRID_HEADER_ROW - 1,
                'endRowIndex': _DELTA_GRID_HEADER_ROW,
                'startColumnIndex': 0,
                'endColumnIndex': 5,
            },
            'cell': {'userEnteredFormat': {'textFormat': {
                'bold': True,
                'foregroundColorStyle': {'rgbColor': {'red': 0.1, 'green': 0.2, 'blue': 0.5}},
            }}},
            'fields': 'userEnteredFormat.textFormat',
        }
    })

    # Delta value cells: blue text
    for i in range(len(driver_list)):
        r = _DELTA_GRID_DATA_START_ROW + i
        fmt_requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': doc_sheet_id,
                    'startRowIndex': r - 1,
                    'endRowIndex': r,
                    'startColumnIndex': 2,  # Column C
                    'endColumnIndex': 2 + len(period_list),
                },
                'cell': {'userEnteredFormat': {'textFormat': {
                    'foregroundColorStyle': {'rgbColor': {'red': 0, 'green': 0, 'blue': 1.0}},
                }}},
                'fields': 'userEnteredFormat.textFormat',
            }
        })

    if fmt_requests:
        _with_retry(
            lambda: spreadsheet.batch_update({'requests': fmt_requests}),
            f"fmt_delta_grid_{ticker}",
        )

    # ── Step 3: Read current Model tab values and write formulas ──
    # Build list of (model_cell, doc_cell_ref, driver, period)
    cell_info = []
    for i, driver_name in enumerate(driver_list):
        model_row = drivers[driver_name]
        doc_row = _DELTA_GRID_DATA_START_ROW + i
        for j, period in enumerate(period_list):
            model_col = periods[period]
            model_cell = f'{model_col}{model_row}'
            doc_col = chr(ord('C') + j)
            doc_cell = f'{doc_col}{doc_row}'
            cell_info.append((model_cell, doc_cell, driver_name, period))

    # Batch-read current Model tab formulas
    read_ranges = [ci[0] for ci in cell_info]
    current_formulas = _with_retry(
        lambda: model_ws.batch_get(read_ranges, value_render_option='FORMULA'),
        f"read_model_formulas_{ticker}",
    )
    current_values = _with_retry(
        lambda: model_ws.batch_get(read_ranges, value_render_option='UNFORMATTED_VALUE'),
        f"read_model_values_{ticker}",
    )

    # Build Model tab formula updates + formatting list
    model_updates = []
    green_cells = []   # (row_0idx, col_0idx) for green formatting
    _FORMULA_PATTERN = re.compile(r"^=([+-]?\d+(?:\.\d+)?)\+'Agent Documentation'!")

    for idx, (model_cell, doc_cell, driver_name, period) in enumerate(cell_info):
        raw_formula = None
        raw_value = None

        if idx < len(current_formulas):
            r = current_formulas[idx]
            raw_formula = r[0][0] if r and r[0] else None
        if idx < len(current_values):
            r = current_values[idx]
            raw_value = r[0][0] if r and r[0] else None

        # Determine baseline: extract from existing link formula or use raw value
        baseline = None
        already_linked = False

        if isinstance(raw_formula, str) and raw_formula.startswith('='):
            m = _FORMULA_PATTERN.match(raw_formula)
            if m:
                baseline = float(m.group(1))
                already_linked = True
            else:
                # Cell has a different formula — don't overwrite it
                print(f"  [sheets_client] Skipping {model_cell}: has non-delta formula")
                continue
        elif raw_value is not None:
            try:
                baseline = float(raw_value)
            except (ValueError, TypeError):
                print(f"  [sheets_client] Skipping {model_cell}: non-numeric value {raw_value!r}")
                continue
        else:
            # Empty cell — skip
            continue

        # Build the formula: =<baseline>+'Agent Documentation'!<doc_cell>
        formula = f"={baseline}+'Agent Documentation'!{doc_cell}"

        # Only write to Model tab if this is the first time (no existing link formula)
        # or if we need to update the doc_cell reference
        if not already_linked:
            model_updates.append({
                'range': model_cell,
                'values': [[formula]],
            })

            # Track for green formatting
            model_row = drivers[driver_name]
            model_col = periods[period]
            green_cells.append((_col_to_index(model_col), model_row - 1))

    # Write formulas to Model tab
    if model_updates:
        _with_retry(
            lambda: model_ws.batch_update(model_updates, value_input_option='USER_ENTERED'),
            f"write_model_formulas_{ticker}",
        )

    # ── Step 4: Format Model tab formula cells with green text ──
    model_sheet_id = model_ws.id
    green_requests = []

    for col_0, row_0 in green_cells:
        green_requests.append({
            'repeatCell': {
                'range': {
                    'sheetId': model_sheet_id,
                    'startRowIndex': row_0,
                    'endRowIndex': row_0 + 1,
                    'startColumnIndex': col_0,
                    'endColumnIndex': col_0 + 1,
                },
                'cell': {'userEnteredFormat': {'textFormat': {
                    'foregroundColorStyle': {'rgbColor': {'red': 0, 'green': 0.498, 'blue': 0}},
                }}},
                'fields': 'userEnteredFormat.textFormat',
            }
        })

    if green_requests:
        _with_retry(
            lambda: spreadsheet.batch_update({'requests': green_requests}),
            f"fmt_model_green_{ticker}",
        )

    total_written = len(model_updates)
    total_delta_only = len(cell_info) - total_written  # cells with existing formulas (only delta updated)
    print(f"  [sheets_client] {ticker} Model tab: {total_written} new formulas written, "
          f"{total_delta_only} existing formula deltas updated")
