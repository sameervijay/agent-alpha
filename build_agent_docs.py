"""
Build "Agent Documentation" tabs on all 5 company Google Sheets.
Pre-populates with data from existing data/analyst_views/{TICKER}_view.json files.
"""
import gspread
import json
import time
from pathlib import Path

CREDS_PATH = 'credentials/google_sheets_sa.json'
VIEWS_DIR = Path('data/analyst_views')

SHEET_IDS = {
    'NVDA': '1PMYaH_sHXOxjAr_zjMWGWNCydl5mPdoVoYIQFKfC2io',
    'TSM':  '1TeUmlVdEJyEu4p24M59wTvJrPC5NHYyUBARAzf8XgsI',
    'CDNS': '14SzOEAAUW3cOs2aiMj0YRGVz13SyeZJa_vQcIYbkrMs',
    'CRWV': '1u8Ds9GrLJZ36eBEGKWUSM-quGoNOlVKZbNHb55iWrqo',
    'ASML': '1flHoFLfiFZGN6cFOsmWps07YpsFOPou-7kOYGchfCAo',
}

COMPANY_NAMES = {
    'NVDA': 'NVIDIA',
    'TSM':  'TSMC',
    'CDNS': 'Cadence Design Systems',
    'CRWV': 'CoreWeave',
    'ASML': 'ASML Holding',
}


def rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}

DARK_BLUE = rgb(31, 56, 100)
WHITE     = rgb(255, 255, 255)
BLUE      = rgb(0, 0, 255)


def cell_range(sid, row, cs, ce=None, re=None):
    return {
        "sheetId": sid,
        "startRowIndex": row,
        "endRowIndex": (re or row) + 1,
        "startColumnIndex": cs,
        "endColumnIndex": (ce or cs) + 1,
    }


def merge_req(sid, row, cs, ce):
    return {"mergeCells": {"range": cell_range(sid, row, cs, ce), "mergeType": "MERGE_ALL"}}


