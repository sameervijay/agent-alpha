"""
DCF grounding utilities for the LangGraph pipeline.

Provides functions to load DCF engines, compute baseline valuations,
apply analyst-proposed driver deltas, and load stored analyst views.
"""

import json
from pathlib import Path
from typing import Any, Optional

import config

from models.pm_agent_interface import NVDADCFEngine
from models.cdns_engine import CDNSDCFEngine
from models.tsmc_engine import TSMCDCFEngine
from models.crwv_engine import CoreWeaveDCFEngine
from models.asml_engine import ASMLDCFEngine

_ENGINE_MAP = {
    'NVDADCFEngine': NVDADCFEngine,
    'CDNSDCFEngine': CDNSDCFEngine,
    'TSMCDCFEngine': TSMCDCFEngine,
    'CoreWeaveDCFEngine': CoreWeaveDCFEngine,
    'ASMLDCFEngine': ASMLDCFEngine,
}

_engine_cache: dict = {}


def clear_engine_cache():
    """Flush engine cache (call at pipeline start)."""
    _engine_cache.clear()


def get_engine(ticker: str):
    """Return a cached DCF engine instance for *ticker*, or None."""
    if ticker in _engine_cache:
        return _engine_cache[ticker]

    comp = config.COMPANIES.get(ticker)
    if not comp or not comp.get('has_full_model'):
        return None

    engine_cls = _ENGINE_MAP.get(comp.get('engine_class', ''))
    if engine_cls is None:
        return None

    try:
        engine = engine_cls(comp['excel_path'])
        _engine_cache[ticker] = engine
        return engine
    except Exception as e:
        print(f"  [dcf_grounding] Could not load {ticker} engine: {e}")
        return None


def compute_baseline(ticker: str) -> Optional[dict]:
    """Compute baseline DCF valuation. Returns dict or None."""
    engine = get_engine(ticker)
    if engine is None:
        return None
    try:
        result = engine.compute_dcf()
        return {
            'implied_price': round(result['implied_price'], 2),
            'current_price': round(result.get('current_price', 0), 2),
            'upside': round(result.get('upside', 0), 4),
            'wacc': result.get('wacc', 0),
            'drivers': engine.drivers,
        }
    except Exception as e:
        print(f"  [dcf_grounding] Baseline failed for {ticker}: {e}")
        return None


def apply_deltas_and_compute(ticker: str, driver_deltas: dict) -> Optional[dict]:
    """Apply additive driver deltas and recompute DCF.

    Args:
        ticker: Company ticker.
        driver_deltas: ``{driver_name: {period: delta_value}}``.
            Deltas are added to current baseline values.

    Returns dict with baseline_price, adjusted_price, current_price, upside,
    alpha_vs_baseline, wacc.  Returns None on failure.
    """
    engine = get_engine(ticker)
    if engine is None:
        return None

    try:
        baseline_result = engine.compute_dcf()
        baseline_price = baseline_result['implied_price']

        changes: dict[str, dict[str, Any]] = {}
        for driver, periods in driver_deltas.items():
            if driver not in engine.drivers:
                continue
            changes[driver] = {}
            for period, delta in periods.items():
                current = engine.drivers.get(driver, {}).get(period, 0)
                changes[driver][period] = current + delta

        if not changes:
            return {
                'baseline_price': round(baseline_price, 2),
                'adjusted_price': round(baseline_price, 2),
                'current_price': round(baseline_result.get('current_price', 0), 2),
                'upside': round(baseline_result.get('upside', 0), 4),
                'alpha_vs_baseline': 0.0,
                'wacc': baseline_result.get('wacc', 0),
            }

        engine.update_drivers(changes)
        adjusted = engine.compute_dcf()

        return {
            'baseline_price': round(baseline_price, 2),
            'adjusted_price': round(adjusted['implied_price'], 2),
            'current_price': round(adjusted.get('current_price', 0), 2),
            'upside': round(adjusted.get('upside', 0), 4),
            'alpha_vs_baseline': round(adjusted['implied_price'] - baseline_price, 2),
            'wacc': adjusted.get('wacc', 0),
        }
    except Exception as e:
        print(f"  [dcf_grounding] Delta application failed for {ticker}: {e}")
        return None


