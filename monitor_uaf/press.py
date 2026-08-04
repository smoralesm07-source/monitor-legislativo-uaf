from __future__ import annotations

import email.utils
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote_plus, urlparse

from .http_client import HttpClient
from .utils import compact_text, normalize_text, unique

LOGGER = logging.getLogger(__name__)


class ProjectPressSource:
    """Búsqueda acotada de prensa chilena sobre boletines vigilados.

    Reutiliza la lógica esencial del monitor de prensa: consultas específicas,
    RSS de Google News Chile, lista blanca y deduplicación. La cobertura de
    prensa se conserva como evidencia complementaria y no modifica el estado
    legislativo ni genera por sí sola alertas de cambio normativo.
    """

    GOOGLE_NEWS = "https://news.google.com/rss/search"
    DEFAULT_DOMAINS = {
        "df.cl", "latercera.com", "emol.com", "biobiochile.cl",
        "cooperativa.cl", "elmostrador.cl", "ciperchile.cl", "ciper.cl",
        "interferencia.cl", "ex-ante.cl", "t13.cl", "24horas.cl",
        "cnnchile.com", "adnradio.cl", "pauta.cl", "meganoticias.cl",
        "chvnoticias.cl", "diarioconstitucional.cl", "radioagricultura.cl",
        "hacienda.cl", "senado.cl", "camara.cl", "uaf.cl", "gob.cl",
    }
    SOURCE_NAMES = {
        "diario financiero", "la tercera", "emol", "el mercurio",
        "biobiochile", "radio bío bío", "cooperativa", "el mostrador",
        "ciper", "interferencia", "ex-ante", "t13", "24 horas",
        "cnn chile", "adn radio", "pauta", "meganoticias", "chv noticias",
        "diario constitucional", "senado", "cámara de diputadas y diputados",
        "ministerio de hacienda", "unidad de análisis financiero",
    }

    def __init__(self, client: HttpClient, config: dict[str, Any]) -> None:
        self.client = client
        self.config = config
        configured = config.get("press_allowed_domains", [])
        self.allowed_domains = set(configured) or set(self.DEFAULT_DOMAINS)
        self.window_days = int(config.get("press_window_days", 365))
        self.max_mentions = int(config.get("press_max_mentions_per_project", 8))

    @staticmethod
    def _host(url: str) -> str:
        host = urlparse(url).hostname or ""
        return host.lower().removeprefix("www.")

    def _allowed(self, url: str, source: str) -> bool:
        host = self._host(url)
        if host and any(host == domain or host.endswith("." + domain) for domain in self.allowed_domains):
            return True
        source_norm = normalize_text(source)
        return any(name in source_norm for name in self.SOURCE_NAMES)

    def _queries(self, project: dict[str, Any]) -> list[str]:
        bulletin = project.get("bulletin", "")
        title = compact_text(project.get("title", ""), 220)
        initiative = compact_text(project.get("initiative_name", ""), 160)
        queries = [f'"{bulletin}"'] if bulletin else []
        if title:
            words = [word for word in re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9]+", title) if len(word) > 3]
            phrase = " ".join(words[:12])
            if phrase:
                queries.append(f'"{phrase}" Chile')
        if initiative and normalize_text(initiative) not in normalize_text(title):
            queries.append(f'"{initiative}" proyecto de ley Chile')
        areas = project.get("affected_legal_areas", []) or []
        if bulletin and areas:
            queries.append(f'"{bulletin}" "{compact_text(str(areas[0]), 80)}"')
        return unique(queries)[:4]

    def _parse(self, content: bytes, query: str) -> list[dict[str, Any]]:
        root = ET.fromstring(content)
        cutoff = datetime.now().astimezone() - timedelta(days=self.window_days)
        results: list[dict[str, Any]] = []
        for item in root.findall(".//item"):
            title = compact_text(item.findtext("title"), 500)
            link = compact_text(item.findtext("link"), 3000)
            published_raw = compact_text(item.findtext("pubDate"), 300)
            source_node = item.find("source")
            source = compact_text(source_node.text if source_node is not None else "", 250)
            source_url = compact_text(source_node.get("url", "") if source_node is not None else "", 2000)
            if not title or not link or not self._allowed(source_url or link, source):
                continue
            published_iso = ""
            try:
                parsed = email.utils.parsedate_to_datetime(published_raw)
                if parsed.tzinfo is None:
                    parsed = parsed.astimezone()
                if parsed < cutoff:
                    continue
                published_iso = parsed.date().isoformat()
            except (TypeError, ValueError, OverflowError):
                pass
            clean_title = re.sub(r"\s+-\s+[^-]{2,80}$", "", title).strip()
            results.append({
                "title": clean_title or title,
                "outlet": source or self._host(source_url or link),
                "date": published_iso,
                "url": link,
                "source_url": source_url,
                "query": query,
            })
        return results

    def search_project(self, project: dict[str, Any]) -> list[dict[str, Any]]:
        mentions: list[dict[str, Any]] = []
        for query in self._queries(project):
            params = {
                "q": query,
                "hl": "es-419",
                "gl": "CL",
                "ceid": "CL:es-419",
            }
            result = self.client.get(self.GOOGLE_NEWS, params=params)
            mentions.extend(self._parse(result.content, query))

        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        bulletin = normalize_text(project.get("bulletin", ""))
        title_terms = {
            word for word in normalize_text(project.get("title", "")).split()
            if len(word) >= 6
        }
        for item in sorted(mentions, key=lambda row: row.get("date", ""), reverse=True):
            marker = normalize_text(item.get("title", "")) + "|" + item.get("url", "")
            if marker in seen:
                continue
            seen.add(marker)
            haystack = normalize_text(" ".join([item.get("title", ""), item.get("query", "")]))
            title_overlap = len(title_terms.intersection(haystack.split()))
            if bulletin not in haystack and title_overlap < 2:
                continue
            output.append(item)
            if len(output) >= self.max_mentions:
                break
        return output

    def enrich(self, projects: dict[str, dict[str, Any]]) -> tuple[int, int]:
        searched = 0
        found = 0
        max_projects = int(self.config.get("press_max_projects_per_run", 20))
        ordered = sorted(
            projects.values(),
            key=lambda item: (
                int(item.get("relevance_level", 9)) == 1,
                int(item.get("pertinence_score", item.get("priority_score", 0)) or 0),
            ),
            reverse=True,
        )[:max_projects]
        for project in ordered:
            searched += 1
            previous = ((project.get("metadata") or {}).get("press_mentions") or [])
            try:
                mentions = self.search_project(project)
                metadata = project.setdefault("metadata", {})
                metadata["press_mentions"] = mentions if mentions else previous
                metadata["press_checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
                found += len(mentions)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("No se pudo consultar prensa para %s: %s", project.get("bulletin"), exc)
                project.setdefault("metadata", {})["press_mentions"] = previous
        return searched, found
