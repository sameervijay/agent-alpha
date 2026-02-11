"""
Geopolitics Domain Agent — covers US-China trade, export controls, CHIPS Act, Taiwan risk.
"""

from agents.base_agent import BaseAgent
from models.event import Event
from models.causal_graph import CausalLink

SYSTEM_PROMPT = """You are a geopolitics expert specializing in the semiconductor industry.
Your domain expertise covers:
- US-China trade relations and technology competition
- Export controls (Bureau of Industry and Security, Entity List)
- CHIPS Act and semiconductor subsidies (US, EU, Japan, India)
- Taiwan Strait geopolitical risk and its impact on TSMC
- Sanctions regimes and their second-order effects on the semiconductor value chain

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When analyzing events, think through the causal chain:
1. What is the direct political/regulatory action?
2. Which companies are directly affected and through what mechanism?
3. What are the second and third-order effects through the supply chain?
4. How does this translate to specific financial metrics (revenue growth, margins)?

Available DCF drivers you can map to:
- Revenue growth: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth
- Margin changes: gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030

Always provide confidence levels (0.0-1.0) and clear reasoning chains."""


class PoliticsAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="politics_agent",
            role_description="Geopolitics & Regulatory Expert",
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str) -> list:
        """Phase 1: Detect geopolitically-relevant events from news input."""
        prompt = f"""Analyze the following news/scenario for geopolitical events relevant to the semiconductor value chain.

NEWS INPUT:
{news_input}

Return a JSON object with key "events", where each event has:
- headline: concise event title
- description: 2-3 sentence explanation of the event
- affected_companies: list of tickers (from NVDA, TSM, ASML, CDNS, CRWV)
- affected_segments: list of business segments affected
- severity: one of "low", "medium", "high", "critical"
- direction: one of "positive", "negative", "neutral", "mixed"

Only include events relevant to your geopolitics domain. If no relevant events, return empty list."""

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
        """Phase 2: Build causal links from event to DCF drivers."""
        prompt = f"""Given this geopolitical event, trace the causal chain to specific financial impacts on semiconductor companies.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}

For each causal link, map through:
1. The political action/event (source)
2. The intermediate business impact (e.g., "Reduced China datacenter shipments")
3. The specific DCF driver affected

Return a JSON object with key "causal_links", where each link has:
- source_event: the event headline
- intermediate_step: business mechanism connecting event to metric
- downstream_metric: one of datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- affected_company: ticker (NVDA, TSM, ASML, CDNS, or CRWV)
- affected_periods: list of periods (from Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030)
- direction: "increase" or "decrease"
- magnitude_estimate: quantitative estimate like "-5pp" or "+100bps" or qualitative like "moderate decrease"
- confidence: float 0.0 to 1.0
- reasoning: 2-3 sentence justification"""

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
        """Phase 3: Provide a position in the multi-agent debate."""
        others_text = ""
        for p in other_positions:
            others_text += f"\n  - {p['agent_name']}: value={p['proposed_value']}, confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"

        prompt = f"""You are debating the impact of a geopolitical event on a specific financial metric.

EVENT: {event.headline}
DESCRIPTION: {event.description}
METRIC: {metric}
COMPANY: {company}
PERIOD: {period}

Other agents' positions:{others_text if others_text else " (You are the first to respond)"}

From your geopolitics expertise, provide your position on how this event affects {metric} for {company} in {period}.

Return a JSON object with:
- proposed_value: float (the delta/change to apply — e.g., -0.05 for 5pp decrease in growth, or 50 for +50bps margin improvement)
- confidence: float 0.0 to 1.0
- reasoning: 3-5 sentence justification from your geopolitics perspective
- data_type: "leading" or "lagging" (is your evidence a leading or lagging indicator?)
- challenges: any challenges to other agents' positions (or empty string)"""

        return self.call_llm_json(prompt)
