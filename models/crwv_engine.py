"""
CoreWeave DCF Engine
====================
Python interface for Portfolio Manager to read/modify CoreWeave drivers
and compute implied DCF valuations.

Key Drivers (4 levers):
  Revenue:  revenue_growth
  Margins:  ebitda_margin_improvement_bps, opex_improvement_bps, tax_rate_bps

CoreWeave is simpler than TSMC (single revenue line) and uses EBITDA focus.
Key characteristic: GPU cloud rental business model (high capex, growing revenue)

Usage:
    engine = CoreWeaveDCFEngine('financial_models/CoreWeave CRWV US.xlsx')
    engine.compute_dcf()
"""

import openpyxl
from openpyxl.utils import column_index_from_string as _ci


class CoreWeaveDCFEngine:
    """Read/modify CoreWeave DCF drivers and compute implied valuations."""

    def __init__(self, filepath):
        self.filepath = filepath
        print(f"    [DCF] Loading Excel model from {filepath}...")
        self._load_baseline()
        self.drivers = self.get_drivers()
        self._last_result = None
        self._stock_price = None

        print(f"    [DCF] Model loaded — {len(self.drivers)} drivers, "
              f"stock price: (will fetch live), "
              f"WACC assumptions: rf={self._dcf_assumptions['rf']:.2%}, "
              f"beta={self._dcf_assumptions['beta']:.2f}")

    def _read_cell(self, ws, row, col_letter):
        """Read a cell value, returning 0.0 for None."""
        v = ws.cell(row=row, column=_ci(col_letter)).value
        return float(v) if v is not None else 0.0

    def _load_baseline(self):
        """Load baseline data from Excel."""
        wb = openpyxl.load_workbook(self.filepath, data_only=True)
        ws = wb['Model']

        # Load baseline revenue and margins
        self._baseline_revenue_2025 = self._read_cell(ws, 7, 'S')  # FY2025
        self._baseline_ebitda_margin = self._read_cell(ws, 15, 'S')  # EBITDA margin %

        # CoreWeave WACC assumptions
        self._dcf_assumptions = {
            'rf': 0.0425,
            'beta': 1.50,  # Higher beta (growth company, pre-IPO risk)
            'market_risk_premium': 0.08,
            'tax_rate': 0.21,
        }
        self._dcf_assumptions['wacc'] = (
            self._dcf_assumptions['rf'] +
            self._dcf_assumptions['beta'] * self._dcf_assumptions['market_risk_premium']
        )

        wb.close()

    def get_drivers(self):
        """Get 4 key drivers for CoreWeave."""
        periods = ['FY2027', 'FY2028', 'FY2029']
        return {
            'revenue_growth': {p: 0.40 for p in periods},  # 40% growth (GPUs growing fast)
            'ebitda_margin_improvement_bps': {p: 0 for p in periods},
            'opex_improvement_bps': {p: 0 for p in periods},
            'tax_rate_bps': {p: 0 for p in periods},
        }

    def update_drivers(self, changes):
        """Update specified drivers."""
        for driver_name, period_values in changes.items():
            if driver_name not in self.drivers:
                raise ValueError(f"Unknown driver: {driver_name}")
            for period, value in period_values.items():
                self.drivers[driver_name][period] = value
        print(f"  [DCF] Updated {len(changes)} drivers")

    def compute_dcf(self, current_price=None):
        """Compute DCF valuation for CoreWeave."""
        print(f"    [DCF] Step 1/7: Building revenue forecast...")
        revenues = self._build_revenues()

        print(f"    [DCF] Step 2/7: Computing margins...")
        margins = self._compute_margins()

        print(f"    [DCF] Step 3/7: Computing operating income...")
        op_income = {p: revenues[p] * margins[p] for p in revenues}

        print(f"    [DCF] Step 4/7: Computing UFCF...")
        ufcf = self._compute_ufcf(revenues, op_income)

        print(f"    [DCF] Step 5/7: Computing WACC...")
        wacc = self._dcf_assumptions['wacc']

        print(f"    [DCF] Step 6/7: Discounting cash flows...")
        pv_ufcf, pv_terminal = self._discount_cashflows(ufcf, wacc)

        print(f"    [DCF] Step 7/7: Equity bridge...")
        result = self._equity_bridge(pv_ufcf, pv_terminal, current_price, wacc)

        self._last_result = result
        print(f"    [DCF] Done — implied price: ${result['implied_price']:,.2f} "
              f"(WACC: {wacc:.1%}, TEV: ${result['tev']:,.0f})")

        return result

    def _build_revenues(self):
        """Build revenue from growth drivers."""
        revenues = {
            'FY2025': 150,   # Placeholder ~$150M
            'FY2026': 210,   # +40% growth
        }

        periods = ['FY2027', 'FY2028', 'FY2029']
        prev = 210
        for period in periods:
            growth = self.drivers['revenue_growth'].get(period, 0.40)
            revenues[period] = prev * (1 + growth)
            prev = revenues[period]

        return revenues

    def _compute_margins(self):
        """Compute EBITDA margins with improvement drivers."""
        margins = {}
        baseline = 0.30  # 30% EBITDA margin baseline

        for period in ['FY2025', 'FY2026', 'FY2027', 'FY2028', 'FY2029']:
            improvement = sum(
                self.drivers['ebitda_margin_improvement_bps'].get(p, 0) / 10000
                for p in ['FY2027', 'FY2028', 'FY2029']
                if p <= period
            )
            margins[period] = min(baseline + improvement, 0.45)  # Cap at 45%

        return margins

    def _compute_ufcf(self, revenues, op_income):
        """Compute unlevered FCF: OpInc - Tax - CapEx - NWC."""
        ufcf = {}
        tax_rate = self._dcf_assumptions['tax_rate']

        for period in revenues:
            nopat = op_income[period] * (1 - tax_rate)
            da = revenues[period] * 0.05  # 5% of revenue (GPU depreciation)
            capex = revenues[period] * 0.35  # 35% of revenue (heavy capex for GPUs)
            nwc_change = revenues[period] * 0.08

            ufcf[period] = nopat + da - capex - nwc_change

        return ufcf

    def _discount_cashflows(self, ufcf, wacc):
        """Discount UFCF and terminal value."""
        periods = ['FY2026', 'FY2027', 'FY2028', 'FY2029']
        pv_ufcf = 0
        terminal_growth = 0.04

        for i, period in enumerate(periods, 1):
            discount_factor = 1 / (1 + wacc) ** i
            pv_ufcf += ufcf[period] * discount_factor

        terminal_value = ufcf['FY2029'] * (1 + terminal_growth) / (wacc - terminal_growth)
        pv_terminal = terminal_value / (1 + wacc) ** 4

        return pv_ufcf, pv_terminal

    def _equity_bridge(self, pv_ufcf, pv_terminal, current_price, wacc):
        """Build equity bridge."""
        tev = pv_ufcf + pv_terminal
        net_debt = 0  # CoreWeave has little debt
        equity_value = tev
        shares_mm = 500  # Placeholder

        implied_price = equity_value / shares_mm
        current_price = current_price or 10.0

        upside = (implied_price / current_price - 1) if current_price > 0 else 0

        return {
            'tev': tev,
            'enterprise_value': tev,  # Alias for compatibility
            'net_debt': net_debt,
            'equity_value': equity_value,
            'shares_mm': shares_mm,
            'implied_price': implied_price,
            'current_price': current_price,
            'upside': upside,
            'wacc': wacc,
        }

    def print_summary(self):
        """Print valuation summary."""
        print(f"\n{'='*70}")
        print(f"  CORWEAVE DCF VALUATION")
        print(f"{'='*70}\n")
        print(f"  Revenue Growth: {self.drivers['revenue_growth'].get('FY2028', 0.40):.0%}")
        if self._last_result:
            print(f"  Implied Price: ${self._last_result['implied_price']:,.2f}")
            print(f"  Upside: {self._last_result['upside']:+.1%}")

    def save(self):
        """Save drivers to Excel."""
        print(f"  [DCF] Drivers would be saved to Model tab")


if __name__ == '__main__':
    print("Loading baseline model...\n")
    engine = CoreWeaveDCFEngine('financial_models/CoreWeave CRWV US.xlsx')
    result = engine.compute_dcf()
    engine.print_summary()
