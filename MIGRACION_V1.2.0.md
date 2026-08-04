# Migración a v1.2.0

Esta versión corrige la reincorporación de boletines históricos, las etapas y las fechas del último antecedente legislativo.

## Archivos que deben reemplazarse

```text
monitor_uaf/analysis.py
monitor_uaf/documents.py
monitor_uaf/models.py
monitor_uaf/pipeline.py
monitor_uaf/render.py
monitor_uaf/sources.py
monitor_uaf/utils.py
config/monitor_config.json
tests/test_monitor.py
tests/fixtures/senado_16808_detail.html
README.md
MIGRACION_V1.2.0.md
```

También puede reemplazar `docs/index.html` para ver inmediatamente la vista previa corregida. La siguiente ejecución lo regenerará.

## Archivos que no deben reemplazarse

Conserve el historial propio del repositorio:

```text
data/state.json
data/alerts.json
data/history.jsonl
data/discovery_index.json
```

El workflow depurará automáticamente de esos archivos el boletín 2975-07 y cualquier otro registro que no supere la validación de vigencia.

## Ejecución

1. Confirme los cambios directamente en `main`.
2. Abra `Actions → Monitor legislativo UAF`.
3. Presione `Run workflow`.
4. Verifique que `pytest -q` termine con 31 pruebas aprobadas.
5. Revise `data/status.json`: los campos `stages_verified` y `movements_verified` deben ser mayores que cero.
6. Confirme que `docs/index.html` no contenga `2975-07`.

No se requieren nuevos Secrets.
