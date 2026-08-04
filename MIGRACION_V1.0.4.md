# Migración a v1.0.4 — ficha legislativa ampliada

## Objetivo

Esta versión reemplaza los cuadros de impacto institucional y decisiones sugeridas de la ficha individual por información legislativa oficial más detallada:

- antecedentes generales del proyecto;
- cronología de tramitación;
- presentaciones ante comisión;
- enlaces a documentos;
- fuentes y auditoría.

## Archivos que debes reemplazar

```text
monitor_uaf/sources.py
monitor_uaf/analysis.py
monitor_uaf/render.py
config/monitor_config.json
docs/index.html
tests/test_monitor.py
tests/fixtures/senado_detail.html
README.md
GUIA_INSTALACION_GITHUB.md
MIGRACION_V1.0.4.md
```

## Archivos que no debes reemplazar

Conserva los archivos históricos de tu repositorio:

```text
data/state.json
data/alerts.json
data/history.jsonl
data/discovery_index.json
data/projects.json
data/status.json
```

## Ejecución posterior

Después de subir los cambios, ejecuta manualmente:

```text
Actions → Monitor legislativo UAF → Run workflow
```

No se requieren nuevos Secrets. La primera ejecución con v1.0.4 guarda como línea base las tablas recién extraídas y evita enviar correos masivos por ese enriquecimiento inicial. Desde las ejecuciones posteriores, una fila nueva o modificada en la tramitación o en las presentaciones ante comisión genera una alerta.
