from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Iterable

from bs4 import BeautifulSoup

from .http_client import HttpClient
from .models import CandidateProject
from .utils import (
    BULLETIN_RE,
    compact_text,
    contains_term,
    latest_dated_text,
    local_tag,
    normalize_text,
    parse_legislative_date,
    stable_hash,
    unique,
)

LOGGER = logging.getLogger(__name__)

MOVEMENT_TERMS = [
    "ingreso de proyecto", "cuenta del proyecto", "oficio", "informe de comisión",
    "informe de comision", "indicación", "indicacion", "votación", "votacion",
    "aprobado", "rechazado", "pasa a", "trámite constitucional", "tramite constitucional",
    "comisión mixta", "comision mixta", "urgencia", "discusión", "discusion",
    "sesión", "sesion", "promulgado", "publicado", "archivado", "retirado",
    "certificado", "texto aprobado", "mensaje", "moción", "mocion",
]


def _history_from_blocks(blocks: Iterable[str], source: str, url: str) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    today = date.today() + timedelta(days=2)
    for block in blocks:
        parsed = parse_legislative_date(block)
        description = compact_text(block, 1500)
        if not parsed or parsed > today or not description:
            continue
        key = (parsed.isoformat(), normalize_text(description))
        if key in seen:
            continue
        seen.add(key)
        history.append({
            "date": parsed.isoformat(),
            "description": description,
            "source": source,
            "url": url,
        })
    history.sort(key=lambda item: item["date"], reverse=True)
    return history[:120]


class CamaraOpenDataSource:
    HOSTS = [
        "https://opendata.camara.cl/camaradiputados/WServices/WSLegislativo.asmx",
        "https://opendata.congreso.cl/camaradiputados/WServices/WSLegislativo.asmx",
    ]

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def _call(self, method: str, params: dict[str, str]) -> bytes:
        errors: list[str] = []
        for host in self.HOSTS:
            try:
                return self.client.get(f"{host}/{method}", params=params).content
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{host}: {exc}")
        raise RuntimeError(" | ".join(errors))

    @staticmethod
    def _first_text(node: ET.Element, names: Iterable[str]) -> str:
        wanted = {normalize_text(name) for name in names}
        for elem in node.iter():
            if normalize_text(local_tag(elem.tag)) in wanted and elem.text and elem.text.strip():
                return compact_text(elem.text, 2000)
        return ""

    @staticmethod
    def _all_text(node: ET.Element) -> str:
        return compact_text(" ".join(t.strip() for t in node.itertext() if t and t.strip()), 50000)

    @staticmethod
    def _collect_named_blocks(node: ET.Element, names: set[str], limit: int = 12) -> list[str]:
        wanted = {normalize_text(name) for name in names}
        out: list[str] = []
        for elem in node.iter():
            if normalize_text(local_tag(elem.tag)) in wanted:
                block = compact_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip()), 2000)
                if block:
                    out.append(block)
        return unique(out)[:limit]

    @classmethod
    def _movement_blocks(cls, root: ET.Element) -> list[str]:
        out: list[str] = []
        movement_tags = {
            "tramite", "movimiento", "oficio", "documento", "informe", "sesion",
            "tramiteconstitucional", "tramiteparlamentario", "votacion",
        }
        for elem in root.iter():
            tag = normalize_text(local_tag(elem.tag)).replace(" ", "")
            if tag not in movement_tags and not any(token in tag for token in ("tramite", "movimiento", "oficio", "informe", "votacion")):
                continue
            block = compact_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip()), 3000)
            if block and parse_legislative_date(block):
                out.append(block)
        return unique(out)[:180]

    def list_by_year(self, year: int) -> list[CandidateProject]:
        projects: dict[str, CandidateProject] = {}
        methods = [
            ("retornarMensajesXAnno", "Cámara XML mensajes"),
            ("retornarMocionesXAnno", "Cámara XML mociones"),
        ]
        for method, label in methods:
            xml_bytes = self._call(method, {"prmAnno": str(year)})
            root = ET.fromstring(xml_bytes)
            for node in root.iter():
                if normalize_text(local_tag(node.tag)) != "proyectoley":
                    continue
                bulletin_value = self._first_text(node, ["NumeroBoletin", "Boletin"])
                match = BULLETIN_RE.search(bulletin_value)
                if not match:
                    continue
                bulletin = match.group(1)
                url = f"https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"
                project = CandidateProject(
                    bulletin=bulletin,
                    title=self._first_text(node, ["Nombre", "Titulo"]),
                    entry_date=self._first_text(node, ["FechaIngreso"]),
                    initiative_type=self._first_text(node, ["TipoIniciativa", "Iniciativa"]),
                    origin_chamber=self._first_text(node, ["CamaraOrigen"]),
                    source_urls=[url],
                    discovered_from=[label],
                    evidence_text=self._all_text(node),
                    metadata={"title_rank": 2},
                )
                projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

    def detail(self, bulletin: str) -> CandidateProject:
        xml_bytes = self._call("retornarProyectoLey", {"prmNumeroBoletin": bulletin})
        root = ET.fromstring(xml_bytes)
        raw_text = self._all_text(root)
        stages = self._collect_named_blocks(root, {"TramiteConstitucional", "TramiteReglamentario", "Etapa"})
        commissions = self._collect_named_blocks(root, {"Comision", "ComisionDestino", "ComisionOrigen"})
        urgencies = self._collect_named_blocks(root, {"Urgencia", "TipoUrgencia"})
        states = self._collect_named_blocks(root, {"Estado", "EstadoProyectoLey"})
        movements = self._movement_blocks(root)
        entry_date = self._first_text(root, ["FechaIngreso"])
        entry = parse_legislative_date(entry_date)
        latest_movement, latest_movement_date = latest_dated_text(
            movements,
            not_before=(entry - timedelta(days=5)) if entry else None,
            bulletin=bulletin,
        )
        url = f"https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"
        return CandidateProject(
            bulletin=bulletin,
            title=self._first_text(root, ["Nombre", "Titulo"]),
            entry_date=entry_date,
            initiative_type=self._first_text(root, ["TipoIniciativa", "Iniciativa"]),
            origin_chamber=self._first_text(root, ["CamaraOrigen"]),
            state=" | ".join(states[:3]),
            stage=" | ".join(stages[:4]),
            commission=" | ".join(commissions[:5]),
            urgency=" | ".join(urgencies[:3]),
            latest_movement=latest_movement,
            latest_movement_date=latest_movement_date,
            legislative_history=_history_from_blocks(movements, "Cámara XML oficial", url),
            source_urls=[url],
            discovered_from=["Cámara XML detalle"],
            evidence_text=raw_text,
            raw_hash=stable_hash(raw_text),
            metadata={
                "title_rank": 5,
                "movement_rank": 6,
                "movement_source": "Cámara XML oficial",
                "official_date_verified": bool(latest_movement_date),
            },
        )


class SenadoSource:
    DETAIL_URL = "https://tramitacion.senado.cl/appsenado/templates/tramitacion/index.php?boletin_ini={bulletin}"
    OPEN_PROJECT_URL = "https://tramitacion.senado.cl/wspublico/tramitacion.php"
    OPEN_MOVEMENTS_URL = "https://tramitacion.senado.cl/wspublico/proyectos.php"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    @staticmethod
    def _xml_first(node: ET.Element, names: Iterable[str]) -> str:
        wanted = {normalize_text(name).replace(" ", "") for name in names}
        for elem in node.iter():
            tag = normalize_text(local_tag(elem.tag)).replace(" ", "")
            if tag in wanted and elem.text and elem.text.strip():
                return compact_text(elem.text, 2000)
        return ""

    @staticmethod
    def _xml_blocks(root: ET.Element) -> list[str]:
        blocks: list[str] = []
        for elem in root.iter():
            tag = normalize_text(local_tag(elem.tag)).replace(" ", "")
            if not any(token in tag for token in ("tramite", "movimiento", "sesion", "documento", "informe", "indicacion", "votacion")):
                continue
            text = compact_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip()), 3000)
            if text and parse_legislative_date(text):
                blocks.append(text)
        return unique(blocks)[:180]

    def recent_movements(self, since: date) -> list[CandidateProject]:
        """Descubre boletines con movimientos mediante el servicio XML oficial del Senado."""
        errors: list[str] = []
        root: ET.Element | None = None
        for params in (
            {"fecha": since.strftime("%d/%m/%Y")},
            {"fecha": since.isoformat()},
            {"fecha_inicio": since.isoformat()},
        ):
            try:
                result = self.client.get(self.OPEN_MOVEMENTS_URL, params=params)
                root = ET.fromstring(result.content)
                break
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{params}: {exc}")
        if root is None:
            raise RuntimeError(" | ".join(errors))
        projects: dict[str, CandidateProject] = {}
        for node in root.iter():
            text = compact_text(" ".join(t.strip() for t in node.itertext() if t and t.strip()), 7000)
            bulletins = BULLETIN_RE.findall(text)
            if not bulletins:
                continue
            # Evita crear el mismo proyecto desde cada nodo hijo: solo usa bloques con contenido suficiente.
            if len(list(node)) == 0 and len(text) < 40:
                continue
            for bulletin in bulletins:
                url = self.DETAIL_URL.format(bulletin=bulletin)
                title = self._xml_first(node, ["Titulo", "Nombre", "Descripcion", "Materia"])
                date_value = self._xml_first(node, ["Fecha", "FechaMovimiento", "FechaIngreso"])
                parsed = parse_legislative_date(date_value or text)
                project = CandidateProject(
                    bulletin=bulletin,
                    title=title,
                    latest_movement=text if parsed else "",
                    latest_movement_date=parsed.isoformat() if parsed else "",
                    legislative_history=_history_from_blocks([text], "Senado XML movimientos", url),
                    source_urls=[url],
                    discovered_from=["Senado XML movimientos desde fecha"],
                    evidence_text=text,
                    metadata={
                        "recent_feed": True,
                        "title_rank": 3,
                        "movement_rank": 5,
                        "movement_source": "Senado XML movimientos",
                        "official_date_verified": bool(parsed),
                    },
                )
                projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

    @staticmethod
    def _key_value_pairs(soup: BeautifulSoup, bulletin: str) -> dict[str, str]:
        pairs: dict[str, str] = {}
        accepted = {
            "titulo", "título", "fecha de ingreso", "estado", "trámite constitucional",
            "tramite constitucional", "etapa", "comisión", "comision", "urgencia actual",
            "urgencia", "cámara de origen", "camara de origen", "iniciativa",
        }
        for row in soup.find_all("tr"):
            cells = [compact_text(cell.get_text(" ", strip=True), 3000) for cell in row.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if len(cells) < 2:
                continue
            row_bulletins = set(BULLETIN_RE.findall(" ".join(cells)))
            if row_bulletins and bulletin not in row_bulletins:
                continue
            key = normalize_text(cells[0]).strip(" :")
            if any(key == normalize_text(label) or key.startswith(normalize_text(label) + ":") for label in accepted):
                pairs.setdefault(key, " | ".join(cells[1:]))
        return pairs

    @staticmethod
    def _pick(pairs: dict[str, str], *needles: str) -> str:
        for key, value in pairs.items():
            if any(normalize_text(needle) in key for needle in needles):
                return value
        return ""

    @staticmethod
    def _movement_rows(soup: BeautifulSoup, bulletin: str, entry: date | None) -> list[str]:
        best_rows: list[str] = []
        best_score = -10_000
        for table in soup.find_all("table"):
            candidate_rows: list[str] = []
            score = 0
            for row in table.find_all("tr"):
                cells = [compact_text(cell.get_text(" ", strip=True), 2500) for cell in row.find_all(["th", "td"])]
                cells = [cell for cell in cells if cell]
                if not cells:
                    continue
                text = " | ".join(cells)
                bulletins = set(BULLETIN_RE.findall(text))
                if bulletins and bulletin not in bulletins:
                    score -= 8
                    continue
                parsed = parse_legislative_date(text)
                if not parsed or parsed > date.today() + timedelta(days=2):
                    continue
                if entry and parsed < entry - timedelta(days=10):
                    continue
                normalized = normalize_text(text)
                action = any(contains_term(normalized, term) for term in MOVEMENT_TERMS)
                leading_date = any(parse_legislative_date(cell) for cell in cells[:2])
                if action and leading_date:
                    candidate_rows.append(text)
                    score += 4
                elif leading_date and len(cells) >= 3:
                    candidate_rows.append(text)
                    score += 2
            if len(candidate_rows) >= 2:
                score += min(len(candidate_rows), 20)
            if score > best_score:
                best_score = score
                best_rows = candidate_rows
        return unique(best_rows)[:180]

    def _detail_xml(self, bulletin: str) -> CandidateProject:
        url = self.DETAIL_URL.format(bulletin=bulletin)
        result = self.client.get(self.OPEN_PROJECT_URL, params={"boletin": bulletin})
        root = ET.fromstring(result.content)
        raw_text = compact_text(" ".join(t.strip() for t in root.itertext() if t and t.strip()), 60000)
        movements = self._xml_blocks(root)
        entry_date = self._xml_first(root, ["FechaIngreso", "FechaDeIngreso"])
        entry = parse_legislative_date(entry_date)
        latest, latest_date = latest_dated_text(
            movements,
            not_before=(entry - timedelta(days=10)) if entry else None,
            bulletin=bulletin,
        )
        return CandidateProject(
            bulletin=bulletin,
            title=self._xml_first(root, ["Titulo", "Nombre"]),
            entry_date=entry_date,
            initiative_type=self._xml_first(root, ["Iniciativa", "TipoIniciativa"]),
            origin_chamber=self._xml_first(root, ["CamaraOrigen", "CámaraOrigen"]),
            state=self._xml_first(root, ["Estado"]),
            stage=self._xml_first(root, ["Etapa", "TramiteConstitucional"]),
            commission=self._xml_first(root, ["Comision", "Comisión"]),
            urgency=self._xml_first(root, ["Urgencia", "UrgenciaActual"]),
            latest_movement=latest,
            latest_movement_date=latest_date,
            legislative_history=_history_from_blocks(movements, "Senado XML oficial", url),
            source_urls=[url],
            discovered_from=["Senado XML detalle"],
            evidence_text=raw_text,
            raw_hash=stable_hash(raw_text),
            metadata={
                "title_rank": 5,
                "movement_rank": 7,
                "movement_source": "Senado XML oficial",
                "official_date_verified": bool(latest_date),
            },
        )

    def _detail_html(self, bulletin: str) -> CandidateProject:
        url = self.DETAIL_URL.format(bulletin=bulletin)
        result = self.client.get(url)
        soup = BeautifulSoup(result.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body_text = compact_text(soup.get_text(" ", strip=True), 60000)
        pairs = self._key_value_pairs(soup, bulletin)
        title = self._pick(pairs, "título", "titulo")
        if not title:
            heading = soup.find(["h1", "h2", "h3"])
            title = compact_text(heading.get_text(" ", strip=True), 2000) if heading else ""
        entry_date = self._pick(pairs, "fecha de ingreso")
        entry = parse_legislative_date(entry_date)
        movement_rows = self._movement_rows(soup, bulletin, entry)
        latest, latest_date = latest_dated_text(
            movement_rows,
            not_before=(entry - timedelta(days=10)) if entry else None,
            bulletin=bulletin,
        )
        return CandidateProject(
            bulletin=bulletin,
            title=title,
            entry_date=entry_date,
            initiative_type=self._pick(pairs, "iniciativa"),
            origin_chamber=self._pick(pairs, "cámara de origen", "camara de origen"),
            state=self._pick(pairs, "estado"),
            stage=self._pick(pairs, "trámite constitucional", "tramite constitucional", "etapa"),
            commission=self._pick(pairs, "comisión", "comision"),
            urgency=self._pick(pairs, "urgencia actual", "urgencia"),
            latest_movement=latest,
            latest_movement_date=latest_date,
            legislative_history=_history_from_blocks(movement_rows, "Senado ficha oficial", url),
            source_urls=[url],
            discovered_from=["Senado ficha oficial de tramitación"],
            evidence_text=body_text,
            raw_hash=stable_hash(body_text),
            metadata={
                "title_rank": 4,
                "movement_rank": 6,
                "movement_source": "Senado ficha oficial",
                "official_date_verified": bool(latest_date),
            },
        )

    def detail(self, bulletin: str) -> CandidateProject:
        combined = CandidateProject(bulletin=bulletin)
        errors: list[str] = []
        try:
            combined.merge(self._detail_xml(bulletin))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"XML: {exc}")
        try:
            combined.merge(self._detail_html(bulletin))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"HTML: {exc}")
        if not combined.source_urls:
            raise RuntimeError(" | ".join(errors) or "Sin respuesta Senado")
        return combined
