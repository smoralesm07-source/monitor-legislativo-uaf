from monitor_uaf.notifier import send_alert_email, send_test_email


def test_notifier_public_contract():
    assert callable(send_alert_email)
    assert callable(send_test_email)


def test_send_test_email_does_not_require_network_when_disabled(monkeypatch):
    monkeypatch.setenv("MONITOR_EMAIL_ACTIVE", "false")
    sent, message = send_test_email({"finished_at": "pytest"})
    assert sent is False
    assert "desactivado" in message.lower()
