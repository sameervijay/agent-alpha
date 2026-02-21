"""
Sensitivity analysis for DCF valuations.
WACC sensitivity, driver sensitivity, and signal stability checks.
"""

import sys
from pathlib import Path
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent / 'models'))
from pm_agent_interface import NVDADCFEngine

import config


def wacc_sensitivity(engine: NVDADCFEngine, range_bps: int = 200,
                     step_bps: int = 50) -> list:
    """Vary WACC +/- range_bps and compute implied price at each level.

    Returns list of dicts with wacc, implied_price, upside for each scenario.
    """
    # Save original assumptions
    original_rf = engine._dcf_assumptions['rf']
    results = []

    for delta_bps in range(-range_bps, range_bps + step_bps, step_bps):
        delta = delta_bps / 10000
        engine._dcf_assumptions['rf'] = original_rf + delta
        r = engine.compute_dcf()
        results.append({
            'wacc_delta_bps': delta_bps,
            'wacc': r['wacc'],
            'implied_price': r['implied_price'],
            'upside': r['upside'],
        })

    # Restore original
    engine._dcf_assumptions['rf'] = original_rf
    engine.compute_dcf()

    return results


def driver_sensitivity(engine: NVDADCFEngine, driver: str, period: str,
                       range_pct: float = 0.05, steps: int = 5) -> list:
    """Vary one driver and show price impact.

    Args:
        engine: DCF engine instance
        driver: driver name (e.g., 'datacenter_growth')
        period: period (e.g., 'FY2028')
        range_pct: range to vary (+/-)
        steps: number of steps on each side

    Returns list of dicts with driver_value, implied_price, upside.
    """
    original_value = engine.drivers.get(driver, {}).get(period, 0)
    results = []

    step_size = range_pct / steps if steps > 0 else range_pct

    for i in range(-steps, steps + 1):
        delta = i * step_size
        test_value = original_value + delta
        engine.drivers[driver][period] = test_value
        r = engine.compute_dcf()
        results.append({
            'driver': driver,
            'period': period,
            'delta': delta,
            'value': test_value,
            'implied_price': r['implied_price'],
            'upside': r['upside'],
        })

    # Restore original
    engine.drivers[driver][period] = original_value
    engine.compute_dcf()

    return results


def signal_stability(wacc_results: list) -> dict:
    """Check if the Buy/Sell signal flips within the WACC sensitivity range.

    Args:
        wacc_results: output from wacc_sensitivity()

    Returns:
        dict with 'stable', 'signal', and optional 're_debate_required' flag.
    """
    threshold = config.UPSIDE_THRESHOLD
    signals = []

    for r in wacc_results:
        if r['upside'] >= threshold:
            signals.append('BUY')
        elif r['upside'] <= -threshold:
            signals.append('SELL')
        else:
            signals.append('HOLD')

    unique_signals = set(signals)
    stable = len(unique_signals) == 1

    # Find the base case signal (delta=0)
    base_signal = 'HOLD'
    for r in wacc_results:
        if r['wacc_delta_bps'] == 0:
            if r['upside'] >= threshold:
                base_signal = 'BUY'
            elif r['upside'] <= -threshold:
                base_signal = 'SELL'
            break

    return {
        'stable': stable,
        'signal': base_signal,
        'signals_in_range': list(unique_signals),
        're_debate_required': not stable,
        'wacc_results': wacc_results,
    }


def print_wacc_table(wacc_results: list):
    """Print a formatted WACC sensitivity table."""
    print("\n  WACC Sensitivity Analysis")
    print("  " + "-" * 50)
    print(f"  {'WACC':>8}  {'Implied Price':>14}  {'Upside':>8}")
    print("  " + "-" * 50)
    for r in wacc_results:
        marker = " <<<" if r['wacc_delta_bps'] == 0 else ""
        print(f"  {r['wacc']:>7.1%}  ${r['implied_price']:>13,.2f}  {r['upside']:>7.1%}{marker}")
    print()
