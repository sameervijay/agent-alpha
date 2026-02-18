"""
Portfolio Manager Agent — orchestrates the 4-phase pipeline.
Phase 1: Event Detection (all 5 domain agents)
Phase 2: Causal Graph construction
Phase 3: Multi-Agent Debate with Devil's Advocate
Phase 4: DCF Valuation via NVDADCFEngine
"""

import json
import time
from datetime import datetime
from pathlib import Path

from agents.base_agent import BaseAgent
from agents.politics_agent import PoliticsAgent
from agents.stock_market_agent import StockMarketAgent
from agents.commodities_agent import CommoditiesAgent
from agents.tech_publications_agent import TechPublicationsAgent
from agents.macro_agent import MacroAgent
from agents.company_analyst_agent import CompanyAnalystAgent
from agents.macro_analyst_agent import MacroAnalystAgent
from models.event import Event
from models.causal_graph import CausalGraph, CausalLink
from models.debate import (DebatePosition, DebateRound, DebateResolution,
                            DebateSession)
from models.update_session import (AnalystUpdateBrief, PMChallenge,
                                    AnalystResponse, PMDecision, UpdateSession)
import config

# Import the existing DCF engines from models
from models.pm_agent_interface import NVDADCFEngine
from models.cdns_engine import CDNSDCFEngine


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
        self.stock_market_agent = StockMarketAgent()
        self.domain_agents = [
            PoliticsAgent(),
            self.stock_market_agent,
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

        # Initialize independent macro analyst
        self.macro_analyst = MacroAnalystAgent()
        print(f"  [PM] Initialized independent macro analyst")

        # Initialize DCF engines for companies with full models
        _ENGINE_MAP = {
            'NVDADCFEngine': NVDADCFEngine,
            'CDNSDCFEngine': CDNSDCFEngine,
        }
        self.engines = {}
        for ticker, comp in config.COMPANIES.items():
            if comp.get('has_full_model') and comp.get('excel_path'):
                engine_cls_name = comp.get('engine_class', '')
                engine_cls = _ENGINE_MAP.get(engine_cls_name)
                if engine_cls is None:
                    print(f"  [PM] Warning: Unknown engine class '{engine_cls_name}' for {ticker}")
                    continue
                try:
                    self.engines[ticker] = engine_cls(comp['excel_path'])
                    print(f"  [PM] Loaded {ticker} DCF engine from {comp['excel_path']}")
                except Exception as e:
                    print(f"  [PM] Warning: Could not load {ticker} DCF engine: {e}")

    # ───────────────────────────────────────────────────────────
    # Live market data
    # ───────────────────────────────────────────────────────────

    def get_current_prices(self, tickers: list = None) -> dict:
        """
        Get live stock prices from the Stock Market Agent (via yfinance).

        Args:
            tickers: list of tickers to fetch, or None for all tracked tickers + SPY

        Returns:
            dict mapping ticker -> price data
        """
        if tickers is None:
            # Default: all companies with DCF models + SPY
            tickers = list(self.engines.keys()) + ['SPY']

        return self.stock_market_agent.get_current_prices(tickers)

    def get_market_snapshot(self) -> dict:
        """Get a full market snapshot from the Stock Market Agent."""
        return self.stock_market_agent.get_market_snapshot()

    # ───────────────────────────────────────────────────────────
    # Macro overview (pure file read, no LLM)
    # ───────────────────────────────────────────────────────────

    def get_macro_overview(self) -> dict:
        """Read the independent macro analyst's current view. No LLM call."""
        return self.macro_analyst.get_view_summary()

    # ───────────────────────────────────────────────────────────
    # PHASE 1: EVENT DETECTION
    # ───────────────────────────────────────────────────────────

    def detect_events(self, news_input: str) -> list:
        """Call all 5 domain agents to detect events, deduplicate, rank by severity."""
        print("\n" + "=" * 70)
        print("  PHASE 1 / 4 : EVENT DETECTION")
        print("=" * 70)
        phase_start = time.time()

        all_events = []
        total_agents = len(self.domain_agents)
        for idx, agent in enumerate(self.domain_agents, 1):
            print(f"  [{idx}/{total_agents}] Querying {agent.name}...")
            try:
                t0 = time.time()
                events = agent.detect_events(news_input)
                print(f"    -> {len(events)} event(s)  ({time.time() - t0:.1f}s)")
                all_events.extend(events)
            except Exception as e:
                print(f"    -> Error: {e}")

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

        print(f"\n  Phase 1 complete in {time.time() - phase_start:.1f}s")
        return unique_events

    # ───────────────────────────────────────────────────────────
    # PHASE 2: CAUSAL GRAPH
    # ───────────────────────────────────────────────────────────

    def build_causal_graph(self, event: Event) -> CausalGraph:
        """All domain agents contribute causal links for a given event."""
        print("\n" + "=" * 70)
        print("  PHASE 2 / 4 : CAUSAL GRAPH CONSTRUCTION")
        print("=" * 70)
        print(f"  Event: {event.headline}")
        phase_start = time.time()

        graph = CausalGraph(
            event_id=event.id,
            event_headline=event.headline,
        )

        total_agents = len(self.domain_agents)
        for idx, agent in enumerate(self.domain_agents, 1):
            print(f"  [{idx}/{total_agents}] Building causal links from {agent.name}...")
            try:
                t0 = time.time()
                links = agent.build_causal_links(event)
                print(f"    -> {len(links)} link(s)  ({time.time() - t0:.1f}s)")
                graph.add_links(links)
            except Exception as e:
                print(f"    -> Error: {e}")

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
        print(f"\n  Phase 2 complete in {time.time() - phase_start:.1f}s")

        return graph

    # ───────────────────────────────────────────────────────────
    # PHASE 3: MULTI-AGENT DEBATE
    # ───────────────────────────────────────────────────────────

    def run_debate(self, event: Event, graph: CausalGraph) -> DebateSession:
        """For each debatable metric, agents defend positions, PM resolves."""
        print("\n" + "=" * 70)
        print("  PHASE 3 / 4 : MULTI-AGENT DEBATE")
        print("=" * 70)
        phase_start = time.time()

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

        total_metrics = len(metrics_to_debate)
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

            print(f"  --- Debate [{i}/{total_metrics}]: {metric} for {company} "
                  f"({len(periods)} period(s)) ---")

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
                print(f"    PM formulating probing question...")
                pm_question = self._ask_probing_question(event, metric, company, period, positions)
                debate_round.pm_probing_question = pm_question
                print(f"    PM probe: {pm_question[:100]}...")

                # Devil's Advocate: lowest-confidence agent challenges consensus
                print(f"    Running devil's advocate challenge...")
                da_challenge = self._devils_advocate(event, metric, company, period, positions)
                debate_round.devils_advocate_challenge = da_challenge

                session.add_round(debate_round)

                # PM resolves the debate
                print(f"    PM resolving debate for {period}...")
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
        print(f"\n  Phase 3 complete in {time.time() - phase_start:.1f}s")

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
        print("  PHASE 4 / 4 : DCF VALUATION")
        print("=" * 70)
        phase_start = time.time()

        if company not in self.engines:
            print(f"  No DCF engine for {company}")
            return {}

        engine = self.engines[company]

        # Get baseline valuation
        print(f"  Computing baseline DCF valuation for {company}...")
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
            print(f"\n  Reconciling debate + analyst driver changes...")
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
        print(f"  Recomputing DCF with adjusted drivers...")
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
        print(f"\n  Phase 4 complete in {time.time() - phase_start:.1f}s")

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

        # Include macro view as optional third context source
        macro_context = ""
        macro_overview = self.get_macro_overview()
        if macro_overview.get('status') == 'active':
            macro_context = f"""

SOURCE 3 — Independent Macro Analyst (macro environment context):
Outlook: {macro_overview['outlook']}
Summary: {macro_overview['summary']}
Key themes: {', '.join(macro_overview.get('key_themes', []))}
Risk factors: {', '.join(macro_overview.get('risk_factors', []))}
Confidence: {macro_overview.get('confidence', 0):.0%}"""

        prompt = f"""As Portfolio Manager, reconcile the sources of driver change recommendations for {company}.

SOURCE 1 — Multi-Agent Debate Resolution (consensus from 5+ domain experts):
{debate_text}

SOURCE 2 — Company News Analyst (based on real-time IR/SEC/finviz news, confidence={analyst_pkg.confidence:.0%}):
Driver updates: {analyst_text}
Rationale: {rationale_text}
Summary: {analyst_pkg.analyst_summary}
{macro_context}

Rules for reconciliation:
1. Company-specific news (Source 2) is a strong signal for near-term periods (Q4-26 through Q4-27)
2. Domain expert consensus (Source 1) captures broader macro/geopolitical effects
3. Macro context (Source 3, if available) provides rate/GDP/inflation backdrop — use it to sanity-check
   demand and margin assumptions but don't let it override company-specific evidence
4. When both agree on direction, use the average magnitude
5. When they disagree, weight higher-confidence source more heavily
6. Be conservative — when uncertain, adjust less

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
    # PM "REQUEST UPDATE" — multi-turn dialogue with analyst
    # ───────────────────────────────────────────────────────────

    def request_update(self, ticker: str) -> UpdateSession:
        """Initiate a focused update dialogue with a company analyst.
        Flow: Analyst Brief → PM Challenges → Analyst Responds → PM Decision → DCF.
        """
        print("\n" + "=" * 70)
        print(f"  PM REQUEST UPDATE — {ticker}")
        print("=" * 70)
        start_time = datetime.now()

        if ticker not in self.company_analysts:
            print(f"  Error: No analyst for {ticker}. Available: {list(self.company_analysts.keys())}")
            return UpdateSession(ticker=ticker)

        analyst = self.company_analysts[ticker]
        session = UpdateSession(ticker=ticker)

        # Phase 1: Analyst Brief
        print(f"\n  Phase 1/5: Analyst Brief")
        print(f"  {'─' * 50}")
        brief = self._get_analyst_brief(analyst, ticker)
        session.brief = brief
        print(f"    Summary: {brief.summary[:120]}...")
        print(f"    Confidence: {brief.confidence:.0%}")
        if brief.recommended_changes:
            print(f"    Recommended changes:")
            for drv, periods in brief.recommended_changes.items():
                for period, val in periods.items():
                    print(f"      {drv}[{period}] = {val:+.4f}")
        else:
            print(f"    No recommended changes (stable view)")

        # Phase 2: PM Challenges
        print(f"\n  Phase 2/5: PM Challenges")
        print(f"  {'─' * 50}")
        challenges = self._generate_update_challenges(brief, ticker)
        session.challenges = challenges
        for i, ch in enumerate(challenges, 1):
            print(f"    Challenge {i} [{ch.challenge_type}]: {ch.question[:100]}...")
            print(f"      Targeting: {', '.join(ch.target_drivers)}")

        # Phase 3: Analyst Responds to each challenge
        print(f"\n  Phase 3/5: Analyst Responses")
        print(f"  {'─' * 50}")
        view = analyst._load_view()
        for ch in challenges:
            print(f"    Responding to challenge {ch.challenge_id}...")
            result = analyst.respond_to_challenge(ch.question, ch.target_drivers, view)
            resp = AnalystResponse(
                challenge_id=ch.challenge_id,
                response=result['response'],
                revised_drivers=result['revised_drivers'],
                confidence_after=result['confidence_after'],
                concedes=result['concedes'],
            )
            session.responses.append(resp)
            status = "CONCEDES" if resp.concedes else "DEFENDS"
            print(f"    [{status}] {resp.response[:100]}...")
            if resp.revised_drivers:
                for drv, periods in resp.revised_drivers.items():
                    for period, val in periods.items():
                        print(f"      Revised: {drv}[{period}] = {val:+.4f}")

        # Phase 4: PM Decision
        print(f"\n  Phase 4/5: PM Decision")
        print(f"  {'─' * 50}")
        decision = self._make_update_decision(session, ticker)
        session.decision = decision
        print(f"    Action: {decision.action.upper()}")
        print(f"    Confidence: {decision.confidence:.0%}")
        print(f"    Rationale: {decision.rationale[:150]}...")
        if decision.final_drivers:
            print(f"    Final driver changes:")
            for drv, periods in decision.final_drivers.items():
                for period, val in periods.items():
                    print(f"      {drv}[{period}] = {val:+.4f}")

        # Phase 5: DCF Application (no LLM)
        print(f"\n  Phase 5/5: DCF Application")
        print(f"  {'─' * 50}")
        if decision.action in ('accept', 'modify') and decision.final_drivers:
            val_result = self._apply_update_to_dcf(ticker, decision.final_drivers)
            if val_result:
                decision.valuation_result = val_result
                print(f"    Baseline price:  ${val_result.get('baseline_price', 0):,.2f}")
                print(f"    Updated price:   ${val_result.get('updated_price', 0):,.2f}")
                print(f"    Upside:          {val_result.get('upside', 0):+.1%}")
            else:
                print(f"    No DCF engine for {ticker} — skipping valuation")
        else:
            print(f"    No changes to apply (action={decision.action})")

        # Finalize session
        session.completed_at = datetime.now().isoformat()
        # Tally LLM usage across PM + analyst
        session.llm_calls = len(self.call_log) + len(analyst.call_log)
        session.total_tokens = self.total_tokens() + analyst.total_tokens()

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.UPDATE_SESSIONS_DIR / f"{timestamp}_{ticker}_update.json"
        session.save(str(filepath))

        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n  {'=' * 50}")
        print(f"  Update session complete for {ticker}")
        print(f"  Session ID:   {session.session_id}")
        print(f"  LLM calls:    {session.llm_calls}")
        print(f"  Total tokens: {session.total_tokens:,}")
        print(f"  Elapsed:      {elapsed:.1f}s")
        print(f"  Saved to:     {filepath}")
        print("=" * 70 + "\n")

        return session

    def _get_analyst_brief(self, analyst, ticker: str) -> AnalystUpdateBrief:
        """Phase 1: Get analyst's current view and recommended changes."""
        # Run the analyst's produce_driver_update (ramp or monitor)
        pkg = analyst.produce_driver_update()

        # Load the full view for rationale and news context
        view = analyst._load_view()
        rationale = view.rationale if view else {}
        news_context = [n.headline for n in analyst._cached_news[:10]] if analyst._cached_news else []

        # Identify non-zero recommended changes
        recommended_changes = {}
        if pkg.driver_updates:
            for drv, periods in pkg.driver_updates.items():
                non_zero = {p: v for p, v in periods.items() if abs(v) > 1e-6}
                if non_zero:
                    recommended_changes[drv] = non_zero

        return AnalystUpdateBrief(
            ticker=ticker,
            summary=pkg.analyst_summary,
            driver_snapshot=pkg.driver_updates,
            rationale=rationale,
            confidence=pkg.confidence,
            recommended_changes=recommended_changes,
            change_explanation=view.summary if view else '',
            news_context=news_context,
        )

    def _generate_update_challenges(self, brief: AnalystUpdateBrief,
                                     ticker: str) -> list:
        """Phase 2: PM generates 2-4 pointed challenge questions."""
        # Include macro context
        macro_context = ""
        macro_overview = self.get_macro_overview()
        if macro_overview.get('status') == 'active':
            macro_context = f"""
MACRO CONTEXT:
Outlook: {macro_overview['outlook']}
Summary: {macro_overview['summary']}
Key themes: {', '.join(macro_overview.get('key_themes', []))}
Risk factors: {', '.join(macro_overview.get('risk_factors', []))}"""

        brief_text = json.dumps({
            'summary': brief.summary,
            'driver_snapshot': brief.driver_snapshot,
            'rationale': brief.rationale,
            'confidence': brief.confidence,
            'recommended_changes': brief.recommended_changes,
            'change_explanation': brief.change_explanation,
        }, indent=2)

        prompt = f"""As Portfolio Manager, you are reviewing the {ticker} analyst's current view and recommended changes.

ANALYST BRIEF:
{brief_text}

RECENT NEWS CONTEXT:
{chr(10).join(f'- {h}' for h in brief.news_context[:8]) if brief.news_context else '(no recent news)'}
{macro_context}

Generate 2-4 pointed challenge questions targeting the WEAKEST assumptions in the analyst's view.
Focus on areas where:
1. The evidence seems thin or dated
2. The magnitude of change seems too aggressive or too conservative
3. The timing of impact may be wrong
4. There are risks the analyst may be underweighting

Return a JSON object with key "challenges", where each challenge has:
- target_drivers: list of 1-3 driver names being challenged
- question: the specific challenge question (1-2 sentences, pointed and specific)
- challenge_type: one of "assumption", "magnitude", "timing", "evidence", "risk"

Valid driver names: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps"""

        result = self.call_llm_json(prompt)

        challenges = []
        for c in result.get('challenges', [])[:4]:
            challenges.append(PMChallenge(
                target_drivers=c.get('target_drivers', []),
                question=c.get('question', ''),
                challenge_type=c.get('challenge_type', 'assumption'),
            ))

        return challenges

    def _make_update_decision(self, session: UpdateSession,
                               ticker: str) -> PMDecision:
        """Phase 4: PM evaluates full dialogue and decides accept/modify/reject."""
        # Build full dialogue transcript
        transcript_parts = []
        transcript_parts.append(f"ANALYST BRIEF:\n{json.dumps(session.brief.to_dict(), indent=2)}")

        for ch, resp in zip(session.challenges, session.responses):
            transcript_parts.append(
                f"\nPM CHALLENGE [{ch.challenge_type}] (targeting {', '.join(ch.target_drivers)}):\n"
                f"{ch.question}\n\n"
                f"ANALYST RESPONSE ({'CONCEDES' if resp.concedes else 'DEFENDS'}):\n"
                f"{resp.response}\n"
                f"Revised drivers: {json.dumps(resp.revised_drivers)}\n"
                f"Confidence after: {resp.confidence_after:.0%}"
            )

        transcript = "\n".join(transcript_parts)

        # Include macro context
        macro_context = ""
        macro_overview = self.get_macro_overview()
        if macro_overview.get('status') == 'active':
            macro_context = f"\nMACRO CONTEXT: {macro_overview['outlook']} — {macro_overview['summary']}"

        # Get ticker-specific drivers and periods
        from agents.company_analyst_agent import VALID_DRIVERS_BY_TICKER, VALID_PERIODS_BY_TICKER
        valid_drivers = VALID_DRIVERS_BY_TICKER.get(ticker, set())
        valid_periods = VALID_PERIODS_BY_TICKER.get(ticker, set())

        prompt = f"""As Portfolio Manager, evaluate the full dialogue with the {ticker} analyst and make your decision.

FULL DIALOGUE:
{transcript}
{macro_context}

Based on this dialogue, decide:
- ACCEPT: The analyst's recommended changes are well-supported. Use their driver values.
- MODIFY: The analyst has some good points but you want to adjust magnitudes or add/remove drivers.
- REJECT: The analyst's case is not convincing enough to change the portfolio.

Return a JSON object with:
- action: one of "accept", "modify", "reject"
- final_drivers: object mapping driver_name -> {{period: delta_value}} — the driver changes to apply (empty if reject)
  If accepting, use the analyst's recommended changes (with any revisions from the dialogue).
  If modifying, provide your adjusted values.
- rationale: 2-4 sentence explanation of your decision
- confidence: float 0.0 to 1.0

Valid driver names: {', '.join(sorted(valid_drivers))}
Valid periods: {', '.join(sorted(valid_periods))}"""

        result = self.call_llm_json(prompt)

        # Validate final_drivers
        from agents.company_analyst_agent import _validate_drivers
        final_drivers = _validate_drivers(result.get('final_drivers', {}), 'pm_agent', ticker)

        return PMDecision(
            action=result.get('action', 'reject'),
            final_drivers=final_drivers,
            rationale=result.get('rationale', ''),
            confidence=float(result.get('confidence', 0.0)),
        )

    def _apply_update_to_dcf(self, ticker: str,
                              driver_changes: dict):
        """Phase 5: Apply driver deltas to DCF engine and compute valuation.
        Returns valuation dict or None if no engine for this ticker.
        """
        if ticker not in self.engines:
            return None

        engine = self.engines[ticker]

        # Compute baseline
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']

        # Apply changes as deltas
        delta_changes = {}
        for driver, periods in driver_changes.items():
            if driver not in engine.drivers:
                continue
            delta_changes[driver] = {}
            for period, delta in periods.items():
                current = engine.drivers.get(driver, {}).get(period, 0)
                delta_changes[driver][period] = current + delta

        if not delta_changes:
            return None

        engine.update_drivers(delta_changes)
        result = engine.compute_dcf()

        val_result = {
            'baseline_price': baseline_price,
            'updated_price': result['implied_price'],
            'current_price': result['current_price'],
            'upside': result['upside'],
            'alpha_vs_baseline': result['implied_price'] - baseline_price,
            'wacc': result['wacc'],
            'enterprise_value': result['enterprise_value'],
            'equity_value': result['equity_value'],
            'driver_changes': driver_changes,
        }

        # Save valuation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.VALUATIONS_DIR / f"{timestamp}_{ticker}_update_valuation.json"
        with open(filepath, 'w') as f:
            json.dump(val_result, f, indent=2, default=str)
        print(f"    Saved valuation to {filepath}")

        return val_result

    # ───────────────────────────────────────────────────────────
    # FULL PIPELINE
    # ───────────────────────────────────────────────────────────

    def run_full_pipeline(self, news_input: str, target_company: str = 'NVDA') -> dict:
        """Run all 4 phases end-to-end."""
        print("\n" + "#" * 70)
        print("  COUNCIL OF AGENTS — SEMICONDUCTOR VALUATION PIPELINE")
        print("#" * 70)
        print(f"  Target company : {target_company}")
        print(f"  News input     : {news_input[:100]}...")
        print(f"  Agents loaded  : {len(self.domain_agents)} domain + PM")
        print(f"  DCF engines    : {list(self.engines.keys()) or 'none'}")
        print(f"  Started at     : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        start_time = datetime.now()

        # Print macro overview if available
        macro_overview = self.get_macro_overview()
        if macro_overview.get('status') == 'active':
            print(f"\n  Macro outlook  : {macro_overview['outlook'].upper()}")
            print(f"  Macro summary  : {macro_overview['summary'][:120]}...")
            if macro_overview.get('key_themes'):
                print(f"  Macro themes   : {', '.join(macro_overview['key_themes'][:3])}")

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

    # ───────────────────────────────────────────────────────────
    # PORTFOLIO BALANCING
    # ───────────────────────────────────────────────────────────

    def balance_portfolio(self) -> dict:
        """
        Analyze all available DCF valuations and allocate portfolio across
        S&P500 and individual stocks based on upside/downside and confidence.

        Returns:
            dict with:
              - allocations: {ticker: weight} where weights sum to 1.0
              - rationale: explanation of allocation decisions
              - valuations: {ticker: {upside, confidence, implied_price, ...}}
              - confidence: overall portfolio confidence 0.0-1.0
        """
        print("=" * 70)
        print("  PORTFOLIO BALANCING")
        print("=" * 70)

        if not self.engines:
            print("  No DCF engines available. Cannot balance portfolio.")
            return {
                'allocations': {'SPY': 1.0},
                'rationale': 'No individual stock DCF views available. 100% S&P500.',
                'valuations': {},
                'confidence': 0.0,
            }

        # Step 1: Get live market prices
        print("\nStep 1: Fetching live stock prices...")
        live_prices = self.get_current_prices()

        # Step 2: Gather DCF valuations for all stocks
        print("\nStep 2: Computing DCF valuations with live prices...")
        valuations = {}
        for ticker, engine in self.engines.items():
            try:
                # Get analyst view for confidence
                analyst = self.company_analysts.get(ticker)
                view = analyst._load_view() if analyst else None
                confidence = view.confidence if view else 0.5

                # Compute DCF
                result = engine.compute_dcf()

                # Override with live price if available
                live_price_data = live_prices.get(ticker, {})
                current_price = live_price_data.get('price', result['current_price'])
                if live_price_data.get('error'):
                    print(f"  {ticker}: Warning - using DCF file price due to fetch error")
                    current_price = result['current_price']

                # Recalculate upside with live price
                implied_price = result['implied_price']
                upside = (implied_price / current_price - 1) if current_price > 0 else 0

                valuations[ticker] = {
                    'implied_price': implied_price,
                    'current_price': current_price,
                    'upside': upside,
                    'wacc': result['wacc'],
                    'enterprise_value': result['enterprise_value'],
                    'confidence': confidence,
                    'price_source': 'live' if not live_price_data.get('error') else 'dcf_file',
                }

                print(f"  {ticker}: ${implied_price:,.2f} vs ${current_price:,.2f} "
                      f"({upside:+.1%}) [confidence: {confidence:.0%}] "
                      f"[price: {valuations[ticker]['price_source']}]")
            except Exception as e:
                print(f"  {ticker}: Error computing valuation: {e}")

        if not valuations:
            print("  No valuations computed. Defaulting to 100% S&P500.")
            return {
                'allocations': {'SPY': 1.0},
                'rationale': 'Could not compute any stock valuations. 100% S&P500.',
                'valuations': {},
                'confidence': 0.0,
            }

        # Step 3: Call LLM to make allocation decision
        print("\nStep 3: Determining optimal allocation...")

        # Format valuations for LLM
        val_summary = []
        for ticker, val in valuations.items():
            val_summary.append(
                f"{ticker}: Implied ${val['implied_price']:.2f} vs Current ${val['current_price']:.2f} "
                f"= {val['upside']:+.1%} upside | Analyst confidence: {val['confidence']:.0%}"
            )
        val_text = "\n".join(val_summary)

        # Include macro context
        macro_context = ""
        macro_overview = self.get_macro_overview()
        if macro_overview.get('status') == 'active':
            macro_context = f"\nMACRO CONTEXT:\n  Outlook: {macro_overview['outlook']}\n  Summary: {macro_overview['summary']}"

        prompt = f"""As Portfolio Manager, allocate a $1M portfolio across S&P500 (SPY) and individual semiconductor stocks.

CURRENT VALUATIONS:
{val_text}
{macro_context}

ALLOCATION RULES:
1. Weights must sum to 100%
2. Available tickers: SPY (S&P500 benchmark) + {', '.join(valuations.keys())}
3. Max 30% per individual stock (concentration risk)
4. Use upside/downside and analyst confidence to determine allocations
5. If all stocks overvalued with high confidence → allocate heavily to SPY
6. If stocks undervalued with high confidence → allocate more to stocks vs SPY
7. Weight both magnitude of upside AND confidence level
8. Consider macro backdrop when assessing risk appetite

Return a JSON object with:
- allocations: object mapping ticker -> weight (decimal, must sum to 1.0)
  Example: {{"SPY": 0.60, "NVDA": 0.25, "CDNS": 0.15}}
- rationale: 3-5 sentence explanation of your allocation logic
- confidence: float 0.0 to 1.0 (your confidence in this portfolio allocation)
- risk_level: one of "conservative", "moderate", "aggressive"

Think like a professional portfolio manager balancing risk and return."""

        result = self.call_llm_json(prompt)

        # Validate allocations
        allocations = result.get('allocations', {})
        total_weight = sum(allocations.values())

        # Normalize if needed
        if abs(total_weight - 1.0) > 0.01:
            print(f"  Warning: Allocations sum to {total_weight:.2%}, normalizing...")
            allocations = {k: v/total_weight for k, v in allocations.items()}
            total_weight = 1.0

        # Enforce max position constraint
        max_weight = config.MAX_POSITION_WEIGHT
        for ticker in list(allocations.keys()):
            if ticker != 'SPY' and allocations[ticker] > max_weight:
                print(f"  Warning: {ticker} allocation {allocations[ticker]:.1%} exceeds max {max_weight:.0%}, capping...")
                excess = allocations[ticker] - max_weight
                allocations[ticker] = max_weight
                allocations['SPY'] = allocations.get('SPY', 0) + excess

        # Re-normalize after capping
        total_weight = sum(allocations.values())
        allocations = {k: v/total_weight for k, v in allocations.items()}

        # Print results
        print("\n" + "─" * 70)
        print("  PORTFOLIO ALLOCATION")
        print("─" * 70)
        for ticker, weight in sorted(allocations.items(), key=lambda x: -x[1]):
            dollar_amt = weight * 1_000_000
            print(f"  {ticker:<6s}: {weight:>6.1%}  (${dollar_amt:>10,.0f})")
        print("─" * 70)
        print(f"  Risk Level:   {result.get('risk_level', 'unknown').upper()}")
        print(f"  Confidence:   {result.get('confidence', 0.0):.0%}")
        print(f"\n  Rationale:\n  {result.get('rationale', 'N/A')}")
        print("=" * 70 + "\n")

        # Save allocation
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        allocation_result = {
            'timestamp': timestamp,
            'allocations': allocations,
            'rationale': result.get('rationale', ''),
            'confidence': result.get('confidence', 0.0),
            'risk_level': result.get('risk_level', 'unknown'),
            'valuations': valuations,
            'macro_context': macro_overview if macro_overview.get('status') == 'active' else None,
        }

        filepath = config.VALUATIONS_DIR / f"{timestamp}_portfolio_allocation.json"
        with open(filepath, 'w') as f:
            json.dump(allocation_result, f, indent=2, default=str)
        print(f"Allocation saved to: {filepath}\n")

        return allocation_result
