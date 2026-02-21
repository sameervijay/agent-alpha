"""
Shared helpers for all agents_langchain agents.
"""

import json
import re

from langchain_openai import ChatOpenAI

import config


def build_model() -> ChatOpenAI:
    """Return a configured ChatOpenAI instance using project config."""
    return ChatOpenAI(
        model=config.PRIMARY_MODEL,
        temperature=config.TEMPERATURE,
        max_tokens=config.MAX_TOKENS,
        max_retries=config.MAX_RETRIES,
        api_key=config.OPENAI_API_KEY,
    )


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
