"""
Commodities Domain Agent — covers raw materials, neon gas, silicon wafers, rare earths, memory pricing.
"""

from agents.base_agent import BaseAgent
from models.event import Event
from models.causal_graph import CausalLink
from tools.memory_pricing_monitor import analyze_memory_impact, estimate_supply_constraint
from tools.advanced_packaging_monitor import (
    analyze_packaging_impact,
    estimate_production_constraint,
    track_cowos_capacity,
)

SYSTEM_PROMPT = """You are a commodities and supply chain expert specializing in semiconductor inputs and packaging.
Your domain expertise covers:
- Silicon wafer supply and pricing (Shin-Etsu, SUMCO, Siltronic)
- Specialty gases: neon, krypton, xenon (critical for lithography)
- Rare earth elements used in chip manufacturing
- Shipping and logistics (container rates, air freight)
- Energy costs for fab operations
- DRAM and HBM (High Bandwidth Memory) pricing and supply constraints ⭐ PRIORITY
- Advanced Packaging Capacity ⭐ PRIORITY
  * CoWoS (Chip-on-Wafer-on-Substrate): GPU packaging, expanding from 75K → 120K wafers/month
  * Advanced Substrates (ABF, GIS, HDI): Watch Unimicron (40% market, tightest capacity)
  * HBM stacking: 3D memory integration, critical for H/GB-series GPUs
  * Chiplet interconnects: Emerging bottleneck for multi-die modules

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When analyzing events, consider:
1. How do input cost changes flow through to COGS and gross margins?
2. Are supply constraints limiting production capacity?
3. What is the lead time for supply chain adjustments?
4. How do inventory levels buffer or amplify the impact?
5. For HBM pricing: track ASP changes, lead times, inventory weeks (leading indicators)
6. For Advanced Packaging: Is this a production BOTTLENECK (limits volume) or cost pressure (limits margin)?
   - CoWoS constraints directly limit NVIDIA H/GB GPU production (can't make enough)
   - Substrate constraints are secondary (manageable but watch Unimicron)
   - HBM stacking is primary for AI GPU competitiveness (50% of BOM cost)

Available DCF drivers: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030

Commodity Monitoring Focus (Phase 1):
- Memory: HBM +20% expected → NVIDIA -70bps, TSMC +240bps, CRWV -180bps margin impact
- Packaging: CoWoS at 85-95% utilization (constrained) → production bottleneck risk for NVIDIA
- Lead indicators: Inventory weeks <6, lead times >30 weeks, supplier CapEx announcements"""


class CommoditiesAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="commodities_agent",
            role_description="Commodities & Supply Chain Expert",
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str) -> list:
        prompt = f"""Analyze the following news/scenario for commodities and supply chain events relevant to semiconductor companies.

NEWS INPUT:
{news_input}

Return a JSON object with key "events", where each event has:
- headline: concise event title
- description: 2-3 sentence explanation
- affected_companies: list of tickers (from NVDA, TSM, ASML, CDNS, CRWV)
- affected_segments: list of segments affected
- severity: "low", "medium", "high", or "critical"
- direction: "positive", "negative", "neutral", or "mixed"

Only include events relevant to your commodities/supply chain domain."""

        data = self.call_llm_json(prompt)
        events = []
        for e in data.get('events', []):
            events.append(Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e['affected_companies'],
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=news_input,
            ))
        return events

    def build_causal_links(self, event: Event) -> list:
        prompt = f"""Given this commodities/supply chain event, trace the causal chain to financial impacts.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}

Return a JSON object with key "causal_links", where each link has:
- source_event: the event headline
- intermediate_step: supply chain mechanism
- downstream_metric: one of datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- affected_company: ticker
- affected_periods: list of periods
- direction: "increase" or "decrease"
- magnitude_estimate: quantitative or qualitative estimate
- confidence: float 0.0 to 1.0
- reasoning: justification"""

        data = self.call_llm_json(prompt)
        links = []
        for l in data.get('causal_links', []):
            links.append(CausalLink(
                source_event=l['source_event'],
                intermediate_step=l['intermediate_step'],
                downstream_metric=l['downstream_metric'],
                affected_company=l['affected_company'],
                affected_periods=l['affected_periods'],
                direction=l['direction'],
                magnitude_estimate=l['magnitude_estimate'],
                confidence=l['confidence'],
                reasoning=l['reasoning'],
                proposed_by=self.name,
            ))
        return links

    def analyze_packaging_capacity_event(self, event: Event) -> dict:
        """
        Specialized analysis for advanced packaging capacity events.
        Maps CoWoS, substrate, and chiplet capacity changes to production bottlenecks.

        Returns:
            - headline: event title
            - affected_companies: tickers impacted
            - packaging_type: CoWoS, Advanced_Substrates, HBM_Stacking, Chiplet
            - capacity_change_estimate: estimated capacity delta
            - constraint_level: abundant, balanced, tight, constrained
            - is_bottleneck: Is this limiting factor for GPU/chip production?
            - margin_impacts: dict of {company: {bps_change}}
            - recommendation: DCF adjustments
        """
        prompt = f"""Analyze this advanced packaging/substrate capacity event.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}

Extract from event:
1. Which packaging type? (CoWoS, substrate/ABF/GIS, HBM stacking, chiplet interconnect)
2. Is capacity increasing (+%) or decreasing (-%)? By how much?
3. Is this a bottleneck for GPU/chip production?
4. Which companies are affected? (NVDA=GPU demand, TSMC=manufacturing)
5. Timeline to impact (this quarter, Q3-Q4, 2027)?

Return JSON with:
- packaging_type: string
- capacity_change_pct: float (-0.20 to +0.30)
- is_bottleneck: boolean
- affected_companies: list
- constraint_level: "abundant", "balanced", "tight", or "constrained"
- confidence: 0.0-1.0
- reasoning: brief explanation"""

        data = self.call_llm_json(prompt)

        # Analyze impact for each company
        impacts = {}
        for company in data.get('affected_companies', []):
            if company in ['NVDA', 'TSMC', 'CRWV']:
                # Estimate constraint level from event
                constraint = data.get('constraint_level', 'balanced')

                impact = analyze_packaging_impact(
                    company,
                    packaging_type=data.get('packaging_type', 'CoWoS'),
                    constraint_level=constraint,
                    cost_increase_pct=data.get('capacity_change_pct', 0.0) * -1,  # Capacity reduction = cost increase
                )
                if 'error' not in impact:
                    impacts[company] = impact

        return {
            'headline': event.headline,
            'packaging_type': data.get('packaging_type', 'unknown'),
            'capacity_change_pct': data.get('capacity_change_pct', 0.0),
            'is_bottleneck': data.get('is_bottleneck', False),
            'constraint_level': data.get('constraint_level', 'balanced'),
            'affected_companies': data.get('affected_companies', []),
            'margin_impacts': impacts,
            'confidence': data.get('confidence', 0.5),
            'reasoning': data.get('reasoning', ''),
            'dcf_actions': [
                impact.get('dcf_recommendation')
                for impact in impacts.values()
                if impact.get('dcf_recommendation')
            ],
        }

    def analyze_memory_pricing_event(self, event: Event) -> dict:
        """
        Specialized analysis for memory pricing events.
        Maps DRAM/HBM price changes to DCF driver impacts.

        Returns:
            - headline: event title
            - affected_companies: tickers impacted
            - memory_type: HBM or DRAM
            - estimated_price_change: ±% ASP change
            - margin_impacts: dict of {company: {driver: bps_change}}
            - recommendation: which DCF drivers to adjust and by how much
            - confidence: 0.0-1.0 confidence in the estimate
        """
        prompt = f"""Analyze this memory pricing event for magnitude and company impact.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}

Extract from the event:
1. Is this HBM or DRAM pricing news?
2. What is the estimated ASP change (±5%, ±10%, ±20%)?
3. Which companies are directly exposed (NVDA, TSMC, CRWV)?
4. Timeline for impact (this quarter, next quarter, 2+ quarters)?

Return a JSON object with:
- memory_type: "HBM" or "DRAM" or "both"
- estimated_price_change: float (-0.20 to +0.20)
- affected_companies: list of tickers
- timeline_quarters: number of quarters to margin impact
- confidence: 0.0-1.0 estimate confidence
- reasoning: brief explanation"""

        data = self.call_llm_json(prompt)

        # Convert LLM output to margin impact analysis
        impacts = {}
        for company in data.get('affected_companies', []):
            impact = analyze_memory_impact(
                company,
                price_change=data.get('estimated_price_change', 0.0),
                memory_type=data.get('memory_type', 'HBM')
            )
            if 'error' not in impact:
                impacts[company] = impact

        return {
            'headline': event.headline,
            'memory_type': data.get('memory_type', 'unknown'),
            'estimated_price_change': data.get('estimated_price_change', 0.0),
            'affected_companies': data.get('affected_companies', []),
            'margin_impacts': impacts,
            'timeline_quarters': data.get('timeline_quarters', 1),
            'confidence': data.get('confidence', 0.5),
            'reasoning': data.get('reasoning', ''),
        }

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        others_text = ""
        for p in other_positions:
            others_text += f"\n  - {p['agent_name']}: value={p['proposed_value']}, confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"

        prompt = f"""You are debating the impact of an event on a financial metric from a commodities/supply chain perspective.

EVENT: {event.headline}
DESCRIPTION: {event.description}
METRIC: {metric}
COMPANY: {company}
PERIOD: {period}

Other agents' positions:{others_text if others_text else " (You are the first to respond)"}

Return a JSON object with:
- proposed_value: float (delta to apply)
- confidence: float 0.0 to 1.0
- reasoning: 3-5 sentence justification from supply chain perspective
- data_type: "leading" or "lagging"
- challenges: challenges to other positions"""

        return self.call_llm_json(prompt)
