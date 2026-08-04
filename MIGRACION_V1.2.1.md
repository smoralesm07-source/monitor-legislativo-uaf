# Migración a v1.2.1

Esta versión corrige el problema de dashboard en cero.

## Reemplazar

Suba todos los archivos incluidos en el ZIP de actualización, respetando sus rutas.

## Agregar

- `data/bootstrap_projects.json`
- `validate_monitor_output.py`
- `tests/fixtures/camara_web_detail.html`

## Conservar

No borre `data/history.jsonl`, `data/alerts.json` ni `data/discovery_index.json`.
El motor utilizará `state.json` cuando contenga un portafolio válido; si quedó vacío,
restaurará la línea base desde `bootstrap_projects.json` y volverá a enriquecerla.

## Ejecutar

`Actions → Monitor legislativo UAF → Run workflow`.

El resultado correcto debe incluir al menos un proyecto. Si las fuentes oficiales están
bloqueadas, el dashboard mostrará el último estado válido y `data/status.json` indicará
`continuity_fallback_used: true`.
