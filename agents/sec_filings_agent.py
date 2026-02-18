"""
SEC Filings Agent - Fetches and parses SEC filings (10-K, 10-Q, 8-K).

Uses the free SEC EDGAR data.sec.gov API for public filing retrieval.
Implements rate limiting (10 req/sec) and caching per SEC guidelines.
"""

import requests
import json
import time
import re
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup
from typing import Dict, List, Optional


# SEC requires User-Agent header with contact info
HEADERS = {
    'User-Agent': 'Matthew Wolfman wolfman701@gmail.com'
}

# Company CIK mappings
CIK_MAP = {
    'NVDA': '0001045810',
    'CDNS': '0001023731',
    'TSMC': '0001046179',
    'ASML': '0000937966',
    'CWEV': '0001908461',  # CoreWeave (if available)
}


class SECFilingsAgent:
    """
    Agent for fetching and parsing SEC filings.

    Features:
    - Rate limiting (10 req/sec per SEC guidelines)
    - Local caching to minimize API calls
    - HTML cleaning and section extraction
    - Support for 10-K, 10-Q, 8-K filings
    """

    def __init__(self):
        self.cache_dir = Path('data/sec_filings')
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Rate limiting: 10 requests/second max
        self.last_request_time = None
        self.min_request_interval = 0.1  # 10 req/sec = 0.1s between requests

    def _rate_limit(self):
        """Enforce SEC's 10 requests/second rate limit."""
        if self.last_request_time:
            elapsed = time.time() - self.last_request_time
            if elapsed < self.min_request_interval:
                time.sleep(self.min_request_interval - elapsed)
        self.last_request_time = time.time()

    def _fetch(self, url: str) -> requests.Response:
        """Fetch URL with rate limiting and proper headers."""
        self._rate_limit()
        response = requests.get(url, headers=HEADERS)
        response.raise_for_status()
        return response

    def _get_cik(self, ticker: str) -> str:
        """Get CIK for ticker (with leading zeros)."""
        cik = CIK_MAP.get(ticker.upper())
        if not cik:
            raise ValueError(f"Unknown ticker: {ticker}. Add to CIK_MAP.")
        return cik

    def _get_cache_path(self, ticker: str, form_type: str, filing_date: str) -> Path:
        """Get cache file path for a filing."""
        ticker_dir = self.cache_dir / ticker.upper()
        ticker_dir.mkdir(exist_ok=True)
        filename = f"{form_type}_{filing_date}.json"
        return ticker_dir / filename

    def _load_cached_filing(self, ticker: str, form_type: str, filing_date: str) -> Optional[Dict]:
        """Load cached filing if available."""
        cache_path = self._get_cache_path(ticker, form_type, filing_date)
        if cache_path.exists():
            with open(cache_path, 'r') as f:
                return json.load(f)
        return None

    def _save_cached_filing(self, ticker: str, form_type: str, filing_date: str, data: Dict):
        """Save filing to cache."""
        cache_path = self._get_cache_path(ticker, form_type, filing_date)
        with open(cache_path, 'w') as f:
            json.dump(data, f, indent=2)

    def _clean_html_text(self, html: str) -> str:
        """Remove HTML tags and clean up text."""
        soup = BeautifulSoup(html, 'html.parser')

        # Remove script and style elements
        for script in soup(['script', 'style']):
            script.decompose()

        # Get text
        text = soup.get_text()

        # Break into lines and remove leading/trailing space
        lines = (line.strip() for line in text.splitlines())

        # Break multi-headlines into a line each
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))

        # Drop blank lines
        text = '\n'.join(chunk for chunk in chunks if chunk)

        return text

    def _extract_section(self, text: str, item_number: str, max_chars: int = 50000) -> str:
        """
        Extract a specific section (Item) from filing text.

        Common sections:
        - Item 1: Business
        - Item 1A: Risk Factors
        - Item 7: MD&A (Management's Discussion and Analysis)
        - Item 8: Financial Statements
        """
        # Find ALL occurrences of this item (might appear in TOC and then actual content)
        item_patterns = [
            rf"Item\s+{re.escape(item_number)}[\.\s]+",
            rf"ITEM\s+{re.escape(item_number)}[\.\s]+",
        ]

        matches = []
        for pattern in item_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                matches.append(match.start())

        if not matches:
            return f"Section Item {item_number} not found in filing"

        # Try each match (skip TOC entries which are usually early and short)
        for start_idx in matches:
            # Find the end of this section (next Item X marker)
            next_item_pattern = r"Item\s+\d+[A-Z]?[\.\s:]+"
            text_after_start = text[start_idx + 50:]  # Skip past our own item marker

            next_match = re.search(next_item_pattern, text_after_start, re.IGNORECASE)

            if next_match:
                # Check if next item is very close (< 500 chars) - likely TOC
                if next_match.start() < 500:
                    continue  # Skip this match, try next one

                # This looks like actual content
                end_idx = start_idx + 50 + next_match.start()
                section_text = text[start_idx:end_idx].strip()
            else:
                # No next section found, take max_chars
                section_text = text[start_idx:start_idx + max_chars].strip()

            # Check if section has substantial content (> 1000 chars)
            if len(section_text) > 1000:
                # Truncate to max_chars if needed
                if len(section_text) > max_chars:
                    section_text = section_text[:max_chars]
                return section_text

        # If we get here, no substantial content found - return first match
        if matches:
            start_idx = matches[0]
            section_text = text[start_idx:start_idx + max_chars].strip()
            return section_text

        return f"Section Item {item_number} not found with substantial content"

    def get_company_submissions(self, ticker: str) -> Dict:
        """
        Fetch company submissions metadata from SEC.

        Returns all filings metadata for the company.
        """
        cik = self._get_cik(ticker)
        url = f"https://data.sec.gov/submissions/CIK{cik}.json"

        print(f"  [sec_filings] Fetching submissions for {ticker} (CIK {cik})...")
        response = self._fetch(url)
        return response.json()

    def get_latest_filing(self, ticker: str, form_type: str) -> Optional[Dict]:
        """
        Get latest filing of specified type (10-K, 10-Q, 8-K).

        Returns:
            Dict with filing metadata and parsed sections, or None if not found.
        """
        # Check cache first
        submissions = self.get_company_submissions(ticker)
        recent = submissions['filings']['recent']

        forms = recent['form']
        filing_dates = recent['filingDate']
        accession_numbers = recent['accessionNumber']
        primary_documents = recent['primaryDocument']
        report_dates = recent.get('reportDate', [None] * len(forms))

        # Find latest matching form
        for i, form in enumerate(forms):
            if form == form_type:
                filing_date = filing_dates[i]

                # Check cache
                cached = self._load_cached_filing(ticker, form_type, filing_date)
                if cached:
                    print(f"  [sec_filings] Loaded {form_type} from cache (filed {filing_date})")
                    return cached

                # Fetch and parse filing
                print(f"  [sec_filings] Fetching {form_type} filed on {filing_date}...")

                cik = self._get_cik(ticker)
                accession = accession_numbers[i]
                document = primary_documents[i]
                report_date = report_dates[i]

                filing_data = self._fetch_and_parse_filing(
                    ticker, cik, form_type, filing_date, report_date,
                    accession, document
                )

                # Cache it
                self._save_cached_filing(ticker, form_type, filing_date, filing_data)

                return filing_data

        print(f"  [sec_filings] No {form_type} filing found for {ticker}")
        return None

    def _fetch_and_parse_filing(
        self, ticker: str, cik: str, form_type: str,
        filing_date: str, report_date: str,
        accession: str, document: str
    ) -> Dict:
        """Fetch filing HTML and extract sections."""

        # Construct document URL
        accession_clean = accession.replace('-', '')
        doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{document}"

        print(f"  [sec_filings] Downloading from {doc_url[:80]}...")
        response = self._fetch(doc_url)
        html_content = response.text

        print(f"  [sec_filings] Cleaning HTML ({len(html_content):,} chars)...")
        clean_text = self._clean_html_text(html_content)

        print(f"  [sec_filings] Extracting sections from {len(clean_text):,} chars of text...")

        # Extract key sections based on form type
        sections = {}

        if form_type in ['10-K', '10-Q']:
            sections['business'] = self._extract_section(clean_text, '1', max_chars=30000)
            sections['risk_factors'] = self._extract_section(clean_text, '1A', max_chars=50000)
            sections['mda'] = self._extract_section(clean_text, '7', max_chars=50000)
            sections['financials'] = self._extract_section(clean_text, '8', max_chars=30000)
        elif form_type == '8-K':
            # 8-K has different structure (Items 1.01, 2.02, etc.)
            # For now, just store full text
            sections['full_text'] = clean_text[:50000]

        filing_data = {
            'ticker': ticker,
            'form_type': form_type,
            'filing_date': filing_date,
            'report_date': report_date,
            'accession_number': accession,
            'document_url': doc_url,
            'cached_at': datetime.now().isoformat(),
            'sections': sections,
            'full_text_length': len(clean_text),
        }

        print(f"  [sec_filings] Extracted {len(sections)} sections")

        return filing_data

    def get_latest_10k(self, ticker: str) -> Optional[Dict]:
        """Fetch latest 10-K annual report."""
        return self.get_latest_filing(ticker, '10-K')

    def get_latest_10q(self, ticker: str) -> Optional[Dict]:
        """Fetch latest 10-Q quarterly report."""
        return self.get_latest_filing(ticker, '10-Q')

    def get_recent_8k(self, ticker: str, limit: int = 5) -> List[Dict]:
        """
        Fetch recent 8-K current reports.

        Args:
            ticker: Stock ticker
            limit: Number of recent 8-Ks to fetch

        Returns:
            List of 8-K filing dicts
        """
        submissions = self.get_company_submissions(ticker)
        recent = submissions['filings']['recent']

        forms = recent['form']
        filing_dates = recent['filingDate']
        accession_numbers = recent['accessionNumber']
        primary_documents = recent['primaryDocument']
        report_dates = recent.get('reportDate', [None] * len(forms))

        filings_8k = []
        cik = self._get_cik(ticker)

        for i, form in enumerate(forms):
            if form == '8-K' and len(filings_8k) < limit:
                filing_date = filing_dates[i]

                # Check cache
                cached = self._load_cached_filing(ticker, '8-K', filing_date)
                if cached:
                    filings_8k.append(cached)
                    continue

                # Fetch
                print(f"  [sec_filings] Fetching 8-K #{len(filings_8k)+1} filed on {filing_date}...")

                filing_data = self._fetch_and_parse_filing(
                    ticker, cik, '8-K', filing_date, report_dates[i],
                    accession_numbers[i], primary_documents[i]
                )

                # Cache it
                self._save_cached_filing(ticker, '8-K', filing_date, filing_data)
                filings_8k.append(filing_data)

        return filings_8k

    def get_company_facts(self, ticker: str) -> Optional[Dict]:
        """
        Fetch XBRL company facts (structured financial data).

        Returns standardized financial statement data from all filings.
        """
        cik = self._get_cik(ticker)
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

        try:
            print(f"  [sec_filings] Fetching XBRL company facts for {ticker}...")
            response = self._fetch(url)
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                print(f"  [sec_filings] No XBRL data available for {ticker}")
                return None
            raise
