from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Iterable

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import CandidateProject
from .utils import (
    BULLETIN_RE,
    DATE_RE,
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
]


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
        wanted = set(names)
        for elem in node.iter():
            if local_tag(elem.tag) in wanted and elem.text and elem.text.strip():
                return compact_text(elem.text, 2000)
        return ""

    @staticmethod
    def _all_text(node: ET.Element) -> str:
        return compact_text(" ".join(t.strip() for t in node.itertext() if t and t.strip()), 50000)

    @staticmethod
    def _collect_named_blocks(node: ET.Element, names: set[str], limit: int = 12) -> list[str]:
        out: list[str] = []
        for elem in node.iter():
            if local_tag(elem.tag) in names:
                block = compact_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip()), 2000)
                if block:
                    out.append(block)
        return unique(out)[:limit]

    @classmethod
    def _movement_blocks(cls, root: ET.Element) -> list[str]:
        out: list[str] = []
        movement_tags = {"Tramite", "Movimiento", "Oficio"}
        for elem in root.iter():
            if local_tag(elem.tag) not in movement_tags:
                continue
            block = compact_text(" ".join(t.strip() for t in elem.itertext() if t and t.strip()), 3000)
            if block and parse_legislative_date(block):
                out.append(block)
        return unique(out)[:150]

    def list_by_year(self, year: int) -> list[CandidateProject]:
        projects: dict[str, CandidateProject] = {}
        for method, label in [("retornarMensajesXAnno", "Cámara XML mensajes"), ("retornarMocionesXAnno", "Cámara XML mociones")]:
            xml_bytes = self._call(method, {"prmAnno": str(year)})
            root = ET.fromstring(xml_bytes)
            for node in root.iter():
                if local_tag(node.tag) != "ProyectoLey":
                    continue
                bulletin = self._first_text(node, ["NumeroBoletin"])
                match = BULLETIN_RE.search(bulletin)
                if not match:
                    continue
                bulletin = match.group(1)
                project = CandidateProject(
                    bulletin=bulletin,
                    title=self._first_text(node, ["Nombre"]),
                    entry_date=self._first_text(node, ["FechaIngreso"]),
                    initiative_type=self._first_text(node, ["TipoIniciativa"]),
                    origin_chamber=self._first_text(node, ["CamaraOrigen"]),
                    source_urls=[f"https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"],
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
        return CandidateProject(
            bulletin=bulletin,
            title=self._first_text(root, ["Nombre"]),
            entry_date=entry_date,
            initiative_type=self._first_text(root, ["TipoIniciativa"]),
            origin_chamber=self._first_text(root, ["CamaraOrigen"]),
            state=" | ".join(states[:3]),
            stage=" | ".join(stages[:4]),
            commission=" | ".join(commissions[:5]),
            urgency=" | ".join(urgencies[:3]),
            latest_movement=latest_movement,
            latest_movement_date=latest_movement_date,
            source_urls=[f"https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"],
            discovered_from=["Cámara XML detalle"],
            evidence_text=raw_text,
            raw_hash=stable_hash(raw_text),
            metadata={
                "camara_movements": movements[-20:],
                "title_rank": 5,
                "movement_rank": 5,
                "movement_source": "Cámara XML oficial",
                "official_date_verified": bool(latest_movement_date),
            },
        )


class SenadoSource:
    # Esta URL se conserva como referencia, pero NO se utiliza para fechar movimientos:
    # corresponde a elementos vistos recientemente, no a la cronología oficial de cada boletín.
    RECENT_URL = "https://tramitacion.senado.cl/appsenado/index.php?ac=ultimos_vistos&etc=&mo=tramitacion"
    DETAIL_URL = "https://tramitacion.senado.cl/appsenado/templates/tramitacion/index.php?boletin_ini={bulletin}"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def recent_movements(self) -> list[CandidateProject]:
        """Deshabilitado como fuente de fechas para evitar confundir 'últimos vistos' con trámites."""
        return []

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
                # Las tablas cronológicas oficiales normalmente tienen la fecha en la primera
                # o segunda celda. Este requisito excluye listados laterales y contenido general.
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
        return unique(best_rows)[:150]

    def detail(self, bulletin: str) -> CandidateProject:
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
            source_urls=[url],
            discovered_from=["Senado ficha oficial de tramitación"],
            evidence_text=body_text,
            raw_hash=stable_hash(body_text),
            metadata={
                "senado_rows": movement_rows[-30:],
                "title_rank": 4,
                "movement_rank": 4,
                "movement_source": "Senado ficha oficial",
                "official_date_verified": bool(latest_date),
            },
        )


class BCNAssociatedProjectsSource:
    URL = (
        "https://nuevo.leychile.cl/servicios/Navegar/scripts/exportarProyectos"
        "?formato=pdf&idNorma=219119&idParte=&idVersion=2022-12-30"
    )

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def list_associated(self) -> list[CandidateProject]:
        result = self.client.get(self.URL)
        reader = PdfReader(io.BytesIO(result.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        normalized = re.sub(r"\s+", " ", text)
        chunks = re.split(r"\s+\d+\.-\s+", normalized)
        projects: dict[str, CandidateProject] = {}
        for chunk in chunks:
            match = BULLETIN_RE.search(chunk)
            if not match:
                continue
            bulletin = match.group(1)
            title = compact_text(chunk[: match.start()].strip(" .-"), 1200)
            project = CandidateProject(
                bulletin=bulletin,
                title=title,
                source_urls=[self.URL, SenadoSource.DETAIL_URL.format(bulletin=bulletin)],
                discovered_from=["BCN proyectos asociados a Ley 19.913"],
                evidence_text=compact_text(chunk, 5000),
                raw_hash=stable_hash(chunk),
                metadata={"bcn_associated": True, "title_rank": 2},
            )
            projects[bulletin] = project
        return list(projects.values())
