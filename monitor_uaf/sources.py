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
from .utils import (
    BULLETIN_RE, DATE_RE, compact_text, latest_dated_text, local_tag,
    normalize_text, parse_legislative_date, stable_hash, unique,
)

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
        camara_proceedings = []
        for movement in movements[-50:]:
            parsed = parse_legislative_date(movement)
            camara_proceedings.append({
                "session": "",
                "date": parsed.isoformat() if parsed else "",
                "substage": movement,
                "stage": " | ".join(stages[:2]),
                "documents": [],
            })
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
            metadata={"camara_movements": movements[-20:], "camara_proceedings": camara_proceedings, "title_rank": 4},
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

    @staticmethod
    def _direct_cells(row) -> list:
        cells = row.find_all(["th", "td"], recursive=False)
        return cells or row.find_all(["th", "td"])

    @staticmethod
    def _cell_text(cell, max_len: int = 5000) -> str:
        return compact_text(cell.get_text(" ", strip=True), max_len)

    @staticmethod
    def _documents(cell, base_url: str) -> list[dict[str, str]]:
        documents: list[dict[str, str]] = []
        for link in cell.find_all("a", href=True):
            href = link.get("href", "").strip()
            if not href or href.lower().startswith("javascript:"):
                continue
            label = compact_text(link.get_text(" ", strip=True), 300) or "Ver documento"
            documents.append({"label": label, "url": urljoin(base_url, href)})
        # Dedupe conservando orden.
        seen: set[tuple[str, str]] = set()
        output: list[dict[str, str]] = []
        for item in documents:
            key = (item["label"], item["url"])
            if key not in seen:
                seen.add(key)
                output.append(item)
        return output

    @staticmethod
    def _normalized_headers(cells: list) -> list[str]:
        return [normalize_text(compact_text(cell.get_text(" ", strip=True), 300)) for cell in cells]

    def _parse_legislative_tables(self, soup: BeautifulSoup, base_url: str) -> tuple[list[dict], list[dict], dict[str, bool]]:
        proceedings: list[dict] = []
        presentations: list[dict] = []
        found = {"proceedings": False, "presentations": False}

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if not rows:
                continue
            header_index = None
            headers: list[str] = []
            for index, row in enumerate(rows[:6]):
                cells = self._direct_cells(row)
                normalized = self._normalized_headers(cells)
                joined = " | ".join(normalized)
                if "fecha" in joined and (
                    ("subetapa" in joined and "etapa" in joined)
                    or ("titulo" in joined and "comision" in joined)
                ):
                    header_index = index
                    headers = normalized
                    break
            if header_index is None:
                continue

            def column(*needles: str) -> int | None:
                for idx, header in enumerate(headers):
                    if any(needle in header for needle in needles):
                        return idx
                return None

            is_proceedings = column("subetapa") is not None and column("etapa") is not None
            is_presentations = column("titulo") is not None and column("comision") is not None
            if is_proceedings:
                found["proceedings"] = True
            if is_presentations:
                found["presentations"] = True

            for row in rows[header_index + 1:]:
                cells = self._direct_cells(row)
                if not cells:
                    continue
                values = [self._cell_text(cell) for cell in cells]
                if not any(values):
                    continue

                def value_at(index: int | None) -> str:
                    return values[index] if index is not None and index < len(values) else ""

                date_raw = value_at(column("fecha"))
                parsed_date = parse_legislative_date(date_raw)
                date_value = parsed_date.isoformat() if parsed_date else date_raw
                doc_idx = column("document", "ver docto", "ver doc")
                documents = self._documents(cells[doc_idx], base_url) if doc_idx is not None and doc_idx < len(cells) else []

                if is_proceedings:
                    item = {
                        "session": value_at(column("sesion", "leg.")),
                        "date": date_value,
                        "substage": value_at(column("subetapa")),
                        "stage": value_at(column("etapa")),
                        "documents": documents,
                    }
                    if item["date"] or item["substage"] or item["stage"]:
                        proceedings.append(item)
                elif is_presentations:
                    item = {
                        "date": date_value,
                        "title": value_at(column("titulo")),
                        "organization": value_at(column("organizacion")),
                        "commission": value_at(column("comision")),
                        "documents": documents,
                    }
                    if item["date"] or item["title"] or item["organization"]:
                        presentations.append(item)

        def dedupe(items: list[dict]) -> list[dict]:
            seen: set[str] = set()
            output: list[dict] = []
            for item in items:
                key = stable_hash(item)
                if key not in seen:
                    seen.add(key)
                    output.append(item)
            return output

        return dedupe(proceedings), dedupe(presentations), found

    def detail(self, bulletin: str) -> CandidateProject:
        url = self.DETAIL_URL.format(bulletin=bulletin)
        result = self.client.get(url)
        soup = BeautifulSoup(result.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body_text = compact_text(soup.get_text(" ", strip=True), 90000)
        pairs: dict[str, str] = {}
        rows: list[str] = []
        standalone_rows: list[str] = []

        for row in soup.find_all("tr"):
            cells_nodes = self._direct_cells(row)
            cells = [self._cell_text(cell, 3000) for cell in cells_nodes]
            cells = [cell for cell in cells if cell]
            if not cells:
                continue
            rows.append(" | ".join(cells))
            if len(cells) == 1:
                standalone_rows.append(cells[0])
                continue
            # Las fichas del Senado suelen usar dos pares etiqueta/valor en una fila.
            for index in range(0, len(cells) - 1, 2):
                raw_key = cells[index].strip().rstrip(":")
                raw_value = cells[index + 1]
                key = normalize_text(raw_key)
                if key and len(key) <= 80 and raw_value:
                    pairs[key] = raw_value

        def pick(*needles: str) -> str:
            normalized_needles = [normalize_text(needle) for needle in needles]
            for key, value in pairs.items():
                if any(needle in key for needle in normalized_needles):
                    return value
            return ""

        title = pick("título", "titulo", "materia", "nombre")
        if not title:
            # Evitar tomar "Boletín 12345-00" como título cuando existe otro encabezado.
            headings = [compact_text(h.get_text(" ", strip=True), 2000) for h in soup.find_all(["h1", "h2", "h3"])]
            title = next((h for h in headings if h and not BULLETIN_RE.search(h) and normalize_text(h) not in {"tramitacion", "presentaciones ante comision"}), "")

        proceedings, presentations, table_found = self._parse_legislative_tables(soup, url)
        activity_rows: list[str] = []
        for item in proceedings:
            activity_rows.append(" | ".join(filter(None, [item.get("date", ""), item.get("substage", ""), item.get("stage", "")])))
        for item in presentations:
            activity_rows.append(" | ".join(filter(None, [item.get("date", ""), "Presentación ante comisión", item.get("title", ""), item.get("commission", "")])))
        if not activity_rows:
            activity_rows = [row for row in rows if DATE_RE.search(row)]
        latest, latest_date = latest_dated_text(activity_rows)

        committee_report = next(
            (row for row in standalone_rows if "informe" in normalize_text(row) and "comision" in normalize_text(row)),
            "",
        )
        commission = pick("comisión", "comision") or committee_report
        metadata = {
            "senado_rows": rows[-100:],
            "senado_detail_schema": "2",
            "title_rank": 5,
            "project_type": pick("tipo de proyecto"),
            "refunded": pick("refundido"),
            "committee_report": committee_report,
            "senado_proceedings_table_found": table_found["proceedings"],
            "senado_presentations_table_found": table_found["presentations"],
        }
        if table_found["proceedings"]:
            metadata["senado_proceedings"] = proceedings[-150:]
        if table_found["presentations"]:
            metadata["commission_presentations"] = presentations[-150:]

        return CandidateProject(
            bulletin=bulletin,
            title=title,
            entry_date=pick("fecha de ingreso"),
            initiative_type=pick("iniciativa"),
            origin_chamber=pick("cámara de origen", "camara de origen"),
            state=pick("estado"),
            stage=pick("trámite constitucional", "tramite constitucional", "etapa"),
            commission=commission,
            urgency=pick("urgencia actual", "urgencia"),
            latest_movement=latest,
            latest_movement_date=latest_date,
            source_urls=[url],
            discovered_from=["Senado ficha de tramitación"],
            evidence_text=body_text,
            raw_hash=stable_hash(body_text),
            metadata=metadata,
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
