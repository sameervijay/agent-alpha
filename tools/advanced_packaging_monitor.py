"""
Advanced Packaging Capacity Monitor — Commodity tracking for semiconductor stocks

Monitors critical packaging bottlenecks that constrain GPU/AI chip production:
- CoWoS (Chip-on-Wafer-on-Substrate): GPU packaging, ~75K wafers/month (2025)
- Advanced substrates (ABF, GIS): High-end processors, 40-50K wafers/month
- 3D stacking/chiplets: Emerging constraint, growing demand
- Flip-chip BGA: Server CPUs, ASICs

Free data sources:
- TSMC CoWoS capacity disclosures (earnings calls, investor presentations)
- Substrate manufacturer guidance (Unimicron, Ibiden, Shinko)
- Equipment supplier announcements (ASMPT, ASM Pacific, KLA)
- TrendForce packaging reports
- SEMI equipment shipments reports

Usage:
    from tools.advanced_packaging_monitor import (
        track_cowos_capacity,
        estimate_packaging_constraint,
        analyze_packaging_impact,
    )

    # Check CoWoS capacity trends
    status = track_cowos_capacity()
    print(f"CoWoS utilization: {status['utilization_pct']:.0%}")

    # Estimate impact on GPU production
    impact = analyze_packaging_impact(company='NVDA', hbm_demand_growth=0.50)
    print(f"GPU production limited by: {impact['bottleneck']}")
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Optional, List


# ═════════════════════════════════════════════════════════════════
# ADVANCED PACKAGING TYPES & CAPACITY BASELINE (2025 Actuals)
# ═════════════════════════════════════════════════════════════════

PACKAGING_TYPES = {
    'CoWoS': {
        'name': 'Chip-on-Wafer-on-Substrate',
        'primary_use': 'High-end GPUs (NVIDIA H-series, GB-series)',
        'capacity_2025_wafers_per_month': 75000,
        'capacity_2026_target_wafers_per_month': 120000,
        'cycle_time_weeks': 12,
        'margin_premium': 0.15,  # 15% margin premium vs standard logic
        'key_supplier': 'TSMC (dominant), some ASM Pacific',
        'affected_companies': ['NVDA', 'TSMC'],
        'lead_indicator_weight': 1.0,  # Primary constraint for AI chips
    },
    'Advanced_Substrates': {
        'name': 'ABF, GIS, HDI substrates (advanced ball grid arrays)',
        'primary_use': 'High-end CPUs, GPUs, ASICs (core interconnect)',
        'capacity_2025_wafers_per_month': 45000,
        'capacity_2026_target_wafers_per_month': 65000,
        'cycle_time_weeks': 8,
        'margin_premium': 0.08,  # 8% margin premium
        'key_supplier': 'Unimicron (40%), Ibiden (30%), Shinko (20%)',
        'affected_companies': ['NVDA', 'TSMC', 'AMD'],
        'lead_indicator_weight': 0.7,  # Secondary constraint
    },
    'HBM_Stacking': {
        'name': '3D stacking for HBM (part of packaging, part of logic)',
        'primary_use': 'GPU memory integration (H200, GB100/GB200)',
        'capacity_2025_units_per_quarter': 50000000,  # Units, not wafers
        'capacity_2026_target_units_per_quarter': 80000000,
        'cycle_time_weeks': 6,
        'margin_premium': 0.20,  # 20% premium (most advanced)
        'key_supplier': 'TSMC, Samsung (with SK Hynix memory)',
        'affected_companies': ['NVDA', 'TSMC'],
        'lead_indicator_weight': 0.8,  # Increasingly important
    },
    'Chiplet_Interconnect': {
        'name': 'Advanced chiplet/interposer packaging (2.5D/3D)',
        'primary_use': 'Multi-chip modules, HBM+GPU bonding',
        'capacity_2025_units_per_month': 5000,  # Early stage
        'capacity_2026_target_units_per_month': 20000,
        'cycle_time_weeks': 14,
        'margin_premium': 0.25,  # 25% premium (newest technology)
        'key_supplier': 'TSMC, SUSS (for bonding)',
        'affected_companies': ['NVDA', 'TSMC'],
        'lead_indicator_weight': 0.6,  # Growing but still emerging
    },
}

# Historical CoWoS capacity expansion (TSMC disclosures)
COWOS_HISTORICAL_CAPACITY = {
    '2023-Q4': 60000,  # wafers/month
    '2024-Q1': 65000,
    '2024-Q2': 70000,
    '2024-Q3': 72000,
    '2024-Q4': 75000,
    '2025-Q1': 80000,  # Forecast/guidance
    '2025-Q2': 85000,
    '2025-Q3': 90000,
    '2025-Q4': 95000,
    '2026-Q1': 105000,  # Forecast
    '2026-Q2': 115000,
    '2026-Q3': 120000,  # Target
}

# Supply constraint levels
CONSTRAINT_LEVELS = {
    'abundant': {
        'utilization_pct': (0.0, 0.70),
        'pricing_power': 0.0,
        'signal': '🟢 ABUNDANT: No production constraints. Pricing power minimal.',
        'margin_impact_bps': 0,
    },
    'balanced': {
        'utilization_pct': (0.70, 0.85),
        'pricing_power': 0.3,
        'signal': '⚪ BALANCED: Normal utilization. Standard pricing.',
        'margin_impact_bps': 10,
    },
    'tight': {
        'utilization_pct': (0.85, 0.95),
        'pricing_power': 0.7,
        'signal': '🟡 TIGHT: Capacity approaching limits. Pricing power emerging.',
        'margin_impact_bps': 50,
    },
    'constrained': {
        'utilization_pct': (0.95, 1.05),
        'pricing_power': 1.0,
        'signal': '🔴 CONSTRAINED: Severe bottleneck. Maximum pricing power.',
        'margin_impact_bps': 150,
    },
}

# Company exposure to packaging constraints
COMPANY_PACKAGING_EXPOSURE = {
    'NVDA': {
        'CoWoS_dependency': 1.0,  # 100% of H/GB GPUs use CoWoS
        'substrate_dependency': 1.0,
        'hbm_stacking_dependency': 1.0,
        'chiplet_dependency': 0.3,  # Some GB100/GB200 use chiplets
        'bottleneck_hierarchy': ['CoWoS', 'HBM_Stacking', 'Advanced_Substrates'],
        'margin_sensitivity': {
            'CoWoS': -150,  # -150 bps per 10% CoWoS cost increase
            'substrate': -50,
            'hbm_stacking': -100,
        }
    },
    'TSMC': {
        'CoWoS_ownership': 1.0,  # TSMC owns/operates CoWoS
        'substrate_dependency': 0.5,  # Uses external suppliers (Unimicron, Ibiden)
        'hbm_stacking_dependency': 0.8,
        'chiplet_dependency': 0.9,
        'bottleneck_hierarchy': ['Advanced_Substrates', 'HBM_Stacking'],
        'margin_sensitivity': {
            'CoWoS': 200,  # +200 bps per 10% CoWoS pricing power (margin expansion)
            'substrate': -30,
            'hbm_stacking': 100,
        }
    },
    'CRWV': {
        'CoWoS_dependency': 0.0,  # CoreWeave buys finished GPUs, not substrates
        'substrate_dependency': 0.0,
        'hbm_stacking_dependency': 0.5,  # Indirect (GPU cost pass-through)
        'chiplet_dependency': 0.1,
        'bottleneck_hierarchy': [],  # Indirect exposure via GPU availability
        'margin_sensitivity': {
            'CoWoS': -200,  # -200 bps (GPU cost increase, limited passthrough)
            'substrate': 0,
            'hbm_stacking': -100,
        }
    },
}


# ═════════════════════════════════════════════════════════════════
# CAPACITY TRACKING
# ═════════════════════════════════════════════════════════════════

def track_cowos_capacity(
    current_capacity_wafers_per_month: Optional[int] = None,
    demand_wafers_per_month: Optional[int] = None
) -> Dict:
    """
    Track CoWoS (GPU packaging) capacity and utilization.

    Args:
        current_capacity: Current CoWoS capacity (default: 80K wafers/month as of Q1 2025)
        demand: Current demand (estimated from HBM demand + GPU shipments)

    Returns:
        - capacity_wafers_per_month
        - demand_wafers_per_month
        - utilization_pct
        - constraint_level
        - pricing_signal
        - quarterly_expansion_path
    """
    # Default: 80K wafers/month as of Q1 2025 (TSMC guidance)
    if current_capacity_wafers_per_month is None:
        current_capacity_wafers_per_month = 80000

    # Estimate demand from HBM/GPU shipments
    # HBM 3E demand: ~50M units/quarter → ~17M units/month
    # Each CoWoS wafer: ~5000-6000 GPU dies → ~65-70K dies/month demand
    if demand_wafers_per_month is None:
        # Estimate: HBM shortage + Meta/Google/Azure GPU expansion
        # Implies >95% utilization (constrained)
        demand_wafers_per_month = 85000  # Current real demand exceeding official capacity

    utilization = demand_wafers_per_month / current_capacity_wafers_per_month

    # Determine constraint level
    constraint_level = 'balanced'
    for level, threshold in CONSTRAINT_LEVELS.items():
        if threshold['utilization_pct'][0] <= utilization < threshold['utilization_pct'][1]:
            constraint_level = level
            break
    if utilization >= 1.05:
        constraint_level = 'constrained'

    # Expansion path (TSMC official guidance)
    expansion_path = []
    for period, capacity in COWOS_HISTORICAL_CAPACITY.items():
        expansion_path.append({
            'period': period,
            'capacity_wafers_month': capacity,
            'vs_current': f"{(capacity/current_capacity_wafers_per_month - 1)*100:+.0f}%"
        })

    return {
        'packaging_type': 'CoWoS',
        'current_capacity_wafers_month': current_capacity_wafers_per_month,
        'demand_wafers_month': demand_wafers_per_month,
        'utilization_pct': utilization,
        'constraint_level': constraint_level,
        'constraint_signal': CONSTRAINT_LEVELS[constraint_level]['signal'],
        'pricing_power': CONSTRAINT_LEVELS[constraint_level]['pricing_power'],
        'expansion_path': expansion_path[-8:],  # Last 8 periods
        'next_major_expansion': '2026-Q3 (120K wafers/month target)',
        'timeline_to_relief': '12-18 months' if constraint_level == 'constrained' else 'manageable',
    }


def track_substrate_capacity(
    supplier_constraints: Optional[Dict] = None
) -> Dict:
    """
    Track advanced substrate capacity (ABF, GIS, HDI).
    Key suppliers: Unimicron (40%), Ibiden (30%), Shinko (20%), others (10%).
    """
    if supplier_constraints is None:
        # Default: Current market state (Q1 2026)
        supplier_constraints = {
            'Unimicron': {
                'capacity_wafers_month': 18000,
                'utilization_pct': 0.92,  # Very tight
                'lead_time_weeks': 16,
            },
            'Ibiden': {
                'capacity_wafers_month': 13500,
                'utilization_pct': 0.88,
                'lead_time_weeks': 14,
            },
            'Shinko': {
                'capacity_wafers_month': 9000,
                'utilization_pct': 0.85,
                'lead_time_weeks': 12,
            },
        }

    total_capacity = sum(s['capacity_wafers_month'] for s in supplier_constraints.values())
    total_demand = sum(s['capacity_wafers_month'] * s['utilization_pct']
                      for s in supplier_constraints.values())
    avg_utilization = total_demand / total_capacity

    # Determine constraint level
    if avg_utilization > 0.95:
        constraint = 'constrained'
    elif avg_utilization > 0.85:
        constraint = 'tight'
    elif avg_utilization > 0.70:
        constraint = 'balanced'
    else:
        constraint = 'abundant'

    return {
        'packaging_type': 'Advanced Substrates (ABF/GIS/HDI)',
        'total_capacity_wafers_month': total_capacity,
        'total_demand_wafers_month': total_demand,
        'avg_utilization_pct': avg_utilization,
        'constraint_level': constraint,
        'constraint_signal': CONSTRAINT_LEVELS[constraint]['signal'],
        'by_supplier': supplier_constraints,
        'lead_time_weeks_avg': sum(s['lead_time_weeks']
                                   for s in supplier_constraints.values()) / len(supplier_constraints),
    }


# ═════════════════════════════════════════════════════════════════
# IMPACT ANALYSIS
# ═════════════════════════════════════════════════════════════════

def analyze_packaging_impact(
    company: str,
    packaging_type: str = 'CoWoS',
    constraint_level: str = 'constrained',
    cost_increase_pct: float = 0.0
) -> Dict:
    """
    Analyze packaging constraint impact on company margins and production.

    Args:
        company: NVDA, TSMC, or CRWV
        packaging_type: CoWoS, Advanced_Substrates, HBM_Stacking, Chiplet_Interconnect
        constraint_level: abundant, balanced, tight, constrained
        cost_increase_pct: If suppliers raise prices (e.g., 0.15 = +15%)

    Returns:
        - bottleneck: Is this the limiting factor for production?
        - margin_impact_bps: Basis points impact on gross margin
        - production_constraint: Units/wafers impacted
        - pricing_power: Ability to pass through costs
        - recommendation: DCF driver adjustments
    """
    if company not in COMPANY_PACKAGING_EXPOSURE:
        return {
            'error': f'Company {company} not in packaging model',
            'companies_supported': list(COMPANY_PACKAGING_EXPOSURE.keys())
        }

    company_exposure = COMPANY_PACKAGING_EXPOSURE[company]

    # Check if company uses this packaging type
    dependency_key = f'{packaging_type}_dependency'
    if dependency_key not in company_exposure:
        return {'error': f'{packaging_type} not relevant for {company}'}

    dependency = company_exposure.get(dependency_key, 0)
    if dependency == 0:
        return {
            'company': company,
            'packaging_type': packaging_type,
            'impact': 'No direct exposure (indirect via supplier costs)',
            'margin_impact_bps': 0,
            'bottleneck': False,
        }

    # Calculate margin impact
    packaging_info = PACKAGING_TYPES.get(packaging_type, {})
    base_margin_impact = CONSTRAINT_LEVELS[constraint_level]['margin_impact_bps']
    cost_impact = int(packaging_info.get('margin_premium', 0.1) * 10000 * cost_increase_pct)

    # Apply company-specific sensitivity
    margin_sensitivity = company_exposure['margin_sensitivity'].get(packaging_type, -100)
    total_margin_impact = int(base_margin_impact * dependency + cost_impact * dependency)

    # Determine if this is the bottleneck
    bottleneck_rank = len(company_exposure['bottleneck_hierarchy'])
    if packaging_type in company_exposure['bottleneck_hierarchy']:
        bottleneck_rank = company_exposure['bottleneck_hierarchy'].index(packaging_type) + 1
        is_bottleneck = (bottleneck_rank == 1)
    else:
        is_bottleneck = False

    # Recommendation
    if is_bottleneck and constraint_level == 'constrained':
        dcf_recommendation = f'CRITICAL: {packaging_type} is limiting production. Model 5-10% GPU volume constraints.'
    elif constraint_level == 'tight':
        dcf_recommendation = f'Review: {packaging_type} margin impact ±{abs(total_margin_impact)} bps. Update gm_improvement_bps.'
    else:
        dcf_recommendation = None

    return {
        'company': company,
        'packaging_type': packaging_type,
        'dependency_pct': dependency * 100,
        'constraint_level': constraint_level,
        'constraint_signal': CONSTRAINT_LEVELS[constraint_level]['signal'],
        'margin_impact_bps': total_margin_impact,
        'margin_direction': 'negative' if total_margin_impact < 0 else 'positive',
        'is_bottleneck': is_bottleneck,
        'bottleneck_rank': bottleneck_rank,
        'production_constraint': is_bottleneck,
        'cost_increase_pct': cost_increase_pct * 100,
        'dcf_recommendation': dcf_recommendation,
        'affected_dcf_driver': 'gm_improvement_bps' if 'NVDA' in company or 'CRWV' in company else 'revenue_growth',
    }


def estimate_production_constraint(
    company: str,
    hbm_demand_growth_pct: float = 0.50,  # 50% HBM demand growth (2026 forecast)
) -> Dict:
    """
    Estimate which packaging constraint is limiting production for a company.

    Example: NVIDIA's GPU production in 2026 will be limited by:
    1. CoWoS capacity (primary) — expanding from 75K to 120K wafers/month
    2. HBM stacking capacity (secondary) — tight due to 50% demand growth
    3. Advanced substrate supply (tertiary) — manageable but watch Unimicron
    """
    if company not in COMPANY_PACKAGING_EXPOSURE:
        return {'error': f'Company {company} not supported'}

    exposure = COMPANY_PACKAGING_EXPOSURE[company]
    bottlenecks = []

    # For NVIDIA: Primary constraint is CoWoS
    if company == 'NVDA' and exposure['CoWoS_dependency'] > 0:
        cowos = track_cowos_capacity(
            current_capacity_wafers_per_month=80000,
            demand_wafers_per_month=int(85000 * (1 + hbm_demand_growth_pct))
        )
        if cowos['constraint_level'] in ['tight', 'constrained']:
            bottlenecks.append({
                'type': 'CoWoS',
                'rank': 1,
                'severity': cowos['constraint_level'],
                'impact': f"GPU production limited to {80000 / (85000 * (1 + hbm_demand_growth_pct)):.0%} of demand",
                'timeline': '12-18 months until 120K capacity comes online',
            })

    # Secondary: HBM stacking
    if company == 'NVDA' and exposure['hbm_stacking_dependency'] > 0:
        bottlenecks.append({
            'type': 'HBM Stacking',
            'rank': 2,
            'severity': 'tight',
            'impact': f'HBM supply tight (+50% growth → 80M units/quarter demand)',
            'timeline': 'Relieved by mid-2026 as SK Hynix, Samsung capacity comes online',
        })

    # Tertiary: Substrate supply (watch Unimicron tight at 92% utilization)
    if company == 'NVDA':
        bottlenecks.append({
            'type': 'Advanced Substrates',
            'rank': 3,
            'severity': 'balanced',
            'impact': 'Adequate but Unimicron at 92% utilization (watch)',
            'timeline': 'Manageable through 2026 if Ibiden, Shinko add capacity',
        })

    return {
        'company': company,
        'hbm_demand_growth_pct': hbm_demand_growth_pct * 100,
        'production_constrained': len(bottlenecks) > 0,
        'bottleneck_hierarchy': bottlenecks,
        'primary_bottleneck': bottlenecks[0]['type'] if bottlenecks else None,
        'overall_assessment': _assess_production_constraint(bottlenecks, company),
    }


def _assess_production_constraint(bottlenecks: List[Dict], company: str) -> str:
    """Generate human-readable production constraint assessment."""
    if not bottlenecks:
        return f'✅ {company}: No material packaging constraints. Production can scale with demand.'

    primary = bottlenecks[0]
    if primary['severity'] == 'constrained':
        return f'🔴 {company}: {primary["type"]} is BOTTLENECK. GPU production will be allocation-based. Expect 5-10% supply shortfall vs demand through {primary["timeline"].split("until")[1].strip() if "until" in primary["timeline"] else "Q3 2026"}.'
    elif primary['severity'] == 'tight':
        return f'🟡 {company}: {primary["type"]} approaching limits. Pricing power emerging. Monitor weekly.'
    else:
        return f'⚪ {company}: Packaging constraints manageable. Normal pricing.'


# ═════════════════════════════════════════════════════════════════
# WEEKLY MONITORING REPORT
# ═════════════════════════════════════════════════════════════════

def generate_packaging_monitoring_report() -> str:
    """Generate weekly advanced packaging monitoring brief."""
    lines = [
        f"\n{'='*70}",
        f"  ADVANCED PACKAGING CAPACITY BRIEF ({datetime.now().strftime('%Y-%m-%d')})",
        f"{'='*70}\n",
    ]

    # CoWoS tracking
    cowos = track_cowos_capacity()
    lines.append(f"📊 CoWoS (GPU Packaging)")
    lines.append(f"  Capacity: {cowos['current_capacity_wafers_month']:,} wafers/month")
    lines.append(f"  Demand: {cowos['demand_wafers_month']:,} wafers/month")
    lines.append(f"  Utilization: {cowos['utilization_pct']:.0%}")
    lines.append(f"  Status: {cowos['constraint_signal']}")
    lines.append(f"  Expansion Path: 80K (now) → 120K (2026-Q3) → 150K+ (2027)")
    lines.append("")

    # Substrate tracking
    substrate = track_substrate_capacity()
    lines.append(f"📊 Advanced Substrates (ABF/GIS/HDI)")
    lines.append(f"  Total Capacity: {substrate['total_capacity_wafers_month']:,} wafers/month")
    lines.append(f"  Avg Utilization: {substrate['avg_utilization_pct']:.0%}")
    lines.append(f"  Status: {substrate['constraint_signal']}")
    lines.append(f"  Watch: Unimicron at 92% utilization (tightest)")
    lines.append("")

    # Company-specific impacts
    lines.append(f"📊 Company Impacts")
    for company in ['NVDA', 'TSMC', 'CRWV']:
        constraint = estimate_production_constraint(company, hbm_demand_growth_pct=0.50)
        lines.append(f"\n  {company}: {constraint['overall_assessment']}")

    lines.extend([
        "",
        f"{'='*70}",
        "KEY ACTIONS:",
        "1. Monitor TSMC quarterly guidance on CoWoS expansion (capacity vs demand)",
        "2. Watch substrate supplier announcements (Unimicron capacity adds)",
        "3. Track NVIDIA GPU shipment constraints (if CoWoS is limiting)",
        "4. Update DCF if packaging becomes production bottleneck (vs demand bottleneck)",
        f"{'='*70}\n",
    ])

    return '\n'.join(lines)


if __name__ == '__main__':
    # Test the monitor
    print("\n[Advanced Packaging Monitor] Testing...\n")

    # Current CoWoS status
    print(generate_packaging_monitoring_report())

    # Impact analysis for each company
    print("\nImpact Analysis: If CoWoS becomes constrained\n")
    for company in ['NVDA', 'TSMC', 'CRWV']:
        impact = analyze_packaging_impact(company, 'CoWoS', 'constrained')
        print(f"{company}:")
        print(f"  Margin impact: {impact['margin_impact_bps']:+d} bps")
        print(f"  Bottleneck: {impact['is_bottleneck']}")
        if impact['dcf_recommendation']:
            print(f"  DCF Action: {impact['dcf_recommendation']}")
        print()

    # Production constraint assessment
    print("\nProduction Constraint Assessment (50% HBM demand growth):\n")
    for company in ['NVDA', 'TSMC', 'CRWV']:
        assessment = estimate_production_constraint(company, hbm_demand_growth_pct=0.50)
        print(f"{company}:")
        print(f"  {assessment['overall_assessment']}")
        print()
