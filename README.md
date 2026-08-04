# Monitor Legislativo Estratégico UAF

Motor en Python para vigilar diariamente proyectos de ley de Chile que:

1. **Nivel 1 — modificación directa:** modifican la Ley N.º 19.913, nombran a la Unidad de Análisis Financiero o alteran expresamente sus artículos, atribuciones u obligaciones.
2. **Nivel 2 — impacto legal potencial:** pueden afectar delitos base, sujetos obligados, acceso a información, secreto bancario, reportes, fiscalización, sanciones, presupuesto, dotación, datos, tecnología o cooperación institucional, aunque no nombren expresamente a la UAF.

El sistema descubre iniciativas nuevas, actualiza los proyectos vigilados, compara cada ejecución con el estado anterior, genera un dashboard y envía un correo solo cuando detecta alertas nuevas.


## Cambios de la versión 1.0.3

- elimina de la cartera publicada leyes ya promulgadas o publicadas y proyectos terminados, archivados, retirados, rechazados o inadmisibles;
- descarta proyectos antiguos que mantienen una etiqueta de trámite, pero no registran actividad oficial dentro de la ventana vigente;
- exige simultáneamente relevancia UAF y vigencia legislativa comprobada;
- utiliza la BCN únicamente como fuente histórica de descubrimiento, nunca como prueba suficiente de vigencia;
- incorpora categorías y filtros para **nuevas / ingreso reciente**, **próximo hito legislativo** y **en tramitación activa**;
- conserva en el dashboard solamente la cartera vigente;
- registra en `data/exclusion_summary.json` cuántos candidatos fueron descartados y por qué, sin publicarlos como proyectos activos;
- genera una alerta de cierre solo cuando un proyecto previamente validado por esta versión pasa realmente a un estado terminal.

### Regla de vigencia

Un proyecto aparece en el dashboard solo si, además de ser relevante para la UAF, cumple al menos una de estas condiciones:

- ingreso dentro de los últimos `new_project_days`;
- movimiento oficial dentro de los últimos `active_movement_days`;
- presencia en una fuente de movimientos recientes;
- urgencia vigente;
- votación, citación, Comisión Mixta, informe u otro próximo hito comprobable.

Por defecto, la ventana para iniciativas nuevas es de 180 días y la ventana máxima de actividad es de 730 días. Ambas se configuran en `config/monitor_config.json`.

## Fuentes utilizadas

- Datos abiertos XML de la Cámara de Diputadas y Diputados: mensajes, mociones y detalle por boletín.
- Fichas de tramitación y movimientos recientes del Senado.
- Lista histórica de proyectos asociados a la Ley N.º 19.913 de la Biblioteca del Congreso Nacional, utilizada solo para descubrir candidatos que luego deben validarse en Cámara o Senado.

La información oficial y la inferencia analítica se almacenan separadamente. La clasificación estratégica requiere validación jurídica antes de adoptar decisiones institucionales.

## Estructura

```text
monitor_legislativo_uaf/
├── monitor.py                         # Punto de entrada
├── monitor_uaf/
│   ├── analysis.py                    # Clasificación, puntajes y comparación
│   ├── config.py                      # Rutas y configuración
│   ├── http_client.py                 # Descarga con reintentos
│   ├── models.py                      # Modelo de proyecto
│   ├── notifier.py                    # Correo SMTP/Gmail
│   ├── pipeline.py                    # Orquestación diaria
│   ├── render.py                      # Dashboard HTML
│   ├── sources.py                     # Cámara, Senado y BCN
│   └── utils.py
├── config/monitor_config.json         # Palabras, pesos y boletines iniciales
├── data/                              # Estado histórico persistente
├── docs/index.html                    # Sitio para GitHub Pages
├── tests/                             # Pruebas sin conexión
└── .github/workflows/monitor-legislativo.yml
```

## Comportamiento de las alertas

### Primera ejecución

La primera ejecución crea una **línea base**. Por defecto no envía correos, para evitar que todos los proyectos históricos sean tratados como novedades.

### Ejecuciones posteriores

Se genera una alerta cuando ocurre alguno de estos eventos:

- aparece una iniciativa nueva clasificada en nivel 1 o nivel 2;
- cambia la etapa o el estado del proyecto;
- cambia la comisión responsable;
- se incorpora o modifica una urgencia;
- aparece un nuevo movimiento, votación, oficio o antecedente;
- cambia el contenido extraído de la ficha oficial;
- una iniciativa pasa de no relevante a relevante;
- cambian sus dimensiones de impacto.

Las alertas se clasifican como crítica, alta o media. Un avance de trámite, Comisión Mixta, aprobación, despacho, secreto bancario o expansión de sujetos obligados aumenta la severidad.

## Ejecución local

```bash
python -m pip install -r requirements.txt
pytest -q
python monitor.py --no-email
```

El dashboard queda en:

```text
docs/index.html
```

Para regenerarlo sin consultar internet:

```bash
python monitor.py --render-only
```

## Configuración de correo Gmail

