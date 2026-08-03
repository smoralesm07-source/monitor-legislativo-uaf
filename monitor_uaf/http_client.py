from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

LOGGER = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str

    @property
    def text(self) -> str:
        encoding = requests.utils.get_encoding_from_headers({"content-type": self.content_type}) or "utf-8"
        return self.content.decode(encoding, errors="replace")


class HttpClient:
    def __init__(self, timeout: int = 35, retries: int = 3) -> None:
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "MonitorLegislativoUAF/1.0 (+https://github.com/)",
            "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
        })

    def get(self, url: str, params: dict | None = None) -> FetchResult:
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                response.raise_for_status()
                return FetchResult(
                    url=response.url,
                    status_code=response.status_code,
                    content=response.content,
                    content_type=response.headers.get("content-type", ""),
                )
            except requests.RequestException as exc:
                last_error = exc
                LOGGER.warning("Fallo HTTP %s/%s en %s: %s", attempt, self.retries, url, exc)
                if attempt < self.retries:
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"No fue posible obtener {url}: {last_error}")
