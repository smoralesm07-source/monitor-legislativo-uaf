#!/usr/bin/env python3
from monitor_uaf.config import DATA_DIR
from monitor_uaf.utils import read_json

projects = read_json(DATA_DIR / "projects.json", [])
status = read_json(DATA_DIR / "status.json", {})
if not isinstance(projects, list) or not projects:
    raise SystemExit(
        "El monitor intentó generar un portafolio vacío. Se detiene antes de publicar para conservar el último dashboard válido."
    )
print(
    f"Salida válida: {len(projects)} proyecto(s); "
    f"respaldo de continuidad={bool(status.get('continuity_fallback_used'))}."
)
