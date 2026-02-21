"""
Smoke test for agents_langchain/pm_agent.py.

Patches create_agent for all 7 agents and DCF engines so no real API
calls or Excel files are needed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Fake responses ────────────────────────────────────────────────────────────

FAKE_EVENTS = json.dumps({"events": [{
    "headline": "Fed rate hike test event",
    "description": "Fed raises rates 25bps.",
    "affected_companies": ["NVDA"],
    "affected_segments": ["datacenter"],
    "severity": "medium",
    "direction": "negative",
}]})

FAKE_LINKS = json.dumps({"causal_links": [{
    "source_event": "Fed rate hike test event",
    "intermediate_step": "Higher WACC",
    "downstream_metric": "datacenter_growth",
    "affected_company": "NVDA",
    "affected_periods": ["Q4-26"],
    "direction": "decrease",
    "magnitude_estimate": "-2pp",
    "confidence": 0.6,
    "reasoning": "Higher rates reduce capex.",
}]})

FAKE_DEBATE = json.dumps({
    "proposed_value": -0.02,
    "confidence": 0.6,
    "reasoning": "Higher rates slow capex.",
    "data_type": "leading",
    "challenges": "",
})

FAKE_PM_QUESTION = json.dumps({"question": "Is this a leading or lagging signal?"})
FAKE_DA = json.dumps({"challenge": "Hyperscalers may not cut capex despite rate rises."})
FAKE_RESOLUTION = json.dumps({
    "resolved_value": -0.015,
    "confidence": 0.65,
    "rationale": "Balanced view from debate.",
    "contributing_agents": ["macro_agent"],
    "dissenting_agents": [],
})
FAKE_ALLOCATION = json.dumps({
    "allocations": {"SPY": 0.6, "NVDA": 0.4},
    "rationale": "NVDA undervalued.",
    "confidence": 0.7,
    "risk_level": "moderate",
    "valuations": {"NVDA": {"implied_price": 150.0, "current_price": 130.0, "upside": 0.15}},
})


def make_result(content):
    msg = MagicMock()
    msg.content = content
    return {"messages": [msg]}


def pm_side_effect(input_dict):
    text = input_dict.get("messages", [{}])[0]
    if isinstance(text, dict):
        text = text.get("content", "")
    text = text.lower()
    if "probing" in text or "question" in text:
        return make_result(FAKE_PM_QUESTION)
    if "devil" in text or "advocate" in text or "challenge" in text:
        return make_result(FAKE_DA)
    if "resolve" in text or "resolution" in text or "final driver" in text:
        return make_result(FAKE_RESOLUTION)
    if "allocation" in text or "portfolio" in text or "balance" in text:
        return make_result(FAKE_ALLOCATION)
    return make_result(FAKE_RESOLUTION)


def domain_side_effect(input_dict):
    text = input_dict.get("messages", [{}])[0]
    if isinstance(text, dict):
        text = text.get("content", "")
    text = text.lower()
    if "causal" in text:
        return make_result(FAKE_LINKS)
    if "debate" in text:
        return make_result(FAKE_DEBATE)
    return make_result(FAKE_EVENTS)


@pytest.fixture(autouse=True)
def patch_everything():
    fake_domain = MagicMock()
    fake_domain.invoke.side_effect = domain_side_effect

    fake_pm = MagicMock()
    fake_pm.invoke.side_effect = pm_side_effect

    # Fake DCF engine
    fake_engine = MagicMock()
    fake_engine.drivers = {"datacenter_growth": {"Q4-26": 0.10}}
    fake_engine.compute_dcf.return_value = {
        "implied_price": 150.0,
        "current_price": 130.0,
        "upside": 0.154,
        "wacc": 0.10,
        "enterprise_value": 1e12,
        "equity_value": 9e11,
    }
    fake_engine.update_drivers.return_value = None

    with patch("agents_langchain.macro_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.politics_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.stock_market_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.tech_publications_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.commodities_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.company_analyst_agent.create_agent", return_value=fake_domain), \
         patch("agents_langchain.pm_agent.create_agent", return_value=fake_pm), \
         patch("agents_langchain.pm_agent.NVDADCFEngine", return_value=fake_engine), \
         patch("agents_langchain.pm_agent.CDNSDCFEngine", return_value=fake_engine), \
         patch("agents_langchain.pm_agent.TSMCDCFEngine", return_value=fake_engine), \
         patch("agents_langchain.pm_agent.CoreWeaveDCFEngine", return_value=fake_engine), \
         patch("agents_langchain.pm_agent.ASMLDCFEngine", return_value=fake_engine):
        yield fake_pm


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestPMAgent:
    def setup_method(self):
        from agents_langchain.pm_agent import PMAgent
        self.pm = PMAgent()

    def test_instantiation(self):
        assert self.pm.name == "pm_agent"
        assert len(self.pm.domain_agents) > 0
        assert len(self.pm.company_analysts) == len(__import__('config').COMPANIES)

    def test_detect_events(self):
        events = self.pm.detect_events("Fed hikes rates by 25bps.")
        assert isinstance(events, list)
        assert len(events) > 0
        assert events[0].headline == "Fed rate hike test event"

    def test_build_causal_graph(self):
        from models.event import Event
        event = Event(
            headline="Fed rate hike test event",
            description="Fed raises rates.",
            source_agent="test",
            affected_companies=["NVDA"],
            affected_segments=["datacenter"],
            severity="medium",
            direction="negative",
            raw_input="",
        )
        graph = self.pm.build_causal_graph(event)
        assert graph is not None
        assert len(graph.links) > 0

    def test_probing_question(self):
        from models.event import Event
        from models.debate import DebatePosition
        event = Event(
            headline="Test",
            description="Test",
            source_agent="test",
            affected_companies=["NVDA"],
            affected_segments=[],
            severity="low",
            direction="negative",
            raw_input="",
        )
        pos = DebatePosition(
            agent_name="macro_agent",
            metric="datacenter_growth",
            company="NVDA",
            period="Q4-26",
            proposed_value=-0.02,
            confidence=0.6,
            reasoning="Test",
            data_type="leading",
        )
        q = self.pm._ask_probing_question(event, "datacenter_growth", "NVDA", "Q4-26", [pos])
        assert isinstance(q, str)

    def test_balance_portfolio(self):
        result = self.pm.balance_portfolio()
        assert isinstance(result, dict)
        assert "allocations" in result
        total = sum(result["allocations"].values())
        assert abs(total - 1.0) < 0.02  # weights sum to ~1.0

    def test_repr(self):
        assert "PMAgent" in repr(self.pm)
        assert "LangChain" in repr(self.pm)
