"""
Pydantic schemas for structured output validation in agents_langchain.

Every agent method that returns events, causal links, or debate positions
validates its output against these models before constructing domain objects.
"""

from typing import List, Literal

from pydantic import BaseModel, Field


class EventSchema(BaseModel):
    headline: str
    description: str
    affected_companies: List[str] = Field(default_factory=list)
    affected_segments: List[str] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"]
    direction: Literal["positive", "negative", "neutral", "mixed"]


class EventsOutput(BaseModel):
    events: List[EventSchema] = Field(default_factory=list)


class CausalLinkSchema(BaseModel):
    source_event: str
    intermediate_step: str
    downstream_metric: str
    affected_company: str
    affected_periods: List[str]
    direction: Literal["increase", "decrease"]
    magnitude_estimate: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class CausalLinksOutput(BaseModel):
    causal_links: List[CausalLinkSchema] = Field(default_factory=list)


class DebatePositionOutput(BaseModel):
    proposed_value: float
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    data_type: Literal["leading", "lagging"]
    challenges: str = ""
