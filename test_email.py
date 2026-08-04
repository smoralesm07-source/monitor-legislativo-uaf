"""Prueba SMTP protegida.

Este archivo NO envía correo por defecto. Solo lo hace cuando se ejecuta
manualmente con ALLOW_TEST_EMAIL=true y TEST_EMAIL_CONFIRM=ENVIAR.
"""
from monitor_uaf.notifier import send_test_email

alert = {
    "bulletin": "15975-25",
    "title": "Correo de prueba del Monitor Legislativo UAF",
    "severity": "Alta",
    "priority_score": 90,
    "relevance_level": 1,
    "relevance_label": "Prueba manual de configuración SMTP",
    "linkage_summary": "Este mensaje no corresponde a una alerta legislativa real.",
    "changes": [{"field": "prueba", "before": "", "after": "La configuración SMTP funciona."}],
    "top_impacts": [{"name": "Responsabilidades UAF"}],
    "decisions": ["No se requiere acción; este mensaje es solo una prueba manual."],
    "source_urls": ["https://www.senado.cl/transparencia/datos-abiertos-legislativos"],
}

sent, message = send_test_email(alert, {"finished_at": "prueba manual"})
print(sent, message)