Usa una **clave de aplicación de Google**, no la contraseña normal de la cuenta.

Variables necesarias:

```text
MONITOR_EMAIL_ACTIVE=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu.correo@gmail.com
SMTP_PASSWORD=clave-de-aplicacion
MAIL_FROM_NAME=Monitor Legislativo UAF
MAIL_TO=cuenta1@dominio.cl,cuenta2@dominio.cl
PUBLIC_DASHBOARD_URL=https://USUARIO.github.io/REPOSITORIO/
```

Para una prueba local, carga las variables en la terminal y ejecuta:

```bash
python test_email.py
```

## Configuración en GitHub

En el repositorio abre:

```text
Settings → Secrets and variables → Actions → New repository secret
```

Crea estos secretos:

| Secreto | Contenido |
|---|---|
| `MONITOR_EMAIL_ACTIVE` | `true` |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | cuenta remitente Gmail |
| `SMTP_PASSWORD` | clave de aplicación Gmail |
| `MAIL_FROM_NAME` | `Monitor Legislativo UAF` |
| `MAIL_TO` | destinatarios separados por coma |
| `PUBLIC_DASHBOARD_URL` | URL del GitHub Pages |

Después abre **Actions → Probar correo del monitor → Run workflow** para validar SMTP. Luego ejecuta **Actions → Monitor legislativo UAF → Run workflow** para crear la primera línea base.

## Activar GitHub Pages

En:

```text
Settings → Pages
```

Selecciona:

```text
Source: GitHub Actions
```

El mismo workflow empaqueta `docs/` y lo publica explícitamente con GitHub Pages después de cada barrido. Esto evita depender de una compilación disparada por el commit automático. El workflow ejecuta dos barridos diarios y también puede iniciarse manualmente desde Actions.

Para comprobar el correo sin esperar una alerta real, ejecuta:

```text
Actions → Probar correo del monitor → Run workflow
```

## Persistencia y auditoría

- `data/state.json`: última versión de cada proyecto vigilado.
- `data/discovery_index.json`: todos los boletines ya observados; permite reconocer nuevas iniciativas.
- `data/alerts.json`: alertas acumuladas y deduplicadas.
- `data/history.jsonl`: historial inmutable de alertas detectadas.
- `data/status.json`: salud de fuentes, cantidad de candidatos, proyectos vigentes, exclusiones y resultado del correo.
- `data/exclusion_summary.json`: resumen de proyectos omitidos por término, antigüedad o falta de vigencia comprobada.

El workflow guarda automáticamente estos archivos mediante un commit. Por eso el historial de Git también funciona como respaldo y auditoría de cambios.

## Ajustar las reglas de impacto

Edita `config/monitor_config.json`:

- `direct_terms`: expresiones que activan nivel 1.
- `secondary_topics`: dimensiones, términos y peso de nivel 2.
- `seed_bulletins`: proyectos recientes o estratégicos que deben revisarse siempre; no debe utilizarse para cargar catálogos históricos completos.
- `new_project_days`: ventana para considerar una iniciativa nueva.
- `active_movement_days`: antigüedad máxima admitida para acreditar actividad legislativa.
- `terminal_state_terms`, `active_state_terms` y `upcoming_terms`: vocabulario de vigencia y cierre.
- `critical_change_terms`: cambios que elevan la alerta.
- `minimum_secondary_score`: sensibilidad del segundo nivel.

Conviene validar mensualmente falsos positivos y falsos negativos, y recalibrar términos y pesos.

## Controles de continuidad

El motor incluye:

- tres reintentos por consulta;
- dos dominios alternativos para el servicio XML de la Cámara;
- continuidad aunque una fuente falle;
- conservación del estado anterior si fallan todas las fuentes;
- registro visible de salud de Cámara, Senado y BCN;
- pruebas automáticas antes de cada barrido;
- bloqueo de ejecuciones simultáneas;
- límite de 25 minutos por ejecución.

Ningún monitor puede garantizar que las páginas oficiales estén siempre disponibles o que no cambien su estructura. La garantía operacional consiste en ejecutar el barrido programado, registrar el éxito o fallo y no generar falsas novedades cuando una fuente deja de responder.

## Guía detallada de despliegue

Consulta `GUIA_INSTALACION_GITHUB.md` para el procedimiento completo usando solamente el navegador.

## Corrección v1.0.4: control de tamaño

La versión 1.0.4 evita que la evidencia cruda descargada desde Cámara y Senado se acumule dentro de los JSON persistentes. `evidence_text` se utiliza solo durante la clasificación y se elimina antes de guardar el estado.

El workflow ejecuta `maintenance_compact.py` antes de cada barrido y valida al final que ningún archivo generado supere el límite interno configurado en `max_generated_file_mb`.

Para reparar un repositorio que ya contiene archivos grandes:

```text
Actions → Reparar archivos grandes del monitor → Run workflow
```

El workflow compacta `state.json`, `projects.json`, `alerts.json`, `history.jsonl` y el dashboard, guarda la reparación y vuelve a publicar GitHub Pages.
