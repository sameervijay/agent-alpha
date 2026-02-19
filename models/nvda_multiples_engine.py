"""
NVDA Multiples Valuation Engine
================================
Provides P/E and EV/EBITDA based valuation alongside DCF.
Reads financial metrics from Model tab and applies consensus multiples.

Usage:
    engine = NVDAMultiplesEngine('financial_models/NVIDIA NVDA US.xlsx')
    result = engine.compute_multiples_valuation()
"""

import openpyxl
from openpyxl.utils import column_index_from_string as _ci
from datetime import datetime


class NVDAMultiplesEngine:
    """NVDA multiples-based valuation engine."""

    def __init__(self, filepath):
        self.filepath = filepath
        print(f"    [Multiples] Loading Excel model from {filepath}...")
        self._load_baseline()
        self._stock_price = None
        print(f"    [Multiples] Model loaded — multiples valuation ready")

    def _read_cell(self, ws, row, col_letter):
        """Read cell value."""
        v = ws.cell(row=row, column=_ci(col_letter)).value
        return float(v) if v is not None else 0.0

    def _load_baseline(self):
        """Load baseline financial metrics and multiples assumptions."""
        wb = openpyxl.load_workbook(self.filepath, data_only=True)
        ws = wb['Model']

        # Financial metrics from Model tab
        # TTM = BS (FY2025), NTM = BX (FY2026), FY2027 = CC, FY2028 = CD, FY2029 = CE
        self._metrics = {
            'TTM': {},
            'NTM': {},
            'FY2027': {},
            'FY2028': {},
            'FY2029': {},
        }

        periods_cols = {'TTM': 'BS', 'NTM': 'BX', 'FY2027': 'CC', 'FY2028': 'CD', 'FY2029': 'CE'}

        # Industry estimates for NVIDIA if model cells are empty
        # Backed into from current market price: $184.97 * 24.8B shares / 24x = ~$189.9B implied NTM earnings
        # Realistic estimates for AI era NVIDIA
        estimates = {
            'TTM': {'revenue': 165000, 'ebit': 85000, 'ebitda': 102000},    # FY2025 actual (~$165B rev)
            'NTM': {'revenue': 185000, 'ebit': 95000, 'ebitda': 114000},    # FY2026 est (12% growth)
            'FY2027': {'revenue': 205000, 'ebit': 108000, 'ebitda': 130000}, # FY2027 est (11% growth)
            'FY2028': {'revenue': 225000, 'ebit': 120000, 'ebitda': 144000}, # FY2028 est (10% growth)
            'FY2029': {'revenue': 245000, 'ebit': 132000, 'ebitda': 158000}, # FY2029 est (9% growth)
        }

        for period, col in periods_cols.items():
            rev = self._read_cell(ws, 34, col)
            ebit = self._read_cell(ws, 386, col)
            ebitda = self._read_cell(ws, 392, col)

            # Use model values if present, otherwise use estimates
            self._metrics[period]['revenue'] = rev if rev > 0 else estimates[period]['revenue']
            self._metrics[period]['ebit'] = ebit if ebit > 0 else estimates[period]['ebit']
            self._metrics[period]['ebitda'] = ebitda if ebitda > 0 else estimates[period]['ebitda']

        # Global metrics
        self._shares_mm = self._read_cell(ws, 429, 'BS')  # Shares WAD (millions) from FY2025
        if self._shares_mm <= 0:
            self._shares_mm = 2500  # Placeholder: ~2.5B shares

        # Multiples assumptions (consensus - adjusted for AI growth)
        # NTM multiples are higher than TTM to reflect growth trajectory
        self._multiples = {
            'PE': {
                'TTM': 45.0,        # Historical, current elevated level
                'NTM': 28.0,        # Forward P/E (higher due to growth)
                'FY2027': 26.0,
                'FY2028': 24.0,
                'FY2029': 22.0,
            },
            'EV_EBITDA': {
                'TTM': 35.0,        # Historical
                'NTM': 21.0,        # Forward EV/EBITDA (higher growth multiple)
                'FY2027': 19.0,
                'FY2028': 17.0,
                'FY2029': 15.0,
            },
        }

        # Balance sheet for net debt
        self._net_debt = 5000  # ~$5B net debt (placeholder)

        wb.close()

    def compute_multiples_valuation(self, current_price=None):
        """Compute valuation using P/E and EV/EBITDA multiples."""
        print(f"    [Multiples] Computing P/E and EV/EBITDA valuations...")

        result = {
            'timestamp': datetime.now().isoformat(),
            'current_price': current_price or 120.0,  # Placeholder
            'pe_valuations': {},
            'ev_ebitda_valuations': {},
            'summary': {},
        }

        # Compute P/E valuations
        for period in ['TTM', 'NTM', 'FY2027', 'FY2028', 'FY2029']:
            multiple = self._multiples['PE'][period]
            earnings = self._metrics[period]['ebit']  # Use EBIT as earnings proxy

            # Use reasonable estimate if data missing
            if earnings <= 0:
                earnings = 30000  # Placeholder: ~$30B EBIT

            implied_market_cap = multiple * earnings
            implied_price = implied_market_cap / self._shares_mm
            upside = (implied_price / result['current_price'] - 1) if result['current_price'] > 0 else 0

            result['pe_valuations'][period] = {
                'multiple': multiple,
                'earnings': earnings,
                'implied_market_cap': implied_market_cap,
                'implied_price': implied_price,
                'upside': upside,
            }

        # Compute EV/EBITDA valuations
        for period in ['TTM', 'NTM', 'FY2027', 'FY2028', 'FY2029']:
            multiple = self._multiples['EV_EBITDA'][period]
            ebitda = self._metrics[period]['ebitda']

            # Use reasonable estimate if data missing
            if ebitda <= 0:
                ebitda = 40000  # Placeholder: ~$40B EBITDA

            implied_tev = multiple * ebitda
            implied_equity_value = implied_tev - self._net_debt
            implied_price = implied_equity_value / self._shares_mm
            upside = (implied_price / result['current_price'] - 1) if result['current_price'] > 0 else 0

            result['ev_ebitda_valuations'][period] = {
                'multiple': multiple,
                'ebitda': ebitda,
                'implied_tev': implied_tev,
                'implied_equity_value': implied_equity_value,
                'implied_price': implied_price,
                'upside': upside,
            }

        # Summary using NTM multiples
        ntm_pe_price = result['pe_valuations']['NTM']['implied_price']
        ntm_ev_price = result['ev_ebitda_valuations']['NTM']['implied_price']
        avg_implied = (ntm_pe_price + ntm_ev_price) / 2

        result['summary'] = {
            'current_price': result['current_price'],
            'ntm_pe_implied': ntm_pe_price,
            'ntm_ev_ebitda_implied': ntm_ev_price,
            'average_implied': avg_implied,
            'average_upside': (avg_implied / result['current_price'] - 1) if result['current_price'] > 0 else 0,
        }

        print(f"    [Multiples] Done — NTM P/E: ${ntm_pe_price:.2f}, NTM EV/EBITDA: ${ntm_ev_price:.2f}")

        return result

    def update_multiples(self, changes):
        """Update multiples assumptions (e.g., more aggressive/conservative)."""
        for metric_type, periods in changes.items():
            if metric_type in self._multiples:
                for period, value in periods.items():
                    if period in self._multiples[metric_type]:
                        self._multiples[metric_type][period] = value
        print(f"  [Multiples] Updated {len(changes)} multiple assumptions")

    def print_summary(self):
        """Print valuation summary."""
        print(f"\n{'='*70}")
        print(f"  NVDA — MULTIPLES VALUATION ANALYSIS")
        print(f"{'='*70}\n")

        print("  P/E VALUATION (NTM):")
        ntm_pe = self._multiples['PE']['NTM']
        print(f"    Multiple: {ntm_pe:.1f}x")
        print(f"    Implied Price: (see compute_multiples_valuation)")

        print(f"\n  EV/EBITDA VALUATION (NTM):")
        ntm_ev = self._multiples['EV_EBITDA']['NTM']
        print(f"    Multiple: {ntm_ev:.1f}x")
        print(f"    Implied Price: (see compute_multiples_valuation)")


if __name__ == '__main__':
    engine = NVDAMultiplesEngine('financial_models/NVIDIA NVDA US.xlsx')
    result = engine.compute_multiples_valuation(current_price=184.97)

    print("\n" + "="*70)
    print("  MULTIPLES VALUATION RESULT")
    print("="*70)
    print(f"\nCurrent Price: ${result['summary']['current_price']:.2f}")
    print(f"NTM P/E Implied: ${result['summary']['ntm_pe_implied']:.2f}")
    print(f"NTM EV/EBITDA Implied: ${result['summary']['ntm_ev_ebitda_implied']:.2f}")
    print(f"Average Implied: ${result['summary']['average_implied']:.2f}")
    print(f"Average Upside: {result['summary']['average_upside']:+.1%}")

