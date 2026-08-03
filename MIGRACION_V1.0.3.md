# Migración a v1.0.3 — depuración de proyectos antiguos

Esta versión corrige la incorporación de boletines históricos provenientes del catálogo BCN.

## Archivos a reemplazar

- `monitor_uaf/analysis.py`
- `monitor_uaf/pipeline.py`
- `monitor_uaf/render.py`
- `monitor_uaf/sources.py`
- `monitor_uaf/utils.py`
- `config/monitor_config.json`
- `docs/index.html`
- `tests/test_monitor.py`
- `README.md`
- `GUIA_INSTALACION_GITHUB.md`

No reemplaces manualmente `data/state.json` ni el historial de alertas de tu repositorio existente. La próxima ejecución depurará automáticamente la cartera guardada.

## Activación

1. Carga los archivos respetando sus carpetas.
2. Confirma el commit en `main`.
3. Ejecuta `Actions → Monitor legislativo UAF → Run workflow`.
4. Revisa `data/status.json`:
   - `projects_monitored`: iniciativas vigentes publicadas;
   - `excluded_count`: candidatos antiguos o terminados omitidos;
   - `exclusion_counts`: motivos de descarte.
5. Comprueba GitHub Pages.

No se requieren Secrets nuevos.
