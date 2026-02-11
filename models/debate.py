"""
Debate data structures for Phase 3 (Multi-Agent Debate).
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class DebatePosition:
    agent_name: str
    metric: str  # DCF driver name
    company: str  # ticker
    period: str  # e.g., "FY2028"
    proposed_value: float  # the delta to apply to baseline
    confidence: float  # 0.0 to 1.0
    reasoning: str
    data_type: str = "unknown"  # leading or lagging indicator

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DebateRound:
    round_number: int
    metric: str
    company: str
    positions: List[DebatePosition]
    pm_probing_question: str = ""
    devils_advocate_challenge: str = ""
    responses: List[dict] = field(default_factory=list)

    def to_dict(self):
        return {
            'round_number': self.round_number,
            'metric': self.metric,
            'company': self.company,
            'positions': [p.to_dict() for p in self.positions],
            'pm_probing_question': self.pm_probing_question,
            'devils_advocate_challenge': self.devils_advocate_challenge,
            'responses': self.responses,
        }

    @classmethod
    def from_dict(cls, d):
        positions = [DebatePosition.from_dict(p) for p in d.get('positions', [])]
        return cls(
            round_number=d['round_number'],
            metric=d['metric'],
            company=d['company'],
            positions=positions,
            pm_probing_question=d.get('pm_probing_question', ''),
            devils_advocate_challenge=d.get('devils_advocate_challenge', ''),
            responses=d.get('responses', []),
        )


@dataclass
class DebateResolution:
    metric: str
    company: str
    resolved_values: dict  # {period: delta_value}
    confidence: float
    rationale: str
    contributing_agents: List[str]
    dissenting_agents: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DebateSession:
    event_id: str
    event_headline: str
    rounds: List[DebateRound] = field(default_factory=list)
    resolutions: List[DebateResolution] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_round(self, debate_round: DebateRound):
        self.rounds.append(debate_round)

    def add_resolution(self, resolution: DebateResolution):
        self.resolutions.append(resolution)

    def get_driver_changes(self) -> dict:
        """Convert all resolutions into a format compatible with NVDADCFEngine.update_drivers()."""
        changes = {}
        for res in self.resolutions:
            metric = res.metric
            if metric not in changes:
                changes[metric] = {}
            for period, value in res.resolved_values.items():
                changes[metric][period] = value
        return changes

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'event_id': self.event_id,
            'event_headline': self.event_headline,
            'created_at': self.created_at,
            'num_rounds': len(self.rounds),
            'num_resolutions': len(self.resolutions),
            'rounds': [r.to_dict() for r in self.rounds],
            'resolutions': [r.to_dict() for r in self.resolutions],
            'driver_changes': self.get_driver_changes(),
        }

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d):
        rounds = [DebateRound.from_dict(r) for r in d.get('rounds', [])]
        resolutions = [DebateResolution.from_dict(r) for r in d.get('resolutions', [])]
        return cls(
            event_id=d['event_id'],
            event_headline=d['event_headline'],
            rounds=rounds,
            resolutions=resolutions,
            session_id=d.get('session_id', ''),
            created_at=d.get('created_at', ''),
        )

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            return cls.from_dict(json.load(f))
