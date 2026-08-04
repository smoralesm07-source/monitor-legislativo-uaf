from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .utils import compact_text


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
            "commission", "urgency", "latest_movement", "latest_movement_date"
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
        self.source_urls = sorted(set(self.source_urls + other.source_urls))[:20]
        self.discovered_from = sorted(set(self.discovered_from + other.discovered_from))[:20]

        # La evidencia se utiliza únicamente durante la ejecución actual. Se deduplica y
        # limita para impedir crecimiento acumulativo si una fuente repite el mismo texto.
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
