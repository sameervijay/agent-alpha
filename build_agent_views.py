"""
Build Agent View tabs on NVIDIA, TSM, CDNS, and CRWV Google Sheets.
Each tab pulls key financials from the Model tab, has hardcoded target multiples,
computes implied share prices, and shows a valuation summary.
"""
import gspread
import json
import time

CREDS_PATH = 'credentials/google_sheets_sa.json'

# ── Company Configurations ──────────────────────────────────────────────

CONFIGS = [
    {
        'sheet_id': '1PMYaH_sHXOxjAr_zjMWGWNCydl5mPdoVoYIQFKfC2io',
        'company': 'NVIDIA',
        'ticker': 'NVDA',
        'fy26_col': 'BX',
        'fy27_col': 'CC',
        'bs_col': 'BX',          # Balance sheet col (latest completed FY)
        'revenue_row': 362,
        'ebitda_row': 392,
        'eps_row': 425,           # Non-GAAP EPS WAD
        'net_income_row': 407,    # Non-GAAP Net Income
        'shares_row': 429,        # Shares WAD
        'debt_formula': '=Model!BX988+Model!BX992',       # ST Debt + LT Debt
        'cash_formula': '=-(Model!BX952+Model!BX953)',     # -(Cash + Mkt Securities)
        'multiples': {
            'ev_rev':    (25.0, 22.0),
            'ev_ebitda': (40.0, 35.0),
            'pe':        (50.0, 45.0),
        },
    },
    {
        'sheet_id': '1TeUmlVdEJyEu4p24M59wTvJrPC5NHYyUBARAzf8XgsI',
        'company': 'TSMC',
        'ticker': 'TSM',
        'fy26_col': 'BT',
        'fy27_col': 'BY',
        'bs_col': 'BT',          # FY2026 estimate (calendar year company, FY2025=BO)
        'revenue_row': 369,
        'ebitda_row': 386,
        'eps_row': 414,           # Adj EPS
        'net_income_row': 402,    # Net Income to Common
        'shares_row': 432,        # EoP Shares
        'debt_formula': '=Model!BT481',                    # Total Debt
        'cash_formula': '=-Model!BT478',                   # -Cash
        'multiples': {
            'ev_rev':    (12.0, 10.0),
            'ev_ebitda': (18.0, 15.0),
            'pe':        (25.0, 22.0),
        },
    },
    {
        'sheet_id': '14SzOEAAUW3cOs2aiMj0YRGVz13SyeZJa_vQcIYbkrMs',
        'company': 'Cadence Design Systems',
        'ticker': 'CDNS',
        'fy26_col': 'BX',
        'fy27_col': 'BY',
        'bs_col': 'BX',
        'revenue_row': 454,
        'ebitda_row': 483,
        'eps_row': 516,           # Non-GAAP Adjusted EPS WAD
        'net_income_row': 498,    # Non-GAAP Net Income
        'shares_row': 521,        # Shares WAD
        'debt_formula': '=Model!BX703',                    # Total Debt
        'cash_formula': '=-Model!BX700',                   # -Cash
        'multiples': {
            'ev_rev':    (18.0, 16.0),
            'ev_ebitda': (35.0, 32.0),
            'pe':        (45.0, 40.0),
        },
    },
    {
        'sheet_id': '1u8Ds9GrLJZ36eBEGKWUSM-quGoNOlVKZbNHb55iWrqo',
        'company': 'CoreWeave',
        'ticker': 'CRWV',
        'fy26_col': 'AR',
        'fy27_col': 'AS',
        'bs_col': 'AR',
        'revenue_row': 333,
        'ebitda_row': 364,
        'eps_row': 401,           # Non-GAAP EPS
        'net_income_row': 383,    # Non-GAAP Net Income
        'shares_row': 405,        # Shares WAD
        'debt_formula': '=Model!AR461+Model!AR462',        # ST + LT Debt
        'cash_formula': '=-Model!AR460',                   # -Cash
        'multiples': {
            'ev_rev':    (8.0, 6.0),
            'ev_ebitda': (25.0, 20.0),
            'pe':        (60.0, 50.0),
        },
    },
]


# ── Helper Functions ────────────────────────────────────────────────────

def rgb(r, g, b):
    return {"red": r / 255, "green": g / 255, "blue": b / 255}

DARK_BLUE = rgb(31, 56, 100)
WHITE     = rgb(255, 255, 255)
BLUE      = rgb(0, 0, 255)
GREEN     = rgb(0, 128, 0)


