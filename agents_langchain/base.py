"""
Shared helpers for all agents_langchain agents.
"""

import json
import re

from langchain_openai import ChatOpenAI

import config
from agents_langchain.schemas import (
    CausalLinksOutput,
    DebatePositionOutput,
    EventsOutput,
)

# ── Session cache ─────────────────────────────────────────────────────────────
# Module-level dict shared across all agents in one pipeline run.
# Call clear_session_cache() at the start of each new PM pipeline run to avoid
# serving stale data across separate invocations.

_SESSION_CACHE: dict = {}


def cache_get(key: str):
    """Return cached value for key, or None if not present."""
    return _SESSION_CACHE.get(key)


def cache_set(key: str, value) -> None:
    """Store value in the session cache under key."""
    _SESSION_CACHE[key] = value


def clear_session_cache() -> None:
    """Flush the session cache (call at the start of each pipeline run)."""
    _SESSION_CACHE.clear()


# ── Model factory ─────────────────────────────────────────────────────────────

def build_model() -> ChatOpenAI:
    """Return a configured ChatOpenAI instance using project config."""
    return ChatOpenAI(
        model=config.PRIMARY_MODEL,
        temperature=config.TEMPERATURE,
        max_tokens=config.MAX_TOKENS,
        max_retries=config.MAX_RETRIES,
        api_key=config.OPENAI_API_KEY,
    )


# ── Raw-output helpers ────────────────────────────────────────────────────────

def extract_json(text: str) -> dict:
    """
    Parse JSON from the agent's final message.
    Handles both clean JSON and JSON embedded inside markdown code blocks or prose.
    """
    text = text.strip()

    # Strip markdown code fences if present
    fenced = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))

    # Try the whole string
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the first {...} block
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        return json.loads(match.group())

    raise ValueError(f"No JSON found in agent output:\n{text[:500]}")


def get_final_message(result: dict) -> str:
    """Extract the content of the last message from an agent invoke() result."""
    messages = result.get("messages", [])
    if not messages:
        raise ValueError("Agent returned no messages")
    return messages[-1].content


# ── Structured-output parse helpers ──────────────────────────────────────────

def parse_events(text: str, source_agent: str, raw_input: str) -> list:
    """
    Parse agent output into validated Event objects.
    Validates against EventsOutput schema; falls back to raw dict parsing on failure.
    """
    from models.event import Event
    data = extract_json(text)
    try:
        output = EventsOutput(**data)
        return [
            Event(
                headline=e.headline,
                description=e.description,
                source_agent=source_agent,
                affected_companies=e.affected_companies,
                affected_segments=e.affected_segments,
                severity=e.severity,
                direction=e.direction,
                raw_input=raw_input,
            )
            for e in output.events
        ]
    except Exception:
        # Fallback: construct from raw dict without Pydantic validation
        return [
            Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=source_agent,
                affected_companies=e.get('affected_companies', []),
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=raw_input,
            )
            for e in data.get('events', [])
        ]


def parse_causal_links(text: str, proposed_by: str) -> list:
    """
    Parse agent output into validated CausalLink objects.
    Validates against CausalLinksOutput schema; falls back to raw dict parsing.
    """
    from models.causal_graph import CausalLink
    data = extract_json(text)
    try:
        output = CausalLinksOutput(**data)
        return [
            CausalLink(
                source_event=l.source_event,
                intermediate_step=l.intermediate_step,
                downstream_metric=l.downstream_metric,
                affected_company=l.affected_company,
                affected_periods=l.affected_periods,
                direction=l.direction,
                magnitude_estimate=l.magnitude_estimate,
                confidence=l.confidence,
                reasoning=l.reasoning,
                proposed_by=proposed_by,
            )
            for l in output.causal_links
        ]
    except Exception:
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
                proposed_by=proposed_by,
            )
            for l in data.get('causal_links', [])
        ]


def parse_debate_position(text: str) -> dict:
    """
    Parse and validate a debate position from agent output.
    Returns a plain dict (validated via Pydantic, or raw on failure).
    """
    data = extract_json(text)
    try:
        pos = DebatePositionOutput(**data)
        return pos.model_dump()
    except Exception:
        return data
