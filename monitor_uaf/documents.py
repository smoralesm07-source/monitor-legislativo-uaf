from __future__ import annotations

import io
import logging
import re
from datetime import timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader

from .http_client import HttpClient
from .models import CandidateProject
from .utils import compact_text, local_now, normalize_text, stable_hash, unique

LOGGER = logging.getLogger(__name__)


class OfficialProjectDocumentSource:
    """Revisa documentos oficiales posteriores al ingreso del proyecto.

    Esta capa busca menciones que pueden aparecer recién en indicaciones,
    informes u oficios. Es especialmente importante para proyectos amplios cuyo
    título no contiene términos LA/FT, pero que durante su tramitación incorporan
    obligaciones, reportes o colaboración con la UAF.
    """

    PAGE_URL = "https://www.camara.cl/legislacion/proyectosdeley/tramitacion.aspx?prmBOLETIN={bulletin}"
    DOCUMENT_HINTS = (
        "indicacion", "informe", "oficio", "comparado", "texto", "comision",
        "presentacion", "mensaje", "mocion", "proyecto",
    )

    def __init__(self, client: HttpClient, config: dict[str, Any]) -> None:
        self.client = client
        self.config = config
        self.max_documents = int(config.get("official_document_scan_max_documents_per_project", 6))
        self.max_chars = int(config.get("official_document_scan_max_chars_per_project", 45000))
        direct = list(config.get("direct_terms", []))
        secondary = [term for rule in config.get("secondary_topics", {}).values() for term in rule.get("terms", [])]
        self.watch_terms = unique(direct + secondary + [
            "unidad de análisis financiero", "unidad de analisis financiero", "uaf",
            "operación sospechosa", "operacion sospechosa", "reporte de operaciones sospechosas",
            "ley 19.913", "ley n° 19.913", "ley n.º 19.913",
        ])

    @staticmethod
    def _extract_pdf(content: bytes) -> str:
        reader = PdfReader(io.BytesIO(content))
        return compact_text(" ".join(page.extract_text() or "" for page in reader.pages), 80000)

    @staticmethod
    def _extract_html(content: bytes) -> str:
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return compact_text(soup.get_text(" ", strip=True), 80000)

    def _extract_text(self, content: bytes, content_type: str, url: str) -> str:
        ctype = normalize_text(content_type)
        path = urlparse(url).path.lower()
        try:
            if "pdf" in ctype or path.endswith(".pdf"):
                return self._extract_pdf(content)
            if "html" in ctype or path.endswith((".htm", ".html", ".aspx", ".php")):
                return self._extract_html(content)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("No se pudo extraer documento %s: %s", url, exc)
        return ""

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
                or any(hint in norm for hint in self.DOCUMENT_HINTS)
            ):
                continue
            seen.add(url)
            rows.append({"label": label or "Documento legislativo", "url": url})
        # Los enlaces más recientes suelen quedar al final de las tablas.
        return rows[-self.max_documents:]

    def scan(self, project: CandidateProject) -> CandidateProject:
        bulletin = project.bulletin
        page_url = self.PAGE_URL.format(bulletin=bulletin)
        page = self.client.get(page_url)
        soup = BeautifulSoup(page.text, "html.parser")
        page_text = self._extract_html(page.content)
        documents = self._candidate_links(soup, page.url)

        evidence_parts = [page_text]
        matched_documents: list[dict[str, Any]] = []
        direct_hits: list[str] = []
        for item in documents:
            try:
                result = self.client.get(item["url"])
                text = self._extract_text(result.content, result.content_type, result.url)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("No se pudo revisar %s para %s: %s", item["url"], bulletin, exc)
                continue
            if not text:
                continue
            normalized = normalize_text(text)
            hits = unique(term for term in self.watch_terms if normalize_text(term) in normalized)
            if not hits:
                continue
            evidence_parts.append(text)
            direct_hits.extend(hits)
            matched_documents.append({
                **item,
                "resolved_url": result.url,
                "content_type": result.content_type,
                "hits": hits[:20],
                "text_hash": stable_hash(text),
            })

        evidence = compact_text(" ".join(evidence_parts), self.max_chars)
        return CandidateProject(
            bulletin=bulletin,
            source_urls=[page_url] + [item.get("resolved_url") or item["url"] for item in matched_documents],
            discovered_from=["Documentos oficiales de tramitación"],
            evidence_text=evidence,
            raw_hash=stable_hash(evidence),
            metadata={
                "official_documents_scanned": len(documents),
                "official_documents_matched": matched_documents,
                "official_document_hits": unique(direct_hits)[:50],
                "official_documents_schema": "1",
            },
        )
