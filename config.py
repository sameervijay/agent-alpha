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

# ── LLM Configuration ──────────────────────────────────────
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')
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
        'segments': ['cloud_gpu', 'managed_services'],
        'has_full_model': False,
    },
    'TSM': {
        'name': 'TSMC',
        'ticker': 'TSM',
        'sector': 'Semiconductor Foundry',
        'segments': ['advanced_nodes', 'mature_nodes', 'packaging'],
        'has_full_model': False,
    },
    'ASML': {
        'name': 'ASML',
        'ticker': 'ASML',
        'sector': 'Semiconductor Equipment',
        'segments': ['euv_systems', 'duv_systems', 'installed_base'],
        'has_full_model': False,
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
