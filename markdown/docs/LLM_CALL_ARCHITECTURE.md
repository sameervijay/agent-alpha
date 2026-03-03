# OpenAI API Call Architecture

## Overview

All OpenAI API calls in the system flow through a single centralized class: **`BaseAgent`** (`agents/base_agent.py`). Every agent in the system inherits from this base class.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      BaseAgent                              │
│                  (agents/base_agent.py)                     │
│                                                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │  OpenAI Client Initialization (line 22)            │   │
│  │  self.client = OpenAI(api_key=config.OPENAI_API_KEY) │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  Two LLM Call Methods:                                     │
│  ┌────────────────────────────────────────────────────┐   │
│  │  call_llm(prompt) → str                            │   │
│  │  - Raw text response                                │   │
│  │  - Lines 33-84                                      │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌────────────────────────────────────────────────────┐   │
│  │  call_llm_json(prompt) → dict                      │   │
│  │  - JSON response format                             │   │
│  │  - Lines 86-97                                      │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ inherits from
                            │
        ┌───────────────────┴──────────────────────┐
        │                                          │
┌───────▼──────────┐                    ┌─────────▼─────────┐
│ CompanyAnalyst   │                    │   MacroAnalyst    │
│     Agent        │                    │      Agent        │
│                  │                    │                   │
│ Calls:           │                    │ Calls:            │
│ - Line 322       │                    │ - Multiple calls  │
│ - Line 450       │                    │                   │
│ - Line 539       │                    └───────────────────┘
│ - Line 612       │
│ - Line 720       │                    ┌───────────────────┐
│ - Line 842       │                    │   PMAgent         │
│ - Line 897       │                    │                   │
│ - Line 936       │                    │ Calls:            │
│ - Line 1334      │                    │ - Debate          │
│ - Line 1425      │                    │ - Portfolio       │
│ - Line 1495      │                    └───────────────────┘
│ - Line 2125      │
└──────────────────┘                    ┌───────────────────┐
                                        │  ThesisSupport    │
                                        │                   │
                                        │ Uses analyst's    │
                                        │ call_llm_json()   │
                                        └───────────────────┘
