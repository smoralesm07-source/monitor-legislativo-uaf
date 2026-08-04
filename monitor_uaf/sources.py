from __future__ import annotations

import io
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
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
                    metadata={"title_rank": 2, "entry_date_verified": True, "field_ranks": {"title": 20, "entry_date": 20, "initiative_type": 20, "origin_chamber": 20}},
                )
                projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

    @staticmethod
    def _structured_movements(root: ET.Element) -> list[dict[str, str]]:
        """Extrae solo movimientos con fecha y descripción dentro del mismo nodo.

        Se evita usar bloques genéricos de sesión u oficio que pueden contener
        fechas administrativas ajenas al último movimiento del proyecto.
        """
        containers = {"Tramite", "Movimiento", "Tramitacion", "TramiteProyectoLey"}
        date_names = {"Fecha", "FechaTramite", "FechaMovimiento", "FechaSesion"}
        description_names = {
            "Descripcion", "Nombre", "Glosa", "Detalle", "SubEtapa", "Subetapa",
            "TramiteReglamentario", "Resultado",
        }
        stage_names = {"TramiteConstitucional", "Etapa", "EtapaConstitucional"}
        session_names = {"Sesion", "NumeroSesion", "Legislatura"}
        rows: list[dict[str, str]] = []
        for node in root.iter():
            if local_tag(node.tag) not in containers:
                continue
            date_value = ""
            descriptions: list[str] = []
            stages: list[str] = []
            sessions: list[str] = []
            for child in node.iter():
                tag = local_tag(child.tag)
                text = compact_text(" ".join(t.strip() for t in child.itertext() if t and t.strip()), 5000)
                if not text:
                    continue
                if tag in date_names and not date_value and parse_legislative_date(text):
                    date_value = parse_legislative_date(text).isoformat()
                elif tag in description_names:
                    descriptions.append(text)
                elif tag in stage_names:
                    stages.append(text)
                elif tag in session_names:
                    sessions.append(text)
            if not date_value:
                continue
            description = next((item for item in descriptions if parse_legislative_date(item) is None), "")
            stage = next((item for item in stages if item and item != description), "")
            if not description and not stage:
                continue
            rows.append({
                "session": " | ".join(unique(sessions)[:2]),
                "date": date_value,
                "substage": compact_text(description, 5000),
                "stage": compact_text(stage, 2000),
                "documents": [],
            })
        deduped: dict[str, dict[str, str]] = {}
        for row in rows:
            deduped[stable_hash(row)] = row
        return sorted(
            deduped.values(),
            key=lambda row: parse_legislative_date(row.get("date", "")) or datetime.min.date(),
        )

    def detail(self, bulletin: str) -> CandidateProject:
        xml_bytes = self._call("retornarProyectoLey", {"prmNumeroBoletin": bulletin})
        root = ET.fromstring(xml_bytes)
        raw_text = self._all_text(root)
        states = self._collect_named_blocks(root, {"Estado", "EstadoProyectoLey"})
        commissions = self._collect_named_blocks(root, {"Comision", "ComisionDestino", "ComisionOrigen"})
        urgencies = self._collect_named_blocks(root, {"Urgencia", "TipoUrgencia"})
        proceedings = self._structured_movements(root)
        today_limit = date.today() + timedelta(days=1)
        dated = [
            (parsed, index, row)
            for index, row in enumerate(proceedings)
            for parsed in [parse_legislative_date(row.get("date", ""))]
            if parsed and parsed <= today_limit
        ]
        dated.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
        latest_row = dated[0][2] if dated else None
        latest_date = dated[0][0].isoformat() if dated else ""
        latest_movement = compact_text(
            " | ".join(filter(None, [
                (latest_row or {}).get("substage", ""),
                (latest_row or {}).get("stage", ""),
            ])),
            6000,
        )

        structured_stages = [row.get("stage", "") for _, _, row in dated if row.get("stage")]
        fallback_stages = self._collect_named_blocks(root, {"TramiteConstitucional", "Etapa"})
        stage = structured_stages[0] if structured_stages else (fallback_stages[-1] if fallback_stages else "")
        commission = " | ".join(unique(commissions)[:5])
        state = " | ".join(unique(states)[:3])

        return CandidateProject(
            bulletin=bulletin,
            title=self._first_text(root, ["Nombre"]),
            entry_date=self._first_text(root, ["FechaIngreso"]),
            initiative_type=self._first_text(root, ["TipoIniciativa"]),
            origin_chamber=self._first_text(root, ["CamaraOrigen"]),
            state=state,
            stage=stage,
            commission=commission,
            urgency=" | ".join(unique(urgencies)[:3]),
            latest_movement=latest_movement,
            latest_movement_date=latest_date,
            source_urls=[f"https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"],
            discovered_from=["Cámara XML detalle estructurado"],
            evidence_text=raw_text,
            raw_hash=stable_hash(raw_text),
            metadata={
                "camara_proceedings": proceedings[-200:],
                "promoters": self._collect_named_blocks(root, {"Autor", "Autores", "Parlamentario", "Diputado", "Diputada", "Senador", "Senadora"}, limit=40),
                "matters": self._collect_named_blocks(root, {"Materia", "Materias", "Descripcion", "Objetivo"}, limit=20),
                "title_rank": 4,
                "official_stage_source": "Cámara XML detalle",
                "official_detail_verified": True,
                "entry_date_verified": bool(self._first_text(root, ["FechaIngreso"])),
                "official_status_verified": bool(state or stage),
                "movement_verified": bool(latest_row),
                "movement_authoritative": bool(proceedings),
                "movement_source": "Cámara XML tramitación estructurada" if latest_row else "",
                "movement_context_exact": True,
                "field_ranks": {
                    "title": 80,
                    "entry_date": 90,
                    "initiative_type": 90,
                    "origin_chamber": 90,
                    "state": 95,
                    "stage": 100,
                    "commission": 90,
                    "urgency": 100,
                    "latest_movement": 105 if latest_row else 0,
                    "latest_movement_date": 105 if latest_row else 0,
                },
            },
        )


