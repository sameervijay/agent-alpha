"""
Weekly Commodity Monitoring — Memory Pricing + Advanced Packaging

Run this every Monday to track both:
1. Memory pricing (DRAM, HBM) — margin impact indicator
2. Advanced packaging capacity (CoWoS, substrates) — production bottleneck indicator

Usage:
    python3 tests/test_commodity_monitoring.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.memory_pricing_monitor import (
    fetch_memory_pricing_news,
    generate_weekly_memory_report,
    analyze_memory_impact,
)
from tools.advanced_packaging_monitor import (
    generate_packaging_monitoring_report,
    track_cowos_capacity,
    track_substrate_capacity,
    analyze_packaging_impact,
    estimate_production_constraint,
)


def run_weekly_commodity_monitoring():
    """Complete weekly commodity monitoring (memory + packaging)."""

    print(f"\n{'='*70}")
    print(f"  WEEKLY COMMODITY MONITORING")
    print(f"  {datetime.now().strftime('%A, %B %d, %Y')}")
    print(f"{'='*70}\n")

    # ────────────────────────────────────────────────────────────────
    # PART 1: MEMORY PRICING
    # ────────────────────────────────────────────────────────────────

    print("PART 1: MEMORY PRICING COMMODITY TRACKING")
    print("="*70)
    print(generate_weekly_memory_report(days_back=7))

    # ────────────────────────────────────────────────────────────────
    # PART 2: ADVANCED PACKAGING CAPACITY
    # ────────────────────────────────────────────────────────────────

    print("\nPART 2: ADVANCED PACKAGING CAPACITY TRACKING")
    print("="*70)
    print(generate_packaging_monitoring_report())

    # ────────────────────────────────────────────────────────────────
    # PART 3: COMBINED PORTFOLIO IMPACT
    # ────────────────────────────────────────────────────────────────

    print("\n" + "="*70)
    print("PART 3: COMBINED PORTFOLIO IMPACT ANALYSIS")
    print("="*70)

    print("\n🎯 KEY SCENARIO: 2026 Upside Case (Memory + Packaging Constraints)")
    print("-"*70)
    print("""
Assumptions:
- HBM prices +20% YoY (Samsung/SK Hynix guidance)
- Server DRAM (DDR5) +60% (current Q1 2026 reality)
- CoWoS utilization 85-95% (constrained, expanding to 120K by Q3 2026)
- Substrate suppliers tight (Unimicron 92% utilization)

