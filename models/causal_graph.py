"""
Causal graph structures for Phase 2 (Causal Reasoning).
Produces the causal_links.json files that get git-tracked for version control diffs.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


@dataclass
class CausalLink:
    source_event: str  # event headline or ID
    intermediate_step: str  # e.g., "Reduced China datacenter demand"
    downstream_metric: str  # DCF driver name, e.g., "datacenter_growth"
    affected_company: str  # ticker, e.g., "NVDA"
    affected_periods: List[str]  # e.g., ["FY2028", "FY2029"]
    direction: str  # increase, decrease, neutral
    magnitude_estimate: str  # e.g., "-5pp", "+200bps", "moderate decrease"
    confidence: float  # 0.0 to 1.0
    reasoning: str
    proposed_by: str  # agent name

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CausalGraph:
    event_id: str
    event_headline: str
    links: List[CausalLink] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_link(self, link: CausalLink):
        self.links.append(link)

    def add_links(self, links: List[CausalLink]):
        self.links.extend(links)

    def get_links_for_company(self, ticker: str) -> List[CausalLink]:
        return [l for l in self.links if l.affected_company == ticker]

    def get_links_for_metric(self, metric: str) -> List[CausalLink]:
        return [l for l in self.links if l.downstream_metric == metric]

    def get_conflicts(self) -> List[dict]:
        """Find links where agents disagree on direction for the same metric+company."""
        conflicts = []
        seen = {}  # (metric, company) -> list of links
        for link in self.links:
            key = (link.downstream_metric, link.affected_company)
            if key not in seen:
                seen[key] = []
            seen[key].append(link)

        for (metric, company), links in seen.items():
            directions = set(l.direction for l in links)
            if len(directions) > 1:
                conflicts.append({
                    'metric': metric,
                    'company': company,
                    'directions': list(directions),
                    'links': [l.to_dict() for l in links],
                    'agents': [l.proposed_by for l in links],
                })
        return conflicts

    def get_unique_metrics(self) -> List[dict]:
        """Get unique (metric, company, direction) combinations with aggregated info."""
        seen = {}
        for link in self.links:
            key = (link.downstream_metric, link.affected_company)
            if key not in seen:
                seen[key] = {
                    'metric': link.downstream_metric,
                    'company': link.affected_company,
                    'directions': [],
                    'agents': [],
                    'periods': set(),
                    'magnitudes': [],
                }
            seen[key]['directions'].append(link.direction)
            seen[key]['agents'].append(link.proposed_by)
            seen[key]['periods'].update(link.affected_periods)
            seen[key]['magnitudes'].append(link.magnitude_estimate)

        result = []
        for v in seen.values():
            v['periods'] = sorted(v['periods'])
            result.append(v)
        return result

    def to_dict(self):
        return {
            'session_id': self.session_id,
            'event_id': self.event_id,
            'event_headline': self.event_headline,
            'version': self.version,
            'created_at': self.created_at,
            'num_links': len(self.links),
            'links': [l.to_dict() for l in self.links],
        }

    def save(self, filepath):
        with open(filepath, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def from_dict(cls, d):
        links = [CausalLink.from_dict(l) for l in d.get('links', [])]
        return cls(
            event_id=d['event_id'],
            event_headline=d['event_headline'],
            links=links,
            session_id=d.get('session_id', ''),
            version=d.get('version', 1),
            created_at=d.get('created_at', ''),
        )

    @classmethod
    def load(cls, filepath):
        with open(filepath) as f:
            return cls.from_dict(json.load(f))
