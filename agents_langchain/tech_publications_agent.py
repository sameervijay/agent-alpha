"""
Tech Publications Agent — LangChain version.

Fetches semiconductor technology intelligence from nine sources:
  1. General filtered news (macro_news_raw cache)     — always available
  2. Industry publications via NewsAPI                — EE Times, The Register, Ars Technica, etc.
  3. arXiv research papers                            — chip architecture leading signal (free)
  4. SEMI equipment billings reports via NewsAPI      — foundry capex leading indicator
  5. Advanced packaging capacity monitor              — CoWoS / HBM supply constraint data
  6. Elsevier Scopus journal search                   — peer-reviewed process node & device physics
  7. Springer Open Access API                         — Nature Electronics, npj Quantum Materials, etc.
  8. Springer Metadata API                            — broad Springer Nature coverage incl. paywalled
  9. Adzuna job postings API                          — hiring volume & role-type leading indicators
"""

import json
import os
import xml.etree.ElementTree as ET

from langchain.agents import create_agent
from langchain.tools import tool

import config
from agents_langchain.base import (
    build_model, cache_get, cache_set,
    get_final_message, parse_causal_links, parse_debate_position, parse_events,
)
from models.event import Event
from models.causal_graph import CausalLink

TECH_KEYWORDS = {
    'process node', 'angstrom', 'euv', 'asml', 'tsmc', 'gate-all-around',
    'gaa', 'backside power', 'chiplet', 'packaging', 'hbm', 'bandwidth',
    'nvidia', 'blackwell', 'hopper', 'cuda', 'architecture', 'foundry',
    'yield', 'wafer', 'lithography', 'cadence', 'synopsys', 'eda',
    'coreweave', 'neocloud', 'high-na', 'high na', 'rubin', 'gb200',
    'carbon nanotubes', 'tmd', '2d materials', 'cfet', 'dram',
    'compute in memory', 'amorphous oxides', 'resistive ram',
    'neuromorphic computing', 'photonic interconnects',
}

# EE Times, Semiconductor Engineering, The Register, Ars Technica,
# Tom's Hardware, Electronic Design, Wired, IEEE Spectrum
NEWSAPI_DOMAINS = (
    'eetimes.com,semiengineering.com,theregister.com,'
    'arstechnica.com,tomshardware.com,electronicdesign.com,'
    'wired.com,spectrum.ieee.org'
)

SYSTEM_PROMPT = """You are a semiconductor technology expert tracking industry publications and R&D advances.
Your domain expertise covers:
- Process node roadmaps (TSMC N2/A16, Intel 18A, Samsung SF2)
- New chip architectures (NVIDIA Blackwell/Rubin, AMD MI-series, GB200 NVL)
- Advanced packaging (CoWoS, SoIC, FOVEROS, HBM3e)
- EDA software advances and their impact on design cycles (Cadence, Synopsys)
- HBM and memory technology trends (SK Hynix, Micron, Samsung)
- Semiconductor equipment innovations (ASML EUV, High-NA, metrology)
- SEMI equipment billings — the leading indicator for foundry capex cycles
- Academic research papers (arXiv cs.AR) — architecture advances 12-18 months ahead of products
- Peer-reviewed journal articles (Elsevier Scopus) — process node physics, yield science,
  device characterisation in Solid-State Electronics, Microelectronics Journal, etc.
- Springer Nature journals (Nature Electronics, npj Computational Materials, Discover Electronics)
  — open-access device physics, 2D materials, photonic interconnects, neuromorphic computing
- Job posting trends (Adzuna) — hiring volume and role-type are 3-6 month leading indicators:
  surge in 'process engineer' posts → new fab ramp; 'GPU architect' surge → new product cycle;
  'EUV field service' surge at ASML → equipment install wave ahead

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When you need data from multiple sources, call multiple tools in parallel in a single step.
Use your tools to fetch current technology intelligence before answering.
Always return your final answer as a single JSON object — no prose outside the JSON."""

