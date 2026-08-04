"""Prueba manual de SMTP para GitHub Actions.

El bloque principal evita que pytest envíe correos al importar este archivo.
"""
from monitor_uaf.notifier import send_test_email


def main() -> int:
    sent, message = send_test_email()
    print(sent, message)
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
