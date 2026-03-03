"""
Central configuration for the Council of Agents system.
API keys loaded from .env file, model settings, company definitions.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
_PROJECT_ROOT = Path(__file__).parent
load_dotenv(_PROJECT_ROOT / '.env')

# ── LangSmith Tracing ─────────────────────────────────────
LANGSMITH_API_KEY = os.getenv('LANGSMITH_API_KEY', '')
LANGCHAIN_PROJECT = os.getenv('LANGCHAIN_PROJECT', 'agent-alpha')
if LANGSMITH_API_KEY:
    os.environ.setdefault('LANGCHAIN_TRACING_V2', 'true')
    os.environ.setdefault('LANGCHAIN_API_KEY', LANGSMITH_API_KEY)
    os.environ.setdefault('LANGCHAIN_PROJECT', LANGCHAIN_PROJECT)

# ── LLM Configuration ──────────────────────────────────────
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# ── External Data APIs ─────────────────────────────────────
NEWS_API_KEY = os.getenv('NEWS_API_KEY', '')          # newsapi.org
ELSEVIER_API_KEY = os.getenv('ELSEVIER_API_KEY', '')   # api.elsevier.com (Scopus)
SPRINGER_OA_API_KEY = os.getenv('SPRINGER_OA_API_KEY', '')    # api.springernature.com/openaccess
SPRINGER_META_API_KEY = os.getenv('SPRINGER_META_API_KEY', '') # api.springernature.com/meta
ADZUNA_APP_ID = os.getenv('ADZUNA_APP_ID', '')   # api.adzuna.com — job postings
ADZUNA_APP_KEY = os.getenv('ADZUNA_APP_KEY', '')
FRED_API_KEY = os.getenv('FRED_API_KEY', '')      # fred.stlouisfed.org/docs/api/api_key.html (free)
SLACK_BOT_TOKEN = os.getenv('SLACK_BOT_TOKEN', '')
SLACK_APP_TOKEN = os.getenv('SLACK_APP_TOKEN', '')  # xapp-... for Socket Mode
SLACK_DEBATE_CHANNEL = os.getenv('SLACK_DEBATE_CHANNEL', 'C0AENBHCUM7')

PRIMARY_MODEL = "gpt-4o-2024-08-06"
TEMPERATURE = 0.2
MAX_TOKENS = 4096
MAX_RETRIES = 3

# ── Rate Limiting ──────────────────────────────────────────
LLM_CALL_DELAY = 0.5  # seconds between API calls

# ── Data Directories ───────────────────────────────────────
DATA_DIR = _PROJECT_ROOT / 'data'
EVENTS_DIR = DATA_DIR / 'events'
CAUSAL_GRAPHS_DIR = DATA_DIR / 'causal_graphs'
DEBATES_DIR = DATA_DIR / 'debates'
VALUATIONS_DIR = DATA_DIR / 'valuations'
NEWS_CACHE_DIR = DATA_DIR / 'news_cache'
ANALYST_VIEWS_DIR = DATA_DIR / 'analyst_views'
MACRO_ANALYST_DIR = DATA_DIR / 'macro_analyst'
UPDATE_SESSIONS_DIR = DATA_DIR / 'update_sessions'

# News fetcher settings
NEWS_CACHE_TTL_HOURS = 4
NEWS_MAX_ITEMS = 20

# Ensure directories exist
for d in [EVENTS_DIR, CAUSAL_GRAPHS_DIR, DEBATES_DIR, VALUATIONS_DIR,
          NEWS_CACHE_DIR, ANALYST_VIEWS_DIR, MACRO_ANALYST_DIR,
          UPDATE_SESSIONS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ── Company Definitions ────────────────────────────────────
COMPANIES = {
    'NVDA': {
        'name': 'NVIDIA',
        'ticker': 'NVDA',
        'sector': 'GPU / AI Accelerators',
        'segments': ['datacenter', 'gaming', 'automotive', 'proviz', 'oem'],
        'excel_path': str(_PROJECT_ROOT / 'financial_models' / 'NVIDIA NVDA US.xlsx'),
        'engine_class': 'NVDADCFEngine',
        'has_full_model': True,
    },
    'CDNS': {
        'name': 'Cadence Design Systems',
        'ticker': 'CDNS',
        'sector': 'EDA Software',
        'segments': ['core_eda', 'system_interconnect', 'ip'],
        'excel_path': str(_PROJECT_ROOT / 'financial_models' / 'Cadence Design CDNS US.xlsx'),
        'engine_class': 'CDNSDCFEngine',
        'has_full_model': True,
    },
    'CRWV': {
        'name': 'CoreWeave',
        'ticker': 'CRWV',
        'sector': 'Neocloud / GPU-as-a-Service',
        'segments': ['gpu_rental', 'managed_services'],
        'excel_path': str(_PROJECT_ROOT / 'financial_models' / 'CoreWeave CRWV US.xlsx'),
        'engine_class': 'CoreWeaveDCFEngine',
        'has_full_model': True,
    },
    'TSM': {
        'name': 'Taiwan Semiconductor Manufacturing Company',
        'ticker': 'TSM',
        'sector': 'Semiconductor Foundry',
        'segments': ['smartphone', 'hpc', 'iot', 'automotive', 'digital_consumer', 'other'],
        'excel_path': str(_PROJECT_ROOT / 'financial_models' / 'Taiwan Semiconductor Manufacturing Company TSM US.xlsx'),
        'engine_class': 'TSMCDCFEngine',
        'has_full_model': True,
    },
    'ASML': {
        'name': 'ASML Holding N.V.',
        'ticker': 'ASML',
        'sector': 'Semiconductor Equipment',
        'segments': ['euv', 'arfi', 'arf', 'krf', 'iline', 'metrology'],
        'excel_path': str(_PROJECT_ROOT / 'financial_models' / 'ASML Holding ASML NA.xlsx'),
        'engine_class': 'ASMLDCFEngine',
        'has_full_model': True,
    },
}

# ── Semiconductor Value Chain Map ──────────────────────────
VALUE_CHAIN = {
    'equipment': ['ASML'],
    'foundry': ['TSM'],
    'eda': ['CDNS'],
    'gpu_design': ['NVDA'],
    'neocloud': ['CRWV'],
}

# Upstream/downstream relationships (direction of supply)
SUPPLY_CHAIN = {
    'ASML': {'downstream': ['TSM']},
    'TSM': {'upstream': ['ASML', 'CDNS'], 'downstream': ['NVDA']},
    'CDNS': {'downstream': ['TSM', 'NVDA']},
    'NVDA': {'upstream': ['TSM'], 'downstream': ['CRWV']},
    'CRWV': {'upstream': ['NVDA']},
}

# ── DCF Assumptions (defaults) ─────────────────────────────
DEFAULT_WACC_RANGE_BPS = 200
DEFAULT_WACC_STEP_BPS = 50
UPSIDE_THRESHOLD = 0.15  # 15% upside for BUY signal
MAX_POSITION_WEIGHT = 0.30  # 30% max per name

# ── Debate Gate ─────────────────────────────────────────────
# Debate rounds only fire when analysts genuinely disagree.
# Gate metric: mean absolute deviation (MAD) of short_term_event_conviction
# across all analyst briefs. If MAD < threshold, analysts broadly agree on
# the event's near-term direction and debate would just add noise.
DEBATE_DISAGREEMENT_THRESHOLD = 0.12  # ~12pp avg spread triggers debate