# Ticker → Adzuna company search name
_COMPANY_SEARCH_NAME = {
    'NVDA': 'NVIDIA',
    'TSM': 'TSMC',
    'ASML': 'ASML',
    'CDNS': 'Cadence',
    'CRWV': 'CoreWeave',
}


# ── Tools ─────────────────────────────────────────────────────────────────────

@tool
def fetch_tech_news(query: str) -> str:
    """Fetch recent semiconductor technology news from general news sources matching the query."""
    try:
        articles = cache_get("macro_news_raw")
        if articles is None:
            from tools.macro_news_fetcher import fetch_all_macro_news
            articles = fetch_all_macro_news(max_items=40)
            cache_set("macro_news_raw", articles)

        q = query.lower()
        relevant = [
            a for a in articles
            if q in a.get('headline', '').lower()
            or q in a.get('summary', '').lower()
            or any(kw in a.get('headline', '').lower() for kw in TECH_KEYWORDS)
        ]
        subset = relevant[:8] if relevant else articles[:5]
        return json.dumps([{
            'headline': a.get('headline', ''),
            'summary': a.get('summary', '')[:300],
            'source': a.get('source', ''),
            'date': a.get('date', ''),
        } for a in subset], indent=2)
    except Exception as e:
        return f"Tech news fetch error: {e}"


