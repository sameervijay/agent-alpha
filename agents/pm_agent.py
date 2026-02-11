"""
Portfolio Manager Agent — orchestrates the 4-phase pipeline.
Phase 1: Event Detection (all 5 domain agents)
Phase 2: Causal Graph construction
Phase 3: Multi-Agent Debate with Devil's Advocate
Phase 4: DCF Valuation via NVDADCFEngine
"""

import json
from datetime import datetime
from pathlib import Path

from agents.base_agent import BaseAgent
from agents.politics_agent import PoliticsAgent
from agents.stock_market_agent import StockMarketAgent
from agents.commodities_agent import CommoditiesAgent
from agents.tech_publications_agent import TechPublicationsAgent
from agents.macro_agent import MacroAgent
from agents.company_analyst_agent import CompanyAnalystAgent
from models.event import Event
from models.causal_graph import CausalGraph, CausalLink
from models.debate import (DebatePosition, DebateRound, DebateResolution,
                            DebateSession)
import config

# Import the existing DCF engine
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from pm_agent_interface import NVDADCFEngine


PM_SYSTEM_PROMPT = """You are the Portfolio Manager (PM) for a semiconductor-focused investment fund.
You orchestrate a council of 5 domain expert agents to analyze events and produce
investment recommendations backed by DCF valuations.

Your role:
1. Synthesize diverse expert perspectives into a coherent investment thesis
2. Identify where experts agree and where they disagree
3. Challenge weak arguments and ask probing questions
4. Translate qualitative insights into quantitative DCF driver adjustments
5. Make final decisions on driver values when experts disagree

You are analytical, skeptical of groupthink, and always ask "what could go wrong?"
You weight leading indicators more heavily than lagging indicators.

Available DCF drivers:
- Revenue growth: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth
- Margin changes: gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""


class PMAgent(BaseAgent):
    """Portfolio Manager that orchestrates the 4-phase analysis pipeline."""

    def __init__(self):
        super().__init__(
            name="pm_agent",
            role_description="Portfolio Manager — Council Orchestrator",
            system_prompt=PM_SYSTEM_PROMPT,
        )

        # Initialize domain agents
        self.domain_agents = [
            PoliticsAgent(),
            StockMarketAgent(),
            CommoditiesAgent(),
            TechPublicationsAgent(),
            MacroAgent(),
        ]

        # Initialize company analyst agents (one per company)
        self.company_analysts = {}
        for ticker in config.COMPANIES:
            analyst = CompanyAnalystAgent(ticker)
            self.company_analysts[ticker] = analyst
            self.domain_agents.append(analyst)
        print(f"  [PM] Initialized {len(self.company_analysts)} company analyst agents")

        # Initialize DCF engines (NVDA only for now)
        self.engines = {}
        nvda_config = config.COMPANIES.get('NVDA', {})
        if nvda_config.get('has_full_model'):
            excel_path = nvda_config['excel_path']
            try:
                self.engines['NVDA'] = NVDADCFEngine(excel_path)
                print(f"  [PM] Loaded NVDA DCF engine from {excel_path}")
            except Exception as e:
                print(f"  [PM] Warning: Could not load NVDA DCF engine: {e}")

    # ───────────────────────────────────────────────────────────
    # PHASE 1: EVENT DETECTION
    # ───────────────────────────────────────────────────────────

    def detect_events(self, news_input: str) -> list:
        """Call all 5 domain agents to detect events, deduplicate, rank by severity."""
        print("\n" + "=" * 70)
        print("  PHASE 1: EVENT DETECTION")
        print("=" * 70)

        all_events = []
        for agent in self.domain_agents:
            print(f"  Querying {agent.name}...")
            try:
                events = agent.detect_events(news_input)
                print(f"    Found {len(events)} events")
                all_events.extend(events)
            except Exception as e:
                print(f"    Error: {e}")

        # Deduplicate by headline similarity (simple: exact match)
        seen_headlines = set()
        unique_events = []
        for event in all_events:
            norm = event.headline.lower().strip()
            if norm not in seen_headlines:
                seen_headlines.add(norm)
                unique_events.append(event)

        # Rank by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        unique_events.sort(key=lambda e: severity_order.get(e.severity, 4))

        print(f"\n  Total unique events detected: {len(unique_events)}")
        for i, event in enumerate(unique_events, 1):
            print(f"    {i}. {event}")

        # Save events
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for event in unique_events:
            filepath = config.EVENTS_DIR / f"{timestamp}_{event.id}.json"
            event.save(str(filepath))

        return unique_events

    # ───────────────────────────────────────────────────────────
    # PHASE 2: CAUSAL GRAPH
    # ───────────────────────────────────────────────────────────

    def build_causal_graph(self, event: Event) -> CausalGraph:
        """All domain agents contribute causal links for a given event."""
        print("\n" + "=" * 70)
        print("  PHASE 2: CAUSAL GRAPH CONSTRUCTION")
        print("=" * 70)
        print(f"  Event: {event.headline}")

        graph = CausalGraph(
            event_id=event.id,
            event_headline=event.headline,
        )

        for agent in self.domain_agents:
            print(f"  Building causal links from {agent.name}...")
            try:
                links = agent.build_causal_links(event)
                print(f"    Produced {len(links)} links")
                graph.add_links(links)
            except Exception as e:
                print(f"    Error: {e}")

        # Report conflicts
        conflicts = graph.get_conflicts()
        if conflicts:
            print(f"\n  Conflicts detected: {len(conflicts)}")
            for c in conflicts:
                print(f"    {c['metric']} ({c['company']}): "
                      f"directions={c['directions']} by {c['agents']}")
        else:
            print(f"\n  No conflicts detected among {len(graph.links)} links")

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.CAUSAL_GRAPHS_DIR / f"{timestamp}_{event.id}_causal.json"
        graph.save(str(filepath))
        print(f"  Saved causal graph to {filepath}")

        return graph

    # ───────────────────────────────────────────────────────────
    # PHASE 3: MULTI-AGENT DEBATE
    # ───────────────────────────────────────────────────────────

    def run_debate(self, event: Event, graph: CausalGraph) -> DebateSession:
        """For each debatable metric, agents defend positions, PM resolves."""
        print("\n" + "=" * 70)
        print("  PHASE 3: MULTI-AGENT DEBATE")
        print("=" * 70)

        session = DebateSession(
            event_id=event.id,
            event_headline=event.headline,
        )

        # Get unique metrics to debate
        metrics_to_debate = graph.get_unique_metrics()
        if not metrics_to_debate:
            print("  No metrics to debate.")
            return session

        print(f"  Debating {len(metrics_to_debate)} metric(s)...\n")

        for i, metric_info in enumerate(metrics_to_debate, 1):
            metric = metric_info['metric']
            company = metric_info['company']
            periods = metric_info['periods']

            # Skip metrics for companies without DCF engines
            if company not in self.engines and company == 'NVDA':
                pass  # proceed, we have NVDA
            elif company not in self.engines:
                print(f"  Skipping {metric} for {company} (no DCF engine)")
                continue

            print(f"  --- Debate {i}: {metric} for {company} ---")

            # Debate each period
            for period in periods:
                positions = []
                round_num = len(session.rounds) + 1
                debate_round = DebateRound(
                    round_number=round_num,
                    metric=metric,
                    company=company,
                    positions=[],
                )

                # Each relevant agent provides a position
                for agent in self.domain_agents:
                    try:
                        other_pos = [p.to_dict() for p in positions]
                        result = agent.debate_position(
                            event, metric, company, period, other_pos
                        )

                        # Company analysts return {} for non-matching tickers
                        if not result:
                            continue

                        pos = DebatePosition(
                            agent_name=agent.name,
                            metric=metric,
                            company=company,
                            period=period,
                            proposed_value=float(result.get('proposed_value', 0)),
                            confidence=float(result.get('confidence', 0.5)),
                            reasoning=result.get('reasoning', ''),
                            data_type=result.get('data_type', 'unknown'),
                        )
                        positions.append(pos)
                        print(f"    {agent.name}: {pos.proposed_value:+.4f} "
                              f"(conf: {pos.confidence:.0%})")

                    except Exception as e:
                        print(f"    {agent.name}: Error - {e}")

                debate_round.positions = positions

                # PM asks probing question
                pm_question = self._ask_probing_question(event, metric, company, period, positions)
                debate_round.pm_probing_question = pm_question
                print(f"    PM probe: {pm_question[:100]}...")

                # Devil's Advocate: lowest-confidence agent challenges consensus
                da_challenge = self._devils_advocate(event, metric, company, period, positions)
                debate_round.devils_advocate_challenge = da_challenge

                session.add_round(debate_round)

                # PM resolves the debate
                resolution = self._resolve_debate(event, metric, company, period,
                                                   positions, pm_question, da_challenge)
                session.add_resolution(resolution)
                print(f"    RESOLVED: {resolution.resolved_values} "
                      f"(conf: {resolution.confidence:.0%})\n")

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.DEBATES_DIR / f"{timestamp}_{event.id}_debate.json"
        session.save(str(filepath))
        print(f"  Saved debate session to {filepath}")

        return session

    def _ask_probing_question(self, event, metric, company, period, positions):
        """PM asks a probing question to distinguish leading vs lagging indicators."""
        positions_text = ""
        for p in positions:
            positions_text += (f"\n  - {p.agent_name}: value={p.proposed_value:+.4f}, "
                              f"confidence={p.confidence:.0%}, "
                              f"data_type={p.data_type}, "
                              f"reasoning={p.reasoning[:150]}")

        prompt = f"""As the Portfolio Manager, you need to probe the expert positions on this metric.

