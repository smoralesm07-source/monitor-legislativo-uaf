from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import CandidateProject
from .utils import BULLETIN_RE, DATE_RE, compact_text, latest_dated_text, local_tag, stable_hash, unique

LOGGER = logging.getLogger(__name__)


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
        movements = self._collect_named_blocks(root, {"Tramite", "Movimiento", "Oficio", "Sesion"}, limit=60)
        latest_movement, latest_movement_date = latest_dated_text(movements)
        return CandidateProject(
            bulletin=bulletin,
            title=self._first_text(root, ["Nombre"]),
            entry_date=self._first_text(root, ["FechaIngreso"]),
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
            metadata={"camara_movements": movements[-20:], "title_rank": 4},
        )


class SenadoSource:
    RECENT_URL = "https://tramitacion.senado.cl/appsenado/index.php?ac=ultimos_vistos&etc=&mo=tramitacion"
    DETAIL_URL = "https://tramitacion.senado.cl/appsenado/templates/tramitacion/index.php?boletin_ini={bulletin}"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    def recent_movements(self) -> list[CandidateProject]:
        result = self.client.get(self.RECENT_URL)
        soup = BeautifulSoup(result.text, "html.parser")
        projects: dict[str, CandidateProject] = {}
        for row in soup.find_all("tr"):
            text = compact_text(row.get_text(" ", strip=True), 3000)
            bulletin_match = BULLETIN_RE.search(text)
            if not bulletin_match:
                href_text = " ".join(a.get("href", "") for a in row.find_all("a"))
                bulletin_match = BULLETIN_RE.search(href_text)
            if not bulletin_match:
                continue
            bulletin = bulletin_match.group(1)
            _, recent_date = latest_dated_text([text])
            links = [urljoin(self.RECENT_URL, a.get("href", "")) for a in row.find_all("a") if a.get("href")]
            project = CandidateProject(
                bulletin=bulletin,
                title=text,
                latest_movement=text,
                latest_movement_date=recent_date,
                source_urls=[self.DETAIL_URL.format(bulletin=bulletin)] + links,
                discovered_from=["Senado últimos movimientos"],
                evidence_text=text,
                raw_hash=stable_hash(text),
                metadata={"title_rank": 1},
            )
            projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

    def detail(self, bulletin: str) -> CandidateProject:
        url = self.DETAIL_URL.format(bulletin=bulletin)
        result = self.client.get(url)
        soup = BeautifulSoup(result.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body_text = compact_text(soup.get_text(" ", strip=True), 60000)
        pairs: dict[str, str] = {}
        rows: list[str] = []
        for row in soup.find_all("tr"):
            cells = [compact_text(cell.get_text(" ", strip=True), 3000) for cell in row.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            rows.append(" | ".join(cells))
            if len(cells) >= 2:
                key = cells[0].lower()
                value = " | ".join(cells[1:])
                pairs[key] = value
        def pick(*needles: str) -> str:
            for key, value in pairs.items():
                if any(needle in key for needle in needles):
                    return value
            return ""
        title = pick("título", "titulo", "materia", "nombre")
        if not title:
            heading = soup.find(["h1", "h2", "h3"])
            title = compact_text(heading.get_text(" ", strip=True), 2000) if heading else ""
        date_rows = [row for row in rows if DATE_RE.search(row)]
        latest, latest_date = latest_dated_text(date_rows)
        return CandidateProject(
            bulletin=bulletin,
            title=title,
            state=pick("estado"),
            stage=pick("trámite constitucional", "tramite constitucional", "etapa"),
            commission=pick("comisión", "comision"),
            urgency=pick("urgencia"),
            latest_movement=latest,
            latest_movement_date=latest_date,
            source_urls=[url],
            discovered_from=["Senado ficha de tramitación"],
            evidence_text=body_text,
            raw_hash=stable_hash(body_text),
            metadata={"senado_rows": rows[-30:], "title_rank": 3},
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
