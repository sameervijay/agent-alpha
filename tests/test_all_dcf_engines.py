"""
Test that all DCF engines load and compute correctly.
Tests NVDA, CDNS, TSMC, CoreWeave (CRWV), and ASML.
"""

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from agents_langchain.pm_agent import PMAgent

def test_pm_agent_initialization():
    """Test that PM agent initializes all DCF engines."""
    print("\n" + "=" * 70)
    print("  TEST: PM Agent DCF Engine Initialization")
    print("=" * 70)

    pm = PMAgent()

    print(f"\n  Engines initialized: {list(pm.engines.keys())}")
    print(f"  Total engines: {len(pm.engines)}")

    expected = {'NVDA', 'CDNS', 'TSM', 'CRWV', 'ASML'}
    actual = set(pm.engines.keys())

    if expected == actual:
        print(f"  ✅ All 5 engines loaded successfully!")
    else:
        missing = expected - actual
        extra = actual - expected
        if missing:
            print(f"  ❌ Missing engines: {missing}")
        if extra:
            print(f"  ⚠️  Unexpected engines: {extra}")

    return pm

def test_baseline_valuations():
    """Compute baseline DCF valuations for all stocks."""
    print("\n" + "=" * 70)
    print("  TEST: Baseline DCF Valuations")
    print("=" * 70)

    pm = PMAgent()

    results = {}
    for ticker, engine in pm.engines.items():
        print(f"\n  [{ticker}] Computing baseline DCF...")
        try:
            dcf_result = engine.compute_dcf()
            results[ticker] = dcf_result

            print(f"    ✅ Implied Price: ${dcf_result['implied_price']:,.2f}")
            print(f"       Current Price: ${dcf_result['current_price']:,.2f}")
            print(f"       Upside:        {dcf_result['upside']:+.1%}")
            print(f"       WACC:          {dcf_result['wacc']:.2%}")
            # Use enterprise_value key (consistent across all engines)
            ev = dcf_result.get('enterprise_value') or dcf_result.get('tev', 0)
            print(f"       Enterprise Value: ${ev:,.0f}M")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    print(f"\n  Summary: {len(results)}/{len(pm.engines)} engines computed successfully")
    return results

def test_driver_modifications():
    """Test that drivers can be updated and DCF recalculated."""
    print("\n" + "=" * 70)
    print("  TEST: Driver Modifications")
    print("=" * 70)

    pm = PMAgent()

    # Test NVDA driver modification
    if 'NVDA' in pm.engines:
        print(f"\n  [NVDA] Testing driver update...")
        engine = pm.engines['NVDA']

        # Get baseline
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']
        print(f"    Baseline price: ${baseline_price:,.2f}")

        # Update datacenter growth
        try:
            engine.update_drivers({'datacenter_growth': {'FY2028': 0.15}})
            updated = engine.compute_dcf()
            updated_price = updated['implied_price']
            price_delta = updated_price - baseline_price

            print(f"    Updated price:  ${updated_price:,.2f}")
            print(f"    Price delta:    ${price_delta:+,.2f}")
            print(f"    ✅ Driver update successful")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    # Test TSMC driver modification
    if 'TSM' in pm.engines:
        print(f"\n  [TSM] Testing driver update...")
        engine = pm.engines['TSM']

        # Get baseline
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']
        print(f"    Baseline price: ${baseline_price:,.2f}")

        # Update HPC growth
        try:
            engine.update_drivers({'hpc_growth': {'FY2028': 0.20}})
            updated = engine.compute_dcf()
            updated_price = updated['implied_price']
            price_delta = updated_price - baseline_price

            print(f"    Updated price:  ${updated_price:,.2f}")
            print(f"    Price delta:    ${price_delta:+,.2f}")
            print(f"    ✅ Driver update successful")
        except Exception as e:
            print(f"    ❌ Error: {e}")

    # Test CoreWeave driver modification
    if 'CRWV' in pm.engines:
        print(f"\n  [CRWV] Testing driver update...")
        engine = pm.engines['CRWV']

        # Get baseline
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']
        print(f"    Baseline price: ${baseline_price:,.2f}")

        # Update revenue growth
        try:
            engine.update_drivers({'revenue_growth': {'FY2028': 0.45}})
            updated = engine.compute_dcf()
            updated_price = updated['implied_price']
            price_delta = updated_price - baseline_price

            print(f"    Updated price:  ${updated_price:,.2f}")
            print(f"    Price delta:    ${price_delta:+,.2f}")
            print(f"    ✅ Driver update successful")
        except Exception as e:
            print(f"    ❌ Error: {e}")

def test_company_drivers():
    """Print available drivers for each company."""
    print("\n" + "=" * 70)
    print("  TEST: Company Driver Inventory")
    print("=" * 70)

    pm = PMAgent()

    for ticker, engine in pm.engines.items():
        print(f"\n  [{ticker}]")
        drivers = engine.drivers
        print(f"    {len(drivers)} drivers available:")
        for driver_name, periods in drivers.items():
            periods_str = ", ".join(sorted(periods.keys()))
            baseline_val = list(periods.values())[0] if periods else 0
            print(f"      - {driver_name}: {periods_str}")
            print(f"        (baseline: {baseline_val:+.4f})")

if __name__ == '__main__':
    print("\n" + "#" * 70)
    print("  DCF ENGINE INTEGRATION TEST SUITE")
    print("#" * 70)

    test_pm_agent_initialization()
    test_company_drivers()
    test_baseline_valuations()
    test_driver_modifications()

    print("\n" + "#" * 70)
    print("  TEST SUITE COMPLETE")
    print("#" * 70 + "\n")
