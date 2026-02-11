"""
Event dataclass for Phase 1 (Event Detection).
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class Event:
    headline: str
    description: str
    source_agent: str
    affected_companies: List[str]
    affected_segments: List[str]
    severity: str  # low, medium, high, critical
    direction: str  # positive, negative, neutral, mixed
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    raw_input: Optional[str] = None

    def to_dict(self):
        return asdict(self)

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            return cls.from_dict(json.load(f))

    def __str__(self):
        return (f"[{self.severity.upper()}] {self.headline} "
                f"({self.direction}) → {', '.join(self.affected_companies)}")
