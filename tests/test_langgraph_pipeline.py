import json
from types import SimpleNamespace

import config
import langgraph_pipeline as lp
from models.event import Event


class _FakeCommoditiesAgent:
    def detect_events(self, _news_input=None):
        return [Event(
            headline="HBM prices spike on constrained supply",
            description="Memory prices moved up in the last hour.",
            source_agent="commodities_agent",
            affected_companies=["NVDA", "TSM"],
            affected_segments=["hbm", "packaging"],
            severity="high",
            direction="negative",
        )]


class _FakeMacroAgent:
    def detect_events(self, _news_input=None):
        return [Event(
            headline="US 10Y yield drifts lower intraday",
            description="Rates eased over the last hour.",
            source_agent="macro_agent",
            affected_companies=["NVDA", "CRWV"],
            affected_segments=["risk_appetite"],
            severity="medium",
            direction="positive",
        )]


class _FakePoliticsAgent:
    def detect_events(self, _news_input=None):
        return [Event(
            headline="Export control commentary drives uncertainty",
            description="Policy chatter created short-term uncertainty.",
            source_agent="politics_agent",
            affected_companies=["ASML", "TSM"],
            affected_segments=["export_controls"],
            severity="medium",
            direction="negative",
        )]


class _FakeStockMarketAgent:
    def detect_events(self, _news_input=None):
        return [Event(
            headline="Semis outperform broad market in morning session",
            description="Relative strength emerged in the last hour.",
            source_agent="stock_market_agent",
            affected_companies=["NVDA", "CDNS", "CRWV"],
            affected_segments=["momentum"],
            severity="medium",
            direction="positive",
        )]


class _FakeTechPublicationsAgent:
    def detect_events(self, _news_input=None):
        return [Event(
            headline="Foundry node update implies stronger HPC roadmap",
            description="Tech publication update on node progression.",
            source_agent="tech_publications_agent",
            affected_companies=["TSM", "NVDA", "CDNS"],
            affected_segments=["process_node", "eda"],
            severity="high",
            direction="positive",
        )]


class _FakeAnalystLLM:
    def __init__(self, ticker):
        self.ticker = ticker

    def invoke(self, _payload):
        content = json.dumps({
            "ticker": self.ticker,
            "thesis": f"{self.ticker} remains fundamentally solid.",
            "key_drivers": ["driver_a", "driver_b"],
            "key_risks": ["risk_a"],
            "conviction": 0.65,
            "recommended_dollars": 200.0,
            "recommended_weight": 0.2,
            "challenge_to_others": "Peer assumptions may be too optimistic.",
        })
        return {"messages": [SimpleNamespace(content=content)]}


class _FakeCompanyAnalystAgent:
    def __init__(self, ticker):
        self.ticker = ticker
        self._agent = _FakeAnalystLLM(ticker)


class _FakePMAgent:
    def _pm_invoke(self, _goal):
        return {
            "debate_summary": "Analysts disagree on cyclicality but agree on AI demand resilience.",
            "rationale": "Allocate more to direct AI beneficiaries and maintain diversification.",
            "risk_notes": ["Policy uncertainty", "Supply constraints"],
            # Intentionally incomplete to verify normalization and missing ticker fill
            "allocation_dollars": {"NVDA": 450, "TSM": 250, "ASML": 150},
        }


def test_langgraph_pm_led_allocation_pipeline(monkeypatch):
    monkeypatch.setattr(lp, "CommoditiesAgent", _FakeCommoditiesAgent)
    monkeypatch.setattr(lp, "MacroAgent", _FakeMacroAgent)
    monkeypatch.setattr(lp, "PoliticsAgent", _FakePoliticsAgent)
    monkeypatch.setattr(lp, "StockMarketAgent", _FakeStockMarketAgent)
    monkeypatch.setattr(lp, "TechPublicationsAgent", _FakeTechPublicationsAgent)
    monkeypatch.setattr(lp, "CompanyAnalystAgent", _FakeCompanyAnalystAgent)
    monkeypatch.setattr(lp, "PMAgent", _FakePMAgent)

    graph = lp.build_graph()
    out = graph.invoke({"event": "Smoke test context", "lookback_hours": 1, "budget": 1000})

    assert out.get("error") is None
    assert out.get("result")

    result = out["result"]
    alloc = result["allocation_dollars"]
    expected_tickers = set(config.COMPANIES.keys())

    assert set(alloc.keys()) == expected_tickers
    assert round(sum(alloc.values()), 2) == 1000.00
    assert result["events_detected"] >= 5
    assert result["routed_events_by_company"]["NVDA"] >= 1
