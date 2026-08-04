from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import compact_text, parse_legislative_date, unique

MAX_EVIDENCE_CHARS = 120_000
MAX_HISTORY_ITEMS = 120


def _history_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("date", "")),
        compact_text(str(item.get("description", "")), 1200),
        str(item.get("source", "")),
    )


@dataclass
class CandidateProject:
    bulletin: str
    title: str = ""
    entry_date: str = ""
    initiative_type: str = ""
    origin_chamber: str = ""
    state: str = ""
    stage: str = ""
    commission: str = ""
    urgency: str = ""
    latest_movement: str = ""
    latest_movement_date: str = ""
    legislative_history: list[dict[str, Any]] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    discovered_from: list[str] = field(default_factory=list)
    evidence_text: str = ""
    raw_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def merge(self, other: "CandidateProject") -> "CandidateProject":
        if self.bulletin != other.bulletin:
            raise ValueError("No se pueden fusionar boletines distintos")

        for field_name in [
            "title", "entry_date", "initiative_type", "origin_chamber", "state", "stage",
            "commission", "urgency",
        ]:
            current = getattr(self, field_name)
            incoming = getattr(other, field_name)
            if field_name == "title":
                current_rank = int(self.metadata.get("title_rank", 0))
                incoming_rank = int(other.metadata.get("title_rank", 0))
                if incoming and (
                    not current
                    or incoming_rank > current_rank
                    or (incoming_rank == current_rank and len(incoming) > len(current))
                ):
                    setattr(self, field_name, incoming)
            elif incoming and (not current or len(incoming) > len(current)):
                setattr(self, field_name, incoming)

        current_date = parse_legislative_date(self.latest_movement_date or self.latest_movement)
        incoming_date = parse_legislative_date(other.latest_movement_date or other.latest_movement)
        current_rank = int(self.metadata.get("movement_rank", 0))
        incoming_rank = int(other.metadata.get("movement_rank", 0))
        take_incoming = False
        if incoming_date and (not current_date or incoming_date > current_date):
            take_incoming = True
        elif incoming_date and current_date and incoming_date == current_date:
            take_incoming = incoming_rank > current_rank or (
                incoming_rank == current_rank and len(other.latest_movement) > len(self.latest_movement)
            )
        elif not current_date and not incoming_date and other.latest_movement:
            take_incoming = incoming_rank > current_rank or len(other.latest_movement) > len(self.latest_movement)
        if take_incoming:
            self.latest_movement = other.latest_movement
            self.latest_movement_date = other.latest_movement_date
            if other.metadata.get("movement_source"):
                self.metadata["movement_source"] = other.metadata["movement_source"]
            self.metadata["movement_rank"] = incoming_rank

        history_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for item in [*self.legislative_history, *other.legislative_history]:
            if not isinstance(item, dict):
                continue
            date_value = str(item.get("date", ""))
            description = compact_text(str(item.get("description", "")), 1600)
            if not date_value or not description:
                continue
            clean = {
                "date": date_value,
                "description": description,
                "source": compact_text(str(item.get("source", "")), 120),
                "url": compact_text(str(item.get("url", "")), 1000),
            }
            history_by_key[_history_key(clean)] = clean
        self.legislative_history = sorted(
            history_by_key.values(),
            key=lambda item: parse_legislative_date(str(item.get("date", ""))) or parse_legislative_date("1900-01-01"),
            reverse=True,
        )[:MAX_HISTORY_ITEMS]

        self.source_urls = sorted(set(self.source_urls + other.source_urls))[:20]
        self.discovered_from = sorted(set(self.discovered_from + other.discovered_from))[:20]

        evidence_parts: list[str] = []
        for value in (self.evidence_text, other.evidence_text):
            clean = compact_text(value, MAX_EVIDENCE_CHARS)
            if clean and clean not in evidence_parts:
                evidence_parts.append(clean)
        self.evidence_text = compact_text(" ".join(evidence_parts), MAX_EVIDENCE_CHARS)

        self.raw_hash = other.raw_hash or self.raw_hash
        self.metadata.update(other.metadata)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