class SenadoSource:
    """Fuente oficial del Senado con separación estricta de contextos.

    Se usan tres vistas diferentes y nunca se mezclan sus filas:

    * la portada de tramitación, para descubrir proyectos iniciados recientemente;
    * ``ultimos_vistos``, que en el sitio corresponde a proyectos tratados en los
      últimos días, para capturar actividad de Sala y comisiones;
    * la ficha individual del boletín, para validar título, etapa, informe vigente,
      urgencia y cronología propia del proyecto.

    La separación evita que tablas globales de la portada del Senado se atribuyan
    al boletín que se está consultando, problema que podía otorgar fechas recientes
    a iniciativas históricas como el boletín 2975-07.
    """

    HOME_URL = "https://tramitacion.senado.cl/"
    RECENT_URL = "https://tramitacion.senado.cl/appsenado/index.php?ac=ultimos_vistos&mo=tramitacion"
    DETAIL_URL = "https://tramitacion.senado.cl/appsenado/templates/tramitacion/index.php?boletin_ini={bulletin}"

    def __init__(self, client: HttpClient) -> None:
        self.client = client

    @staticmethod
    def _direct_cells(row) -> list:
        cells = row.find_all(["th", "td"], recursive=False)
        return cells or row.find_all(["th", "td"])

    @staticmethod
    def _cell_text(cell, max_len: int = 5000) -> str:
        return compact_text(cell.get_text(" ", strip=True), max_len)

    @staticmethod
    def _canonical_stage(value: str, *, senate_context: bool = False) -> str:
        text = compact_text(value, 1500)
        norm = normalize_text(text)
        chamber = "Senado" if senate_context else ""
        if "disc. informe c.mixta" in norm or "comision mixta" in norm:
            return "Discusión de informe de Comisión Mixta" + (" (Senado)" if senate_context else "")
        for number, label in (("primer", "Primer"), ("segundo", "Segundo"), ("tercer", "Tercer")):
            if f"{number} tramite constitucional" in norm:
                if "c.diputados" in norm or "c. diputados" in norm or "camara de diputados" in norm:
                    chamber = "C.Diputados"
                elif "senado" in norm:
                    chamber = "Senado"
                return f"{label} trámite constitucional" + (f" ({chamber})" if chamber else "")
        replacements = {
            "Primer trámite constitucional / Senado": "Primer trámite constitucional (Senado)",
            "Segundo trámite constitucional / Senado": "Segundo trámite constitucional (Senado)",
            "Tercer trámite constitucional / Senado": "Tercer trámite constitucional (Senado)",
            "Primer trámite constitucional / C.Diputados": "Primer trámite constitucional (C.Diputados)",
            "Segundo trámite constitucional / C.Diputados": "Segundo trámite constitucional (C.Diputados)",
            "Tercer trámite constitucional / C.Diputados": "Tercer trámite constitucional (C.Diputados)",
        }
        return replacements.get(text, text)

    @staticmethod
    def _documents(cell, base_url: str) -> list[dict[str, str]]:
        documents: list[dict[str, str]] = []
        for link in cell.find_all("a", href=True):
            href = link.get("href", "").strip()
            if not href or href.lower().startswith("javascript:"):
                continue
            label = compact_text(link.get_text(" ", strip=True), 300) or "Ver documento"
            documents.append({"label": label, "url": urljoin(base_url, href)})
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

    @staticmethod
    def _column(headers: list[str], *needles: str) -> int | None:
        wanted = [normalize_text(item) for item in needles]
        for idx, header in enumerate(headers):
            if any(header == needle for needle in wanted):
                return idx
        for idx, header in enumerate(headers):
            if any(needle in header for needle in wanted):
                return idx
        return None

    def _find_table(self, soup: BeautifulSoup, required: tuple[str, ...], forbidden: tuple[str, ...] = ()):
        best = None
        best_score = -1
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows[:8]:
                headers = self._normalized_headers(self._direct_cells(row))
                joined = " | ".join(headers)
                if all(normalize_text(item) in joined for item in required) and not any(
                    normalize_text(item) in joined for item in forbidden
                ):
                    score = sum(1 for item in required if normalize_text(item) in joined)
                    if score > best_score:
                        best = (table, row, headers)
                        best_score = score
        return best

    def list_current_projects(self, days: int = 420) -> list[CandidateProject]:
        """Descubre proyectos recientes desde la tabla oficial de la portada.

        Solo acepta filas de la tabla cuyo encabezado contiene Boletín, Título,
        Estado y Fecha. No lee tablas globales sin encabezado ni resultados de
        navegación. La fecha se usa como ingreso/registro, no como movimiento.
        """
        result = self.client.get(self.HOME_URL)
        soup = BeautifulSoup(result.text, "html.parser")
        found = self._find_table(soup, ("boletin", "titulo", "estado", "fecha"))
        if not found:
            return []
        table, header_row, headers = found
        rows = table.find_all("tr")
        start = rows.index(header_row) + 1
        bidx = self._column(headers, "boletin")
        tidx = self._column(headers, "titulo")
        sidx = self._column(headers, "estado")
        didx = self._column(headers, "fecha")
        today = date.today()
        projects: dict[str, CandidateProject] = {}
        for row in rows[start:]:
            cells = self._direct_cells(row)
            values = [self._cell_text(cell, 5000) for cell in cells]
            if bidx is None or bidx >= len(values):
                continue
            match = BULLETIN_RE.search(values[bidx])
            if not match:
                continue
            bulletin = match.group(1)
            title = values[tidx] if tidx is not None and tidx < len(values) else ""
            state = values[sidx] if sidx is not None and sidx < len(values) else ""
            entry_raw = values[didx] if didx is not None and didx < len(values) else ""
            entry = parse_legislative_date(entry_raw)
            if not entry or entry > today + timedelta(days=1) or (today - entry).days > max(1, days):
                continue
            if normalize_text(state) != "en tramitacion":
                continue
            row_text = " | ".join(values)
            links = [urljoin(result.url or self.HOME_URL, a.get("href", "")) for a in row.find_all("a", href=True)]
            project = CandidateProject(
                bulletin=bulletin,
                title=title,
                entry_date=entry.isoformat(),
                state=state,
                source_urls=unique([self.DETAIL_URL.format(bulletin=bulletin), *links]),
                discovered_from=["Senado proyectos iniciados recientes"],
                evidence_text=row_text,
                raw_hash=stable_hash(row_text),
                metadata={
                    "senate_current_list_verified": True,
                    "entry_date_verified": True,
                    "official_status_verified": True,
                    "field_ranks": {"title": 35, "entry_date": 50, "state": 45},
                },
            )
            projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

    def recent_movements(self) -> list[CandidateProject]:
        """Obtiene actividad reciente de Sala y comisiones con filas estrictas."""
        result = self.client.get(self.RECENT_URL)
        soup = BeautifulSoup(result.text, "html.parser")
        projects: dict[str, CandidateProject] = {}
        today_limit = date.today() + timedelta(days=1)

        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            header_index = None
            headers: list[str] = []
            for index, row in enumerate(rows[:8]):
                candidate_headers = self._normalized_headers(self._direct_cells(row))
                joined = " | ".join(candidate_headers)
                if "fecha" in joined and "boletin" in joined and (
                    ("etapa" in joined and "resultado" in joined)
                    or ("comision" in joined and "tema" in joined and "acuerdo" in joined)
                ):
                    header_index = index
                    headers = candidate_headers
                    break
            if header_index is None:
                continue

            bidx = self._column(headers, "boletin")
            didx = self._column(headers, "fecha")
            tidx = self._column(headers, "titulo")
            eidx = self._column(headers, "etapa")
            ridx = self._column(headers, "resultado")
            cidx = self._column(headers, "comision")
            pidx = self._column(headers, "punto")
            midx = self._column(headers, "tema")
            aidx = self._column(headers, "acuerdo")

            for row in rows[header_index + 1:]:
                cells = self._direct_cells(row)
                values = [self._cell_text(cell, 6000) for cell in cells]
                if bidx is None or bidx >= len(values):
                    continue
                match = BULLETIN_RE.search(values[bidx])
                if not match:
                    continue
                bulletin = match.group(1)
                raw_date = values[didx] if didx is not None and didx < len(values) else ""
                movement_date = parse_legislative_date(raw_date)
                if not movement_date or movement_date > today_limit:
                    continue

                def at(idx: int | None) -> str:
                    return values[idx] if idx is not None and idx < len(values) else ""

                if eidx is not None:
                    title = at(tidx)
                    stage_raw = at(eidx)
                    result_text = at(ridx)
                    stage = self._canonical_stage(stage_raw, senate_context=True)
                    latest = compact_text(" | ".join(filter(None, [stage_raw, result_text])), 5000)
                    commission = ""
                    movement_kind = "Sala"
                else:
                    title = at(midx) or at(pidx)
                    commission = at(cidx)
                    point = at(pidx)
                    topic = at(midx)
                    agreement = at(aidx)
                    latest = compact_text(" | ".join(filter(None, [point, topic, agreement])), 7000)
                    stage = self._canonical_stage(" ".join([point, topic]), senate_context=True)
                    movement_kind = "Comisión"

                row_text = " | ".join(values)
                project = CandidateProject(
                    bulletin=bulletin,
                    title=title,
                    state="En tramitación",
                    stage=stage,
                    commission=commission,
                    latest_movement=latest,
                    latest_movement_date=movement_date.isoformat(),
                    source_urls=[self.DETAIL_URL.format(bulletin=bulletin), self.RECENT_URL],
                    discovered_from=[f"Senado actividad reciente de {movement_kind}"],
                    evidence_text=row_text,
                    raw_hash=stable_hash(row_text),
                    metadata={
                        "official_status_verified": True,
                        "movement_verified": True,
                        "movement_source": f"Senado actividad reciente de {movement_kind}",
                        "movement_context_exact": True,
                        "field_ranks": {
                            "title": 45,
                            "state": 65,
                            "stage": 70 if stage else 0,
                            "commission": 70 if commission else 0,
                            "latest_movement": 90,
                            "latest_movement_date": 90,
                        },
                    },
                )
                projects.setdefault(bulletin, project).merge(project)
        return list(projects.values())

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
            for index, row in enumerate(rows[:8]):
                cells = self._direct_cells(row)
                normalized = self._normalized_headers(cells)
                joined = " | ".join(normalized)
                if "fecha" in joined and (
                    ("subetapa" in joined and "etapa" in joined)
                    or ("titulo" in joined and "comision" in joined and "boletin" not in joined)
                ):
                    header_index = index
                    headers = normalized
                    break
            if header_index is None:
                continue

            def column(*needles: str) -> int | None:
                return self._column(headers, *needles)

            is_proceedings = column("subetapa") is not None and column("etapa") is not None
            is_presentations = column("titulo") is not None and column("comision") is not None and column("boletin") is None
            found["proceedings"] = found["proceedings"] or is_proceedings
            found["presentations"] = found["presentations"] or is_presentations

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
                        "stage": self._canonical_stage(value_at(column("etapa"))),
                        "documents": documents,
                    }
                    if parsed_date and (item["substage"] or item["stage"]):
                        proceedings.append(item)
                elif is_presentations:
                    item = {
                        "date": date_value,
                        "title": value_at(column("titulo")),
                        "organization": value_at(column("organizacion")),
                        "commission": value_at(column("comision")),
                        "documents": documents,
                    }
                    if parsed_date or item["title"] or item["organization"]:
                        presentations.append(item)

        def dedupe_and_sort(items: list[dict]) -> list[dict]:
            seen: set[str] = set()
            output: list[dict] = []
            for item in items:
                key = stable_hash(item)
                if key not in seen:
                    seen.add(key)
                    output.append(item)
            return sorted(output, key=lambda item: parse_legislative_date(item.get("date", "")) or datetime.min.date())

        return dedupe_and_sort(proceedings), dedupe_and_sort(presentations), found

    def _project_info_table(self, soup: BeautifulSoup, bulletin: str):
        labels = (
            "fecha de ingreso", "urgencia actual", "camara de origen", "iniciativa",
            "tipo de proyecto", "refundido", "etapa", "estado", "titulo",
        )
        scored = []
        for table in soup.find_all("table"):
            text = normalize_text(self._cell_text(table, 25000))
            bulletins = set(BULLETIN_RE.findall(text))
            # Las tablas globales de proyectos recientes contienen muchos boletines.
            # La ficha general del proyecto contiene el boletín consultado y pocos más
            # (solo refundidos, cuando corresponde).
            if len(bulletins) > 8:
                continue
            score = sum(1 for label in labels if label in text)
            if bulletin in text:
                score += 5
            if "fecha de ingreso" in text and "etapa" in text:
                score += 5
            if score >= 6:
                scored.append((score, table))
        return max(scored, key=lambda item: item[0])[1] if scored else None

    @staticmethod
    def _extract_people(text: str) -> list[str]:
        clean = compact_text(text, 16000)
        candidates: list[str] = []
        patterns = [
            r"(?:Autor(?:es)?|Patrocinante(?:s)?|Mocionantes?)\s*[:|]\s*([^\n]{5,2500})",
            r"(?:Diputad[oa]s?|Senador(?:a|es)?)\s+(?:señor(?:a|es)?\s+)?([^\n]{5,2000})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, clean, flags=re.IGNORECASE):
                segment = re.split(
                    r"(?:Tramitación|Informes|Oficios|Indicaciones|Urgencias|Votaciones|Proyectos Iniciados)",
                    match.group(1), flags=re.IGNORECASE,
                )[0]
                for item in re.split(r"\s*\|\s*|\s*;\s*|\s*,\s*(?=[A-ZÁÉÍÓÚÑ])", segment):
                    item = compact_text(re.sub(r"\([^)]*\)", "", item), 180)
                    norm = normalize_text(item)
                    if 2 <= len(item.split()) <= 8 and not any(term in norm for term in ("camara", "comision", "proyecto", "boletin", "fecha")):
                        candidates.append(item)
        return unique(candidates)[:40]

    def detail(self, bulletin: str) -> CandidateProject:
        url = self.DETAIL_URL.format(bulletin=bulletin)
        result = self.client.get(url)
        soup = BeautifulSoup(result.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        full_text = compact_text(soup.get_text("\n", strip=True), 120000)
        info_table = self._project_info_table(soup, bulletin)
        pairs: dict[str, str] = {}
        info_rows: list[str] = []
        standalone_rows: list[str] = []

        if info_table is not None:
            for row in info_table.find_all("tr"):
                cells = [self._cell_text(cell, 5000) for cell in self._direct_cells(row)]
                cells = [cell for cell in cells if cell]
                if not cells:
                    continue
                info_rows.append(" | ".join(cells))
                if len(cells) == 1:
                    standalone_rows.append(cells[0])
                    continue
                for index in range(0, len(cells) - 1, 2):
                    key = normalize_text(cells[index].strip().rstrip(":"))
                    value = cells[index + 1]
                    if key and len(key) <= 100 and value:
                        pairs[key] = value

        def pick(*needles: str) -> str:
            wanted = [normalize_text(item) for item in needles]
            for key, value in pairs.items():
                if any(key == item for item in wanted):
                    return value
            for key, value in pairs.items():
                if any(item in key for item in wanted):
                    return value
            return ""

        title = pick("título", "titulo", "materia", "nombre")
        if not title:
            headings = [compact_text(h.get_text(" ", strip=True), 2500) for h in soup.find_all(["h1", "h2", "h3"])]
            title = next((h for h in headings if h and not BULLETIN_RE.search(h) and normalize_text(h) not in {"tramitacion", "presentaciones ante comision"}), "")

        proceedings, presentations, table_found = self._parse_legislative_tables(soup, url)
        today_limit = date.today() + timedelta(days=1)
        dated_proceedings = [
            (parsed, index, item)
            for index, item in enumerate(proceedings)
            for parsed in [parse_legislative_date(item.get("date", ""))]
            if parsed and parsed <= today_limit
        ]
        # La tabla del Senado puede contener varias filas en una misma fecha. En
        # ese caso se prefiere la última fila publicada para no mostrar como
        # antecedente final una cuenta o trámite previo del mismo día.
        dated_proceedings.sort(key=lambda pair: (pair[0], pair[1]), reverse=True)
        latest_item = dated_proceedings[0][2] if dated_proceedings else None
        latest_date = dated_proceedings[0][0].isoformat() if dated_proceedings else ""
        latest = ""
        if latest_item:
            latest = compact_text(
                " | ".join(filter(None, [latest_item.get("substage", ""), latest_item.get("stage", "")])),
                5000,
            )

        explicit_stage = self._canonical_stage(pick("etapa", "trámite constitucional", "tramite constitucional"))
        latest_stage = self._canonical_stage((latest_item or {}).get("stage", ""))
        stage = explicit_stage or latest_stage

        committee_report = next(
            (row for row in standalone_rows if "informe" in normalize_text(row) and "comision" in normalize_text(row)),
            "",
        )
        if not committee_report:
            current_stage_norm = normalize_text(stage)
            committee_report = next(
                (
                    compact_text(item.get("substage", ""), 1500)
                    for _, _, item in dated_proceedings
                    if "informe" in normalize_text(item.get("substage", ""))
                    and "comision" in normalize_text(item.get("substage", ""))
                    and (not current_stage_norm or normalize_text(item.get("stage", "")) == current_stage_norm)
                ),
                "",
            )
        if not committee_report:
            committee_report = pick("informe de comisión", "informe de comision", "informe")
        commission = pick("comisión", "comision")
        if committee_report and (not commission or len(committee_report) > len(commission)):
            commission = committee_report

        author_context = ""
        for marker in ("Autores:", "Autor:", "Mocionantes:", "Patrocinantes:"):
            pos = full_text.lower().find(marker.lower())
            if pos >= 0:
                author_context = full_text[pos: pos + 5000]
                break
        promoters = self._extract_people("\n".join([pick("autor", "autores", "mocionantes"), author_context]))
        matters = unique([pick("materia", "objetivo", "idea matriz"), title])
        scoped_evidence = compact_text(" ".join([
            title,
            " ".join(info_rows),
            " ".join(f"{item.get('date', '')} {item.get('substage', '')} {item.get('stage', '')}" for item in proceedings),
            " ".join(f"{item.get('date', '')} {item.get('title', '')} {item.get('organization', '')}" for item in presentations),
            author_context,
        ]), 90000)

        state = pick("estado")
        stage_norm = normalize_text(stage)
        if not state and any(term in stage_norm for term in ("tramitacion terminada", "ley n°", "ley nº", "publicado")):
            state = "Tramitación terminada"
        elif not state and stage:
            state = "En tramitación"

        terminal_from_law = bool(re.search(r"\bLey\s+N[°ºo.]?\s*\d", " ".join(info_rows), flags=re.IGNORECASE))
        if terminal_from_law and "tramitacion terminada" in normalize_text(" ".join(info_rows)):
            state = "Tramitación terminada"

        metadata = {
            "senado_rows": info_rows[-40:],
            "senado_detail_schema": "5",
            "title_rank": 5,
            "project_type": pick("tipo de proyecto"),
            "refunded": pick("refundido"),
            "committee_report": committee_report,
            "promoters": promoters,
            "matters": matters,
            "official_stage_source": "Senado ficha individual",
            "official_detail_verified": bool(info_table is not None),
            "entry_date_verified": bool(pick("fecha de ingreso")),
            "official_status_verified": bool(info_table is not None and (state or stage)),
            "movement_verified": bool(latest_item),
            "movement_authoritative": bool(table_found["proceedings"]),
            "movement_source": "Senado tabla de tramitación del boletín" if latest_item else "",
            "movement_context_exact": True,
            "senado_proceedings_table_found": table_found["proceedings"],
            "senado_presentations_table_found": table_found["presentations"],
            "field_ranks": {
                "title": 90,
                "entry_date": 90,
                "initiative_type": 90,
                "origin_chamber": 90,
                "state": 120,
                "stage": 125,
                "commission": 125,
                "urgency": 120,
                "latest_movement": 120 if latest_item else 0,
                "latest_movement_date": 120 if latest_item else 0,
            },
        }
        if table_found["proceedings"]:
            metadata["senado_proceedings"] = proceedings[-200:]
        if table_found["presentations"]:
            metadata["commission_presentations"] = presentations[-200:]

        return CandidateProject(
            bulletin=bulletin,
            title=title,
            entry_date=pick("fecha de ingreso"),
            initiative_type=pick("iniciativa"),
            origin_chamber=pick("cámara de origen", "camara de origen"),
            state=state,
            stage=stage,
            commission=commission,
            urgency=pick("urgencia actual", "urgencia"),
            latest_movement=latest,
            latest_movement_date=latest_date,
            source_urls=[url],
            discovered_from=["Senado ficha individual de tramitación"],
            evidence_text=scoped_evidence,
            raw_hash=stable_hash(scoped_evidence),
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
                metadata={"bcn_associated": True, "title_rank": 2, "field_ranks": {"title": 15}},
            )
            projects[bulletin] = project
        return list(projects.values())
