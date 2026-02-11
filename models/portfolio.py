"""
Portfolio construction models for Phase C.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional

from config import UPSIDE_THRESHOLD, MAX_POSITION_WEIGHT


@dataclass
class Position:
    ticker: str
    company_name: str
    implied_price: float
    current_price: float
    upside: float
    confidence: float
    signal: str  # BUY, HOLD, SELL
    weight: float = 0.0
    rationale: str = ""

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Portfolio:
    positions: List[Position] = field(default_factory=list)
    session_id: str = ""
    event_headline: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_position(self, position: Position):
        self.positions.append(position)

    def compute_weights(self):
        """Weight proportional to upside * confidence, capped at MAX_POSITION_WEIGHT."""
        buy_positions = [p for p in self.positions if p.signal == 'BUY']
        if not buy_positions:
            return

        raw_scores = []
        for p in buy_positions:
            raw_scores.append(p.upside * p.confidence)

        total_score = sum(raw_scores)
        if total_score <= 0:
            return

        # Normalize and cap
        for p, score in zip(buy_positions, raw_scores):
            p.weight = min(score / total_score, MAX_POSITION_WEIGHT)

        # Renormalize after capping
        total_weight = sum(p.weight for p in buy_positions)
        if total_weight > 0:
            for p in buy_positions:
                p.weight = p.weight / total_weight

    @staticmethod
    def determine_signal(upside: float, confidence: float) -> str:
        if upside >= UPSIDE_THRESHOLD and confidence >= 0.5:
            return 'BUY'
        elif upside <= -UPSIDE_THRESHOLD and confidence >= 0.5:
            return 'SELL'
        return 'HOLD'

    def summary(self) -> str:
        lines = ["\n  PORTFOLIO ALLOCATION", "  " + "=" * 60]
        for p in sorted(self.positions, key=lambda x: -x.weight):
            lines.append(
                f"  {p.ticker:<6} {p.signal:<5} "
                f"Weight: {p.weight:>6.1%}  "
                f"Upside: {p.upside:>6.1%}  "
                f"Conf: {p.confidence:.0%}"
            )
        return "\n".join(lines)

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'event_headline': self.event_headline,
            'created_at': self.created_at,
            'positions': [p.to_dict() for p in self.positions],
        }

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