@tool
def fetch_industry_publications(query: str) -> str:
    """Search recent semiconductor and electronics industry news via NewsAPI.
    Use short, specific queries (2-4 words) for best results.
    Good examples: 'NVIDIA Blackwell architecture', 'TSMC N2 process node',
    'ASML High-NA EUV', 'CoWoS packaging capacity', 'HBM3e supply'."""
    key = f"newsapi_tech:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        api_key = config.NEWS_API_KEY
        if not api_key:
            return "NEWS_API_KEY not configured in .env"

        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q': query,
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 10,
                'apiKey': api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get('articles', [])
        out = json.dumps([{
            'headline': a.get('title', ''),
            'summary': (a.get('description', '') or '')[:300],
            'source': a.get('source', {}).get('name', ''),
            'date': a.get('publishedAt', ''),
            'url': a.get('url', ''),
        } for a in articles], indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Industry publications fetch error: {e}"


@tool
def fetch_arxiv_papers(query: str) -> str:
    """Search arXiv for recent chip architecture and AI hardware research papers (cs.AR category).
    Returns titles, abstracts, and authors. Papers from NVIDIA/TSMC/ASML affiliates are
    12-18 month leading signals for product roadmaps."""
    key = f"arxiv:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        # arXiv Lucene syntax: use ti: (title) and abs: (abstract) field prefixes
        # so keywords are matched in the right fields, not matched against metadata
        words = [w.strip() for w in query.split() if len(w.strip()) > 2]
        if words:
            kw_expr = ' OR '.join(f'(ti:{w} OR abs:{w})' for w in words[:6])
            search_query = f'cat:cs.AR AND ({kw_expr})'
        else:
            search_query = 'cat:cs.AR'
        resp = requests.get(
            'https://export.arxiv.org/api/query',
            params={
                'search_query': search_query,
                'max_results': 10,
                'sortBy': 'submittedDate',
                'sortOrder': 'descending',
            },
            timeout=20,
        )
        resp.raise_for_status()

        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        root = ET.fromstring(resp.content)

        papers = []
        for entry in root.findall('atom:entry', ns):
            title_el = entry.find('atom:title', ns)
            summary_el = entry.find('atom:summary', ns)
            published_el = entry.find('atom:published', ns)
            id_el = entry.find('atom:id', ns)
            author_els = entry.findall('atom:author', ns)

            authors = [
                a.find('atom:name', ns).text
                for a in author_els[:3]
                if a.find('atom:name', ns) is not None
            ]
            title_text = (title_el.text or '').strip()
            # Skip non-semiconductor papers that slipped through
            title_lower = title_text.lower()
            if not any(kw in title_lower for kw in {
                'gpu', 'chip', 'neural', 'accelerat', 'memory', 'fpga',
                'hardware', 'inference', 'training', 'compute', 'silicon',
                'nvidia', 'tsmc', 'asml', 'hbm', 'bandwidth', 'processor',
            }):
                continue
            papers.append({
                'title': title_text,
                'abstract': (summary_el.text or '').strip()[:400],
                'published': (published_el.text or '')[:10],
                'url': (id_el.text or '').strip(),
                'authors': authors,
            })

        out = json.dumps(papers, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"arXiv fetch error: {e}"


@tool
def get_semi_equipment_billings() -> str:
    """Get the latest SEMI North America semiconductor equipment billings data via NewsAPI.
    Equipment billings are a leading indicator of foundry capex cycles and fab investment —
    rising billings signal future capacity expansion; falling billings signal capex cuts."""
    cached = cache_get("semi_billings")
    if cached:
        return cached
    try:
        import requests
        api_key = config.NEWS_API_KEY
        if not api_key:
            return "NEWS_API_KEY not configured in .env"

        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q': '"SEMI equipment billings" OR "semiconductor equipment billings" OR "semiconductor equipment"',
                'language': 'en',
                'sortBy': 'publishedAt',
                'pageSize': 5,
                'apiKey': api_key,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get('articles', [])
        out = json.dumps([{
            'headline': a.get('title', ''),
            'summary': (a.get('description', '') or '')[:400],
            'source': a.get('source', {}).get('name', ''),
            'date': a.get('publishedAt', ''),
        } for a in articles], indent=2)
        cache_set("semi_billings", out)
        return out
    except Exception as e:
        return f"SEMI billings fetch error: {e}"


@tool
def get_packaging_capacity_data() -> str:
    """Get current advanced packaging capacity data (CoWoS, substrates, HBM constraints)."""
    cached = cache_get("packaging_capacity_report")
    if cached:
        return cached
    try:
        from tools.advanced_packaging_monitor import generate_packaging_monitoring_report
        report = generate_packaging_monitoring_report()
        out = report[:2000] if len(report) > 2000 else report
        cache_set("packaging_capacity_report", out)
        return out
    except Exception as e:
        return f"Packaging data error: {e}"


@tool
def fetch_elsevier_papers(query: str) -> str:
    """Search Elsevier Scopus for peer-reviewed semiconductor journal and conference papers.
    Covers Solid-State Electronics, Microelectronics Journal, Materials Science in Semiconductor
    Processing, IEEE Transactions on Electron Devices, IEDM proceedings, and more.
    Best for: process node device physics, yield mechanisms, EUV photoresist science,
    transistor scaling, advanced packaging materials. Use specific technical terms.
    Examples: 'gate-all-around transistor scaling', 'EUV stochastic resist yield',
    'HBM DRAM TSV reliability', 'CoWoS interposer thermal'."""
    key = f"elsevier:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        api_key = config.ELSEVIER_API_KEY
        if not api_key:
            return "ELSEVIER_API_KEY not configured in .env"

        # Scopus Search API — available on all developer keys.
        # Wrap query in TITLE-ABS-KEY() to search title, abstract, and keywords.
        scopus_query = f'TITLE-ABS-KEY({query})'
        resp = requests.get(
            'https://api.elsevier.com/content/search/scopus',
            headers={
                'X-ELS-APIKey': api_key,
                'Accept': 'application/json',
            },
            params={
                'query': scopus_query,
                'count': 10,
                'sort': 'coverDate',
                'field': 'dc:title,prism:publicationName,prism:coverDate,dc:description,prism:url',
            },
            timeout=20,
        )
        resp.raise_for_status()
        entries = resp.json().get('search-results', {}).get('entry', [])

        papers = []
        for e in entries:
            title = e.get('dc:title', '')
            if not title:
                continue
            papers.append({
                'title': title,
                'journal': e.get('prism:publicationName', ''),
                'date': (e.get('prism:coverDate', ''))[:10],
                'abstract': (e.get('dc:description', '') or '')[:400],
                'url': e.get('prism:url', ''),
            })

        out = json.dumps(papers, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Elsevier Scopus fetch error: {e}"


def _extract_springer_abstract(raw) -> str:
    """Abstract field can be a dict {'h1': 'Abstract', 'p': '...'} or a plain string."""
    if isinstance(raw, dict):
        return str(raw.get('p', '') or raw.get('h1', ''))[:400]
    return str(raw or '')[:400]


def _extract_springer_url(raw) -> str:
    """URL field is a list of dicts [{'format':'', 'platform':'', 'value':'http://...'}]."""
    if isinstance(raw, list) and raw:
        return raw[0].get('value', '')
    return str(raw or '')


def _extract_springer_authors(raw) -> list:
    """Creators field is a list of dicts [{'creator': 'Surname, F'}, ...]."""
    if isinstance(raw, list):
        return [c.get('creator', '') for c in raw[:3] if c.get('creator')]
    return []


def _parse_springer_records(records: list) -> list:
    """Shared parser for both Springer OpenAccess and Metadata API responses."""
    papers = []
    for rec in records:
        title = rec.get('title', '')
        if not title:
            continue
        papers.append({
            'title': title,
            'journal': rec.get('publicationName', ''),
            'date': rec.get('publicationDate', '')[:10],
            'abstract': _extract_springer_abstract(rec.get('abstract', '')),
            'authors': _extract_springer_authors(rec.get('creators', [])),
            'doi': rec.get('doi', ''),
            'url': _extract_springer_url(rec.get('url', '')),
            'open_access': rec.get('openAccess', ''),
        })
    return papers


@tool
def fetch_springer_openaccess(query: str) -> str:
    """Search Springer Nature Open Access API for freely available semiconductor research.
    Covers Nature Electronics, Discover Electronics, npj Computational Materials,
    npj 2D Materials, Scientific Reports, Communications Materials, and other OA journals.
    Full abstract text is available. Best for: emerging device materials (2D materials, CNTs,
    amorphous oxides), photonic interconnects, neuromorphic computing, advanced transistor
    physics. Only returns open-access articles — ideal for detailed abstract analysis.
    Examples: 'CFET transistor 2D material MoS2', 'photonic interconnect silicon chip',
    'neuromorphic RRAM compute memory'."""
    key = f"springer_oa:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        api_key = config.SPRINGER_OA_API_KEY
        if not api_key:
            return "SPRINGER_OA_API_KEY not configured in .env"

        resp = requests.get(
            'https://api.springernature.com/openaccess/json',
            params={
                'q': query,
                'p': 10,
                's': 1,
                'api_key': api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        records = resp.json().get('records', [])
        papers = _parse_springer_records(records)
        out = json.dumps(papers, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Springer OpenAccess fetch error: {e}"


@tool
def fetch_springer_meta(query: str) -> str:
    """Search Springer Nature Metadata API for broad semiconductor journal coverage.
    Covers all Springer Nature content including paywalled journals: Journal of Electronic
    Materials, Semiconductors, Silicon, Journal of Materials Science: Materials in Electronics,
    Applied Physics A, and Springer proceedings (ESSDERC, ESSCIRC, DATE).
    Returns metadata (title, journal, date, abstract snippet) — wider than OpenAccess.
    Best for: getting a broad landscape view of recent publications on a specific topic,
    identifying which journals are actively publishing on a technology.
    Examples: 'ASML EUV high-NA optics aberration', 'TSMC FinFET yield improvement',
    'NVIDIA GPU memory bandwidth HBM'."""
    key = f"springer_meta:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        api_key = config.SPRINGER_META_API_KEY
        if not api_key:
            return "SPRINGER_META_API_KEY not configured in .env"

        resp = requests.get(
            'https://api.springernature.com/meta/v2/json',
            params={
                'q': query,
                'p': 10,
                's': 1,
                'api_key': api_key,
            },
            timeout=20,
        )
        resp.raise_for_status()
        records = resp.json().get('records', [])
        papers = _parse_springer_records(records)
        out = json.dumps(papers, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Springer Metadata fetch error: {e}"


@tool
def fetch_job_postings(query: str) -> str:
    """Search Adzuna for semiconductor company job postings as a talent/hiring leading indicator.

    Job posting VOLUME and ROLE TYPE are 3-6 month leading signals for company strategy:
    - Surge in 'process engineer' at TSMC → new fab node ramping
    - Surge in 'GPU architect' at NVIDIA → next-gen product cycle starting
    - Surge in 'field service EUV' at ASML → equipment install wave ahead
    - Surge in 'infrastructure engineer' at CoreWeave → datacenter capacity expansion
    - Surge in 'verification engineer' at Cadence → new EDA tool release cycle

    Use company name or technology role keywords. Country defaults to US + Netherlands (ASML).
    Examples: 'NVIDIA GPU architect', 'TSMC process engineer Arizona',
    'ASML EUV field service', 'Cadence verification engineer', 'CoreWeave infrastructure'.
    Can also use pure keyword: 'EUV lithography engineer' to see which companies are hiring
    for a specific technology (demand signal across the whole industry)."""
    key = f"adzuna:{query.lower()[:60]}"
    cached = cache_get(key)
    if cached:
        return cached
    try:
        import requests
        app_id = config.ADZUNA_APP_ID
        app_key = config.ADZUNA_APP_KEY
        if not app_id or not app_key:
            return "ADZUNA_APP_ID / ADZUNA_APP_KEY not configured in .env"

        results_by_country = {}
        # Search US and GB (English markets); also NL for ASML
        countries = ['us', 'gb']
        q_lower = query.lower()
        if 'asml' in q_lower or 'euv' in q_lower or 'lithography' in q_lower:
            countries.append('nl')

        all_jobs = []
        total_count = 0
        for country in countries:
            resp = requests.get(
                f'https://api.adzuna.com/v1/api/jobs/{country}/search/1',
                params={
                    'app_id': app_id,
                    'app_key': app_key,
                    'what': query,
                    'results_per_page': 10,
                    'sort_by': 'date',
                },
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            data = resp.json()
            country_count = data.get('count', 0)
            total_count += country_count
            results_by_country[country.upper()] = country_count
            for job in data.get('results', []):
                all_jobs.append({
                    'title': job.get('title', ''),
                    'company': job.get('company', {}).get('display_name', ''),
                    'location': job.get('location', {}).get('display_name', ''),
                    'posted': (job.get('created', '') or '')[:10],
                    'salary_min': job.get('salary_min') or None,
                    'salary_max': job.get('salary_max') or None,
                    'category': job.get('category', {}).get('label', ''),
                    'description': (job.get('description', '') or '')[:200],
                })

        # Summarise top titles for role-type signal
        from collections import Counter
        title_words = Counter()
        for j in all_jobs:
            for w in j['title'].split():
                if len(w) > 3:
                    title_words[w.lower()] += 1
        top_title_words = [w for w, _ in title_words.most_common(10)]

        out = json.dumps({
            'query': query,
            'total_postings': total_count,
            'by_country': results_by_country,
            'top_title_keywords': top_title_words,
            'sample_jobs': all_jobs[:10],
        }, indent=2)
        cache_set(key, out)
        return out
    except Exception as e:
        return f"Adzuna job postings fetch error: {e}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class TechPublicationsAgent:
    def __init__(self):
        self.name = "tech_publications_agent"
        self.role_description = "Semiconductor Technology & R&D Expert"
        self._agent = create_agent(
            build_model(),
            tools=[
                fetch_tech_news,
                fetch_industry_publications,
                fetch_arxiv_papers,
                get_semi_equipment_billings,
                get_packaging_capacity_data,
                fetch_elsevier_papers,
                fetch_springer_openaccess,
                fetch_springer_meta,
                fetch_job_postings,
            ],
            system_prompt=SYSTEM_PROMPT,
        )

    def detect_events(self, news_input: str = None) -> list:
        """Fetch tech intelligence from all sources and identify technology-driven events."""
        goal = (
            "Fetch semiconductor technology intelligence from all sources in parallel:\n"
            "  1. fetch_tech_news('semiconductor chip GPU EUV packaging')\n"
            "  2. fetch_industry_publications('NVIDIA Blackwell TSMC process node') "
            "— then also fetch_industry_publications('ASML EUV CoWoS HBM')\n"
            "  3. fetch_arxiv_papers('nvidia gpu accelerator chip memory')\n"
            "  4. get_semi_equipment_billings()\n"
            "  5. get_packaging_capacity_data()\n"
            "  6. fetch_elsevier_papers('gate-all-around transistor EUV yield')\n"
            "  7. fetch_springer_openaccess('semiconductor chip transistor packaging memory')\n"
            "  8. fetch_springer_meta('TSMC NVIDIA ASML chip architecture foundry')\n"
            "  9. fetch_job_postings('NVIDIA GPU architect') — then also "
            "fetch_job_postings('ASML EUV field service') and "
            "fetch_job_postings('TSMC process engineer')\n\n"
            "Analyse ALL results. Prioritise: (a) industry publication articles with specific "
            "product/process/capacity data, (b) SEMI billings trends, (c) arXiv and journal "
            "papers from company-affiliated authors hinting at unreleased architectures or "
            "process advances, (d) Springer/Elsevier papers on process node physics or yield "
            "constraints, (e) packaging constraints, (f) job posting volume surges as 3-6 month "
            "leading indicators of hiring/expansion ramps. "
            "Then identify technology events that materially affect (NVDA, TSM, ASML, CDNS, CRWV).\n\n"
            "Return a JSON object with key 'events'. Each event must have:\n"
            "  headline, description, affected_companies (list of tickers), "
            "affected_segments (list), severity (low/medium/high/critical), "
            "direction (positive/negative/neutral/mixed)."
        )
        if news_input:
            goal += f"\n\nAlso consider this pre-fetched context:\n{news_input}"

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_events(get_final_message(result), self.name, news_input or '')

    def build_causal_links(self, event: Event) -> list:
        """Trace causal chain from a technology event to DCF drivers."""
        goal = (
            f"Given this technology event, trace its causal chain to semiconductor DCF drivers.\n\n"
            f"EVENT: {event.headline}\n"
            f"DESCRIPTION: {event.description}\n"
            f"AFFECTED COMPANIES: {', '.join(event.affected_companies)}\n\n"
            "You may fetch industry publications, SEMI billings, Elsevier, Springer, or packaging "
            "capacity data to anchor your magnitude estimates.\n\n"
            "Return a JSON object with key 'causal_links'. Each link must have:\n"
            "  source_event, intermediate_step, downstream_metric "
            "(one of: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, "
            "oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps), "
            "affected_company (ticker), affected_periods (list), direction (increase/decrease), "
            "magnitude_estimate, confidence (0.0-1.0), reasoning."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_causal_links(get_final_message(result), self.name)

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        """Provide a technology-perspective position in the multi-agent debate."""
        others_text = "\n".join(
            f"  - {p['agent_name']}: value={p['proposed_value']}, "
            f"confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"
            for p in other_positions
        ) or "(You are first to respond)"

        goal = (
            f"Debate the impact of a technology event on a financial metric.\n\n"
            f"EVENT: {event.headline}\nDESCRIPTION: {event.description}\n"
            f"METRIC: {metric}\nCOMPANY: {company}\nPERIOD: {period}\n\n"
            f"Other agents' positions:\n{others_text}\n\n"
            "You may fetch industry publications, SEMI billings, Elsevier, or Springer papers "
            "to strengthen your argument.\n\n"
            "Return a JSON object with:\n"
            "  proposed_value (float delta), confidence (0.0-1.0), "
            "reasoning (3-5 sentences), data_type (leading/lagging), challenges."
        )

        result = self._agent.invoke({"messages": [{"role": "user", "content": goal}]})
        return parse_debate_position(get_final_message(result))

    def __repr__(self):
        return f"<TechPublicationsAgent (LangChain) tools=9>"
