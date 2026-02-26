"""
Portfolio Manager Agent — LangChain version.

Orchestrates the 4-phase pipeline using agents_langchain/ domain agents.
The PM's own reasoning (probing questions, devil's advocate, debate resolution,
portfolio allocation) is backed by create_agent() with market-data tools.
"""

import json
import time
from datetime import datetime
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import (
    build_model, cache_get, cache_set, clear_session_cache,
    extract_json, get_final_message,
)
from agents_langchain.macro_agent import MacroAgent
from agents_langchain.politics_agent import PoliticsAgent
from agents_langchain.stock_market_agent import StockMarketAgent
from agents_langchain.commodities_agent import CommoditiesAgent
from agents_langchain.tech_publications_agent import TechPublicationsAgent
from agents_langchain.company_analyst_agent import CompanyAnalystAgent

from models.event import Event
from models.causal_graph import CausalGraph, CausalLink
from models.debate import (DebatePosition, DebateRound, DebateResolution,
                            DebateSession)

import config

from models.pm_agent_interface import NVDADCFEngine
from models.cdns_engine import CDNSDCFEngine
from models.tsmc_engine import TSMCDCFEngine
from models.crwv_engine import CoreWeaveDCFEngine
from models.asml_engine import ASMLDCFEngine

PM_SYSTEM_PROMPT = """You are the Portfolio Manager (PM) for a semiconductor-focused investment fund.
You orchestrate a council of domain expert agents and make final investment decisions.

Your role:
1. Synthesize diverse expert perspectives into a coherent investment thesis
2. Identify where experts agree and where they disagree
3. Challenge weak arguments and ask probing questions
4. Translate qualitative insights into quantitative DCF driver adjustments
5. Make final portfolio allocation decisions backed by DCF valuations

You are analytical, skeptical of groupthink, and always ask "what could go wrong?"
You weight leading indicators more heavily than lagging indicators.

Use your tools to fetch live market data before making allocation decisions.
Always return your final answer as a single JSON object — no prose outside the JSON."""

_ENGINE_MAP = {
    'NVDADCFEngine': NVDADCFEngine,
    'CDNSDCFEngine': CDNSDCFEngine,
    'TSMCDCFEngine': TSMCDCFEngine,
    'CoreWeaveDCFEngine': CoreWeaveDCFEngine,
    'ASMLDCFEngine': ASMLDCFEngine,
}


# ── PM Tools ──────────────────────────────────────────────────────────────────

@tool
def get_all_live_prices() -> str:
    """Fetch current live stock prices for all portfolio tickers (NVDA, TSM, ASML, CDNS, CRWV) and SPY."""
    cached = cache_get("pm_live_prices")
    if cached:
        return cached
    try:
        import yfinance as yf
        tickers = list(config.COMPANIES.keys()) + ['SPY']
        result = {}
        for ticker in tickers:
            hist = yf.Ticker(ticker).history(period='5d')
            if not hist.empty:
                result[ticker] = {
                    'price': round(float(hist['Close'].iloc[-1]), 2),
                    'change_5d_pct': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100, 2
                    ),
                }
        out = json.dumps(result, indent=2)
        cache_set("pm_live_prices", out)
        return out
    except Exception as e:
        return f"Price fetch error: {e}"


@tool
def compute_dcf_valuation(ticker: str) -> str:
    """Compute the DCF implied price for a given ticker using the stored DCF engine."""
    try:
        comp = config.COMPANIES.get(ticker.upper())
        if not comp or not comp.get('has_full_model'):
            return f"No DCF model available for {ticker}."
        engine_cls = _ENGINE_MAP.get(comp['engine_class'])
        if not engine_cls:
            return f"Unknown engine class for {ticker}."
        engine = engine_cls(comp['excel_path'])
        result = engine.compute_dcf()
        return json.dumps({
            'ticker': ticker,
            'implied_price': round(result['implied_price'], 2),
            'current_price': round(result['current_price'], 2),
            'upside': round(result['upside'], 4),
            'wacc': result['wacc'],
        }, indent=2)
    except Exception as e:
        return f"DCF error for {ticker}: {e}"


