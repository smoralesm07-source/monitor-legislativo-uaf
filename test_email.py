"""Envía un correo de prueba usando las mismas variables de entorno del monitor."""
from monitor_uaf.notifier import send_alert_email

alert = {
    "id": "prueba",
    "kind": "test",
    "bulletin": "15975-25",
    "title": "Correo de prueba del Monitor Legislativo UAF",
    "severity": "Alta",
    "priority_score": 90,
    "relevance_level": 1,
    "relevance_label": "Prueba de configuración SMTP",
    "changes": [{"field": "prueba", "before": "", "after": "La configuración de correo funciona correctamente."}],
    "top_impacts": [{"name": "Responsabilidades UAF"}],
    "decisions": ["No se requiere acción; este mensaje es solo una prueba."],
    "source_urls": ["https://www.senado.cl/transparencia/datos-abiertos-legislativos"],
}

sent, message = send_alert_email([alert], {"finished_at": "prueba manual"})
print(sent, message)