def section_header_reqs(sid, row_0):
    return [
        merge_req(sid, row_0, 0, 4),
        {"repeatCell": {
            "range": cell_range(sid, row_0, 0, 4),
            "cell": {"userEnteredFormat": {
                "backgroundColor": DARK_BLUE,
                "textFormat": {"foregroundColor": WHITE, "bold": True, "fontSize": 11},
                "horizontalAlignment": "LEFT",
                "verticalAlignment": "MIDDLE",
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
        }}
    ]


def load_existing_view(ticker):
    """Load existing analyst view JSON if available."""
    for suffix in ['_view.json', '_thesis.json']:
        path = VIEWS_DIR / f"{ticker}{suffix}"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
    return {}


def build_agent_documentation(gc, ticker, sheet_id):
    company = COMPANY_NAMES.get(ticker, ticker)

    print(f"\n{'='*60}")
    print(f"  Building Agent Documentation for {company} ({ticker})")
    print(f"{'='*60}")

    sh = gc.open_by_key(sheet_id)

    # Delete existing tab if present
    try:
        old = sh.worksheet('Agent Documentation')
        sh.del_worksheet(old)
        print(f"  Deleted existing Agent Documentation tab")
        time.sleep(2)
    except gspread.exceptions.WorksheetNotFound:
        pass

    ws = sh.add_worksheet(title='Agent Documentation', rows=65, cols=5)
    sid = ws.id
    print(f"  Created tab (sheetId={sid})")
    time.sleep(2)

    # Load existing data
    view = load_existing_view(ticker)

    # Extract fields with defaults
    last_updated = view.get('last_updated', '')
    conviction = view.get('conviction', '')
    st_conv = view.get('short_term_event_conviction', '')
    thesis = view.get('summary', '')
    recovery = view.get('recovery_thesis', '')
    rationale = view.get('rationale_for_deltas', '')
    key_drivers = view.get('key_drivers', [])
    key_risks = view.get('key_risks', [])
    deltas = view.get('proposed_driver_deltas', {})
    challenge = view.get('challenge_to_others', '')
    headlines = view.get('seen_headlines', [])

    # Build cells
    cells = [
        # Title
        {'range': 'A1', 'values': [[f'{company} ({ticker}) Agent Documentation']]},

        # THESIS & CONVICTION
        {'range': 'A3', 'values': [['THESIS & CONVICTION']]},
        {'range': 'A5', 'values': [['Last Updated']]},
        {'range': 'C5', 'values': [[last_updated]]},
        {'range': 'A6', 'values': [['Analyst Conviction (0-1)']]},
        {'range': 'C6', 'values': [[conviction]]},
        {'range': 'A7', 'values': [['ST Event Conviction (0-1)']]},
        {'range': 'C7', 'values': [[st_conv]]},
        {'range': 'A8', 'values': [['Investment Thesis']]},
        {'range': 'C8', 'values': [[thesis]]},
        {'range': 'A9', 'values': [['Recovery Thesis']]},
        {'range': 'C9', 'values': [[recovery]]},
        {'range': 'A10', 'values': [['Rationale for Deltas']]},
        {'range': 'C10', 'values': [[rationale]]},

        # KEY DRIVERS
        {'range': 'A12', 'values': [['KEY DRIVERS']]},
    ]

    # Add drivers (rows 14-18)
    for i in range(5):
        row = 14 + i
        val = key_drivers[i] if i < len(key_drivers) else ''
        cells.append({'range': f'C{row}', 'values': [[val]]})
        cells.append({'range': f'A{row}', 'values': [[f'Driver {i+1}']]})

    # KEY RISKS
    cells.append({'range': 'A20', 'values': [['KEY RISKS']]})

    for i in range(5):
        row = 22 + i
        val = key_risks[i] if i < len(key_risks) else ''
        cells.append({'range': f'C{row}', 'values': [[val]]})
        cells.append({'range': f'A{row}', 'values': [[f'Risk {i+1}']]})

    # PROPOSED DRIVER DELTAS
    cells.append({'range': 'A28', 'values': [['PROPOSED DRIVER DELTAS']]})
    cells.append({'range': 'A30', 'values': [['Driver']]})
    cells.append({'range': 'B30', 'values': [['Period']]})
    cells.append({'range': 'C30', 'values': [['Delta']]})

    # Flatten deltas into rows
    delta_rows = []
    for driver, periods in deltas.items():
        if isinstance(periods, dict):
            for period, value in periods.items():
                delta_rows.append((driver, period, value))

    for i in range(10):
        row = 31 + i
        if i < len(delta_rows):
            d, p, v = delta_rows[i]
            cells.append({'range': f'A{row}', 'values': [[d]]})
            cells.append({'range': f'B{row}', 'values': [[p]]})
            cells.append({'range': f'C{row}', 'values': [[v]]})

    # DEBATE & CHALLENGES
    cells.append({'range': 'A42', 'values': [['DEBATE & CHALLENGES']]})
    cells.append({'range': 'A44', 'values': [['Challenge to Others']]})
    cells.append({'range': 'C44', 'values': [[challenge]]})

    # HEADLINES SEEN
    cells.append({'range': 'A46', 'values': [['HEADLINES SEEN']]})

    for i in range(15):
        row = 48 + i
        val = headlines[i] if i < len(headlines) else ''
        if val:
            cells.append({'range': f'A{row}', 'values': [[val]]})

    ws.batch_update(cells, value_input_option='USER_ENTERED')
    print(f"  Populated {len(cells)} cells")
    time.sleep(2)

    # ── Formatting ──
    reqs = []

    # Column widths: A=250, B=80, C=500, D=80, E=80
    for ci, px in [(0, 250), (1, 80), (2, 500), (3, 80), (4, 80)]:
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": ci, "endIndex": ci + 1},
            "properties": {"pixelSize": px}, "fields": "pixelSize"}})

    # Title: merge, bold 14pt
    reqs.append(merge_req(sid, 0, 0, 4))
    reqs.append({"repeatCell": {
        "range": cell_range(sid, 0, 0, 4),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
        "fields": "userEnteredFormat.textFormat"}})

    # Section headers (0-indexed): rows 3,12,20,28,42,46 → 2,11,19,27,41,45
    for r1 in [3, 12, 20, 28, 42, 46]:
        reqs.extend(section_header_reqs(sid, r1 - 1))

    # Bold labels in column A
    bold_rows = [5, 6, 7, 8, 9, 10, 14, 15, 16, 17, 18, 22, 23, 24, 25, 26, 30, 44]
    for r1 in bold_rows:
        reqs.append({"repeatCell": {
            "range": cell_range(sid, r1 - 1, 0, 0),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
            "fields": "userEnteredFormat.textFormat"}})

    # Delta table header row 30: bold
    reqs.append({"repeatCell": {
        "range": cell_range(sid, 29, 0, 2),
        "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
        "fields": "userEnteredFormat.textFormat"}})

    # Blue font for all agent-written values
    blue_ranges = [
        # Thesis & Conviction values
        (4, 2, 2),   # C5
        (5, 2, 2),   # C6
        (6, 2, 2),   # C7
        (7, 2, 2),   # C8
        (8, 2, 2),   # C9
        (9, 2, 2),   # C10
    ]
    # Drivers C14-C18
    for r in range(13, 18):
        blue_ranges.append((r, 2, 2))
    # Risks C22-C26
    for r in range(21, 26):
        blue_ranges.append((r, 2, 2))
    # Delta values A31-C40
    for r in range(30, 40):
        blue_ranges.append((r, 0, 2))
    # Challenge C44
    blue_ranges.append((43, 2, 2))
    # Headlines A48-A62
    for r in range(47, 62):
        blue_ranges.append((r, 0, 0))

    for r0, cs, ce in blue_ranges:
        reqs.append({"repeatCell": {
            "range": cell_range(sid, r0, cs, ce),
            "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": BLUE}}},
            "fields": "userEnteredFormat.textFormat.foregroundColor"}})

    # Conviction fields: 0.00 format
    for r0 in [5, 6]:
        reqs.append({"repeatCell": {
            "range": cell_range(sid, r0, 2, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "0.00"}}},
            "fields": "userEnteredFormat.numberFormat"}})

    # Wrap text for long text cells
    for r0 in [7, 8, 9, 43]:
        reqs.append({"repeatCell": {
            "range": cell_range(sid, r0, 2, 2),
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
            "fields": "userEnteredFormat.wrapStrategy"}})

    sh.batch_update({"requests": reqs})
    print(f"  Applied {len(reqs)} formatting requests")

    print(f"  Done: {company} ({ticker})")
    return True


if __name__ == '__main__':
    creds = json.load(open(CREDS_PATH))
    gc = gspread.service_account_from_dict(creds)

    for i, (ticker, sheet_id) in enumerate(SHEET_IDS.items()):
        if i > 0:
            print(f"\n  Waiting 5s (rate limit)...")
            time.sleep(5)
        try:
            build_agent_documentation(gc, ticker, sheet_id)
        except Exception as e:
            print(f"  ERROR on {ticker}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  ALL DONE!")
    print(f"{'='*60}")
