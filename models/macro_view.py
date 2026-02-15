"""
Data models for the Independent Macro Analyst Agent.
Four dataclasses following the AnalystView pattern (to_dict/from_dict/save/load).
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class MacroSnapshot:
    """Point-in-time reading of all tracked macro indicators."""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    indicators: Dict[str, float] = field(default_factory=dict)  # {indicator_key: value}
    sector_performance: Dict[str, float] = field(default_factory=dict)  # {period: return}
    news_items: List[Dict] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MacroView:
    """Persisted macro thesis — the analyst's current view on the macro environment."""
    established_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())
    summary: str = ""
    outlook: str = "neutral"  # bullish, bearish, neutral, cautious
    key_themes: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)
    indicator_history: Dict[str, List[Dict]] = field(default_factory=dict)
    # indicator_history: {indicator_key: [{timestamp, value}, ...]}
    company_implications: Dict[str, str] = field(default_factory=dict)
    # company_implications: {ticker: "implication text"}
    confidence: float = 0.5
    seen_headlines: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MacroAlert:
    """Push notification sent when macro conditions shift materially."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    severity: str = "medium"  # low, medium, high, critical
    headline: str = ""
    description: str = ""
    affected_indicators: List[str] = field(default_factory=list)
    suggested_driver_impacts: Dict[str, Dict[str, float]] = field(default_factory=dict)
    # suggested_driver_impacts: {driver_name: {period: delta}}
    target_tickers: List[str] = field(default_factory=list)
    confidence: float = 0.5
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledgement_response: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MacroBriefing:
    """Nightly macro summary delivered to all company analysts and PM."""
    date: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d'))
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    macro_summary: str = ""
    outlook: str = "neutral"
    indicator_table: List[Dict] = field(default_factory=list)
    # indicator_table: [{indicator, label, current, previous, change, unit}, ...]
    company_notes: Dict[str, str] = field(default_factory=dict)
    # company_notes: {ticker: "note for this company"}
    risk_factors: List[str] = field(default_factory=list)
    key_themes: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