Company Impacts:
""")

    companies_analysis = {}

    for company in ['NVDA', 'TSMC', 'CRWV']:
        print(f"\n{company}:")
        print("-" * 40)

        # Memory impact
        hbm_impact = analyze_memory_impact(company, price_change=0.20, memory_type='HBM')
        dram_impact = analyze_memory_impact(company, price_change=0.60, memory_type='DRAM')

        # Packaging impact
        packaging_impact = analyze_packaging_impact(
            company,
            packaging_type='CoWoS',
            constraint_level='constrained',
            cost_increase_pct=0.05  # 5% cost pressure from capacity constraints
        )

        # Production constraints
        production = estimate_production_constraint(company, hbm_demand_growth_pct=0.50)

        companies_analysis[company] = {
            'memory': hbm_impact,
            'dram': dram_impact,
            'packaging': packaging_impact,
            'production': production,
        }

        # Print summary
        print(f"  Memory Impact:")
        print(f"    • HBM +20%: {hbm_impact['estimated_margin_impact_bps']:+d} bps")
        print(f"    • DDR5 +60%: {dram_impact['estimated_margin_impact_bps']:+d} bps")

        print(f"  Packaging Impact:")
        if 'margin_impact_bps' in packaging_impact and 'error' not in packaging_impact:
            print(f"    • CoWoS constrained: {packaging_impact['margin_impact_bps']:+d} bps")
            print(f"    • Bottleneck: {packaging_impact.get('is_bottleneck', False)}")
        else:
            print(f"    • CoWoS: No material exposure (indirect via GPU costs)")

        print(f"  Production Constraint:")
        if production['bottleneck_hierarchy']:
            primary = production['bottleneck_hierarchy'][0]
            print(f"    • Primary: {primary['type']} ({primary['severity'].upper()})")
            print(f"    • Impact: {primary['impact']}")
        else:
            print(f"    • No material constraints")

        if hbm_impact.get('dcf_driver_affected'):
            print(f"  DCF Action:")
            print(f"    • Driver: {hbm_impact['dcf_driver_affected']}")
            print(f"    • Adjustment: {hbm_impact['estimated_margin_impact_bps']:+d} bps")

    # ────────────────────────────────────────────────────────────────
    # PART 4: DATA COLLECTION CHECKLIST
    # ────────────────────────────────────────────────────────────────

    print("\n\n" + "="*70)
    print("PART 4: DATA COLLECTION CHECKLIST (Weekly)")
    print("="*70)

    checklist = [
        ("TrendForce Memory News", "https://www.trendforce.com/news", "2-3x/week"),
        ("DRAM Lead Times", "Google 'DRAM lead times' / Sourceability", "Weekly"),
        ("DRAM Inventory", "SEMI reports, component distributors", "Weekly"),
        ("CoWoS Capacity News", "TrendForce, TSMC earnings", "Quarterly"),
        ("Substrate News", "Unimicron, Ibiden, Shinko announcements", "Quarterly"),
        ("Packaging Equipment", "ASMPT, ASM Pacific earnings", "Quarterly"),
    ]

    print("\nDATA SOURCES:")
    for source, url, frequency in checklist:
        print(f"  □ {source:30s} {frequency:15s}")
        print(f"    → {url}")

    # ────────────────────────────────────────────────────────────────
    # PART 5: DCF ADJUSTMENT THRESHOLDS
    # ────────────────────────────────────────────────────────────────

    print("\n\n" + "="*70)
    print("PART 5: DCF ADJUSTMENT THRESHOLDS")
    print("="*70)

    thresholds = [
        ("Memory Pricing", "HBM ASP changes >8% month-over-month", "Update gm_improvement_bps", "NVIDIA, CoreWeave"),
        ("", "DRAM ASP changes >15%", "Update gm_improvement_bps", "TSMC, CoreWeave"),
        ("", "Lead times expand >30 weeks", "Increase pricing power assumption", "All"),
        ("", "Inventory weeks <6", "Model margin expansion imminent", "All"),
        ("", "", "", ""),
        ("Advanced Packaging", "CoWoS utilization >95%", "Model 5-10% GPU volume constraint", "NVIDIA"),
        ("", "Unimicron capacity add announced", "Update substrate cost assumptions", "NVIDIA, TSMC"),
        ("", "HBM stacking shortfall reported", "Review 2026-27 GPU production limits", "NVIDIA"),
        ("", "Chiplet packaging scale-up", "Monitor as emerging constraint 2027+", "NVIDIA, TSMC"),
    ]

    for category, trigger, action, companies in thresholds:
        if category:
            print(f"\n{category}:")
        if trigger:
            print(f"  ▪ Trigger: {trigger}")
            print(f"    → Action: {action} ({companies})")

    # ────────────────────────────────────────────────────────────────
    # SAVE RESULTS
    # ────────────────────────────────────────────────────────────────

    print("\n\n" + "="*70)
    print("SAVING ANALYSIS RESULTS")
    print("="*70 + "\n")

    output_file = Path('data/valuations/commodity_monitoring_latest.json')
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump({
            'timestamp': datetime.now().isoformat(),
            'analysis_date': datetime.now().strftime('%Y-%m-%d'),
            'memory_scenarios': {
                'HBM_plus_20pct': {
                    'NVDA': companies_analysis['NVDA']['memory'],
                    'TSMC': companies_analysis['TSMC']['memory'],
                    'CRWV': companies_analysis['CRWV']['memory'],
                },
                'DRAM_plus_60pct': {
                    'NVDA': companies_analysis['NVDA']['dram'],
                    'TSMC': companies_analysis['TSMC']['dram'],
                    'CRWV': companies_analysis['CRWV']['dram'],
                }
            },
            'packaging_scenarios': {
                'CoWoS_constrained': {
                    'NVDA': companies_analysis['NVDA']['packaging'],
                    'TSMC': companies_analysis['TSMC']['packaging'],
                    'CRWV': companies_analysis['CRWV']['packaging'],
                }
            },
            'production_constraints': {
                'NVDA': companies_analysis['NVDA']['production'],
                'TSMC': companies_analysis['TSMC']['production'],
                'CRWV': companies_analysis['CRWV']['production'],
            }
        }, f, indent=2, default=str)

    print(f"✅ Results saved to {output_file}")
    print(f"\nUse this output for:")
    print(f"  • PM agent briefing")
    print(f"  • DCF margin assumption updates")
    print(f"  • Portfolio risk assessment")
    print(f"  • Quarterly review with analysts\n")


if __name__ == '__main__':
    try:
        run_weekly_commodity_monitoring()
    except Exception as e:
        print(f"\n❌ Error running commodity monitoring: {e}")
        import traceback
        traceback.print_exc()
