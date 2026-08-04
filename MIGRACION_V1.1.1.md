# Migración a v1.1.1

Reemplace o agregue:

- `monitor_uaf/analysis.py`
- `monitor_uaf/documents.py` (nuevo)
- `monitor_uaf/pipeline.py`
- `monitor_uaf/press.py`
- `monitor_uaf/render.py`
- `monitor_uaf/sources.py`
- `config/monitor_config.json`
- `docs/index.html`
- `tests/test_monitor.py`
- `tests/fixtures/camara_documents_18216.html`
- `tests/fixtures/indications_18216.html`
- `README.md`

No reemplace los archivos históricos de `data/` en su repositorio. La próxima ejecución reconstruirá el dashboard y conservará las alertas acumuladas.

No se requieren nuevos Secrets. La búsqueda de prensa y documentos oficiales utiliza fuentes públicas.