```

## The OpenAI Call Flow

### 1. **Initialization** (BaseAgent.__init__)

```python
# agents/base_agent.py, line 22
self.client = OpenAI(api_key=config.OPENAI_API_KEY)
```

- Creates one OpenAI client per agent instance
- API key loaded from `config.OPENAI_API_KEY` (from `.env` file)
- Each agent (CompanyAnalyst, MacroAnalyst, PM, etc.) gets its own client

### 2. **The Two Call Methods**

#### Method 1: `call_llm(prompt)` - Raw Text Response

```python
# agents/base_agent.py, lines 33-84
def call_llm(self, user_prompt: str, response_format=None,
             max_retries: int = None) -> str:
    """Call LLM with retry and exponential backoff. Returns raw text response."""

    messages = [
        {"role": "system", "content": self.system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    kwargs = {
        "model": config.PRIMARY_MODEL,           # "gpt-4o-2024-08-06"
        "messages": messages,
        "temperature": config.TEMPERATURE,       # 0.2
        "max_tokens": config.MAX_TOKENS,         # 4096
    }

    # The actual OpenAI API call:
    response = self.client.chat.completions.create(**kwargs)
    result = response.choices[0].message.content

    return result
```

**Features:**
- Rate limiting (0.5s delay between calls)
- Retry with exponential backoff (3 attempts by default)
- Token usage logging
- Audit trail (`self.call_log`)

#### Method 2: `call_llm_json(prompt)` - JSON Response

```python
# agents/base_agent.py, lines 86-97
def call_llm_json(self, user_prompt: str) -> dict:
    """Call LLM with JSON response format, parse and return dict."""

    result = self.call_llm(
        user_prompt,
        response_format={"type": "json_object"},  # Forces JSON output
    )

    return json.loads(result)
```

**Usage:** 99% of calls use this method for structured data extraction

### 3. **Configuration** (config.py)

```python
# API Settings
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
PRIMARY_MODEL = "gpt-4o-2024-08-06"
TEMPERATURE = 0.2
MAX_TOKENS = 4096
MAX_RETRIES = 3

# Rate Limiting
LLM_CALL_DELAY = 0.5  # seconds between API calls
```

## Where Calls Are Made

### CompanyAnalystAgent (13 call sites)

| Line | Method | Purpose |
|------|--------|---------|
| 322 | `monitor()` | Synthesize news into driver updates |
| 450 | `ramp()` | Initial deep research on ticker |
| 539 | `process_macro_alert()` | Integrate macro regime changes |
| 612 | `produce_driver_update()` | Convert view to DCF drivers |
| 720 | `respond_to_challenge()` | Answer devil's advocate questions |
| 842 | `detect_events()` | Identify material events from news |
| 897 | `build_causal_links()` | Map event to causal relationships |
| 936 | `develop_thesis()` | Generate thesis points |
| 1334 | `_identify_thesis_points()` | **Thesis generation with consensus** |
| 1425 | `_gather_evidence_for_question()` | Evidence synthesis |
| 1495 | `_quantify_thesis_to_drivers()` | Map thesis to DCF drivers |
| 1892 | `seek_specialist_input()` | Get specialist recommendations |
| 2125 | `debate_position()` | Multi-agent debate responses |

### ThesisSupport (_conduct_deep_analysis)

```python
# agents/thesis_support.py, line ~180
data = self.analyst.call_llm_json(prompt)
```

- Uses the analyst's `call_llm_json()` method
- No direct OpenAI client (delegates to analyst)
- Multiple calls per analysis (5-7 for deep mode)

### MacroAnalystAgent

```python
# agents/macro_analyst_agent.py
- Economic regime detection
- Inflation/growth/rates synthesis
- Sector impact analysis
```

### PMAgent

```python
# agents/pm_agent.py
- Multi-agent debate coordination
- Portfolio construction decisions
- Risk assessment synthesis
```

## Example: Consensus Thesis Call

When you run `analyst.develop_thesis(mode='contrarian')`:

```
1. CompanyAnalyst.develop_thesis() called
   ↓
2. understand_consensus() (no LLM call - pure data)
   ↓
3. _identify_thesis_points(mode, consensus_comparison)
   ↓
4. call_llm_json() with prompt:

   System: "You are a Company News Analyst specializing in NVDA..."

   User: "You are developing an investment thesis for NVDA.
          Mode: contrarian

          Context:
          Specialist findings: [...]
          Market valuation: [...]
          Consensus comparison:
            FY2027: Op Margin BELOW by 4,681bps (19.8% vs 66.6%)

          Identify 1-3 thesis points..."
   ↓
5. OpenAI API called (line 57 in base_agent.py):
   response = self.client.chat.completions.create(
       model="gpt-4o-2024-08-06",
       messages=[{system}, {user}],
       temperature=0.2,
       max_tokens=4096,
       response_format={"type": "json_object"}
   )
   ↓
6. JSON response parsed and returned:
   {
     "thesis_points": [
       {
         "thesis": "Datacenter will outperform consensus...",
         "direction": "bullish",
         "conviction": 0.8,
         ...
       }
     ]
   }
```

## Token Usage Tracking

Every call is logged in `self.call_log`:

```python
{
    'timestamp': '2026-02-17T22:17:55',
    'agent': 'analyst_nvda',
    'prompt_preview': 'You are developing an investment thesis...',
    'response_preview': '{"thesis_points": [{"thesis": "Datacenter...',
    'tokens_prompt': 1523,
    'tokens_completion': 847,
    'attempt': 1
}
```

**Access logs:**
```python
analyst = CompanyAnalystAgent('NVDA')
analyst.develop_thesis()

# View all calls
logs = analyst.get_audit_log()

# Get total tokens used
total = analyst.total_tokens()
```

## Rate Limiting

```python
# agents/base_agent.py, lines 26-31
def _rate_limit(self):
    """Enforce minimum delay between API calls."""
    elapsed = time.time() - self._last_call_time
    if elapsed < config.LLM_CALL_DELAY:  # 0.5 seconds
        time.sleep(config.LLM_CALL_DELAY - elapsed)
    self._last_call_time = time.time()
```

- Ensures 0.5s minimum between calls
- Prevents rate limit errors
- Applied automatically before every call

## Error Handling

```python
# Exponential backoff on failure
for attempt in range(max_retries):  # default 3
    try:
        response = self.client.chat.completions.create(**kwargs)
        return result
    except Exception as e:
        wait = 2 ** attempt  # 1s, 2s, 4s
        time.sleep(wait)
```

**Retry schedule:**
- Attempt 1: Immediate
- Attempt 2: Wait 1 second
- Attempt 3: Wait 2 seconds
- Attempt 4: Wait 4 seconds (if max_retries increased)

## Cost Estimation

**Typical thesis development workflow:**

| Operation | LLM Calls | Avg Tokens | Cost (GPT-4o) |
|-----------|-----------|------------|---------------|
| `understand_consensus()` | 0 | 0 | $0.00 |
| `_identify_thesis_points()` | 1 | 2,500 | $0.01 |
| `_conduct_supporting_analyses()` (3) | 3 | 7,500 | $0.03 |
| `_quantify_thesis_to_drivers()` (3) | 3 | 4,500 | $0.02 |
| **Total per thesis development** | **7** | **14,500** | **$0.06** |

**Deep thesis support (5 analyses):**

| Operation | LLM Calls | Avg Tokens | Cost |
|-----------|-----------|------------|------|
| Question expansion | 1 | 1,000 | $0.004 |
| Deep analyses (5) | 5 | 12,500 | $0.05 |
| Risk identification | 1 | 2,000 | $0.008 |
| **Total per deep support** | **7** | **15,500** | **$0.062** |

*Assuming GPT-4o pricing: ~$0.004/1K tokens blended rate*

## Key Design Decisions

### ✅ Why Centralized in BaseAgent?

1. **Single point of control** - All LLM calls go through one place
2. **Consistent error handling** - Retry logic applied uniformly
3. **Audit trail** - Every call logged automatically
4. **Rate limiting** - Prevents hitting API limits
5. **Easy to swap models** - Change `config.PRIMARY_MODEL` once

### ✅ Why Two Methods (call_llm vs call_llm_json)?

1. **Type safety** - `call_llm_json()` guarantees dict output
2. **JSON validation** - Catches parse errors immediately
3. **Structured extraction** - 99% of use cases need structured data
4. **Backward compatibility** - `call_llm()` available for raw text

### ✅ Why System + User Messages?

```python
messages = [
    {"role": "system", "content": self.system_prompt},  # Agent's identity/role
    {"role": "user", "content": user_prompt},           # Specific task
]
```

- **System prompt**: Defines agent's role, expertise, available tools
- **User prompt**: Specific task, context, structured output format
- Separation allows role to persist while tasks vary

## Future Enhancements

Potential improvements to the LLM call architecture:

- [ ] **Streaming support** - For long-running analyses
- [ ] **Token budgets** - Per-agent token limits
- [ ] **Model selection** - Different models for different tasks (Haiku for quick, Opus for complex)
- [ ] **Caching** - Cache identical prompts within session
- [ ] **Batch API** - For non-urgent background analyses
- [ ] **Local model support** - Ollama/LiteLLM integration
- [ ] **Cost tracking** - Per-agent, per-method cost attribution
- [ ] **A/B testing** - Compare different prompts/temperatures

## Summary

**Single Entry Point:**
```
All OpenAI calls → BaseAgent.call_llm() or .call_llm_json()
                   (agents/base_agent.py, lines 33-97)
```

**Benefits:**
- Centralized error handling
- Consistent rate limiting
- Automatic audit logging
- Easy monitoring and debugging
- Simple to swap models/providers

**Usage Pattern:**
```python
# Every agent inherits from BaseAgent
class CompanyAnalystAgent(BaseAgent):
    def some_method(self):
        # Just call inherited methods
        result = self.call_llm_json(prompt)
        # No need to manage OpenAI client directly
```

This architecture makes the system maintainable, observable, and easy to extend!
