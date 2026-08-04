from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import compact_text, parse_legislative_date


MAX_EVIDENCE_CHARS = 120_000


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

        # El movimiento y su fecha se fusionan como una unidad para impedir fechas
        # pertenecientes a otra fila o fuente combinadas con una descripción distinta.
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
