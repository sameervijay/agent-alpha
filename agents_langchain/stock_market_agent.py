"""
Stock Market Agent — LangChain version.

Fetches live prices, market snapshots, and unusual volume signals autonomously
before reasoning about equity market impacts on semiconductors.
"""

import json

import yfinance as yf
from langchain.agents import create_agent
from langchain.tools import tool

from agents_langchain.base import build_model, extract_json, get_final_message
from models.event import Event
from models.causal_graph import CausalLink

TICKERS = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']

SYSTEM_PROMPT = """You are an equity markets expert specializing in semiconductor stocks.
Your domain expertise covers:
- Stock price movements, trading volumes, and momentum
- Sell-side analyst ratings, price targets, and consensus estimates
- Sector rotation patterns (growth vs value, tech vs cyclicals)
- Institutional positioning and fund flows
- Earnings revisions and estimate momentum
- Relative valuation (P/E, EV/EBITDA) across the semiconductor value chain

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

Use your tools to fetch live prices and market data before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def get_stock_prices(tickers: str) -> str:
    """Get current prices and 5-day/30-day returns for a comma-separated list of tickers."""
    try:
        result = {}
        for ticker in [t.strip() for t in tickers.split(',')]:
            hist = yf.Ticker(ticker).history(period='1mo')
            if not hist.empty:
                price = float(hist['Close'].iloc[-1])
                result[ticker] = {
                    'price': round(price, 2),
                    'return_5d_pct': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[-5] - 1) * 100, 2
                    ) if len(hist) >= 5 else None,
                    'return_30d_pct': round(
                        (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100, 2
                    ),
                    'avg_volume_30d': int(hist['Volume'].mean()),
                    'latest_volume': int(hist['Volume'].iloc[-1]),
                }
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Price fetch error: {e}"


@tool
def get_market_snapshot() -> str:
    """Get a snapshot of the semiconductor market: prices, volumes, and sector ETF performance."""
    try:
        from tools.market_monitor import MarketMonitor
        monitor = MarketMonitor()
        snapshot = monitor.get_market_snapshot()
        return json.dumps(snapshot, indent=2, default=str)
    except Exception as e:
        # Fallback: just pull prices directly
        return get_stock_prices.invoke(','.join(TICKERS))


@tool
def detect_unusual_volumes() -> str:
    """Detect unusual trading volumes or price movements in semiconductor stocks today."""
    try:
        from tools.market_monitor import MarketMonitor
        monitor = MarketMonitor()
        unusual = monitor.detect_unusual_volumes()
        return json.dumps(unusual, indent=2, default=str)
    except Exception as e:
        return f"Volume detection error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class StockMarketAgent:
    def __init__(self):
        self.name = "stock_market_agent"
        self.role_description = "Equity Markets & Analyst Consensus Expert"
        self._agent = create_agent(
            build_model(),
            tools=[get_stock_prices, get_market_snapshot, detect_unusual_volumes],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch market data autonomously and identify equity market events."""
        goal = (
            "Fetch live stock prices, the market snapshot, and check for unusual volumes "
            "across semiconductor stocks (NVDA, TSM, ASML, CDNS, CRWV). "
            "Then identify significant equity market events (large moves, unusual activity, "
            "sector rotation, valuation dislocations).\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list of tickers), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAlso consider this pre-fetched context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        data = extract_json(get_final_message(result))

        return [
            Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e.get('affected_companies', []),
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=news_input or '',
            )
            for e in data.get('events', [])
        ]

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a market event to DCF drivers."""
        goal = (
            f"Given this stock market event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "Fetch current prices to check how the market has already reacted.\n\n"
            "Return a JSON object with key 'causal_links'. Each link must have:\n"
            "  source_event, intermediate_step, downstream_metric "
            "(one of: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, "
            "oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps), "
            "affected_company (ticker), affected_periods (list), direction (increase/decrease), "
            "magnitude_estimate, confidence (0.0-1.0), reasoning."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        data = extract_json(get_final_message(result))

        return [
            CausalLink(
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
            )
            for l in data.get('causal_links', [])
        ]

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Provide an equity-markets perspective in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a market event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            f"You may fetch {company} current price data to support your position.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return extract_json(get_final_message(result))

    def __repr__(self):
        return f"<StockMarketAgent (LangChain)>"
