from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

BULLETIN_RE = re.compile(r"\b(\d{4,5}-\d{2})\b")
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})\b")
TEXT_DATE_RE = re.compile(
    r"\b(\d{1,2})\s+(?:de\s+)?(ene(?:ro)?|feb(?:rero)?|mar(?:zo)?|abr(?:il)?|may(?:o)?|jun(?:io)?|"
    r"jul(?:io)?|ago(?:sto)?|sep(?:tiembre)?|sept(?:iembre)?|oct(?:ubre)?|nov(?:iembre)?|dic(?:iembre)?)"
    r"\.?\s*(?:de\s+)?[,]?\s*(\d{4})\b",
    re.IGNORECASE,
)
MONTHS = {
    "ene": 1, "enero": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6,
    "jul": 7, "julio": 7, "ago": 8, "agosto": 8, "sep": 9, "sept": 9,
    "septiembre": 9, "setiembre": 9, "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11, "dic": 12, "diciembre": 12,
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower().replace("º", "°")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def compact_text(value: str | None, max_len: int = 5000) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:max_len]


def contains_term(normalized_text: str, term: str) -> bool:
    """Busca frases con límites de palabra; evita que ROS coincida con profesores/otros."""
    needle = normalize_text(term)
    if not normalized_text or not needle:
        return False
    pattern = rf"(?<![\w]){re.escape(needle)}(?![\w])"
    return re.search(pattern, normalized_text, flags=re.IGNORECASE) is not None


def matching_terms(normalized_text: str, terms: Iterable[str]) -> list[str]:
    return unique(term for term in terms if contains_term(normalized_text, term))


def bulletin_from_text(value: str | None) -> str | None:
    match = BULLETIN_RE.search(value or "")
    return match.group(1) if match else None


def parse_legislative_date(value: str | None) -> date | None:
    """Extrae la fecha completa más reciente desde formatos oficiales habituales."""
    if not value:
        return None
    text = str(value).strip()
    candidates: list[date] = []
    for raw in DATE_RE.findall(text):
        try:
            if re.match(r"^\d{4}-", raw):
                candidates.append(datetime.strptime(raw, "%Y-%m-%d").date())
            else:
                separator = "/" if "/" in raw else "-"
                candidates.append(datetime.strptime(raw, f"%d{separator}%m{separator}%Y").date())
        except ValueError:
            continue
    normalized = normalize_text(text)
    for day, month_name, year in TEXT_DATE_RE.findall(normalized):
        month = MONTHS.get(month_name.rstrip(".").lower())
        if not month:
            continue
        try:
            candidates.append(date(int(year), month, int(day)))
        except ValueError:
            continue
    return max(candidates) if candidates else None


def latest_dated_text(
    items: Iterable[str],
    *,
    not_after: date | None = None,
    not_before: date | None = None,
    bulletin: str | None = None,
) -> tuple[str, str]:
    """Retorna el movimiento oficial más reciente dentro de límites razonables."""
    best_text = ""
    best_date: date | None = None
    fallback = ""
    ceiling = not_after or (date.today() + timedelta(days=2))
    for item in items:
        if not item:
            continue
        fallback = item
        bulletins = set(BULLETIN_RE.findall(item))
        if bulletin and bulletins and bulletin not in bulletins:
            continue
        parsed = parse_legislative_date(item)
        if not parsed or parsed > ceiling or (not_before and parsed < not_before):
            continue
        if best_date is None or parsed > best_date:
            best_date = parsed
            best_text = item
    if best_date:
        return best_text, best_date.isoformat()
    return fallback, ""


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def local_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def iso_now(timezone_name: str) -> str:
    return local_now(timezone_name).isoformat(timespec="seconds")


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    temp.replace(path)


def unique(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        clean = compact_text(item, 1000)
        if clean and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag
