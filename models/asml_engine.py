"""
ASML DCF Engine
===============
Portfolio Manager interface for ASML Holding NV DCF valuation.

Key Drivers (6 levers):
  Equipment Mix: euv_growth, arfi_growth, arf_growth, krf_growth, others_growth
  Margin:        gm_improvement_bps

ASML is a semiconductor equipment manufacturer with:
- High gross margins (>50%)
- Low capex intensity (asset-light design)
- Product-based revenue (EUV dominance provides pricing power)
- Equipment cycle correlates with semiconductor capex cycles

Usage:
    engine = ASMLDCFEngine('financial_models/ASML Holding ASML NA.xlsx')
    engine.update_drivers({'euv_growth': {'FY2028': 0.15}})
    result = engine.compute_dcf()
"""

import openpyxl
from openpyxl.utils import column_index_from_string as _ci


class ASMLDCFEngine:
    """ASML DCF valuation engine."""

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
        """Read cell value."""
        v = ws.cell(row=row, column=_ci(col_letter)).value
        return float(v) if v is not None else 0.0

    def _load_baseline(self):
        """Load baseline data."""
        wb = openpyxl.load_workbook(self.filepath, data_only=True)
        ws = wb['Model']

        # Baseline revenue FY2025-FY2026
        self._baseline_2025 = self._read_cell(ws, 67, 'L')  # Row 67 = Normalized revenue
        self._baseline_gm = self._read_cell(ws, 74, 'L')    # Row 74 = GM%

        # ASML WACC
        self._dcf_assumptions = {
            'rf': 0.0425,
            'beta': 0.80,  # Defensive equipment supplier
            'market_risk_premium': 0.08,
            'tax_rate': 0.14,
        }
        self._dcf_assumptions['wacc'] = (
            self._dcf_assumptions['rf'] +
            self._dcf_assumptions['beta'] * self._dcf_assumptions['market_risk_premium']
        )

        wb.close()

    def get_drivers(self):
        """Get 6 key drivers."""
        periods = ['FY2027', 'FY2028', 'FY2029']
        return {
            'euv_growth': {p: 0.15 for p in periods},      # EUV = 40% of revenue
            'arfi_growth': {p: 0.10 for p in periods},     # ArFi = 20%
            'arf_growth': {p: 0.08 for p in periods},      # ArF = 15%
            'krf_growth': {p: 0.05 for p in periods},      # KrF = 10%
            'others_growth': {p: 0.05 for p in periods},   # Other = 15%
            'gm_improvement_bps': {p: 0 for p in periods},
        }

    def update_drivers(self, changes):
        """Update drivers."""
        for driver_name, period_values in changes.items():
            if driver_name not in self.drivers:
                raise ValueError(f"Unknown driver: {driver_name}")
            for period, value in period_values.items():
                self.drivers[driver_name][period] = value
        print(f"  [DCF] Updated {len(changes)} drivers")

    def compute_dcf(self, current_price=None):
        """Compute DCF."""
        print(f"    [DCF] Step 1/7: Building equipment-based revenues...")
        revenues = self._build_revenues()

        print(f"    [DCF] Step 2/7: Computing margins...")
        margins = self._compute_margins()

        print(f"    [DCF] Step 3/7: Computing EBIT...")
        ebit = {p: revenues[p] * margins[p] for p in revenues}

        print(f"    [DCF] Step 4/7: Computing UFCF...")
        ufcf = self._compute_ufcf(revenues, ebit)

        print(f"    [DCF] Step 5/7: Computing WACC...")
        wacc = self._dcf_assumptions['wacc']

        print(f"    [DCF] Step 6/7: Discounting...")
        pv_ufcf, pv_tv = self._discount_cashflows(ufcf, wacc)

        print(f"    [DCF] Step 7/7: Equity bridge...")
        result = self._equity_bridge(pv_ufcf, pv_tv, current_price, wacc)

        self._last_result = result
        print(f"    [DCF] Done — implied price: ${result['implied_price']:,.2f} "
              f"(WACC: {wacc:.1%}, TEV: ${result['tev']:,.0f})")

        return result

    def _build_revenues(self):
        """Build equipment-based revenues."""
        # Baseline 2025-2026
        revenues = {
            'FY2025': 27000,  # ~$27B actual
            'FY2026': 30000,  # ~$30B (growth from EUV orders)
        }

        # Project using equipment-specific growth
        prev = 30000
        weights = {
            'euv_growth': 0.40,
            'arfi_growth': 0.20,
            'arf_growth': 0.15,
            'krf_growth': 0.10,
            'others_growth': 0.15,
        }

        for period in ['FY2027', 'FY2028', 'FY2029']:
            growth = sum(
                weights[driver] * self.drivers[driver].get(period, 0.08)
                for driver in weights
            )
            revenues[period] = prev * (1 + growth)
            prev = revenues[period]

        return revenues

    def _compute_margins(self):
        """Compute EBIT margins."""
        margins = {}
        baseline_gm = 0.52  # 52% gross margin
        baseline_opex_ratio = 0.20  # 20% OpEx

        for period in ['FY2025', 'FY2026', 'FY2027', 'FY2028', 'FY2029']:
            gm_improvement = sum(
                self.drivers['gm_improvement_bps'].get(p, 0) / 10000
                for p in ['FY2027', 'FY2028', 'FY2029']
                if p <= period
            )
            margins[period] = (baseline_gm + gm_improvement) - baseline_opex_ratio
            margins[period] = min(margins[period], 0.35)  # Cap at 35% EBIT margin

        return margins

    def _compute_ufcf(self, revenues, ebit):
        """Compute UFCF."""
        ufcf = {}
        tax_rate = self._dcf_assumptions['tax_rate']

        for period in revenues:
            nopat = ebit[period] * (1 - tax_rate)
            da = revenues[period] * 0.04  # 4% of revenue (light depreciation)
            capex = revenues[period] * 0.03  # 3% of revenue (asset-light)
            nwc_change = revenues[period] * 0.05

            ufcf[period] = nopat + da - capex - nwc_change

        return ufcf

    def _discount_cashflows(self, ufcf, wacc):
        """Discount cash flows."""
        periods = ['FY2026', 'FY2027', 'FY2028', 'FY2029']
        pv = 0
        tg = 0.02

        for i, period in enumerate(periods, 1):
            df = 1 / (1 + wacc) ** i
            pv += ufcf[period] * df

        tv = ufcf['FY2029'] * (1 + tg) / (wacc - tg)
        pv_tv = tv / (1 + wacc) ** 4

        return pv, pv_tv

    def _equity_bridge(self, pv_ufcf, pv_tv, current_price, wacc):
        """Build equity bridge."""
        tev = pv_ufcf + pv_tv
        net_debt = 3000  # ~$3B net debt
        equity = tev - net_debt
        shares = 900  # ~900M shares

        implied = equity / shares
        current = current_price or 650.0

        upside = (implied / current - 1) if current > 0 else 0

        return {
            'tev': tev,
            'enterprise_value': tev,  # Alias for compatibility
            'net_debt': net_debt,
            'equity_value': equity,
            'shares_mm': shares,
            'implied_price': implied,
            'current_price': current,
            'upside': upside,
            'wacc': wacc,
        }

    def print_summary(self):
        """Print summary."""
        print(f"\n{'='*70}")
        print(f"  ASML DCF VALUATION")
        print(f"{'='*70}\n")
        if self._last_result:
            print(f"  Implied Price: ${self._last_result['implied_price']:,.2f}")
            print(f"  Upside: {self._last_result['upside']:+.1%}")

    def save(self):
        """Save drivers."""
        print(f"  [DCF] Drivers would be saved to Model tab")


if __name__ == '__main__':
    print("Loading baseline model...\n")
    engine = ASMLDCFEngine('financial_models/ASML Holding ASML NA.xlsx')
    result = engine.compute_dcf()
    engine.print_summary()
