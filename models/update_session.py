"""
Data structures for PM "Request Update" mode — multi-turn PM <-> Analyst dialogue.
Follows the DebateSession pattern (to_dict / save / load).
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class AnalystUpdateBrief:
    """Analyst's initial response to PM's update request."""
    ticker: str
    summary: str = ""
    driver_snapshot: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rationale: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    recommended_changes: Dict[str, Dict[str, float]] = field(default_factory=dict)
    change_explanation: str = ""
    news_context: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PMChallenge:
    """A challenge question from the PM targeting specific assumptions."""
    challenge_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    target_drivers: List[str] = field(default_factory=list)
    question: str = ""
    challenge_type: str = "assumption"  # assumption, magnitude, timing, evidence, risk

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AnalystResponse:
    """Analyst's response to a PM challenge."""
    challenge_id: str = ""
    response: str = ""
    revised_drivers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    confidence_after: float = 0.0
    concedes: bool = False

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class PMDecision:
    """PM's final decision after the dialogue."""
    action: str = "reject"  # accept, modify, reject
    final_drivers: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rationale: str = ""
    confidence: float = 0.0
    valuation_result: Optional[Dict] = None

    def to_dict(self):
        d = asdict(self)
        # asdict converts None to None, which is fine for JSON
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class UpdateSession:
    """Full audit trail for a PM <-> Analyst update dialogue."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    ticker: str = ""
    brief: Optional[AnalystUpdateBrief] = None
    challenges: List[PMChallenge] = field(default_factory=list)
    responses: List[AnalystResponse] = field(default_factory=list)
    decision: Optional[PMDecision] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: str = ""
    llm_calls: int = 0
    total_tokens: int = 0

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'ticker': self.ticker,
            'created_at': self.created_at,
            'completed_at': self.completed_at,
            'llm_calls': self.llm_calls,
            'total_tokens': self.total_tokens,
            'brief': self.brief.to_dict() if self.brief else None,
            'challenges': [c.to_dict() for c in self.challenges],
            'responses': [r.to_dict() for r in self.responses],
            'decision': self.decision.to_dict() if self.decision else None,
        }

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d):
        brief = AnalystUpdateBrief.from_dict(d['brief']) if d.get('brief') else None
        challenges = [PMChallenge.from_dict(c) for c in d.get('challenges', [])]
        responses = [AnalystResponse.from_dict(r) for r in d.get('responses', [])]
        decision = PMDecision.from_dict(d['decision']) if d.get('decision') else None
        return cls(
            session_id=d.get('session_id', ''),
            ticker=d.get('ticker', ''),
            brief=brief,
            challenges=challenges,
            responses=responses,
            decision=decision,
            created_at=d.get('created_at', ''),
            completed_at=d.get('completed_at', ''),
            llm_calls=d.get('llm_calls', 0),
            total_tokens=d.get('total_tokens', 0),
        )

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            return cls.from_dict(json.load(f))