@tool
def get_macro_overview() -> str:
    """Get the macro agent's current sector outlook and key themes (uses LangChain MacroAgent)."""
    cached = cache_get("macro_overview")
    if cached:
        return cached
    try:
        from agents_langchain.macro_agent import MacroAgent
        agent = MacroAgent()
        goal = (
            "Fetch relevant macro news (Fed policy, yields, inflation, GDP) and treasury yields, "
            "then provide a brief macro overview as a single JSON object with keys: "
            "outlook (1-2 sentences), key_themes (list of strings), risk_factors (list, max 3), "
            "confidence (0.0-1.0). No prose outside the JSON."
        )
        result = agent._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        overview = extract_json(get_final_message(result))
        out = json.dumps(overview, indent=2, default=str)
        cache_set("macro_overview", out)
        return out
    except Exception as e:
        return f"Macro overview unavailable: {e}"


# ── PMAgent ───────────────────────────────────────────────────────────────────

class PMAgent:
    """Portfolio Manager orchestrating the 4-phase LangChain pipeline."""

    def __init__(self):
        self.name = "pm_agent"
        self.role_description = "Portfolio Manager — Council Orchestrator"

        # Domain agents (all LangChain versions)
        self.stock_market_agent = StockMarketAgent()
        self.domain_agents = [
            PoliticsAgent(),
            self.stock_market_agent,
            CommoditiesAgent(),
            TechPublicationsAgent(),
            MacroAgent(),
        ]

        # Company analysts — one per ticker
        self.company_analysts = {}
        for ticker in config.COMPANIES:
            analyst = CompanyAnalystAgent(ticker)
            self.company_analysts[ticker] = analyst
            self.domain_agents.append(analyst)
        print(f"  [PM] Initialized {len(self.company_analysts)} company analyst agents")

        # DCF engines
        self.engines = {}
        for ticker, comp in config.COMPANIES.items():
            if comp.get('has_full_model') and comp.get('excel_path'):
                engine_cls = _ENGINE_MAP.get(comp.get('engine_class', ''))
                if engine_cls is None:
                    print(f"  [PM] Warning: Unknown engine class for {ticker}")
                    continue
                try:
                    self.engines[ticker] = engine_cls(comp['excel_path'])
                    print(f"  [PM] Loaded {ticker} DCF engine")
                except Exception as e:
                    print(f"  [PM] Warning: Could not load {ticker} DCF engine: {e}")

        # PM's own LangChain agent for reasoning tasks
        self._agent = create_agent(
            build_model(),
            tools=[get_all_live_prices, compute_dcf_valuation, get_macro_overview],
            system_prompt=PM_SYSTEM_PROMPT,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _pm_invoke(self, goal: str) -> dict:
        """Invoke the PM agent and parse the JSON result."""
        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return extract_json(get_final_message(result))

    # ── Phase 1: Event Detection ──────────────────────────────────────────────

    def detect_events(self, news_input: str) -> list:
        """Call all domain agents to detect events, deduplicate, rank by severity."""
        clear_session_cache()  # Fresh cache for each pipeline run
        print("\n" + "=" * 70)
        print("  PHASE 1 / 4 : EVENT DETECTION")
        print("=" * 70)
        phase_start = time.time()

        all_events = []
        for idx, agent in enumerate(self.domain_agents, 1):
            print(f"  [{idx}/{len(self.domain_agents)}] Querying {agent.name}...")
            try:
                t0 = time.time()
                events = agent.detect_events(news_input)
                print(f"    -> {len(events)} event(s)  ({time.time() - t0:.1f}s)")
                all_events.extend(events)
            except Exception as e:
                print(f"    -> Error: {e}")

        # Deduplicate
        seen = set()
        unique_events = []
        for event in all_events:
            norm = event.headline.lower().strip()
            if norm not in seen:
                seen.add(norm)
                unique_events.append(event)

        # Rank by severity
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        unique_events.sort(key=lambda e: severity_order.get(e.severity, 4))

        print(f"\n  Total unique events: {len(unique_events)}")
        for i, event in enumerate(unique_events, 1):
            print(f"    {i}. {event}")

        # Save
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        for event in unique_events:
            filepath = config.EVENTS_DIR / f"{timestamp}_{event.id}.json"
            event.save(str(filepath))

        print(f"  Phase 1 complete in {time.time() - phase_start:.1f}s")
        return unique_events

    # ── Phase 2: Causal Graph ─────────────────────────────────────────────────

    def build_causal_graph(self, event: Event) -> CausalGraph:
        """All domain agents contribute causal links for the given event."""
        print("\n" + "=" * 70)
        print("  PHASE 2 / 4 : CAUSAL GRAPH CONSTRUCTION")
        print("=" * 70)
        print(f"  Event: {event.headline}")
        phase_start = time.time()

        graph = CausalGraph(event_id=event.id, event_headline=event.headline)

        for idx, agent in enumerate(self.domain_agents, 1):
            print(f"  [{idx}/{len(self.domain_agents)}] {agent.name}...")
            try:
                t0 = time.time()
                links = agent.build_causal_links(event)
                print(f"    -> {len(links)} link(s)  ({time.time() - t0:.1f}s)")
                graph.add_links(links)
            except Exception as e:
                print(f"    -> Error: {e}")

        conflicts = graph.get_conflicts()
        if conflicts:
            print(f"\n  Conflicts detected: {len(conflicts)}")
            for c in conflicts:
                print(f"    {c['metric']} ({c['company']}): "
                      f"directions={c['directions']} by {c['agents']}")
        else:
            print(f"\n  No conflicts among {len(graph.links)} links")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.CAUSAL_GRAPHS_DIR / f"{timestamp}_{event.id}_causal.json"
        graph.save(str(filepath))
        print(f"  Saved causal graph → {filepath}")
        print(f"  Phase 2 complete in {time.time() - phase_start:.1f}s")
        return graph

    # ── Phase 3: Debate ───────────────────────────────────────────────────────

    def run_debate(self, event: Event, graph: CausalGraph) -> DebateSession:
        """Agents defend positions; PM (LangChain) probes, advocates, and resolves."""
        print("\n" + "=" * 70)
        print("  PHASE 3 / 4 : MULTI-AGENT DEBATE")
        print("=" * 70)
        phase_start = time.time()

        session = DebateSession(event_id=event.id, event_headline=event.headline)
        metrics_to_debate = graph.get_unique_metrics()

        if not metrics_to_debate:
            print("  No metrics to debate.")
            return session

        print(f"  Debating {len(metrics_to_debate)} metric(s)...\n")

        for i, metric_info in enumerate(metrics_to_debate, 1):
            metric = metric_info['metric']
            company = metric_info['company']
            periods = metric_info['periods']

            print(f"  --- Debate [{i}/{len(metrics_to_debate)}]: {metric} / {company} ---")

            for period in periods:
                positions = []
                debate_round = DebateRound(
                    round_number=len(session.rounds) + 1,
                    metric=metric,
                    company=company,
                    positions=[],
                )

                # Each agent provides a position
                for agent in self.domain_agents:
                    try:
                        result = agent.debate_position(
                            event, metric, company, period,
                            [p.to_dict() for p in positions]
                        )
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

                # PM: probing question (LangChain agent)
                print(f"    PM formulating probing question...")
                pm_question = self._ask_probing_question(event, metric, company, period, positions)
                debate_round.pm_probing_question = pm_question
                print(f"    PM probe: {pm_question[:100]}...")

                # PM: devil's advocate (LangChain agent)
                print(f"    Running devil's advocate...")
                da_challenge = self._devils_advocate(event, metric, company, period, positions)
                debate_round.devils_advocate_challenge = da_challenge

                session.add_round(debate_round)

                # PM: resolve (LangChain agent)
                print(f"    PM resolving for {period}...")
                resolution = self._resolve_debate(event, metric, company, period,
                                                   positions, pm_question, da_challenge)
                session.add_resolution(resolution)
                print(f"    RESOLVED: {resolution.resolved_values} "
                      f"(conf: {resolution.confidence:.0%})\n")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = config.DEBATES_DIR / f"{timestamp}_{event.id}_debate.json"
        session.save(str(filepath))
        print(f"  Saved debate → {filepath}")
        print(f"  Phase 3 complete in {time.time() - phase_start:.1f}s")
        return session

    def _ask_probing_question(self, event, metric, company, period, positions) -> str:
        positions_text = "\n".join(
            f"  - {p.agent_name}: value={p.proposed_value:+.4f}, "
            f"conf={p.confidence:.0%}, type={p.data_type}, "
            f"reasoning={p.reasoning[:150]}"
            for p in positions
        )
        goal = (
            f"As Portfolio Manager, ask ONE probing question about this debate.\n\n"
            f"EVENT: {event.headline}\n"
            f"METRIC: {metric} for {company}, PERIOD: {period}\n\n"
            f"Expert positions:\n{positions_text}\n\n"
            "The question should probe: which evidence is leading vs lagging, "
            "what assumptions might be wrong, or what the time horizon implies.\n\n"
            "Return a JSON object with key 'question'."
        )
        result = self._pm_invoke(goal)
        return result.get('question', '')

    def _devils_advocate(self, event, metric, company, period, positions) -> str:
        if not positions:
            return ""
        avg_value = sum(p.proposed_value for p in positions) / len(positions)
        direction = "positive" if avg_value > 0 else "negative" if avg_value < 0 else "neutral"
        goal = (
            f"As Devil's Advocate, challenge the {direction} consensus on {metric} for {company} / {period}.\n\n"
            f"EVENT: {event.headline}\n"
            f"Average proposed change: {avg_value:+.4f}\n\n"
            "What could make the opposite happen? What are experts missing? "
            "Is the magnitude over/underestimated?\n\n"
            "Return a JSON object with key 'challenge' (2-3 sentences)."
        )
        result = self._pm_invoke(goal)
        return result.get('challenge', '')

    def _resolve_debate(self, event, metric, company, period, positions,
                        pm_question, da_challenge) -> DebateResolution:
        positions_text = "\n".join(
            f"  - {p.agent_name}: value={p.proposed_value:+.4f}, "
            f"conf={p.confidence:.0%}, type={p.data_type}, "
            f"reasoning={p.reasoning[:200]}"
            for p in positions
        )
        goal = (
            f"As Portfolio Manager, resolve this debate and choose a final driver adjustment.\n\n"
            f"EVENT: {event.headline}\n"
            f"METRIC: {metric} for {company}, PERIOD: {period}\n\n"
            f"Expert positions:\n{positions_text}\n\n"
            f"Probing question: {pm_question}\n"
            f"Devil's advocate: {da_challenge}\n\n"
            "Rules: weight leading indicators > lagging; higher-confidence positions > lower; "
            "when uncertain, adjust less not more.\n\n"
            "Return a JSON object with:\n"
            "  resolved_value (float), confidence (0-1), rationale (2-3 sentences), "
            "contributing_agents (list), dissenting_agents (list)."
        )
        result = self._pm_invoke(goal)
        return DebateResolution(
            metric=metric,
            company=company,
            resolved_values={period: float(result.get('resolved_value', 0))},
            confidence=float(result.get('confidence', 0.5)),
            rationale=result.get('rationale', ''),
            contributing_agents=result.get('contributing_agents', []),
            dissenting_agents=result.get('dissenting_agents', []),
        )

    # ── Phase 4: DCF Valuation ────────────────────────────────────────────────

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
        baseline = engine.compute_dcf()
        baseline_price = baseline['implied_price']
        print(f"  Baseline implied price: ${baseline_price:,.2f}")

        debate_changes = session.get_driver_changes()
        if not debate_changes:
            print("  No driver changes from debate")
            return baseline

        # Apply as deltas
        delta_changes = {}
        for driver, periods in debate_changes.items():
            if driver not in engine.drivers:
                continue
            delta_changes[driver] = {}
            for period, delta in periods.items():
                current = engine.drivers.get(driver, {}).get(period, 0)
                delta_changes[driver][period] = current + delta

        if not delta_changes:
            return baseline

        print(f"  Applying driver changes:")
        for driver, periods in delta_changes.items():
            for period, value in periods.items():
                print(f"    {driver}[{period}] = {value:+.4f}")

        engine.update_drivers(delta_changes)
        result = engine.compute_dcf()
        alpha = result['implied_price'] - baseline_price

        print(f"\n  Council-adjusted price: ${result['implied_price']:,.2f}")
        print(f"  Current market price:   ${result['current_price']:,.2f}")
        print(f"  Upside/Downside:        {result['upside']:+.1%}")
        print(f"  Alpha vs baseline:      ${alpha:+,.2f}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        valuation_output = {
            'company': company,
            'event_id': session.event_id,
            'timestamp': timestamp,
            'baseline_price': baseline_price,
            'council_price': result['implied_price'],
            'current_price': result['current_price'],
            'upside': result['upside'],
            'alpha_vs_baseline': alpha,
            'wacc': result['wacc'],
            'driver_changes': debate_changes,
        }
        filepath = config.VALUATIONS_DIR / f"{timestamp}_{company}_valuation.json"
        with open(filepath, 'w') as f:
            json.dump(valuation_output, f, indent=2)
        print(f"  Saved valuation → {filepath}")
        print(f"  Phase 4 complete in {time.time() - phase_start:.1f}s")
        return result

    # ── Full Pipeline ─────────────────────────────────────────────────────────

    def run_full_pipeline(self, news_input: str, target_company: str = 'NVDA') -> dict:
        """Run all 4 phases end-to-end."""
        print("\n" + "#" * 70)
        print("  COUNCIL OF AGENTS — SEMICONDUCTOR VALUATION PIPELINE (LangChain)")
        print("#" * 70)
        print(f"  Target company : {target_company}")
        print(f"  News input     : {news_input[:100]}...")
        print(f"  Domain agents  : {len(self.domain_agents)}")
        print(f"  DCF engines    : {list(self.engines.keys()) or 'none'}")
        print(f"  Started        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        start_time = datetime.now()

        # Phase 1
        events = self.detect_events(news_input)
        if not events:
            print("\n  No events detected. Pipeline complete.")
            return {}

        primary_event = events[0]
        print(f"\n  Primary event: {primary_event}")

        # Phase 2
        graph = self.build_causal_graph(primary_event)

        # Phase 3 — filter to target company
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

        # Phase 4
        result = self.apply_to_dcf(target_company, session)

        elapsed = (datetime.now() - start_time).total_seconds()
        print("\n" + "#" * 70)
        print("  PIPELINE COMPLETE")
        print("#" * 70)
        print(f"  Events:       {len(events)}")
        print(f"  Causal links: {len(graph.links)}")
        print(f"  Debates:      {len(session.rounds)}")
        if result:
            print(f"  Implied price: ${result.get('implied_price', 0):,.2f}")
            print(f"  Upside:        {result.get('upside', 0):+.1%}")
        print(f"  Elapsed:       {elapsed:.1f}s")
        print("#" * 70 + "\n")
        return result

    # ── Portfolio Balancing ───────────────────────────────────────────────────

    def balance_portfolio(self) -> dict:
        """
        LangChain agent fetches live prices and DCF valuations autonomously,
        then decides the optimal allocation across S&P500 and individual stocks.
        """
        print("=" * 70)
        print("  PORTFOLIO BALANCING (LangChain)")
        print("=" * 70)

        if not self.engines:
            return {
                'allocations': {'SPY': 1.0},
                'rationale': 'No DCF models available. 100% S&P500.',
                'valuations': {},
                'confidence': 0.0,
            }

        tickers_with_models = list(self.engines.keys())

        goal = (
            "You are the Portfolio Manager making an allocation decision for a $1M fund.\n\n"
            f"Stocks with DCF models: {', '.join(tickers_with_models)}\n\n"
            "Steps:\n"
            f"1. Fetch live prices for all portfolio tickers.\n"
            f"2. Compute DCF valuations for: {', '.join(tickers_with_models)}.\n"
            "3. Get the macro overview for context.\n"
            "4. Decide the optimal allocation.\n\n"
            "Allocation rules:\n"
            "- Weights must sum to 1.0\n"
            "- Available tickers: SPY (benchmark) + individual stocks above\n"
            "- Max 30% per individual stock\n"
            "- Undervalued stocks with high upside → overweight vs SPY\n"
            "- Overvalued or uncertain → allocate to SPY\n"
            "- Factor in macro backdrop for risk appetite\n\n"
            "Return a JSON object with:\n"
            "  allocations (dict ticker→weight, summing to 1.0), "
            "rationale (3-5 sentences), confidence (0-1), "
            "risk_level (conservative/moderate/aggressive), "
            "valuations (dict ticker→{implied_price, current_price, upside})."
        )

        result = self._pm_invoke(goal)

        # Validate and normalise allocations
        allocations = result.get('allocations', {'SPY': 1.0})
        total_weight = sum(allocations.values())
        if abs(total_weight - 1.0) > 0.01:
            print(f"  Normalising allocations (sum={total_weight:.2%})...")
            allocations = {k: v / total_weight for k, v in allocations.items()}

        # Enforce 30% cap
        for ticker in list(allocations.keys()):
            if ticker != 'SPY' and allocations[ticker] > config.MAX_POSITION_WEIGHT:
                excess = allocations[ticker] - config.MAX_POSITION_WEIGHT
                allocations[ticker] = config.MAX_POSITION_WEIGHT
                allocations['SPY'] = allocations.get('SPY', 0) + excess

        total_weight = sum(allocations.values())
        allocations = {k: v / total_weight for k, v in allocations.items()}

        print("\n" + "─" * 70)
        print("  PORTFOLIO ALLOCATION")
        print("─" * 70)
        for ticker, weight in sorted(allocations.items(), key=lambda x: -x[1]):
            print(f"  {ticker:<6s}: {weight:>6.1%}  (${weight * 1_000_000:>10,.0f})")
        print("─" * 70)
        print(f"  Risk Level:  {result.get('risk_level', 'unknown').upper()}")
        print(f"  Confidence:  {result.get('confidence', 0.0):.0%}")
        print(f"\n  Rationale: {result.get('rationale', 'N/A')}")
        print("=" * 70 + "\n")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        allocation_result = {
            'timestamp': timestamp,
            'allocations': allocations,
            'rationale': result.get('rationale', ''),
            'confidence': result.get('confidence', 0.0),
            'risk_level': result.get('risk_level', 'unknown'),
            'valuations': result.get('valuations', {}),
        }
        filepath = config.VALUATIONS_DIR / f"{timestamp}_portfolio_allocation.json"
        with open(filepath, 'w') as f:
            json.dump(allocation_result, f, indent=2, default=str)
        print(f"Allocation saved → {filepath}\n")

        return allocation_result

    def __repr__(self):
        return (f"<PMAgent (LangChain) engines={list(self.engines.keys())} "
                f"domain_agents={len(self.domain_agents)}>")
