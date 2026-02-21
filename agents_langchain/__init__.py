"""
LangChain-native agent implementations.

Each agent uses create_agent() with domain-specific @tool functions so the
LLM can autonomously decide what data to fetch before reasoning.

Agents expose the same public methods as agents/ for drop-in compatibility:
  detect_events(news_input=None) -> list[Event]
  build_causal_links(event)      -> list[CausalLink]
  debate_position(...)           -> dict
"""

from agents_langchain.macro_agent import MacroAgent
from agents_langchain.politics_agent import PoliticsAgent
from agents_langchain.stock_market_agent import StockMarketAgent
from agents_langchain.tech_publications_agent import TechPublicationsAgent
from agents_langchain.commodities_agent import CommoditiesAgent
from agents_langchain.company_analyst_agent import CompanyAnalystAgent
from agents_langchain.pm_agent import PMAgent

__all__ = [
    "MacroAgent",
    "PoliticsAgent",
    "StockMarketAgent",
    "TechPublicationsAgent",
    "CommoditiesAgent",
    "CompanyAnalystAgent",
    "PMAgent",
]
