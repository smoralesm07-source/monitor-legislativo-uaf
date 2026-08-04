from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage
from typing import Any

from .config import env_bool

PRODUCTION_ALERT_KINDS = frozenset({"new_project", "project_changed", "project_closed"})


def production_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Devuelve únicamente alertas legislativas reales.

    Las alertas de prueba o de diagnóstico nunca pueden salir por el canal
    productivo, aunque un script auxiliar las entregue accidentalmente.
    """
    return [
        alert
        for alert in alerts
        if alert.get("kind") in PRODUCTION_ALERT_KINDS and alert.get("id")
    ]


def filter_unsent_alerts(
    alerts: list[dict[str, Any]],
    email_log: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Excluye alertas ya enviadas, usando su identificador estable."""
    sent_ids = set((email_log or {}).get("sent_alert_ids", []))
    return [alert for alert in production_alerts(alerts) if alert["id"] not in sent_ids]


def updated_email_log(
    email_log: dict[str, Any] | None,
    sent_alerts: list[dict[str, Any]],
    sent_at: str,
    *,
    max_ids: int = 2000,
) -> dict[str, Any]:
    """Actualiza el registro persistente solo después de un envío exitoso."""
    existing = list((email_log or {}).get("sent_alert_ids", []))
    new_ids = [alert["id"] for alert in production_alerts(sent_alerts)]
    combined: list[str] = []
    seen: set[str] = set()
    # Los IDs nuevos quedan primero para conservar los más recientes al recortar.
    for alert_id in new_ids + existing:
        if alert_id and alert_id not in seen:
            seen.add(alert_id)
            combined.append(alert_id)
    return {
        "last_sent_at": sent_at,
        "last_sent_count": len(new_ids),
        "sent_alert_ids": combined[:max(1, int(max_ids))],
    }


def send_alert_email(alerts: list[dict[str, Any]], status: dict[str, Any]) -> tuple[bool, str]:
    alerts = production_alerts(alerts)
    if not alerts:
        return False, "Sin alertas legislativas nuevas"
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
    subject = f"[Monitor Legislativo UAF] {len(alerts)} alerta(s) legislativa(s) nueva(s)"
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


def send_test_email(alert: dict[str, Any], status: dict[str, Any]) -> tuple[bool, str]:
    """Envío de prueba protegido por doble confirmación explícita.

    No se utiliza en el workflow diario. Requiere simultáneamente:
    ALLOW_TEST_EMAIL=true y TEST_EMAIL_CONFIRM=ENVIAR.
    """
    if not env_bool("ALLOW_TEST_EMAIL", False):
        return False, "Correo de prueba bloqueado: ALLOW_TEST_EMAIL no está activo"
    if os.getenv("TEST_EMAIL_CONFIRM", "").strip().upper() != "ENVIAR":
        return False, "Correo de prueba bloqueado: falta TEST_EMAIL_CONFIRM=ENVIAR"

    test_alert = dict(alert)
    test_alert["kind"] = "new_project"
    test_alert["id"] = f"manual-test-{status.get('finished_at', 'sin-fecha')}"
    test_alert["title"] = f"PRUEBA MANUAL — {test_alert.get('title', 'Monitor Legislativo UAF')}"
    return send_alert_email([test_alert], status)


def build_plain_text(alerts: list[dict[str, Any]], status: dict[str, Any], dashboard_url: str) -> str:
    lines = [
        "MONITOR LEGISLATIVO UAF",
        f"Ejecución: {status.get('finished_at', '')}",
        f"Alertas legislativas nuevas: {len(alerts)}",
        "",
    ]
    for alert in alerts:
        lines.extend([
            f"[{alert['severity']}] {alert.get('initiative_name') or alert['title']} — Boletín {alert['bulletin']}",
            alert.get("relevance_label", ""),
            alert.get("linkage_summary", ""),
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
          <h3 style="margin:6px 0 8px;font-size:17px;color:#10263a">{html.escape(alert.get('initiative_name') or alert['title'])}</h3>
          <div style="font-size:12px;color:#6b7d8d;margin-bottom:6px">{html.escape(alert['title'])}</div>
          <div style="font-size:13px;color:#4c6071">{html.escape(alert.get('relevance_label',''))}</div>
          <div style="font-size:13px;color:#263e52;margin-top:6px">{html.escape(alert.get('linkage_summary',''))}</div>
          <div style="font-size:12px;margin-top:8px"><b>Tópicos LA/FT:</b> {html.escape(', '.join(alert.get('laft_topics', [])[:6]) or 'Por revisar')}</div>
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
