"""
Market Monitor Tool
===================
Tracks stock market metrics for the 5 semiconductor companies:
- Short interest levels
- Trading volumes and unusual activity
- Earnings calendar
- Sector rotation indicators
- Relative valuations
- Technical levels

Usage:
    from tools.market_monitor import MarketMonitor
    monitor = MarketMonitor()

    # Get full market snapshot
    snapshot = monitor.get_market_snapshot()

    # Check earnings calendar
    calendar = monitor.get_earnings_calendar()

    # Check for unusual trading activity
    unusual = monitor.detect_unusual_volumes()
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List
import yfinance as yf

# Tickers we monitor
TICKERS = ['NVDA', 'TSM', 'ASML', 'CDNS', 'CRWV']

# Earnings calendar (estimated based on historical patterns)
EARNINGS_CALENDAR = {
    'NVDA': {
        'Q1FY2026': '2026-05-20',  # Estimated
        'Q2FY2026': '2026-08-25',  # Estimated
        'Q3FY2026': '2026-11-18',  # Estimated
        'Q4FY2026': '2027-02-24',  # Estimated
    },
    'TSM': {
        'Q4FY2025': '2026-01-14',  # Historical
        'Q1FY2026': '2026-04-15',  # Estimated
        'Q2FY2026': '2026-07-15',  # Estimated
        'Q3FY2026': '2026-10-14',  # Estimated
    },
    'ASML': {
        'Q4FY2025': '2026-01-29',  # Historical
        'Q1FY2026': '2026-04-23',  # Estimated
        'Q2FY2026': '2026-07-23',  # Estimated
        'Q3FY2026': '2026-10-22',  # Estimated
    },
    'CDNS': {
        'Q4FY2025': '2026-02-09',  # Estimated
        'Q1FY2026': '2026-05-11',  # Estimated
        'Q2FY2026': '2026-08-10',  # Estimated
        'Q3FY2026': '2026-11-09',  # Estimated
    },
    'CRWV': {
        'Q4FY2025': '2026-03-15',  # Estimated (new public company)
        'Q1FY2026': '2026-06-15',  # Estimated
        'Q2FY2026': '2026-09-15',  # Estimated
    },
}

# Sector classifications
SECTORS = {
    'NVDA': 'Semiconductors',
    'TSM': 'Semiconductors',
    'ASML': 'Semiconductors',
    'CDNS': 'Software',
    'CRWV': 'Cloud Infrastructure',
}


class MarketMonitor:
    """Monitor market metrics for semiconductor stocks."""

    def __init__(self):
        self.data_dir = Path(__file__).parent.parent / 'data'
        self.market_view_file = self.data_dir / 'valuations' / 'market_view_latest.json'
        self._cache = {}

    def get_market_snapshot(self) -> Dict:
        """Get current market snapshot: prices, volumes, valuations."""
        print("Fetching market snapshot...")

        snapshot = {
            'timestamp': datetime.now().isoformat(),
            'stocks': {},
            'sector_rotation': self._analyze_sector_rotation(),
            'technical_signals': self._get_technical_signals(),
        }

        for ticker in TICKERS:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='1d')
                info = stock.info if hasattr(stock, 'info') else {}

                snapshot['stocks'][ticker] = {
                    'price': hist['Close'].iloc[-1] if len(hist) > 0 else None,
                    'volume': hist['Volume'].iloc[-1] if len(hist) > 0 else None,
                    'volume_avg_30d': self._get_avg_volume(ticker, days=30),
                    'sector': SECTORS.get(ticker, 'Unknown'),
                    'pe_forward_ntm': info.get('forwardPE'),  # NTM is primary
                    'pe_trailing_ttm': info.get('trailingPE'),  # TTM is secondary
                    'market_cap': info.get('marketCap'),
                    'short_interest': self._estimate_short_interest(ticker),
                    'days_to_cover': self._estimate_days_to_cover(ticker),
                    'next_earnings': self._get_next_earnings(ticker),
                    'unusual_volume': self._check_unusual_volume(ticker),
                }
            except Exception as e:
                print(f"  Error fetching {ticker}: {e}")
                snapshot['stocks'][ticker] = {'error': str(e)}

        # Save snapshot
        self._save_snapshot(snapshot)
        return snapshot

    def _get_avg_volume(self, ticker: str, days: int = 30) -> float:
        """Get average volume over N days."""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period=f'{days}d')
            return float(hist['Volume'].mean()) if len(hist) > 0 else 0
        except:
            return 0

    def _estimate_short_interest(self, ticker: str) -> Dict:
        """
        Estimate short interest based on available data.
        NOTE: Real data would come from shortvolume.com or similar
        For now, using historical estimates.
        """
        # These are placeholder estimates (would need real data source)
        estimates = {
            'NVDA': {'pct_float': 1.2, 'shares_millions': 30},
            'TSM': {'pct_float': 0.8, 'shares_millions': 20},
            'ASML': {'pct_float': 1.5, 'shares_millions': 13},
            'CDNS': {'pct_float': 2.1, 'shares_millions': 10},
            'CRWV': {'pct_float': 5.0, 'shares_millions': 25},  # Higher as newer stock
        }
        return estimates.get(ticker, {'pct_float': None, 'shares_millions': None})

    def _estimate_days_to_cover(self, ticker: str) -> float:
        """Estimate days to cover short position (short interest / avg daily volume)."""
        try:
            si = self._estimate_short_interest(ticker)
            avg_vol = self._get_avg_volume(ticker, days=30)

            if si['shares_millions'] and avg_vol > 0:
                return (si['shares_millions'] * 1_000_000) / avg_vol
        except:
            pass
        return None

    def _check_unusual_volume(self, ticker: str) -> Dict:
        """Check if current volume is unusual vs 30-day average."""
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period='35d')

            if len(hist) < 2:
                return {'unusual': False}

            current_vol = hist['Volume'].iloc[-1]
            avg_vol = hist['Volume'].iloc[:-1].mean()
            volume_ratio = current_vol / avg_vol if avg_vol > 0 else 0

            # Flag as unusual if > 150% or < 50% of average
            is_unusual = volume_ratio > 1.5 or volume_ratio < 0.5

            return {
                'unusual': is_unusual,
                'current_volume': current_vol,
                'avg_volume_30d': avg_vol,
                'ratio': volume_ratio,
                'signal': 'HIGH VOLUME' if volume_ratio > 1.5 else 'LOW VOLUME' if volume_ratio < 0.5 else 'NORMAL',
            }
        except:
            return {'unusual': False, 'error': 'Could not calculate'}

    def _analyze_sector_rotation(self) -> Dict:
        """Analyze sector rotation: growth vs value, semiconductors vs others."""
        sectors_performance = {}

        for ticker in TICKERS:
            sector = SECTORS[ticker]
            if sector not in sectors_performance:
                sectors_performance[sector] = []

            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='3mo')

                if len(hist) > 1:
                    perf = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                    sectors_performance[sector].append({
                        'ticker': ticker,
                        '3m_return': perf,
                    })
            except:
                pass

        # Calculate sector averages
        sector_summary = {}
        for sector, stocks in sectors_performance.items():
            if stocks:
                avg_return = sum(s['3m_return'] for s in stocks) / len(stocks)
                sector_summary[sector] = {
                    'avg_3m_return': avg_return,
                    'stocks': stocks,
                }

        return sector_summary

    def _get_technical_signals(self) -> Dict:
        """Get technical signals for each stock."""
        signals = {}

        for ticker in TICKERS:
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='1y')

                if len(hist) > 50:
                    # Simple moving averages
                    sma_50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                    sma_200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                    current = hist['Close'].iloc[-1]

                    # Relative strength
                    trend = "UPTREND" if current > sma_50 > sma_200 else "DOWNTREND" if current < sma_50 < sma_200 else "MIXED"

                    signals[ticker] = {
                        'current_price': current,
                        'sma_50': sma_50,
                        'sma_200': sma_200,
                        'trend': trend,
                        'above_50d': current > sma_50,
                        'above_200d': current > sma_200,
                    }
            except:
                signals[ticker] = {'error': 'Could not calculate'}

        return signals

    def _get_next_earnings(self, ticker: str) -> str:
        """Get next earnings date for a specific ticker."""
        now = datetime.now()
        next_date = None
        min_days = float('inf')

        for quarter, date_str in EARNINGS_CALENDAR.get(ticker, {}).items():
            date = datetime.fromisoformat(date_str)
            days_until = (date - now).days

            if days_until >= 0 and days_until < min_days:
                min_days = days_until
                next_date = date_str

        return next_date

    def get_earnings_calendar(self) -> Dict:
        """Get upcoming earnings calendar."""
        calendar = {
            'timestamp': datetime.now().isoformat(),
            'upcoming_earnings': [],
        }

        now = datetime.now()

        for ticker, quarters in EARNINGS_CALENDAR.items():
            for quarter, date_str in quarters.items():
                date = datetime.fromisoformat(date_str)
                days_until = (date - now).days

                if 0 <= days_until <= 365:  # Show next 365 days
                    calendar['upcoming_earnings'].append({
                        'ticker': ticker,
                        'quarter': quarter,
                        'date': date_str,
                        'days_until': days_until,
                        'sector': SECTORS[ticker],
                    })

        # Sort by days until
        calendar['upcoming_earnings'].sort(key=lambda x: x['days_until'])

        return calendar

    def detect_unusual_volumes(self) -> List[Dict]:
        """Detect unusual trading volumes across all stocks."""
        unusual = []

        for ticker in TICKERS:
            vol_check = self._check_unusual_volume(ticker)
            if vol_check.get('unusual'):
                unusual.append({
                    'ticker': ticker,
                    **vol_check,
                })

        return unusual

    def get_market_view(self) -> Dict:
        """Generate comprehensive market view."""
        view = {
            'timestamp': datetime.now().isoformat(),
            'market_snapshot': self.get_market_snapshot(),
            'earnings_calendar': self.get_earnings_calendar(),
            'unusual_volumes': self.detect_unusual_volumes(),
            'short_interest_summary': self._summarize_short_interest(),
            'valuation_summary': self._summarize_valuations(),
        }

        self._save_view(view)
        return view

    def _summarize_short_interest(self) -> Dict:
        """Summarize short interest across portfolio."""
        summary = {
            'total_shorts': {},
            'high_short_stocks': [],
        }

        for ticker in TICKERS:
            si = self._estimate_short_interest(ticker)
            dtc = self._estimate_days_to_cover(ticker)

            summary['total_shorts'][ticker] = si

            if si['pct_float'] and si['pct_float'] > 2.0:  # Flag if > 2% of float
                summary['high_short_stocks'].append({
                    'ticker': ticker,
                    'short_pct_float': si['pct_float'],
                    'days_to_cover': dtc,
                    'risk_level': 'HIGH' if si['pct_float'] > 5.0 else 'MODERATE',
                })

        summary['high_short_stocks'].sort(key=lambda x: x['short_pct_float'], reverse=True)
        return summary

    def _summarize_valuations(self) -> Dict:
        """Summarize relative valuations. Forward P/E (NTM) is primary metric."""
        valuations = {}

        for ticker in TICKERS:
            try:
                stock = yf.Ticker(ticker)
                info = stock.info if hasattr(stock, 'info') else {}

                valuations[ticker] = {
                    'pe_forward': info.get('forwardPE'),  # NTM - primary metric
                    'pe_trailing': info.get('trailingPE'),  # TTM - secondary
                    'price_to_book': info.get('priceToBook'),
                    'dividend_yield': info.get('dividendYield'),
                    'market_cap_millions': info.get('marketCap', 0) / 1_000_000 if info.get('marketCap') else None,
                }
            except:
                valuations[ticker] = {'error': 'Could not fetch'}

        return valuations

    def _save_view(self, view: Dict):
        """Save market view to JSON file."""
        try:
            self.market_view_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.market_view_file, 'w') as f:
                json.dump(view, f, indent=2, default=str)
            print(f"✅ Market view saved to {self.market_view_file}")
        except Exception as e:
            print(f"⚠️ Could not save market view: {e}")

    def _save_snapshot(self, snapshot: Dict):
        """Save market snapshot."""
        snapshot_file = self.data_dir / 'valuations' / 'market_snapshot_latest.json'
        try:
            snapshot_file.parent.mkdir(parents=True, exist_ok=True)
            with open(snapshot_file, 'w') as f:
                json.dump(snapshot, f, indent=2, default=str)
        except:
            pass

    # ───────────────────────────────────────────────────────────
    # MULTIPLES FRAMEWORK INTEGRATION
    # ───────────────────────────────────────────────────────────

    def develop_multiples_framework(self) -> Dict:
        """
        Develop a principled view on fair valuation multiples.

        Uses framework that considers:
        - S&P 500 baseline P/E
        - Industry characteristics
        - Business model (asset-light vs asset-heavy)
        - Growth profile
        - Profitability
        - Competitive position (Porter's Five Forces)

        Returns framework with fair multiples for all companies.
        """
        from tools.multiples_framework import MultiplesFramework

        print("  [Market Monitor] Developing multiples framework...")
        framework = MultiplesFramework()
        view = framework.develop_view()

        return view

    def assess_valuation_vs_framework(self) -> Dict:
        """
        Compare current market multiples to fair multiples from framework.

        Returns:
            {
                'timestamp': str,
                'assessments': {
                    'NVDA': {
                        'actual_pe': float,
                        'fair_pe': float,
                        'assessment': 'UNDERVALUED/FAIRLY VALUED/OVERVALUED',
                        'premium_discount': float,
                    },
                    ...
                },
                'summary': str,
            }
        """
        from tools.multiples_framework import MultiplesFramework

        print("\n  [Market Monitor] Assessing valuations vs framework...")

        framework = MultiplesFramework()

        # Try to load existing framework, develop if doesn't exist
        if not framework.framework_file.exists():
            print("    No existing framework found, developing new one...")
            framework.develop_view()

        # Get current market data
        snapshot = self.get_market_snapshot()

        assessments = {}
        for ticker in TICKERS:
            stock_data = snapshot['stocks'].get(ticker, {})

            if 'error' not in stock_data:
                actual_pe = stock_data.get('pe_forward_ntm')

                if actual_pe:
                    comparison = framework.compare_to_market(ticker, actual_pe)
                    assessments[ticker] = comparison

        # Build summary
        undervalued = [t for t, a in assessments.items() if 'UNDERVALUED' in a.get('assessment', '')]
        overvalued = [t for t, a in assessments.items() if 'OVERVALUED' in a.get('assessment', '')]
        fairly_valued = [t for t, a in assessments.items() if 'FAIRLY VALUED' in a.get('assessment', '')]

        summary_lines = []
        if undervalued:
            summary_lines.append(f"UNDERVALUED: {', '.join(undervalued)}")
        if fairly_valued:
            summary_lines.append(f"FAIRLY VALUED: {', '.join(fairly_valued)}")
        if overvalued:
            summary_lines.append(f"OVERVALUED: {', '.join(overvalued)}")

        result = {
            'timestamp': datetime.now().isoformat(),
            'assessments': assessments,
            'summary': ' | '.join(summary_lines) if summary_lines else 'No assessments available',
        }

        # Save assessment
        self._save_valuation_assessment(result)

        return result

    def _save_valuation_assessment(self, assessment: Dict):
        """Save valuation assessment to file."""
        assessment_file = self.data_dir / 'valuations' / 'multiples_assessment_latest.json'
        try:
            assessment_file.parent.mkdir(parents=True, exist_ok=True)
            with open(assessment_file, 'w') as f:
                json.dump(assessment, f, indent=2, default=str)
            print(f"  ✅ Valuation assessment saved to {assessment_file}")
        except Exception as e:
            print(f"  ⚠️  Could not save assessment: {e}")


if __name__ == '__main__':
    monitor = MarketMonitor()

    print("\n" + "="*70)
    print("MARKET MONITOR - Full Analysis")
    print("="*70)

    view = monitor.get_market_view()

    print("\n📊 Market Snapshot:")
    for ticker, data in view['market_snapshot']['stocks'].items():
        if 'error' not in data:
            print(f"  {ticker}: ${data['price']:.2f}, Vol: {data['volume']:,.0f}, SI: {data['short_interest']['pct_float']:.1f}%")

    print("\n📅 Next Earnings (30 days):")
    for earning in view['earnings_calendar']['upcoming_earnings'][:5]:
        if earning['days_until'] <= 30:
            print(f"  {earning['ticker']}: {earning['quarter']} on {earning['date']}")

    print("\n⚠️ Unusual Volumes:")
    if view['unusual_volumes']:
        for unusual in view['unusual_volumes']:
            print(f"  {unusual['ticker']}: {unusual['signal']} ({unusual['ratio']:.2f}x avg)")
    else:
        print("  None detected")

    print("\n" + "="*70 + "\n")
