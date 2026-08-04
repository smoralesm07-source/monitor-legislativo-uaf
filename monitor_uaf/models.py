from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


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

    _SCALAR_FIELDS = (
        "title", "entry_date", "initiative_type", "origin_chamber", "state",
        "stage", "commission", "urgency", "latest_movement", "latest_movement_date",
    )

    @staticmethod
    def _rank(metadata: dict[str, Any], field_name: str) -> int:
        ranks = metadata.get("field_ranks", {}) if isinstance(metadata, dict) else {}
        if isinstance(ranks, dict):
            try:
                return int(ranks.get(field_name, metadata.get(f"{field_name}_rank", 0)) or 0)
            except (TypeError, ValueError):
                return 0
        try:
            return int(metadata.get(f"{field_name}_rank", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _merge_list(current: list[Any], incoming: list[Any]) -> list[Any]:
        output: list[Any] = []
        seen: set[str] = set()
        for item in [*current, *incoming]:
            marker = repr(item)
            if marker not in seen:
                seen.add(marker)
                output.append(deepcopy(item))
        return output

    @classmethod
    def _merge_metadata(cls, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        merged = deepcopy(current or {})
        for key, value in (incoming or {}).items():
            if key == "field_ranks":
                ranks = merged.setdefault("field_ranks", {})
                if not isinstance(ranks, dict):
                    ranks = {}
                    merged["field_ranks"] = ranks
                if isinstance(value, dict):
                    for field_name, rank in value.items():
                        try:
                            ranks[field_name] = max(int(ranks.get(field_name, 0) or 0), int(rank or 0))
                        except (TypeError, ValueError):
                            continue
                continue
            if isinstance(value, list):
                existing = merged.get(key, [])
                if not isinstance(existing, list):
                    existing = []
                merged[key] = cls._merge_list(existing, value)
            elif isinstance(value, dict):
                existing = merged.get(key, {})
                if not isinstance(existing, dict):
                    existing = {}
                nested = deepcopy(existing)
                nested.update(deepcopy(value))
                merged[key] = nested
            elif value not in (None, ""):
                merged[key] = deepcopy(value)
        return merged

    def merge(self, other: "CandidateProject") -> "CandidateProject":
        """Combina fuentes priorizando autoridad y actualidad, no largo del texto.

        Cada fuente puede declarar ``metadata.field_ranks``. La ficha del Senado
        tiene mayor autoridad para la etapa actual cuando el proyecto ya se
        encuentra en esa cámara; la Cámara conserva prioridad para autores y
        antecedentes de origen. Con ello, una etiqueta histórica de primer
        trámite no puede reemplazar un segundo trámite más reciente.
        """
        if self.bulletin != other.bulletin:
            raise ValueError("No se pueden fusionar boletines distintos")

        for field_name in self._SCALAR_FIELDS:
            current = getattr(self, field_name)
            incoming = getattr(other, field_name)
            if not incoming:
                continue
            current_rank = self._rank(self.metadata, field_name)
            incoming_rank = self._rank(other.metadata, field_name)
            should_replace = (
                not current
                or incoming_rank > current_rank
                or (
                    incoming_rank == current_rank
                    and field_name == "latest_movement_date"
                    and incoming > current
                )
                or (
                    incoming_rank == current_rank
                    and field_name == "title"
                    and len(incoming) > len(current)
                )
            )
            if should_replace:
                setattr(self, field_name, incoming)

        self.source_urls = sorted(set(self.source_urls + other.source_urls))
        self.discovered_from = sorted(set(self.discovered_from + other.discovered_from))
        if other.evidence_text:
            combined = " ".join(x for x in [self.evidence_text, other.evidence_text] if x).strip()
            self.evidence_text = combined[:120000]
        self.raw_hash = other.raw_hash or self.raw_hash
        self.metadata = self._merge_metadata(self.metadata, other.metadata)
        return self

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
