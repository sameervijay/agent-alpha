"""
Data structures for Company News Analyst — NewsItem, DriverUpdatePackage, AnalystView.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class NewsItem:
    headline: str
    url: str
    date: str
    source: str  # "ir_rss", "sec_edgar", "finviz"
    ticker: str
    summary: str = ""
    form_type: Optional[str] = None  # e.g. "8-K" for SEC filings

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DriverUpdatePackage:
    ticker: str
    analyst_summary: str = ""
    driver_updates: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rationale: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    news_sources: List[dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def empty(cls, ticker: str):
        """Return an empty package with zero confidence (used on fetch failure)."""
        return cls(ticker=ticker, analyst_summary="No news available", confidence=0.0)


@dataclass
class AnalystView:
    """Persisted baseline view that an analyst builds during ramp and updates in monitor mode."""
    ticker: str
    established_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: str = ""
    baseline_drivers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rationale: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    seen_headlines: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_driver_update_package(self) -> 'DriverUpdatePackage':
        """Convert the current view into a DriverUpdatePackage for the PM."""
        return DriverUpdatePackage(
            ticker=self.ticker,
            analyst_summary=self.summary,
            driver_updates=self.baseline_drivers,
            rationale=self.rationale,
            confidence=self.confidence,
        )