def compute_financials(ticker: str) -> Optional[dict]:
    """Return model-implied financials (rev, EBITDA, EPS) for FY2026 and FY2027.

    These come straight from the DCF engine's compute_dcf() output.
    Returns None if the engine can't be loaded or doesn't produce the needed fields.
    """
    engine = get_engine(ticker)
    if engine is None:
        return None
    try:
        result = engine.compute_dcf()
        total_rev = result.get('total_rev', {})
        ebitda = result.get('ebitda', {})
        eps = result.get('eps', {})
        return {
            'rev_2026': round(total_rev.get('FY2026', 0), 1),
            'rev_2027': round(total_rev.get('FY2027', 0), 1),
            'ebitda_2026': round(ebitda.get('FY2026', 0), 1),
            'ebitda_2027': round(ebitda.get('FY2027', 0), 1),
            'eps_2026': round(eps.get('FY2026', 0), 2),
            'eps_2027': round(eps.get('FY2027', 0), 2),
            'shares': result.get('shares', 0),
            'net_debt': round(result.get('net_debt', 0), 1),
            'current_price': round(result.get('current_price', 0), 2),
        }
    except Exception as e:
        print(f"  [dcf_grounding] compute_financials failed for {ticker}: {e}")
        return None


def load_analyst_view(ticker: str) -> Optional[dict]:
    """Load stored analyst view from ``data/analyst_views/``."""
    views_dir = config.ANALYST_VIEWS_DIR
    for suffix in ['_thesis.json', '_view.json']:
        path = views_dir / f"{ticker}{suffix}"
        if path.exists():
            try:
                with open(path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                print(f"  [dcf_grounding] Could not load view for {ticker}: {e}")
                return None
    return None


def format_dcf_context_for_analyst(ticker: str) -> str:
    """Build a prompt-injectable text block with stored view + baseline DCF."""
    parts: list[str] = []

    # Stored analyst view
    view = load_analyst_view(ticker)
    if view:
        summary = view.get('summary', '')
        baseline_drivers = view.get('baseline_drivers', {})

        # Extract driver implications from NVDA-style thesis
        driver_implications: dict = {}
        for tp in view.get('thesis_points', []):
            for drv, info in tp.get('driver_implications', {}).get('driver_changes', {}).items():
                # Keep only period->value pairs (skip meta keys like baseline/change/rationale)
                period_vals = {k: v for k, v in info.items()
                              if k.startswith(('FY', 'Q')) and isinstance(v, (int, float))}
                if period_vals:
                    driver_implications[drv] = period_vals

        parts.append(f"STORED_ANALYST_VIEW for {ticker}:")
        if summary:
            parts.append(f"  Summary: {summary[:500]}")
        if baseline_drivers:
            parts.append(f"  Baseline drivers: {json.dumps(baseline_drivers, indent=2)}")
        if driver_implications:
            parts.append(f"  Prior driver change recommendations: {json.dumps(driver_implications, indent=2)}")
        parts.append("")

    # Baseline DCF
    baseline = compute_baseline(ticker)
    if baseline:
        parts.append(f"BASELINE_DCF_VALUATION for {ticker}:")
        parts.append(f"  Implied price: ${baseline['implied_price']:,.2f}")
        parts.append(f"  Current price: ${baseline['current_price']:,.2f}")
        parts.append(f"  Upside/Downside: {baseline['upside']:+.1%}")
        parts.append(f"  WACC: {baseline['wacc']:.1%}")
        parts.append(f"  Current model drivers: {json.dumps(baseline['drivers'], indent=2)}")
        parts.append("")

    if not parts:
        return f"No stored view or DCF model available for {ticker}."

    return "\n".join(parts)