EVENT: {event.headline}
METRIC: {metric} for {company}, PERIOD: {period}

Expert positions:{positions_text}

Ask ONE probing question that helps distinguish:
1. Which evidence is a LEADING indicator vs LAGGING indicator for this event?
2. What assumptions might be wrong?
3. What is the time horizon for this impact?

Return a JSON object with key "question" containing your probing question."""

        result = self.call_llm_json(prompt)
        return result.get('question', '')

    def _devils_advocate(self, event, metric, company, period, positions):
        """Challenge the emerging consensus."""
        if not positions:
            return ""

        # Find the consensus direction
        values = [p.proposed_value for p in positions]
        avg_value = sum(values) / len(values) if values else 0
        direction = "positive" if avg_value > 0 else "negative" if avg_value < 0 else "neutral"

        prompt = f"""As Devil's Advocate, challenge the emerging consensus among the experts.

EVENT: {event.headline}
METRIC: {metric} for {company}, PERIOD: {period}
CONSENSUS DIRECTION: {direction} (average proposed change: {avg_value:+.4f})

The experts generally agree this event will have a {direction} impact on {metric}.

Challenge this consensus:
1. What could make the opposite happen?
2. What are the experts overlooking?
3. Is the magnitude being over/underestimated?

Return a JSON object with key "challenge" containing your devil's advocate argument (2-3 sentences)."""

        result = self.call_llm_json(prompt)
        return result.get('challenge', '')

    def _resolve_debate(self, event, metric, company, period, positions,
                        pm_question, da_challenge):
        """PM makes final decision on the driver adjustment."""
        positions_text = ""
        for p in positions:
            positions_text += (f"\n  - {p.agent_name}: value={p.proposed_value:+.4f}, "
                              f"confidence={p.confidence:.0%}, "
                              f"data_type={p.data_type}, "
                              f"reasoning={p.reasoning[:200]}")

        prompt = f"""As Portfolio Manager, resolve this debate and decide the final driver adjustment.

EVENT: {event.headline}
METRIC: {metric} for {company}, PERIOD: {period}

Expert positions:{positions_text}

Probing question asked: {pm_question}
Devil's advocate challenge: {da_challenge}

Rules for resolution:
1. Weight LEADING indicators more heavily than LAGGING indicators
2. Higher-confidence positions carry more weight
3. Consider the devil's advocate challenge — does it change your view?
4. Be conservative: when uncertain, adjust less rather than more

Return a JSON object with:
- resolved_value: float (the final delta to apply to the baseline driver)
- confidence: float 0.0 to 1.0
- rationale: 2-3 sentence explanation of your decision
- contributing_agents: list of agent names whose views you weighted most
- dissenting_agents: list of agent names whose views you discounted"""

        result = self.call_llm_json(prompt)

        return DebateResolution(
            metric=metric,
            company=company,
            resolved_values={period: float(result.get('resolved_value', 0))},
            confidence=float(result.get('confidence', 0.5)),
            rationale=result.get('rationale', ''),
            contributing_agents=result.get('contributing_agents', []),
            dissenting_agents=result.get('dissenting_agents', []),
        )

    # ───────────────────────────────────────────────────────────
    # PHASE 4: DCF VALUATION
    # ───────────────────────────────────────────────────────────

    def apply_to_dcf(self, company: str, session: DebateSession) -> dict:
        """Translate debate resolutions into DCF driver updates and compute valuation."""
        print("\n" + "=" * 70)
        print("  PHASE 4: DCF VALUATION")
        print("=" * 70)

        if company not in self.engines:
            print(f"  No DCF engine for {company}")
            return {}

        engine = self.engines[company]

        # Get baseline valuation
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']
        print(f"  Baseline implied price: ${baseline_price:,.2f}")

        # Get driver changes from debate
        debate_changes = session.get_driver_changes()

        # Get company analyst's direct assessment
        analyst_pkg = None
        if company in self.company_analysts:
            print(f"\n  Fetching {company} analyst's direct assessment...")
            analyst_pkg = self.company_analysts[company].produce_driver_update()
            if analyst_pkg and analyst_pkg.driver_updates:
                print(f"    Analyst summary: {analyst_pkg.analyst_summary[:120]}")
                print(f"    Analyst confidence: {analyst_pkg.confidence:.0%}")
                for drv, periods in analyst_pkg.driver_updates.items():
                    for period, val in periods.items():
                        print(f"    analyst {drv}[{period}] = {val:+.4f}")
            else:
                print(f"    No analyst driver updates for {company}")

        # Reconcile debate changes with analyst package
        if debate_changes or (analyst_pkg and analyst_pkg.driver_updates):
            filtered_changes = self._reconcile_analyst_with_debate(
                company, debate_changes, analyst_pkg, engine
            )
        else:
            print("  No driver changes from debate or analyst")
            return baseline

        if not filtered_changes:
            print("  No valid driver changes after reconciliation")
            return baseline

        print(f"\n  Applying reconciled driver changes:")
        for driver, periods in filtered_changes.items():
            for period, value in periods.items():
                print(f"    {driver}[{period}] += {value:+.4f}")

        # Apply changes as deltas (add to current baseline values)
        delta_changes = {}
        for driver, periods in filtered_changes.items():
            delta_changes[driver] = {}
            for period, delta in periods.items():
                current = engine.drivers.get(driver, {}).get(period, 0)
                delta_changes[driver][period] = current + delta

        engine.update_drivers(delta_changes)
        result = engine.compute_dcf()

        # Print summary
        print(f"\n  Council-adjusted implied price: ${result['implied_price']:,.2f}")
        print(f"  Current market price:           ${result['current_price']:,.2f}")
        print(f"  Upside/Downside:                {result['upside']:+.1%}")
        alpha = result['implied_price'] - baseline_price
        print(f"  Intrinsic Value Alpha:          ${alpha:+,.2f} vs baseline")

        # Save valuation result
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        valuation_output = {
            'company': company,
            'event_id': session.event_id,
            'event_headline': session.event_headline,
            'timestamp': timestamp,
            'baseline_price': baseline_price,
            'council_price': result['implied_price'],
            'current_price': result['current_price'],
            'upside': result['upside'],
            'alpha_vs_baseline': alpha,
            'wacc': result['wacc'],
            'driver_changes': filtered_changes,
            'enterprise_value': result['enterprise_value'],
            'equity_value': result['equity_value'],
            'analyst_summary': analyst_pkg.analyst_summary if analyst_pkg else '',
            'analyst_confidence': analyst_pkg.confidence if analyst_pkg else 0.0,
        }
        filepath = config.VALUATIONS_DIR / f"{timestamp}_{company}_valuation.json"
        with open(filepath, 'w') as f:
            json.dump(valuation_output, f, indent=2)
        print(f"  Saved valuation to {filepath}")

        return result

    def _reconcile_analyst_with_debate(self, company: str, debate_changes: dict,
                                        analyst_pkg, engine) -> dict:
        """Use PM's LLM to merge debate-resolved changes with analyst's driver package."""
        valid_drivers = set(engine.drivers.keys())

        # If only one source has data, use it directly (no LLM call needed)
        has_debate = bool(debate_changes)
        has_analyst = bool(analyst_pkg and analyst_pkg.driver_updates)

        if has_debate and not has_analyst:
            return {d: p for d, p in debate_changes.items() if d in valid_drivers}
        if has_analyst and not has_debate:
            return {d: p for d, p in analyst_pkg.driver_updates.items() if d in valid_drivers}

        # Both sources have data — use LLM to reconcile
        debate_text = json.dumps(debate_changes, indent=2)
        analyst_text = json.dumps(analyst_pkg.driver_updates, indent=2)
        rationale_text = json.dumps(analyst_pkg.rationale, indent=2)

        prompt = f"""As Portfolio Manager, reconcile two sources of driver change recommendations for {company}.

SOURCE 1 — Multi-Agent Debate Resolution (consensus from 5+ domain experts):
{debate_text}

SOURCE 2 — Company News Analyst (based on real-time IR/SEC/finviz news, confidence={analyst_pkg.confidence:.0%}):
Driver updates: {analyst_text}
Rationale: {rationale_text}
Summary: {analyst_pkg.analyst_summary}

Rules for reconciliation:
1. Company-specific news (Source 2) is a strong signal for near-term periods (Q4-26 through Q4-27)
2. Domain expert consensus (Source 1) captures broader macro/geopolitical effects
3. When both agree on direction, use the average magnitude
4. When they disagree, weight higher-confidence source more heavily
5. Be conservative — when uncertain, adjust less

Return a JSON object with key "merged_changes" mapping driver_name -> {{period: delta_value}}.
Only include valid drivers: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Only include valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""

        result = self.call_llm_json(prompt)
        merged = result.get('merged_changes', {})

        # Validate
        filtered = {}
        for driver, periods in merged.items():
            if driver not in valid_drivers:
                print(f"  [PM] Stripping invalid driver from reconciliation: {driver}")
                continue
            if isinstance(periods, dict):
                valid_periods = {p: float(v) for p, v in periods.items()
                                 if p in {'Q4-26', 'Q1-27', 'Q2-27', 'Q3-27', 'Q4-27',
                                           'FY2028', 'FY2029', 'FY2030'}}
                if valid_periods:
                    filtered[driver] = valid_periods

        return filtered

    # ───────────────────────────────────────────────────────────
    # FULL PIPELINE
    # ───────────────────────────────────────────────────────────

    def run_full_pipeline(self, news_input: str, target_company: str = 'NVDA') -> dict:
        """Run all 4 phases end-to-end."""
        print("\n" + "#" * 70)
        print("  COUNCIL OF AGENTS — SEMICONDUCTOR VALUATION PIPELINE")
        print("#" * 70)
        print(f"  Target: {target_company}")
        print(f"  Input: {news_input[:100]}...")
        start_time = datetime.now()

        # Phase 1: Event Detection
        events = self.detect_events(news_input)
        if not events:
            print("\n  No events detected. Pipeline complete.")
            return {}

        # Use the highest-severity event for the pipeline
        primary_event = events[0]
        print(f"\n  Primary event: {primary_event}")

        # Phase 2: Causal Graph
        graph = self.build_causal_graph(primary_event)

        # Phase 3: Debate (only for target company links)
        # Filter graph to target company
        target_links = graph.get_links_for_company(target_company)
        if not target_links:
            print(f"\n  No causal links for {target_company}. Skipping debate.")
            return {}

        target_graph = CausalGraph(
            event_id=primary_event.id,
            event_headline=primary_event.headline,
            links=target_links,
        )

        session = self.run_debate(primary_event, target_graph)

        # Phase 4: DCF Valuation
        result = self.apply_to_dcf(target_company, session)

        # Print token usage
        elapsed = (datetime.now() - start_time).total_seconds()
        total_tokens = self.total_tokens()
        for agent in self.domain_agents:
            total_tokens += agent.total_tokens()

        print("\n" + "#" * 70)
        print("  PIPELINE COMPLETE")
        print("#" * 70)
        print(f"  Events detected:    {len(events)}")
        print(f"  Causal links:       {len(graph.links)}")
        print(f"  Debate rounds:      {len(session.rounds)}")
        print(f"  Resolutions:        {len(session.resolutions)}")
        if result:
            print(f"  Implied price:      ${result.get('implied_price', 0):,.2f}")
            print(f"  Upside:             {result.get('upside', 0):+.1%}")
        print(f"  Total tokens used:  {total_tokens:,}")
        print(f"  Elapsed time:       {elapsed:.1f}s")
        print("#" * 70 + "\n")

        return result