def cell_range(sid, row, col_start, col_end=None, row_end=None):
    return {
        "sheetId": sid,
        "startRowIndex": row,
        "endRowIndex": (row_end or row) + 1,
        "startColumnIndex": col_start,
        "endColumnIndex": (col_end or col_start) + 1,
    }


def merge_req(sid, row, col_start, col_end):
    return {
        "mergeCells": {
            "range": cell_range(sid, row, col_start, col_end),
            "mergeType": "MERGE_ALL"
        }
    }


def section_header_reqs(sid, row_0):
    """Dark blue bg, white bold text, merged A-E for a section header."""
    return [
        merge_req(sid, row_0, 0, 4),
        {
            "repeatCell": {
                "range": cell_range(sid, row_0, 0, 4),
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": DARK_BLUE,
                        "textFormat": {
                            "foregroundColor": WHITE,
                            "bold": True,
                            "fontSize": 11,
                        },
                        "horizontalAlignment": "LEFT",
                        "verticalAlignment": "MIDDLE",
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment,verticalAlignment)"
            }
        }
    ]


# ── Main Build Function ────────────────────────────────────────────────

def build_agent_view(gc, cfg):
    company   = cfg['company']
    ticker    = cfg['ticker']
    fy26      = cfg['fy26_col']
    fy27      = cfg['fy27_col']
    bs        = cfg['bs_col']
    ev_rev    = cfg['multiples']['ev_rev']
    ev_ebitda = cfg['multiples']['ev_ebitda']
    pe        = cfg['multiples']['pe']

    print(f"\n{'='*60}")
    print(f"  Building Agent View for {company} ({ticker})")
    print(f"{'='*60}")

    sh = gc.open_by_key(cfg['sheet_id'])

    # Delete existing Agent View tab if it exists
    try:
        old = sh.worksheet('Agent View')
        sh.del_worksheet(old)
        print(f"  Deleted existing Agent View tab")
        time.sleep(2)
    except gspread.exceptions.WorksheetNotFound:
        pass

    ws = sh.add_worksheet(title='Agent View', rows=45, cols=6)
    sid = ws.id
    print(f"  Created Agent View tab (sheetId={sid})")
    time.sleep(2)

    # ── Populate Cells ──
    cells = [
        # Title
        {'range': 'A1', 'values': [[f'{company} ({ticker}) Agent View']]},

        # MARKET DATA
        {'range': 'A3', 'values': [['MARKET DATA']]},
        {'range': 'A5', 'values': [['Current Stock Price']]},
        {'range': 'C5', 'values': [["='Front Page'!H20"]]},
        {'range': 'A6', 'values': [['Diluted Shares Outstanding (mm)']]},
        {'range': 'C6', 'values': [[f"=Model!{bs}{cfg['shares_row']}"]]},

        # KEY FINANCIALS
        {'range': 'A8',  'values': [['KEY FINANCIALS']]},
        {'range': 'D10', 'values': [['FY2026']]},
        {'range': 'E10', 'values': [['FY2027']]},

        {'range': 'A11', 'values': [['Revenue ($M)']]},
        {'range': 'D11', 'values': [[f"=Model!{fy26}{cfg['revenue_row']}"]]},
        {'range': 'E11', 'values': [[f"=Model!{fy27}{cfg['revenue_row']}"]]},

        {'range': 'A12', 'values': [['EBITDA ($M)']]},
        {'range': 'D12', 'values': [[f"=Model!{fy26}{cfg['ebitda_row']}"]]},
        {'range': 'E12', 'values': [[f"=Model!{fy27}{cfg['ebitda_row']}"]]},

        {'range': 'A13', 'values': [['Non-GAAP EPS ($/share)']]},
        {'range': 'D13', 'values': [[f"=Model!{fy26}{cfg['eps_row']}"]]},
        {'range': 'E13', 'values': [[f"=Model!{fy27}{cfg['eps_row']}"]]},

        {'range': 'A14', 'values': [['Non-GAAP Net Income ($M)']]},
        {'range': 'D14', 'values': [[f"=Model!{fy26}{cfg['net_income_row']}"]]},
        {'range': 'E14', 'values': [[f"=Model!{fy27}{cfg['net_income_row']}"]]},

        # EV BRIDGE
        {'range': 'A16', 'values': [['EV BRIDGE']]},
        {'range': 'A18', 'values': [['Total Debt ($M)']]},
        {'range': 'C18', 'values': [[cfg['debt_formula']]]},
        {'range': 'A19', 'values': [['Cash & Equivalents ($M)']]},
        {'range': 'C19', 'values': [[cfg['cash_formula']]]},
        {'range': 'A20', 'values': [['Net Debt ($M)']]},
        {'range': 'C20', 'values': [['=C18+C19']]},
        {'range': 'A21', 'values': [['Market Cap ($M)']]},
        {'range': 'C21', 'values': [['=C5*C6']]},
        {'range': 'A22', 'values': [['Enterprise Value ($M)']]},
        {'range': 'C22', 'values': [['=C21+C20']]},

        # TARGET MULTIPLES
        {'range': 'A24', 'values': [['TARGET MULTIPLES \u2014 AGENT INPUTS']]},
        {'range': 'D26', 'values': [['FY2026']]},
        {'range': 'E26', 'values': [['FY2027']]},

        {'range': 'A27', 'values': [['EV / Revenue']]},
        {'range': 'D27', 'values': [[ev_rev[0]]]},
        {'range': 'E27', 'values': [[ev_rev[1]]]},

        {'range': 'A28', 'values': [['EV / EBITDA']]},
        {'range': 'D28', 'values': [[ev_ebitda[0]]]},
        {'range': 'E28', 'values': [[ev_ebitda[1]]]},

        {'range': 'A29', 'values': [['P / E']]},
        {'range': 'D29', 'values': [[pe[0]]]},
        {'range': 'E29', 'values': [[pe[1]]]},

        # IMPLIED SHARE PRICES
        {'range': 'A31', 'values': [['IMPLIED SHARE PRICES']]},
        {'range': 'D33', 'values': [['FY2026']]},
        {'range': 'E33', 'values': [['FY2027']]},

        {'range': 'A34', 'values': [['EV/Revenue Implied']]},
        {'range': 'D34', 'values': [['=IFERROR((D27*D11-C20)/C6,"N/A")']]},
        {'range': 'E34', 'values': [['=IFERROR((E27*E11-C20)/C6,"N/A")']]},

        {'range': 'A35', 'values': [['EV/EBITDA Implied']]},
        {'range': 'D35', 'values': [['=IFERROR((D28*D12-C20)/C6,"N/A")']]},
        {'range': 'E35', 'values': [['=IFERROR((E28*E12-C20)/C6,"N/A")']]},

        {'range': 'A36', 'values': [['P/E Implied']]},
        {'range': 'D36', 'values': [['=IFERROR(D29*D13,"N/A")']]},
        {'range': 'E36', 'values': [['=IFERROR(E29*E13,"N/A")']]},

        # VALUATION SUMMARY
        {'range': 'A38', 'values': [['VALUATION SUMMARY']]},
        {'range': 'A40', 'values': [['Average Implied Share Price ($)']]},
        {'range': 'C40', 'values': [['=IFERROR(AVERAGE(D34:E36),"N/A")']]},
        {'range': 'A41', 'values': [['Current Share Price ($)']]},
        {'range': 'C41', 'values': [['=C5']]},
        {'range': 'A42', 'values': [['Upside / (Downside) %']]},
        {'range': 'C42', 'values': [['=IFERROR(C40/C41-1,"N/A")']]},
    ]

    ws.batch_update(cells, value_input_option='USER_ENTERED')
    print(f"  Populated {len(cells)} cells")
    time.sleep(2)

    # ── Formatting ──
    requests = []

    # Column widths
    for col_idx, px in [(0, 280), (1, 20), (2, 130), (3, 110), (4, 110)]:
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sid,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize"
            }
        })

    # Title: merge A1:E1, bold 14pt
    requests.append(merge_req(sid, 0, 0, 4))
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 0, 0, 4),
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
            "fields": "userEnteredFormat.textFormat"
        }
    })

    # Section headers (rows 3, 8, 16, 24, 31, 38 → 0-indexed: 2, 7, 15, 23, 30, 37)
    for row_1 in [3, 8, 16, 24, 31, 38]:
        requests.extend(section_header_reqs(sid, row_1 - 1))

    # Bold labels in column A
    for row_1 in [5, 6, 11, 12, 13, 14, 18, 19, 20, 21, 22, 27, 28, 29, 34, 35, 36, 40, 41, 42]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, row_1 - 1, 0, 0),
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat"
            }
        })

    # Period headers: bold + centered
    for row_1 in [10, 26, 33]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, row_1 - 1, 3, 4),
                "cell": {"userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                }},
                "fields": "userEnteredFormat(textFormat,horizontalAlignment)"
            }
        })

    # Green font for cells linking to other tabs
    green_cells = [
        (4, 2, 2),   # C5
        (5, 2, 2),   # C6
        (10, 3, 4),  # D11:E11
        (11, 3, 4),  # D12:E12
        (12, 3, 4),  # D13:E13
        (13, 3, 4),  # D14:E14
        (17, 2, 2),  # C18
        (18, 2, 2),  # C19
    ]
    for r0, cs, ce in green_cells:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, r0, cs, ce),
                "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": GREEN}}},
                "fields": "userEnteredFormat.textFormat.foregroundColor"
            }
        })

    # Blue font for hardcoded multiples (D27:E29)
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 26, 3, 4, 28),
            "cell": {"userEnteredFormat": {"textFormat": {"foregroundColor": BLUE}}},
            "fields": "userEnteredFormat.textFormat.foregroundColor"
        }
    })

    # Number formats
    # Stock price: $#,##0.00
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 4, 2, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}},
            "fields": "userEnteredFormat.numberFormat"
        }
    })

    # Shares: #,##0
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 5, 2, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}},
            "fields": "userEnteredFormat.numberFormat"
        }
    })

    # Revenue, EBITDA, Net Income: $#,##0
    for r0 in [10, 11, 13]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, r0, 3, 4),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"}}},
                "fields": "userEnteredFormat.numberFormat"
            }
        })

    # EPS: $#,##0.00
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 12, 3, 4),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}},
            "fields": "userEnteredFormat.numberFormat"
        }
    })

    # EV Bridge items: $#,##0
    for r0 in [17, 18, 19, 20, 21]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, r0, 2, 2),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0"}}},
                "fields": "userEnteredFormat.numberFormat"
            }
        })

    # Multiples: 0.0"x"
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 26, 3, 4, 28),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": '0.0"x"'}}},
            "fields": "userEnteredFormat.numberFormat"
        }
    })

    # Implied prices: $#,##0.00
    for r0 in [33, 34, 35]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, r0, 3, 4),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}},
                "fields": "userEnteredFormat.numberFormat"
            }
        })

    # Avg implied + current price: $#,##0.00
    for r0 in [39, 40]:
        requests.append({
            "repeatCell": {
                "range": cell_range(sid, r0, 2, 2),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": "$#,##0.00"}}},
                "fields": "userEnteredFormat.numberFormat"
            }
        })

    # Upside: 0.0%
    requests.append({
        "repeatCell": {
            "range": cell_range(sid, 41, 2, 2),
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}}},
            "fields": "userEnteredFormat.numberFormat"
        }
    })

    # Right-align number columns C, D, E
    for col in [2, 3, 4]:
        requests.append({
            "repeatCell": {
                "range": {
                    "sheetId": sid,
                    "startRowIndex": 4,
                    "endRowIndex": 43,
                    "startColumnIndex": col,
                    "endColumnIndex": col + 1,
                },
                "cell": {"userEnteredFormat": {"horizontalAlignment": "RIGHT"}},
                "fields": "userEnteredFormat.horizontalAlignment"
            }
        })

    sh.batch_update({"requests": requests})
    print(f"  Applied {len(requests)} formatting requests")
    time.sleep(2)

    # ── Verify ──
    try:
        test = ws.batch_get(['C5', 'C6', 'D11', 'C40', 'C42'])
        print(f"  Verification:")
        labels = ['Stock Price', 'Shares', 'FY26 Revenue', 'Avg Implied', 'Upside']
        for label, val in zip(labels, test):
            v = val[0][0] if val and val[0] else 'EMPTY'
            print(f"    {label}: {v}")
    except Exception as e:
        print(f"  Verification skipped: {e}")

    print(f"  Done: {company} ({ticker})")
    return True


# ── Main ────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    creds = json.load(open(CREDS_PATH))
    gc = gspread.service_account_from_dict(creds)

    for i, cfg in enumerate(CONFIGS):
        if i > 0:
            print(f"\n  Waiting 5s before next sheet (rate limit)...")
            time.sleep(5)
        try:
            build_agent_view(gc, cfg)
        except Exception as e:
            print(f"  ERROR on {cfg['ticker']}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"  ALL DONE!")
    print(f"{'='*60}")
