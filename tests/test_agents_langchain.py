"""
Smoke test: verify all agents_langchain agents instantiate correctly and
that their methods work end-to-end with a mocked LangChain agent.

No real API calls are made — create_agent() is patched to return a mock.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Fake agent response factory ───────────────────────────────────────────────

def make_agent_result(content: str) -> dict:
    msg = MagicMock()
    msg.content = content
    return {"messages": [msg]}

FAKE_EVENTS = json.dumps({
    "events": [{
        "headline": "Test event",
        "description": "A test macro event.",
        "affected_companies": ["NVDA", "TSM"],
        "affected_segments": ["datacenter"],
        "severity": "medium",
        "direction": "negative",
    }]
})

FAKE_LINKS = json.dumps({
    "causal_links": [{
        "source_event": "Test event",
        "intermediate_step": "Mechanism",
        "downstream_metric": "datacenter_growth",
        "affected_company": "NVDA",
        "affected_periods": ["Q4-26"],
        "direction": "decrease",
        "magnitude_estimate": "-3pp",
        "confidence": 0.7,
        "reasoning": "Test reasoning.",
    }]
})

FAKE_DEBATE = json.dumps({
    "proposed_value": -0.03,
    "confidence": 0.7,
    "reasoning": "Test reasoning.",
    "data_type": "leading",
    "challenges": "None",
})

FAKE_THESIS = json.dumps({
    "ticker": "NVDA",
    "thesis": "Strong AI demand.",
    "bull_case": ["AI capex", "Blackwell ramp", "Margin expansion"],
    "bear_case": ["China export controls", "Competition", "Valuation"],
    "conviction": 0.75,
    "key_risks": ["Export controls"],
    "dcf_driver_adjustments": {"datacenter_growth": 0.05},
})


@pytest.fixture(autouse=True)
def patch_create_agent():
    """Replace create_agent with a mock that returns predictable responses."""
    mock_agent = MagicMock()
    mock_agent.invoke.return_value = make_agent_result(FAKE_EVENTS)

    def side_effect(content):
        # Return different responses based on what was asked
        msg = content.get("messages", [{}])[0]
        text = msg.get("content", "") if isinstance(msg, dict) else ""
        if "causal" in text.lower():
            return make_agent_result(FAKE_LINKS)
        if "debate" in text.lower():
            return make_agent_result(FAKE_DEBATE)
        if "thesis" in text.lower():
            return make_agent_result(FAKE_THESIS)
        return make_agent_result(FAKE_EVENTS)

    mock_agent.invoke.side_effect = side_effect

    with patch("agents_langchain.macro_agent.create_agent", return_value=mock_agent), \
         patch("agents_langchain.politics_agent.create_agent", return_value=mock_agent), \
         patch("agents_langchain.stock_market_agent.create_agent", return_value=mock_agent), \
         patch("agents_langchain.tech_publications_agent.create_agent", return_value=mock_agent), \
         patch("agents_langchain.commodities_agent.create_agent", return_value=mock_agent), \
         patch("agents_langchain.company_analyst_agent.create_agent", return_value=mock_agent):
        yield mock_agent


# ── Shared helper ─────────────────────────────────────────────────────────────

def make_event():
    from models.event import Event
    return Event(
        headline="Test event",
        description="A test macro event.",
        source_agent="test",
        affected_companies=["NVDA", "TSM"],
        affected_segments=["datacenter"],
        severity="medium",
        direction="negative",
        raw_input="",
    )


# ── MacroAgent ────────────────────────────────────────────────────────────────

class TestMacroAgent:
    def setup_method(self):
        from agents_langchain.macro_agent import MacroAgent
        self.agent = MacroAgent()

    def test_instantiation(self):
        assert self.agent.name == "macro_agent"

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)
        assert len(events) == 1
        assert events[0].headline == "Test event"

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)
        assert links[0].downstream_metric == "datacenter_growth"

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)
        assert "proposed_value" in result


# ── PoliticsAgent ─────────────────────────────────────────────────────────────

class TestPoliticsAgent:
    def setup_method(self):
        from agents_langchain.politics_agent import PoliticsAgent
        self.agent = PoliticsAgent()

    def test_instantiation(self):
        assert self.agent.name == "politics_agent"

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)


# ── StockMarketAgent ──────────────────────────────────────────────────────────

class TestStockMarketAgent:
    def setup_method(self):
        from agents_langchain.stock_market_agent import StockMarketAgent
        self.agent = StockMarketAgent()

    def test_instantiation(self):
        assert self.agent.name == "stock_market_agent"

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)


# ── TechPublicationsAgent ─────────────────────────────────────────────────────

class TestTechPublicationsAgent:
    def setup_method(self):
        from agents_langchain.tech_publications_agent import TechPublicationsAgent
        self.agent = TechPublicationsAgent()

    def test_instantiation(self):
        assert self.agent.name == "tech_publications_agent"

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)


# ── CommoditiesAgent ──────────────────────────────────────────────────────────

class TestCommoditiesAgent:
    def setup_method(self):
        from agents_langchain.commodities_agent import CommoditiesAgent
        self.agent = CommoditiesAgent()

    def test_instantiation(self):
        assert self.agent.name == "commodities_agent"

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)


# ── CompanyAnalystAgent ───────────────────────────────────────────────────────

class TestCompanyAnalystAgent:
    def setup_method(self):
        from agents_langchain.company_analyst_agent import CompanyAnalystAgent
        self.agent = CompanyAnalystAgent(ticker="NVDA")

    def test_instantiation(self):
        assert self.agent.ticker == "NVDA"
        assert self.agent.name == "analyst_nvda"

    def test_develop_thesis(self):
        thesis = self.agent.develop_thesis()
        assert isinstance(thesis, dict)

    def test_detect_events(self):
        events = self.agent.detect_events()
        assert isinstance(events, list)

    def test_build_causal_links(self):
        links = self.agent.build_causal_links(make_event())
        assert isinstance(links, list)

    def test_debate_position(self):
        result = self.agent.debate_position(make_event(), "datacenter_growth", "NVDA", "Q4-26", [])
        assert isinstance(result, dict)
