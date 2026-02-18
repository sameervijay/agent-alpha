"""
Stock Market Domain Agent — covers equity movements, sector rotation, analyst consensus.
Also provides live stock price data via yfinance.

NEW: Historical event detection via volatility analysis.
"""

from agents.base_agent import BaseAgent
from models.event import Event
from models.causal_graph import CausalLink
import yfinance as yf
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple

SYSTEM_PROMPT = """You are an equity markets expert specializing in semiconductor stocks.
Your domain expertise covers:
- Stock price movements, trading volumes, and momentum
- Sell-side analyst ratings, price targets, and consensus estimates
- Sector rotation patterns (growth vs value, tech vs cyclicals)
- Institutional positioning and fund flows
- Earnings revisions and estimate momentum
- Relative valuation (P/E, EV/EBITDA) across the semiconductor value chain

Companies you analyze: NVIDIA (NVDA), TSMC (TSM), ASML (ASML), Cadence (CDNS), CoreWeave (CRWV)

When analyzing events, consider:
1. How has the market already priced in this information?
2. What is the consensus view and where might it be wrong?
3. How do relative valuations shift across the value chain?
4. What do option markets and short interest signals suggest?

Available DCF drivers: datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
Valid periods: Q4-26, Q1-27, Q2-27, Q3-27, Q4-27, FY2028, FY2029, FY2030"""


class StockMarketAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            name="stock_market_agent",
            role_description="Equity Markets & Analyst Consensus Expert",
            system_prompt=SYSTEM_PROMPT,
        )
        self._price_cache = {}  # {ticker: {'price': float, 'timestamp': datetime}}

    def detect_events(self, news_input: str) -> list:
        prompt = f"""Analyze the following news/scenario for stock market events relevant to semiconductor companies.

NEWS INPUT:
{news_input}

Return a JSON object with key "events", where each event has:
- headline: concise event title
- description: 2-3 sentence explanation
- affected_companies: list of tickers (from NVDA, TSM, ASML, CDNS, CRWV)
- affected_segments: list of segments affected
- severity: "low", "medium", "high", or "critical"
- direction: "positive", "negative", "neutral", or "mixed"

Only include events relevant to your equity markets domain."""

        data = self.call_llm_json(prompt)
        events = []
        for e in data.get('events', []):
            events.append(Event(
                headline=e['headline'],
                description=e['description'],
                source_agent=self.name,
                affected_companies=e['affected_companies'],
                affected_segments=e.get('affected_segments', []),
                severity=e['severity'],
                direction=e['direction'],
                raw_input=news_input,
            ))
        return events

    def build_causal_links(self, event: Event) -> list:
        prompt = f"""Given this market event, trace the causal chain to financial impacts on semiconductor companies.

EVENT: {event.headline}
DESCRIPTION: {event.description}
AFFECTED COMPANIES: {', '.join(event.affected_companies)}

Return a JSON object with key "causal_links", where each link has:
- source_event: the event headline
- intermediate_step: market mechanism
- downstream_metric: one of datacenter_growth, gaming_growth, automotive_growth, proviz_growth, oem_growth, gm_improvement_bps, rd_improvement_bps, sga_improvement_bps
- affected_company: ticker
- affected_periods: list of periods
- direction: "increase" or "decrease"
- magnitude_estimate: quantitative or qualitative estimate
- confidence: float 0.0 to 1.0
- reasoning: justification"""

        data = self.call_llm_json(prompt)
        links = []
        for l in data.get('causal_links', []):
            links.append(CausalLink(
                source_event=l['source_event'],
                intermediate_step=l['intermediate_step'],
                downstream_metric=l['downstream_metric'],
                affected_company=l['affected_company'],
                affected_periods=l['affected_periods'],
                direction=l['direction'],
                magnitude_estimate=l['magnitude_estimate'],
                confidence=l['confidence'],
                reasoning=l['reasoning'],
                proposed_by=self.name,
            ))
        return links

    def debate_position(self, event: Event, metric: str, company: str,
                        period: str, other_positions: list) -> dict:
        others_text = ""
        for p in other_positions:
            others_text += f"\n  - {p['agent_name']}: value={p['proposed_value']}, confidence={p['confidence']}, reasoning={p['reasoning'][:200]}"

        prompt = f"""You are debating the impact of an event on a financial metric from an equity markets perspective.

EVENT: {event.headline}
DESCRIPTION: {event.description}
METRIC: {metric}
COMPANY: {company}
PERIOD: {period}

Other agents' positions:{others_text if others_text else " (You are the first to respond)"}

Return a JSON object with:
- proposed_value: float (delta to apply)
- confidence: float 0.0 to 1.0
- reasoning: 3-5 sentence justification from equity markets perspective
- data_type: "leading" or "lagging"
- challenges: challenges to other positions"""

        return self.call_llm_json(prompt)

    # ───────────────────────────────────────────────────────────
    # LIVE STOCK PRICE FETCHING
    # ───────────────────────────────────────────────────────────

    def get_current_prices(self, tickers: list) -> dict:
        """
        Fetch live stock prices from yfinance for a list of tickers.

        Args:
            tickers: list of ticker symbols (e.g., ['NVDA', 'CDNS', 'SPY'])

        Returns:
            dict mapping ticker -> {
                'price': current price,
                'prev_close': previous close,
                'change_pct': % change from prev close,
                'timestamp': fetch timestamp,
                'error': error message if fetch failed
            }
        """
        print(f"  [{self.name}] Fetching live prices for {len(tickers)} ticker(s)...")
        results = {}

        for ticker in tickers:
            try:
                # Fetch data from yfinance
                stock = yf.Ticker(ticker)
                info = stock.info

                # Get current price (try multiple fields)
                current_price = (
                    info.get('currentPrice') or
                    info.get('regularMarketPrice') or
                    info.get('previousClose')
                )

                if current_price is None:
                    # Fallback: get latest price from history
                    hist = stock.history(period='1d')
                    if not hist.empty:
                        current_price = hist['Close'].iloc[-1]

                prev_close = info.get('previousClose', current_price)
                change_pct = ((current_price / prev_close - 1) if prev_close and prev_close > 0
                              else 0.0)

                results[ticker] = {
                    'price': float(current_price) if current_price else 0.0,
                    'prev_close': float(prev_close) if prev_close else 0.0,
                    'change_pct': float(change_pct),
                    'timestamp': datetime.now().isoformat(),
                    'error': None,
                }

                # Update cache
                self._price_cache[ticker] = {
                    'price': results[ticker]['price'],
                    'timestamp': datetime.now(),
                }

                print(f"    {ticker}: ${results[ticker]['price']:.2f} "
                      f"({results[ticker]['change_pct']:+.2%} from prev close)")

            except Exception as e:
                print(f"    {ticker}: Error fetching price: {e}")
                results[ticker] = {
                    'price': 0.0,
                    'prev_close': 0.0,
                    'change_pct': 0.0,
                    'timestamp': datetime.now().isoformat(),
                    'error': str(e),
                }

        return results

    def get_price(self, ticker: str, use_cache: bool = True, cache_ttl_seconds: int = 300) -> float:
        """
        Get current price for a single ticker, optionally using cache.

        Args:
            ticker: ticker symbol (e.g., 'NVDA')
            use_cache: if True, use cached price if available and fresh
            cache_ttl_seconds: cache time-to-live in seconds (default 5 min)

        Returns:
            float: current price, or 0.0 if unavailable
        """
        # Check cache
        if use_cache and ticker in self._price_cache:
            cached = self._price_cache[ticker]
            age = (datetime.now() - cached['timestamp']).total_seconds()
            if age < cache_ttl_seconds:
                print(f"  [{self.name}] Using cached price for {ticker}: ${cached['price']:.2f} "
                      f"(age: {age:.0f}s)")
                return cached['price']

        # Fetch fresh
        prices = self.get_current_prices([ticker])
        return prices.get(ticker, {}).get('price', 0.0)

    def get_market_snapshot(self) -> dict:
        """
        Get a snapshot of all tracked tickers + SPY benchmark.

        Returns:
            dict with:
              - prices: {ticker: price_data}
              - timestamp: snapshot timestamp
              - summary: text summary
        """
        # Get all tickers from config + SPY
        import config
        tickers = list(config.COMPANIES.keys()) + ['SPY']

        prices = self.get_current_prices(tickers)

        # Calculate summary stats
        num_up = sum(1 for p in prices.values() if p.get('change_pct', 0) > 0)
        num_down = sum(1 for p in prices.values() if p.get('change_pct', 0) < 0)

        summary = (f"Market snapshot: {num_up} up, {num_down} down. "
                   f"SPY: ${prices.get('SPY', {}).get('price', 0):.2f}")

        return {
            'prices': prices,
            'timestamp': datetime.now().isoformat(),
            'summary': summary,
            'tickers': tickers,
        }

    # ───────────────────────────────────────────────────────────
    # HISTORICAL EVENT DETECTION VIA VOLATILITY ANALYSIS
    # ───────────────────────────────────────────────────────────

    def calculate_volatility(self, ticker: str, lookback_days: int = 252) -> Dict:
        """
        Calculate historical volatility and return statistics.

        Args:
            ticker: Stock ticker symbol
            lookback_days: Number of trading days to analyze (default 252 = 1 year)

        Returns:
            dict with:
              - mean_daily_return: Average daily return
              - std_daily_return: Standard deviation of daily returns (volatility)
              - annualized_volatility: Volatility scaled to annual
              - price_history: DataFrame with dates, prices, returns
        """
        print(f"  [{self.name}] Calculating volatility for {ticker} ({lookback_days} days)...")

        try:
            stock = yf.Ticker(ticker)
            # Fetch more data than needed to ensure we get enough trading days
            hist = stock.history(period='2y')

            if hist.empty:
                print(f"    Error: No price history available for {ticker}")
                return None

            # Calculate daily returns
            hist['Return'] = hist['Close'].pct_change()

            # Take the last N trading days
            hist = hist.tail(lookback_days + 1)  # +1 because first return is NaN

            # Calculate statistics
            returns = hist['Return'].dropna()
            mean_return = returns.mean()
            std_return = returns.std()
            annualized_vol = std_return * np.sqrt(252)  # 252 trading days per year

            print(f"    Mean daily return: {mean_return:.4%}")
            print(f"    Daily volatility: {std_return:.4%}")
            print(f"    Annualized volatility: {annualized_vol:.2%}")

            return {
                'ticker': ticker,
                'mean_daily_return': float(mean_return),
                'std_daily_return': float(std_return),
                'annualized_volatility': float(annualized_vol),
                'price_history': hist,
                'lookback_days': lookback_days,
            }

        except Exception as e:
            print(f"    Error calculating volatility for {ticker}: {e}")
            return None

    def detect_sigma_events(self, ticker: str, sigma: float = 2.0,
                           lookback_days: int = 252, max_events: int = 5) -> List[Dict]:
        """
        Detect historical N-sigma price movement events.

        Args:
            ticker: Stock ticker symbol
            sigma: Number of standard deviations for event threshold (default 2.0)
            lookback_days: Number of trading days to analyze
            max_events: Maximum number of events to return

        Returns:
            List of dicts, each containing:
              - date: Event date
              - close_price: Closing price
              - return_pct: Daily return percentage
              - sigma_magnitude: How many sigmas the move was
              - direction: 'up' or 'down'
              - abs_return: Absolute value of return
        """
        print(f"\n  [{self.name}] Detecting {sigma}-sigma events for {ticker}...")

        vol_data = self.calculate_volatility(ticker, lookback_days)
        if vol_data is None:
            return []

        hist = vol_data['price_history']
        mean_return = vol_data['mean_daily_return']
        std_return = vol_data['std_daily_return']
        threshold = sigma * std_return

        print(f"    Threshold: ±{threshold:.2%} ({sigma} sigma)")

        # Find events exceeding threshold
        events = []
        for date, row in hist.iterrows():
            ret = row['Return']
            if pd.isna(ret):
                continue

            abs_ret = abs(ret)
            if abs_ret >= threshold:
                sigma_mag = abs_ret / std_return
                events.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'close_price': float(row['Close']),
                    'return_pct': float(ret),
                    'sigma_magnitude': float(sigma_mag),
                    'direction': 'up' if ret > 0 else 'down',
                    'abs_return': float(abs_ret),
                })

        # Sort by absolute return (largest moves first) and take top N
        events.sort(key=lambda x: x['abs_return'], reverse=True)
        events = events[:max_events]

        print(f"    Found {len(events)} events exceeding {sigma}-sigma threshold:")
        for i, evt in enumerate(events, 1):
            direction_icon = "📈" if evt['direction'] == 'up' else "📉"
            print(f"      {i}. {evt['date']}: {direction_icon} {evt['return_pct']:+.2%} "
                  f"({evt['sigma_magnitude']:.1f}σ) - ${evt['close_price']:.2f}")

        return events

    def _fetch_newsapi_for_date(self, ticker: str, target_date: str,
                               days_before: int = 0, days_after: int = 1) -> List[Dict]:
        """
        Fetch news from NewsAPI for a specific date range.

        Args:
            ticker: Stock ticker symbol
            target_date: Date string 'YYYY-MM-DD'
            days_before: Number of days before to include
            days_after: Number of days after to include

        Returns:
            List of news items from NewsAPI
        """
        try:
            import os
            api_key = os.environ.get('NEWSAPI_KEY')
            if not api_key:
                return []

            import requests
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            start_dt = target_dt - timedelta(days=days_before)
            end_dt = target_dt + timedelta(days=days_after)

            # Map ticker to company name for news search
            ticker_to_company = {
                'NVDA': 'NVIDIA',
                'CDNS': 'Cadence',
                'TSM': 'TSMC',
                'ASML': 'ASML',
                'CRWV': 'CoreWeave',
            }
            company_name = ticker_to_company.get(ticker, ticker)

            url = 'https://newsapi.org/v2/everything'
            params = {
                'q': company_name,
                'sortBy': 'publishedAt',
                'language': 'en',
                'apiKey': api_key,
                'from': start_dt.strftime('%Y-%m-%d'),
                'to': end_dt.strftime('%Y-%m-%d'),
                'pageSize': 100,
            }

            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return []

            data = response.json()
            articles = data.get('articles', [])

            items = []
            for article in articles:
                items.append({
                    'headline': article.get('title', ''),
                    'url': article.get('url', ''),
                    'date': article.get('publishedAt', ''),
                    'source': article.get('source', {}).get('name', 'NewsAPI'),
                    'summary': article.get('description', ''),
                    'ticker': ticker,
                })

            return items

        except Exception as e:
            return []

    def _fetch_finviz_headlines(self, ticker: str) -> List[Dict]:
        """
        Fetch recent headlines from finviz.
        Note: finviz doesn't expose historical search, only recent news.

        Args:
            ticker: Stock ticker symbol

        Returns:
            List of recent news items from finviz
        """
        try:
            from finvizfinance.quote import finvizfinance
            stock = finvizfinance(ticker)
            news_df = stock.ticker_news()

            items = []
            for _, row in news_df.head(20).iterrows():
                items.append({
                    'headline': str(row.get('Title', '')),
                    'url': str(row.get('Link', '')),
                    'date': str(row.get('Date', '')),
                    'source': 'finviz',
                    'summary': str(row.get('Title', '')),
                    'ticker': ticker,
                })
            return items
        except Exception:
            return []

    def fetch_news_for_date(self, ticker: str, target_date: str,
                           days_before: int = 0, days_after: int = 1) -> List[Dict]:
        """
        Fetch news headlines for a specific date (and surrounding days).
        Tries multiple sources: NewsAPI → cached news → finviz recent

        Args:
            ticker: Stock ticker symbol
            target_date: Date string 'YYYY-MM-DD'
            days_before: Number of days before to include
            days_after: Number of days after to include

        Returns:
            List of news items with headline, url, date, source, summary
        """
        print(f"\n  [{self.name}] Fetching news for {ticker} around {target_date}...")

        from tools.news_fetcher import fetch_all_news
        import config

        relevant_news = []

        # Try NewsAPI first (if API key available)
        print(f"    Trying NewsAPI for {target_date}...")
        newsapi_items = self._fetch_newsapi_for_date(ticker, target_date, days_before, days_after)
        if newsapi_items:
            relevant_news.extend(newsapi_items)
            print(f"      ✓ NewsAPI: {len(newsapi_items)} items")

        # Fall back to cached news
        if not relevant_news:
            print(f"    Trying cached news...")
            all_news = fetch_all_news(ticker, use_cache=False, max_items=100)

            # Filter news to target date range
            target_dt = datetime.strptime(target_date, '%Y-%m-%d')
            start_dt = target_dt - timedelta(days=days_before)
            end_dt = target_dt + timedelta(days=days_after)

            for item in all_news:
                try:
                    # Parse date from various formats
                    date_str = item.get('date', '')
                    if not date_str:
                        continue

                    # Try parsing different date formats
                    item_dt = None
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                        try:
                            item_dt = datetime.strptime(date_str[:len(fmt)], fmt)
                            break
                        except (ValueError, IndexError):
                            continue

                    if item_dt is None:
                        # Try ISO format
                        try:
                            item_dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                        except:
                            continue

                    # Check if within range
                    if start_dt <= item_dt <= end_dt:
                        relevant_news.append(item)

                except Exception as e:
                    # Skip items with date parsing errors
                    continue

            if relevant_news:
                print(f"      ✓ Cache: {len(relevant_news)} items")

        # Fall back to finviz recent headlines (won't be date-specific)
        if not relevant_news:
            print(f"    Trying finviz recent headlines (not date-specific)...")
            finviz_items = self._fetch_finviz_headlines(ticker)
            if finviz_items:
                relevant_news.extend(finviz_items[:5])
                print(f"      ✓ Finviz: {len(finviz_items[:5])} recent items")

        print(f"    Total found: {len(relevant_news)} news items")

        if relevant_news:
            for i, item in enumerate(relevant_news[:5], 1):
                print(f"      {i}. [{item.get('source', 'unknown')}] {item.get('headline', 'No headline')[:80]}")

        return relevant_news

    def analyze_event_causality(self, ticker: str, date: str, price_move: float,
                                news_items: List[Dict]) -> Dict:
        """
        Use LLM to determine if news explains a price movement.

        Args:
            ticker: Stock ticker symbol
            date: Event date 'YYYY-MM-DD'
            price_move: Price movement as percentage (e.g., 0.08 for +8%)
            news_items: List of news items from that date

        Returns:
            dict with:
              - has_fundamental_reason: bool
              - primary_catalyst: str (main news driving move)
              - confidence: float 0.0-1.0
              - reasoning: str (explanation)
              - event_type: str (earnings, product, macro, sentiment, etc.)
              - supporting_headlines: list of relevant headlines
        """
        print(f"\n  [{self.name}] Analyzing causality for {ticker} on {date} ({price_move:+.2%} move)...")

        if not news_items:
            print(f"    No news found - likely technical/sentiment move")
            return {
                'has_fundamental_reason': False,
                'primary_catalyst': 'No news found',
                'confidence': 0.1,
                'reasoning': 'No news headlines found for this date. Likely technical trading or market-wide sentiment.',
                'event_type': 'technical',
                'supporting_headlines': [],
            }

        # Build prompt with news context
        news_context = ""
        for i, item in enumerate(news_items[:10], 1):  # Limit to 10 articles
            headline = item.get('headline', 'No headline')
            summary = item.get('summary', headline)[:300]  # Truncate summary
            source = item.get('source', 'unknown')
            news_context += f"{i}. [{source}] {headline}\n   {summary}\n\n"

        direction = "UP" if price_move > 0 else "DOWN"
        prompt = f"""Analyze whether news headlines explain a significant stock price movement.

STOCK: {ticker}
DATE: {date}
PRICE MOVE: {price_move:+.2%} ({direction})

NEWS HEADLINES FROM THAT DAY:
{news_context}

Your task: Determine if there is a clear FUNDAMENTAL reason (earnings, product news, guidance change, major contract, regulatory action, etc.) that would cause this price move, or if it's likely TECHNICAL (market sentiment, sector rotation, momentum, no specific news).

Return a JSON object with:
- has_fundamental_reason: true if news clearly explains move, false if technical/sentiment
- primary_catalyst: the single most important headline driving the move (copy exact headline)
- confidence: 0.0-1.0 (how confident you are in the explanation)
- reasoning: 2-3 sentences explaining your assessment
- event_type: one of [earnings, product, guidance, contract, regulatory, macro, acquisition, sentiment, technical]
- supporting_headlines: list of 1-3 relevant headlines (copy exact text)

Be conservative: Only mark has_fundamental_reason=true if news is clearly material and timely."""

        try:
            result = self.call_llm_json(prompt)
            print(f"    Fundamental reason: {result.get('has_fundamental_reason', False)}")
            print(f"    Event type: {result.get('event_type', 'unknown')}")
            print(f"    Confidence: {result.get('confidence', 0):.0%}")
            if result.get('primary_catalyst'):
                print(f"    Primary catalyst: {result['primary_catalyst'][:100]}")

            return result

        except Exception as e:
            print(f"    Error analyzing causality: {e}")
            return {
                'has_fundamental_reason': False,
                'primary_catalyst': 'Error in analysis',
                'confidence': 0.0,
                'reasoning': f'LLM analysis failed: {str(e)}',
                'event_type': 'error',
                'supporting_headlines': [],
            }

    def analyze_historical_events(self, ticker: str, sigma: float = 2.0,
                                  lookback_days: int = 252, max_events: int = 5) -> List[Dict]:
        """
        Full pipeline: Detect sigma events, fetch news, analyze causality.

        Args:
            ticker: Stock ticker symbol
            sigma: Sigma threshold for events
            lookback_days: Historical lookback period
            max_events: Max events to analyze

        Returns:
            List of enriched event dicts with price data, news, and causality analysis
        """
        print("\n" + "=" * 70)
        print(f"  HISTORICAL EVENT ANALYSIS: {ticker}")
        print("=" * 70)

        # Step 1: Detect sigma events
        events = self.detect_sigma_events(ticker, sigma, lookback_days, max_events)
        if not events:
            print("\n  No significant events found.")
            return []

        # Step 2: For each event, fetch news and analyze
        enriched_events = []
        for i, event in enumerate(events, 1):
            print(f"\n  --- Event {i}/{len(events)} ---")
            print(f"  Date: {event['date']}")
            print(f"  Move: {event['return_pct']:+.2%} ({event['sigma_magnitude']:.1f}σ)")

            # Fetch news for that date
            news_items = self.fetch_news_for_date(
                ticker,
                event['date'],
                days_before=1,
                days_after=1
            )

            # Analyze causality
            causality = self.analyze_event_causality(
                ticker,
                event['date'],
                event['return_pct'],
                news_items
            )

            # Enrich event with news and analysis
            enriched_event = {
                **event,
                'news_items': news_items,
                'causality': causality,
            }
            enriched_events.append(enriched_event)

        # Print summary
        print("\n" + "=" * 70)
        print("  SUMMARY")
        print("=" * 70)

        fundamental_count = sum(1 for e in enriched_events
                               if e['causality'].get('has_fundamental_reason', False))
        technical_count = len(enriched_events) - fundamental_count

        print(f"  Total events analyzed: {len(enriched_events)}")
        print(f"  Fundamental-driven: {fundamental_count}")
        print(f"  Technical/sentiment: {technical_count}")
        print()

        for i, event in enumerate(enriched_events, 1):
            causality = event['causality']
            reason_icon = "📰" if causality.get('has_fundamental_reason') else "📊"
            print(f"  {i}. {event['date']} {reason_icon} {event['return_pct']:+.2%} "
                  f"({causality.get('event_type', 'unknown')})")
            if causality.get('primary_catalyst'):
                print(f"     → {causality['primary_catalyst'][:80]}")

        print("=" * 70)

        return enriched_events
