"""
Smoke test: verify all BaseAgent subclasses still instantiate correctly
and that BaseAgent's LangChain-backed call_llm / call_llm_json work.

Does NOT make real API calls — patches the LangChain model so no tokens
are consumed and no API key is required.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

# ── Patch LangChain before any agent imports ──────────────────────────────────
# We mock the ChatOpenAI class so instantiation works without a real API key.

FAKE_CONTENT = json.dumps({"status": "ok", "value": 42})

def make_fake_response(content: str):
    msg = MagicMock()
    msg.content = content
    msg.usage_metadata = {"input_tokens": 10, "output_tokens": 20}
    return msg

@pytest.fixture(autouse=True)
def patch_chat_openai():
    fake_model = MagicMock()
    fake_model.bind.return_value = fake_model
    fake_model.invoke.return_value = make_fake_response(FAKE_CONTENT)

    with patch("agents.base_agent.ChatOpenAI", return_value=fake_model):
        yield fake_model


# ── Import agents AFTER patch is in place ────────────────────────────────────
from agents.base_agent import BaseAgent
from agents.macro_agent import MacroAgent
from agents.politics_agent import PoliticsAgent
from agents.stock_market_agent import StockMarketAgent
from agents.tech_publications_agent import TechPublicationsAgent
from agents.commodities_agent import CommoditiesAgent
from agents.macro_analyst_agent import MacroAnalystAgent
from agents.company_analyst_agent import CompanyAnalystAgent


# ── BaseAgent unit tests ──────────────────────────────────────────────────────

class TestBaseAgent:
    def test_instantiation(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        assert agent.name == "test"
        assert agent.role_description == "tester"
        assert agent.system_prompt == "You are a tester."
        assert agent.call_log == []

    def test_call_llm_returns_string(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        result = agent.call_llm("Hello?")
        assert isinstance(result, str)
        assert result == FAKE_CONTENT

    def test_call_llm_json_returns_dict(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        result = agent.call_llm_json("Give me JSON.")
        assert isinstance(result, dict)
        assert result["status"] == "ok"

    def test_call_log_populated(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        agent.call_llm("Hello?")
        assert len(agent.call_log) == 1
        entry = agent.call_log[0]
        assert entry["agent"] == "test"
        assert "timestamp" in entry
        assert entry["tokens_prompt"] == 10
        assert entry["tokens_completion"] == 20

    def test_total_tokens(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        agent.call_llm("Hello?")
        agent.call_llm("World?")
        assert agent.total_tokens() == 60  # 2 calls × (10 + 20)

    def test_get_audit_log(self):
        agent = BaseAgent("test", "tester", "You are a tester.")
        agent.call_llm("Hello?")
        log = agent.get_audit_log()
        assert log is agent.call_log

    def test_repr(self):
        agent = BaseAgent("alpha", "tester", "prompt")
        assert "BaseAgent" in repr(agent)
        assert "alpha" in repr(agent)


# ── Subclass instantiation smoke tests ───────────────────────────────────────

class TestAgentInstantiation:
    def test_macro_agent(self):
        a = MacroAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_politics_agent(self):
        a = PoliticsAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_stock_market_agent(self):
        a = StockMarketAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_tech_publications_agent(self):
        a = TechPublicationsAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_commodities_agent(self):
        a = CommoditiesAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_macro_analyst_agent(self):
        a = MacroAnalystAgent()
        assert isinstance(a, BaseAgent)
        assert a.name

    def test_company_analyst_agent(self):
        a = CompanyAnalystAgent(ticker="NVDA")
        assert isinstance(a, BaseAgent)
        assert a.name
