# Migración a v1.1.2

Esta versión corrige la compatibilidad entre `test_email.py` y
`monitor_uaf/notifier.py`.

Reemplace ambos archivos conjuntamente:

- `monitor_uaf/notifier.py`
- `test_email.py`

Opcionalmente agregue `tests/test_notifier_contract.py`.

Luego ejecute el workflow principal. `pytest -q` ya no enviará correos durante
la recolección; el correo de prueba solo se envía al ejecutar explícitamente
`python test_email.py` o el workflow **Probar correo del monitor**.
