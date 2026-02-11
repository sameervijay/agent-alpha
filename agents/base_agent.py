"""
Base agent class: LLM calls with retry, JSON parsing, audit logging.
All 6 agents (5 domain + PM) inherit from this.
"""

import json
import time
from datetime import datetime

from openai import OpenAI

import config


class BaseAgent:
    """Foundation class for all agents in the Council."""

    def __init__(self, name: str, role_description: str, system_prompt: str):
        self.name = name
        self.role_description = role_description
        self.system_prompt = system_prompt
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)
        self.call_log = []
        self._last_call_time = 0

    def _rate_limit(self):
        """Enforce minimum delay between API calls."""
        elapsed = time.time() - self._last_call_time
        if elapsed < config.LLM_CALL_DELAY:
            time.sleep(config.LLM_CALL_DELAY - elapsed)
        self._last_call_time = time.time()

    def call_llm(self, user_prompt: str, response_format=None,
                 max_retries: int = None) -> str:
        """Call LLM with retry and exponential backoff. Returns raw text response."""
        if max_retries is None:
            max_retries = config.MAX_RETRIES

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs = {
            "model": config.PRIMARY_MODEL,
            "messages": messages,
            "temperature": config.TEMPERATURE,
            "max_tokens": config.MAX_TOKENS,
        }
        if response_format:
            kwargs["response_format"] = response_format

        last_error = None
        for attempt in range(max_retries):
            self._rate_limit()
            try:
                response = self.client.chat.completions.create(**kwargs)
                result = response.choices[0].message.content
                usage = response.usage

                # Log the call
                self.call_log.append({
                    'timestamp': datetime.now().isoformat(),
                    'agent': self.name,
                    'prompt_preview': user_prompt[:200],
                    'response_preview': result[:200] if result else '',
                    'tokens_prompt': usage.prompt_tokens if usage else 0,
                    'tokens_completion': usage.completion_tokens if usage else 0,
                    'attempt': attempt + 1,
                })

                return result

            except Exception as e:
                last_error = e
                wait = 2 ** attempt
                print(f"  [{self.name}] LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    print(f"  Retrying in {wait}s...")
                    time.sleep(wait)

        raise RuntimeError(
            f"[{self.name}] LLM call failed after {max_retries} attempts: {last_error}"
        )

    def call_llm_json(self, user_prompt: str) -> dict:
        """Call LLM with JSON response format, parse and return dict."""
        result = self.call_llm(
            user_prompt,
            response_format={"type": "json_object"},
        )
        try:
            return json.loads(result)
        except json.JSONDecodeError as e:
            print(f"  [{self.name}] JSON parse error: {e}")
            print(f"  Raw response: {result[:500]}")
            raise

    def get_audit_log(self) -> list:
        return self.call_log

    def total_tokens(self) -> int:
        return sum(
            c.get('tokens_prompt', 0) + c.get('tokens_completion', 0)
            for c in self.call_log
        )

    def __repr__(self):
        return f"<{self.__class__.__name__} name={self.name!r}>"
