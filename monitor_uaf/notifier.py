from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage
from typing import Any

from .config import env_bool


def send_alert_email(alerts: list[dict[str, Any]], status: dict[str, Any]) -> tuple[bool, str]:
    if not alerts:
        return False, "Sin alertas nuevas"
    if not env_bool("MONITOR_EMAIL_ACTIVE", False):
        return False, "Correo desactivado"

    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    recipients = [item.strip() for item in os.getenv("MAIL_TO", "").split(",") if item.strip()]
    if not user or not password or not recipients:
        return False, "Faltan SMTP_USER, SMTP_PASSWORD o MAIL_TO"

    host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    from_name = os.getenv("MAIL_FROM_NAME", "Monitor Legislativo UAF").strip()
    dashboard_url = os.getenv("PUBLIC_DASHBOARD_URL", "").strip()

    critical = sum(1 for item in alerts if item["severity"] == "Crítica")
    subject = f"[Monitor Legislativo UAF] {len(alerts)} alerta(s) nueva(s)"
    if critical:
        subject = f"[ALERTA CRÍTICA UAF] {critical} cambio(s) crítico(s) y {len(alerts)} alerta(s)"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{user}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(build_plain_text(alerts, status, dashboard_url))
    msg.add_alternative(build_html(alerts, status, dashboard_url), subtype="html")

    with smtplib.SMTP(host, port, timeout=40) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)
    return True, f"Correo enviado a {len(recipients)} destinatario(s)"


def send_test_email(status: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Envía una alerta SMTP controlada para validar la configuración.

    La función existe como interfaz estable para ``test_email.py`` y para el
    workflow manual de prueba. No se ejecuta durante la importación del módulo.
    """
    test_alert = {
        "id": "smtp-test",
        "kind": "test",
        "bulletin": "PRUEBA",
        "title": "Correo de prueba del Monitor Legislativo UAF",
        "severity": "Alta",
        "priority_score": 0,
        "relevance_level": 0,
        "relevance_label": "Prueba de configuración SMTP",
        "changes": [
            {
                "field": "Configuración",
                "before": "",
                "after": "La configuración de correo funciona correctamente.",
            }
        ],
        "top_impacts": [],
        "decisions": [],
        "source_urls": [],
    }
    effective_status = status or {"finished_at": "prueba manual"}
    return send_alert_email([test_alert], effective_status)


def build_plain_text(alerts: list[dict[str, Any]], status: dict[str, Any], dashboard_url: str) -> str:
    lines = [
        "MONITOR LEGISLATIVO UAF",
        f"Ejecución: {status.get('finished_at', '')}",
        f"Alertas nuevas: {len(alerts)}",
        "",
    ]
    for alert in alerts:
        lines.extend([
            f"[{alert['severity']}] Boletín {alert['bulletin']} — {alert['title']}",
            alert.get("relevance_label", ""),
        ])
        for change in alert.get("changes", []):
            lines.append(f"- {change['field']}: {change['after']}")
        for decision in alert.get("decisions", [])[:3]:
            lines.append(f"  Decisión sugerida: {decision}")
        if alert.get("source_urls"):
            lines.append(f"  Fuente: {alert['source_urls'][0]}")
        lines.append("")
    if dashboard_url:
        lines.append(f"Dashboard: {dashboard_url}")
    return "\n".join(lines)


def build_html(alerts: list[dict[str, Any]], status: dict[str, Any], dashboard_url: str) -> str:
    cards = []
    colors = {"Crítica": "#b42318", "Alta": "#c85f00", "Media": "#8b6b00"}
    for alert in alerts:
        changes = "".join(
            f"<li><b>{html.escape(change['field'])}:</b> {html.escape(change['after'] or 'Sin detalle')}</li>"
            for change in alert.get("changes", [])
        )
        impacts = ", ".join(html.escape(item["name"]) for item in alert.get("top_impacts", [])[:4])
        decisions = "".join(f"<li>{html.escape(item)}</li>" for item in alert.get("decisions", [])[:3])
        source = alert.get("source_urls", [""])[0] if alert.get("source_urls") else ""
        source_link = f'<a href="{html.escape(source)}">Abrir fuente oficial</a>' if source else ""
        cards.append(f"""
        <div style="border:1px solid #dce4eb;border-left:5px solid {colors.get(alert['severity'], '#356b8c')};border-radius:10px;padding:16px;margin:14px 0;background:#fff">
          <div style="font-size:12px;font-weight:800;color:{colors.get(alert['severity'], '#356b8c')}">{html.escape(alert['severity'])} · BOLETÍN {html.escape(alert['bulletin'])}</div>
          <h3 style="margin:6px 0 8px;font-size:17px;color:#10263a">{html.escape(alert['title'])}</h3>
          <div style="font-size:13px;color:#4c6071">{html.escape(alert.get('relevance_label',''))}</div>
          <ul style="font-size:13px;line-height:1.5;color:#263e52">{changes}</ul>
          <div style="font-size:12px"><b>Impactos:</b> {impacts or 'Por revisar'}</div>
          <div style="font-size:12px;margin-top:8px"><b>Decisiones sugeridas:</b><ol>{decisions}</ol></div>
          <div style="font-size:12px">{source_link}</div>
        </div>""")
    dashboard_button = ""
    if dashboard_url:
        dashboard_button = f'<p><a href="{html.escape(dashboard_url)}" style="background:#176b9b;color:white;padding:10px 14px;border-radius:7px;text-decoration:none;font-weight:700">Abrir dashboard</a></p>'
    return f"""
    <html><body style="margin:0;background:#f2f5f8;font-family:Arial,sans-serif;color:#14283a">
      <div style="max-width:760px;margin:auto;padding:22px">
        <div style="background:#0d2941;color:#fff;padding:20px;border-radius:12px">
          <div style="font-size:12px;letter-spacing:1px">OBSERVATORIO LEGISLATIVO ESTRATÉGICO</div>
          <h2 style="margin:6px 0">Nuevas alertas con impacto UAF</h2>
          <div style="font-size:12px;color:#c8d9e5">Ejecución {html.escape(status.get('finished_at',''))}</div>
        </div>
        {''.join(cards)}
        {dashboard_button}
        <p style="font-size:11px;color:#6c7d8a">El análisis de impacto es una clasificación automatizada que debe ser validada jurídicamente antes de adoptar decisiones institucionales.</p>
      </div>
    </body></html>"""
