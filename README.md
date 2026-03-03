# agent-alpha

PM-led multi-agent allocation pipeline for the semiconductor value chain, built with LangGraph + LangChain.  
Package management uses [uv](https://docs.astral.sh/uv/).

## Prerequisites

- Python 3.11+ (recommended)
- [`uv`](https://docs.astral.sh/uv/) installed
- OpenAI account and `OPENAI_API_KEY`
- (Optional) API keys for external data sources:
  - `NEWS_API_KEY` (newsapi.org)
  - `ELSEVIER_API_KEY`
  - `SPRINGER_OA_API_KEY`, `SPRINGER_META_API_KEY`
  - `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`

## 1. Clone and install dependencies

From your terminal:

```bash
git clone <this-repo-url>
cd agent-alpha

# Install all Python dependencies
uv sync
```

If you don’t have `uv` yet, follow the official install instructions:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Configure environment variables

Create a `.env` file in the project root (same directory as `config.py` and `main.py`):

```bash
cp .env.example .env    # if you have a template, otherwise create .env manually
```

At minimum, you need:

```bash
OPENAI_API_KEY=sk-...
LANGSMITH_API_KEY=sk-...
```

Optional but recommended (uncomment / add as needed):

```bash
NEWS_API_KEY=...
ELSEVIER_API_KEY=...
SPRINGER_OA_API_KEY=...
SPRINGER_META_API_KEY=...
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...
```

These are loaded by `config.py` via `python-dotenv`.

## 3. Run the LangGraph dev server (local graph UI)

To bring up the LangGraph dev server and inspect/run the allocation pipeline locally:

```bash
uv run langgraph dev
```

This starts a local server (by default on `http://127.0.0.1:2024`) where you can:

- Inspect the `pipeline` graph defined in `langgraph_pipeline.py`
- Trigger runs with different inputs
- Iterate on graph/agent behavior while developing

This is the same entry point used when deploying to LangSmith Cloud (see `DEPLOYMENT.md` for details).

## 4. Run the CLI agents directly

You can also run the Council of Agents from the CLI via `main.py`:

```bash
# Default: PM-led allocation (LangGraph graph invoked locally)
uv run python main.py                               # $1000 budget, last 1h, autonomous event

# Full event → detect → causal → debate → DCF pipeline for NVDA
uv run python main.py --event "US announces new AI chip export controls"

# Same pipeline but target a different company
uv run python main.py --event "TSMC raises capex guidance" --company NVDA

# Run only a specific phase
uv run python main.py --phase detect --event "Fed raises rates 25bps"

# Historical backtest
uv run python main.py --backtest

# PM-led allocation pipeline (LangGraph graph invoked locally) with explicit flag
uv run python main.py --langgraph-alloc                    # $1000 budget, last 1h, autonomous event
uv run python main.py --langgraph-alloc --budget 500 --event "Focus on Fed"
```

If you run `uv run python main.py` with no arguments, it now defaults to the PM-led allocation pipeline (`--langgraph-alloc` with `$1000` budget, last `1h`, autonomous event).

## 5. Data layout

All persistent data lives under `data/`:

```
data/
├── analyst_views/              # Analyst standing views (updated each pipeline run)
│   ├── NVDA_view.json          #   ticker, thesis, conviction, proposed_driver_deltas,
│   ├── TSM_view.json           #   dcf_implied_price, key_drivers, key_risks, etc.
│   ├── ASML_view.json
│   ├── CDNS_view.json
│   └── CRWV_view.json
├── benchmarks/                 # Portfolio tracking (initialized by --ablation --init-portfolios)
│   ├── daily_benchmarks.csv    #   Combined: SPY, mcap-weighted semis, 3 PM profiles
│   ├── pm_trades.csv           #   Full-debate PM: trade log (date, ticker, action, shares, price)
│   ├── pm_daily_nav.csv        #   Full-debate PM: daily NAV snapshots
│   ├── pm_nodebate_trades.csv  #   No-debate PM (analysts only, 0 debate rounds)
│   ├── pm_nodebate_daily_nav.csv
│   ├── pm_noanalysts_trades.csv #  No-analysts PM (PM + DCF only)
│   └── pm_noanalysts_daily_nav.csv
├── debates/                    # Ablation results JSONs (timestamped)
│   └── 20260302_184500_ablation_results.json
├── events/                     # Detected events cache
├── news_cache/                 # Cached news API responses
├── causal_graphs/              # Causal graph outputs
├── valuations/                 # DCF valuation snapshots
├── macro_analyst/              # Macro analyst outputs
└── update_sessions/            # PM update session logs
```

### Portfolio profiles

Three PM portfolios track the ablation experiment over time:

| Profile | CSV prefix | Condition | Description |
|---------|-----------|-----------|-------------|
| `pm` | `pm_` | Full debate | Analysts + cross-analyst challenges + PM probing |
| `pm_nodebate` | `pm_nodebate_` | Analysts only | Analyst briefs but no debate rounds |
| `pm_noanalysts` | `pm_noanalysts_` | PM only | PM allocates from events + DCF/multiples only |

Run `python eval/pm_portfolio.py --status --profile pm` (or `pm_nodebate`, `pm_noanalysts`) to check any profile. Run `python eval/benchmark_tracker.py` to update all benchmarks including SPY and the semis basket.

## 6. Debate ablation experiment

The ablation compares 3 conditions to measure the value of analyst input and debate:

```bash
# Run ablation (live events, 1 debate round) and initialize all 3 portfolios
uv run python main.py --ablation --init-portfolios

# Run ablation on historical benchmark events
uv run python main.py --ablation --backtest

# Run ablation directly (saves results to data/debates/)
uv run python eval/debate_ablation.py --rounds 2
```

## 7. Slack bot

The Slack bot responds to `@AgentAlpha` mentions with portfolio status. Requires `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`.

```bash
uv run python tools/slack_listener.py
```

Commands: `status`, `status nodebate`, `status noanalysts`, `status all`, `help`.

## 8. Where to edit agents

- Core configuration: `config.py` (API keys, model settings, company definitions)
- LangChain agents (PM, company analysts, macro analyst, etc.): `agents_langchain/`
- Financial / valuation engines: `models/` and `financial_models/`
- LangGraph pipeline entry point: `langgraph_pipeline.py`

To work on or extend the agents:

1. Make changes in the relevant `agents_langchain/*` or `models/*` files.
2. Run the LangGraph dev server (`uv run langgraph dev`) or the CLI (`uv run python main.py ...`) with test inputs.
3. Iterate until the behaviors and outputs align with your PM / research goals.
