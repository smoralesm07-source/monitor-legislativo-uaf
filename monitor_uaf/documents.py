from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import CandidateProject
from .utils import compact_text, normalize_text, parse_legislative_date, stable_hash, unique

LOGGER = logging.getLogger(__name__)


class OfficialProjectDocumentSource:
    """Descarga, lee y reseña documentos oficiales asociados a un boletín.

    La fuente utiliza dos entradas complementarias:

    * enlaces publicados en la ficha de la Cámara;
    * enlaces de la columna ``Documentos`` y de presentaciones de la ficha del
      Senado, previamente extraídos por :class:`SenadoSource`.

    Las reseñas son extractivas y deterministas: no dependen de una API externa
    ni inventan contenido. Se seleccionan oraciones del documento que describen
    su objeto, las modificaciones propuestas y las referencias LA/FT o UAF.
    """

    PAGE_URL = "https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"
    DOCUMENT_HINTS = (
        "indicacion", "informe", "oficio", "comparado", "texto", "comision",
        "presentacion", "mensaje", "mocion", "proyecto", "documento", "docto",
    )
    SUMMARY_TERMS = (
        "modifica", "incorpora", "agrega", "sustituye", "reemplaza", "suprime",
        "propone", "objetivo", "finalidad", "artículo", "articulo", "indicación",
        "indicacion", "informe", "acuerda", "aprueba", "rechaza", "unidad de análisis financiero",
        "unidad de analisis financiero", "uaf", "ley 19.913", "lavado de activos",
        "operación sospechosa", "operacion sospechosa", "sujeto obligado",
        "secreto bancario", "delito precedente", "delito base", "remesas",
    )

    def __init__(self, client: HttpClient, config: dict[str, Any]) -> None:
        self.client = client
        self.config = config
        self.max_documents = int(config.get("official_document_scan_max_documents_per_project", 8))
        self.max_chars = int(config.get("official_document_scan_max_chars_per_project", 50000))
        self.summary_max_chars = int(config.get("official_document_summary_max_chars", 850))
        direct = list(config.get("direct_terms", []))
        secondary = [
            term
            for rule in config.get("secondary_topics", {}).values()
            for term in rule.get("terms", [])
        ]
        self.watch_terms = unique(direct + secondary + [
            "unidad de análisis financiero", "unidad de analisis financiero", "uaf",
            "operación sospechosa", "operacion sospechosa", "reporte de operaciones sospechosas",
            "ley 19.913", "ley n° 19.913", "ley n.º 19.913",
        ])

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        return compact_text(" ".join(page.extract_text() or "" for page in reader.pages), 120000)

    @staticmethod
    def _extract_html(content: bytes) -> str:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer"]):
            tag.decompose()
        return compact_text(soup.get_text(" ", strip=True), 120000)

    @staticmethod
    def _extract_docx(content: bytes) -> str:
        """Extrae texto de DOCX sin sumar una dependencia adicional."""
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            raw = archive.read("word/document.xml")
        root = ET.fromstring(raw)
        chunks = [node.text for node in root.iter() if node.tag.endswith("}t") and node.text]
        return compact_text(" ".join(chunks), 120000)

    @staticmethod
    def _extract_plain(content: bytes) -> str:
        for encoding in ("utf-8", "latin-1"):
            try:
                return compact_text(content.decode(encoding), 120000)
            except UnicodeDecodeError:
                continue
        return ""

    def _extract_text(self, content: bytes, content_type: str, url: str) -> str:
        ctype = normalize_text(content_type)
        path = urlparse(url).path.lower()
        try:
            # El Content-Type real tiene prioridad. Algunas fichas oficiales usan
            # URLs que terminan en .pdf pero responden HTML de validación/error;
            # decidir primero por extensión produciría extracciones falsas.
            if "html" in ctype:
                return self._extract_html(content)
            if "pdf" in ctype:
                return self._extract_pdf(content)
            if "wordprocessingml" in ctype:
                return self._extract_docx(content)
            if "text/" in ctype:
                return self._extract_plain(content)

            # Solo cuando el servidor omite un tipo útil se usa la extensión.
            if path.endswith((".htm", ".html", ".aspx", ".php")):
                return self._extract_html(content)
            if path.endswith(".pdf"):
                return self._extract_pdf(content)
            if path.endswith(".docx"):
                return self._extract_docx(content)
            if path.endswith((".txt", ".csv")):
                return self._extract_plain(content)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("No se pudo extraer documento %s: %s", url, exc)
        return ""

    @staticmethod
    def _document_kind(label: str, url: str) -> str:
        norm = normalize_text(label + " " + url)
        rules = (
            (("indicacion",), "Indicaciones"),
            (("informe de comision mixta", "comision mixta"), "Informe de Comisión Mixta"),
            (("informe",), "Informe de comisión"),
            (("mocion", "mensaje"), "Mensaje o moción"),
            (("oficio",), "Oficio"),
            (("comparado",), "Texto comparado"),
            (("presentacion", "ppt", "exposicion"), "Presentación ante comisión"),
        )
        for terms, kind in rules:
            if any(term in norm for term in terms):
                return kind
        return "Documento legislativo"

    def _candidate_links(self, soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            href = link.get("href", "").strip()
            label = compact_text(link.get_text(" ", strip=True), 350)
            url = urljoin(base_url, href)
            norm = normalize_text(label + " " + href)
            if not url.startswith("http") or url in seen:
                continue
            if not (
                "verdoc" in norm or "documento" in norm or "oficiopley" in norm
                or "getdocto" in norm or "microservicio-documentos" in norm
                or any(hint in norm for hint in self.DOCUMENT_HINTS)
            ):
                continue
            seen.add(url)
            rows.append({
                "label": label or "Documento legislativo",
                "url": url,
                "date": "",
                "context": "Cámara: documentos de tramitación",
            })
        return rows

    @staticmethod
    def _linked_documents(project: CandidateProject) -> list[dict[str, str]]:
        metadata = project.metadata or {}
        output: list[dict[str, str]] = []

        def add_documents(rows: Any, context: str) -> None:
            if not isinstance(rows, list):
                return
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_date = str(row.get("date", "") or "")
                for document in row.get("documents", []) or []:
                    if not isinstance(document, dict) or not document.get("url"):
                        continue
                    output.append({
                        "label": compact_text(document.get("label") or context, 350),
                        "url": str(document["url"]),
                        "date": row_date,
                        "context": context,
                    })

        add_documents(metadata.get("senado_proceedings"), "Senado: tramitación")
        add_documents(metadata.get("camara_proceedings"), "Cámara: tramitación")
        add_documents(metadata.get("commission_presentations"), "Presentación ante comisión")
        for item in metadata.get("official_documents_matched", []) or []:
            if isinstance(item, dict) and (item.get("resolved_url") or item.get("url")):
                output.append({
                    "label": compact_text(item.get("label") or "Documento oficial", 350),
                    "url": str(item.get("resolved_url") or item.get("url")),
                    "date": str(item.get("date", "") or ""),
                    "context": str(item.get("context", "Documentos oficiales") or "Documentos oficiales"),
                })
        return output

    @staticmethod
    def _sentence_candidates(text: str) -> list[str]:
        cleaned = compact_text(text, 120000)
        parts = re.split(r"(?<=[.!?;])\s+(?=[A-ZÁÉÍÓÚÑ0-9])|\n+", cleaned)
        output: list[str] = []
        for sentence in parts:
            sentence = compact_text(sentence, 700)
            norm = normalize_text(sentence)
            if len(sentence) < 45 or len(sentence) > 650:
                continue
            if any(noise in norm for noise in (
                "senado de la republica", "camara de diputadas", "javascript",
                "volver proyecto de ley", "biblioteca del congreso nacional",
            )) and len(sentence) < 150:
                continue
            output.append(sentence)
        return output

    def _summary(self, text: str, project: CandidateProject) -> str:
        sentences = self._sentence_candidates(text)
        if not sentences:
            return "El documento no entregó texto suficiente para construir una reseña automática."

        title_tokens = {
            token for token in re.findall(r"[a-záéíóúñ]{5,}", normalize_text(project.title))
            if token not in {"modifica", "proyecto", "establece", "diversos", "cuerpos", "legales"}
        }
        scored: list[tuple[float, int, str]] = []
        for index, sentence in enumerate(sentences):
            norm = normalize_text(sentence)
            score = 0.0
            score += sum(3.0 for term in self.SUMMARY_TERMS if normalize_text(term) in norm)
            score += sum(1.2 for token in title_tokens if token in norm)
            if re.search(r"art[ií]culo\s+(?:único|\d+)", sentence, flags=re.IGNORECASE):
                score += 3
            if 90 <= len(sentence) <= 380:
                score += 1.5
            if index < 12:
                score += 0.6
            if score > 0:
                scored.append((score, index, sentence))

        if not scored:
            selected = sentences[:2]
        else:
            scored.sort(key=lambda item: (-item[0], item[1]))
            selected: list[str] = []
            normalized_selected: list[str] = []
            for _, _, sentence in scored:
                norm = normalize_text(sentence)
                if any(norm in prior or prior in norm for prior in normalized_selected):
                    continue
                selected.append(sentence)
                normalized_selected.append(norm)
                if len(selected) >= 3:
                    break
            selected.sort(key=lambda sentence: sentences.index(sentence))

        summary = " ".join(selected)
        return compact_text(summary, self.summary_max_chars)

    @staticmethod
    def _sort_key(item: dict[str, Any]) -> tuple[date, int, str]:
        parsed = parse_legislative_date(str(item.get("date", "") or "")) or date.min
        kind = normalize_text(str(item.get("kind", "") or item.get("label", "")))
        kind_rank = 3 if "informe" in kind else 2 if "indicacion" in kind else 1
        return parsed, kind_rank, str(item.get("url", ""))

    def scan(self, project: CandidateProject, *, include_all: bool | None = None) -> CandidateProject:
        """Revisa documentos y devuelve una ficha fusionable.

        ``include_all=False`` se utiliza en descubrimiento: solo conserva
        documentos que contienen señales LA/FT. Una vez que el proyecto ya fue
        clasificado o seguido, ``include_all=True`` permite reseñar también el
        informe o moción que explica la materia general.
        """
        bulletin = project.bulletin
        page_url = self.PAGE_URL.format(bulletin=bulletin)
        page_links: list[dict[str, str]] = []
        page_text = ""
        try:
            page = self.client.get(page_url)
            soup = BeautifulSoup(page.text, "html.parser")
            page_text = self._extract_html(page.content)
            page_links = self._candidate_links(soup, page.url)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("No se pudo abrir la ficha Cámara de %s para documentos: %s", bulletin, exc)

        linked = self._linked_documents(project)
        combined = linked + page_links
        deduped: dict[str, dict[str, str]] = {}
        for item in combined:
            url = item.get("url", "")
            if not url:
                continue
            previous = deduped.get(url, {})
            merged = {**previous, **{key: value for key, value in item.items() if value}}
            deduped[url] = merged

        candidates = list(deduped.values())
        candidates.sort(
            key=lambda item: (
                parse_legislative_date(item.get("date", "")) or date.min,
                1 if "senado" in normalize_text(item.get("context", "")) else 0,
            ),
            reverse=True,
        )

        if include_all is None:
            title_evidence = normalize_text(" ".join([project.title, project.evidence_text]))
            include_all = any(normalize_text(term) in title_evidence for term in self.watch_terms)

        previous_reviews = {
            item.get("url"): item
            for item in (project.metadata or {}).get("official_document_reviews", []) or []
            if isinstance(item, dict) and item.get("url")
        }

        reviews: list[dict[str, Any]] = []
        evidence_parts = [page_text]
        direct_hits: list[str] = []
        fetched = 0
        for item in candidates:
            if len(reviews) >= self.max_documents:
                break
            url = item["url"]
            if url in previous_reviews:
                cached = dict(previous_reviews[url])
                cached.update({key: value for key, value in item.items() if value})
                reviews.append(cached)
                direct_hits.extend(cached.get("hits", []) or [])
                continue
            try:
                result = self.client.get(url)
                fetched += 1
                text = self._extract_text(result.content, result.content_type, result.url)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("No se pudo revisar %s para %s: %s", url, bulletin, exc)
                continue
            if not text:
                continue
            normalized = normalize_text(text)
            hits = unique(term for term in self.watch_terms if normalize_text(term) in normalized)
            if not hits and not include_all:
                continue
            summary = self._summary(text, project)
            kind = self._document_kind(item.get("label", ""), result.url)
            review = {
                "label": item.get("label") or kind,
                "kind": kind,
                "url": result.url,
                "date": item.get("date", ""),
                "context": item.get("context", "Documento oficial"),
                "content_type": result.content_type,
                "hits": hits[:20],
                "summary": summary,
                "text_hash": stable_hash(text),
            }
            reviews.append(review)
            direct_hits.extend(hits)
            evidence_parts.append(compact_text(text, 12000))

        reviews.sort(key=self._sort_key, reverse=True)
        documentary_summary = " ".join(
            f"{item.get('kind', 'Documento')}: {item.get('summary', '')}"
            for item in reviews[:3]
            if item.get("summary")
        )
        evidence = compact_text(" ".join(evidence_parts), self.max_chars)
        source_urls = unique([page_url] + [item.get("url", "") for item in reviews])

        return CandidateProject(
            bulletin=bulletin,
            source_urls=source_urls,
            discovered_from=["Documentos oficiales de tramitación"],
            evidence_text=evidence,
            raw_hash=stable_hash({"evidence": evidence, "reviews": reviews}),
            metadata={
                "official_documents_scanned": len(candidates),
                "official_documents_fetched": fetched,
                "official_documents_matched": reviews,
                "official_document_reviews": reviews,
                "official_document_hits": unique(direct_hits)[:50],
                "documentary_summary": compact_text(documentary_summary, 2200),
                "official_documents_schema": "2",
            },
        )
