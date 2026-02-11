"""
Technology term → financial metric translator.
Maps semiconductor technology events to specific DCF driver impacts.
"""

# Static mapping: tech event → (company, metric, direction)
TECH_MAPPINGS = {
    # EUV / Lithography
    "euv throughput improvement": {
        "company": "TSM",
        "metric": "gm_improvement_bps",
        "direction": "increase",
        "reasoning": "Higher EUV throughput reduces cost per wafer, improving foundry gross margins",
    },
    "high-na euv deployment": {
        "company": "ASML",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "High-NA EUV systems are higher ASP, driving equipment revenue growth",
    },
    "euv pellicle development": {
        "company": "ASML",
        "metric": "gm_improvement_bps",
        "direction": "increase",
        "reasoning": "Pellicle enables higher dose EUV, improving system economics",
    },

    # Process Nodes
    "3nm yield improvement": {
        "company": "TSM",
        "metric": "gm_improvement_bps",
        "direction": "increase",
        "reasoning": "Better yields mean fewer defective dies, directly improving gross margins",
    },
    "2nm production ramp": {
        "company": "TSM",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "New node ramp drives higher wafer revenue from leading-edge customers",
    },
    "gaa transistor transition": {
        "company": "TSM",
        "metric": "rd_improvement_bps",
        "direction": "decrease",
        "reasoning": "GAA transition requires significant R&D investment, increasing R&D spend",
    },

    # Advanced Packaging
    "cowos capacity expansion": {
        "company": "TSM",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "More CoWoS capacity enables more AI chip production for NVIDIA/AMD",
    },
    "chiplet adoption": {
        "company": "NVDA",
        "metric": "gm_improvement_bps",
        "direction": "increase",
        "reasoning": "Chiplet design improves yield and reduces per-chip cost",
    },
    "3d stacking advancement": {
        "company": "TSM",
        "metric": "gm_improvement_bps",
        "direction": "increase",
        "reasoning": "3D stacking commands premium pricing at foundry",
    },

    # HBM
    "hbm capacity expansion": {
        "company": "NVDA",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "More HBM supply removes bottleneck for AI GPU production",
    },
    "hbm4 development": {
        "company": "NVDA",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "Next-gen HBM enables higher-performance AI chips",
    },

    # AI Accelerators
    "new gpu architecture": {
        "company": "NVDA",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "New architecture drives upgrade cycle and higher ASPs",
    },
    "custom asic competition": {
        "company": "NVDA",
        "metric": "datacenter_growth",
        "direction": "decrease",
        "reasoning": "Custom ASICs from hyperscalers reduce GPU market share",
    },

    # EDA
    "ai-driven eda tools": {
        "company": "CDNS",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "AI-enhanced EDA tools command premium pricing",
    },
    "design complexity increase": {
        "company": "CDNS",
        "metric": "datacenter_growth",
        "direction": "increase",
        "reasoning": "More complex chips require more EDA tool licenses",
    },
}


def translate_term(tech_term: str) -> dict:
    """Translate a technology term into a DCF driver impact.

    Args:
        tech_term: A technology event or term (e.g., "EUV throughput improvement")

    Returns:
        Dict with company, metric, direction, and reasoning. Empty dict if no match.
    """
    normalized = tech_term.lower().strip()

    # Exact match
    if normalized in TECH_MAPPINGS:
        return TECH_MAPPINGS[normalized]

    # Partial match
    for key, value in TECH_MAPPINGS.items():
        if key in normalized or normalized in key:
            return value

    return {}


def get_all_mappings() -> dict:
    """Return all tech term mappings for reference."""
    return TECH_MAPPINGS.copy()
