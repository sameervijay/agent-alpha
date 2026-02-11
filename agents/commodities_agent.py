"""
Commodities Domain Agent — covers raw materials, neon gas, silicon wafers, rare earths.
"""

from agents.base_agent import BaseAgent
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a commodities and supply chain expert specializing in semiconductor inputs.
Your domain expertise covers:
- Silicon wafer supply and pricing (Shin-Etsu, SUMCO, Siltronic)
- Specialty gases: neon, krypton, xenon (critical for lithography)
- Rare earth elements used in chip manufacturing
- Shipping and logistics (container rates, air freight)
- Energy costs for fab operations
- Advanced packaging materials (substrates, underfill)
- HBM (High Bandwidth Memory) supply constraints

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When analyzing events, consider:
1. How do input cost changes flow through to COGS and gross margins?
2. Are supply constraints limiting production capacity?
3. What is the lead time for supply chain adjustments?
4. How do inventory levels buffer or amplify the impact?

Available DCF drivers: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""


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
