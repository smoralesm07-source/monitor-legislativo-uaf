# Guía de instalación en GitHub — Monitor Legislativo UAF

Esta guía asume que se trabajará solo desde el navegador, sin Git ni Python instalados localmente.

## 1. Preparar los archivos

1. Descarga y descomprime `monitor_legislativo_uaf.zip`.
2. Abre la carpeta descomprimida `monitor_legislativo_uaf`.
3. Debes subir **el contenido de esa carpeta**, no la carpeta contenedora completa.
4. En la raíz del repositorio deben quedar directamente `monitor.py`, `requirements.txt`, `README.md`, `config`, `data`, `docs`, `monitor_uaf`, `tests` y `.github`.

## 2. Crear el repositorio

1. En GitHub, pulsa `+` → `New repository`.
2. Nombre sugerido: `monitor-legislativo-uaf`.
3. Selecciona `Public` para publicar con GitHub Pages usando GitHub Free.
4. No agregues README, `.gitignore` ni licencia: ya vienen incluidos.
5. Pulsa `Create repository`.

## 3. Cargar el proyecto

1. En el repositorio vacío, pulsa `uploading an existing file` o `Add file` → `Upload files`.
2. Arrastra al navegador todo el contenido interno de la carpeta descomprimida.
3. Verifica que también se cargue `.github/workflows/monitor-legislativo.yml` y `.github/workflows/test-email.yml`.
4. Mensaje de commit: `Carga inicial monitor legislativo UAF`.
5. Confirma el commit en la rama `main`.

## 4. Permisos de GitHub Actions

1. Abre `Settings` → `Actions` → `General`.
2. En `Actions permissions`, permite acciones de GitHub y acciones reutilizables necesarias.
3. En `Workflow permissions`, selecciona `Read and write permissions`.
4. Guarda los cambios.

El workflow además limita explícitamente los permisos: escritura de contenido para guardar el estado y permisos de Pages solo para el trabajo de publicación.

## 5. Crear la clave de aplicación de Gmail

1. En la cuenta Gmail remitente, activa la verificación en dos pasos.
2. Abre la administración de `App passwords` o `Contraseñas de aplicaciones`.
3. Crea una clave con nombre `Monitor Legislativo UAF`.
4. Copia la clave generada. Se utiliza sin espacios como `SMTP_PASSWORD`.
5. No uses la contraseña normal de Gmail y no guardes la clave dentro de ningún archivo del repositorio.

## 6. Crear los secretos

En el repositorio abre `Settings` → `Secrets and variables` → `Actions` → `Secrets` → `New repository secret`.

Crea exactamente estos secretos:

- `MONITOR_EMAIL_ACTIVE` = `true`
- `SMTP_HOST` = `smtp.gmail.com`
- `SMTP_PORT` = `587`
- `SMTP_USER` = cuenta Gmail remitente completa
- `SMTP_PASSWORD` = clave de aplicación de Google, sin espacios
- `MAIL_FROM_NAME` = `Monitor Legislativo UAF`
- `MAIL_TO` = uno o más destinatarios separados por coma
- `PUBLIC_DASHBOARD_URL` = inicialmente puede ser `https://USUARIO.github.io/monitor-legislativo-uaf/`

Reemplaza `USUARIO` por el nombre exacto de tu cuenta y ajusta el nombre del repositorio si elegiste otro.

## 7. Activar GitHub Pages

1. Abre `Settings` → `Pages`.
2. En `Build and deployment`, elige `Source: GitHub Actions`.
3. No selecciones `Deploy from a branch`: el workflow ya genera y publica el artefacto Pages.

## 8. Probar el correo

1. Abre `Actions`.
2. Selecciona `Probar correo del monitor`.
3. Pulsa `Run workflow` → `Run workflow`.
4. Abre la ejecución y confirma que todos los pasos estén verdes.
5. Comprueba la bandeja de entrada y spam de los destinatarios.

## 9. Crear la línea base y publicar

1. En `Actions`, abre `Monitor legislativo UAF`.
2. Pulsa `Run workflow` → `Run workflow`.
3. La primera ejecución crea la línea base y, por diseño, no envía alertas históricas.
4. Deben finalizar correctamente los trabajos `monitor` y `Publicar dashboard`.
5. Abre `Settings` → `Pages` para ver la URL publicada.
6. Si la URL real difiere de la configurada, actualiza el secreto `PUBLIC_DASHBOARD_URL`.

## 10. Verificaciones posteriores

Después de la primera ejecución revisa:

- `data/status.json`: salud de fuentes, fecha, cantidad de proyectos y estado del correo.
- `data/state.json`: línea base de proyectos vigilados.
- `data/discovery_index.json`: boletines ya observados.
- `docs/index.html`: dashboard actualizado.
- `Actions`: trabajos programados y manuales.
- `Deployments` o `Settings` → `Pages`: última publicación.

## 11. Horario automático

El workflow usa:

```yaml
- cron: "17 12,21 * * *"
```

Se ejecuta dos veces al día. Como el horario está expresado en UTC, corresponde aproximadamente a 08:17 y 17:17 en horario estándar de Chile, y 09:17 y 18:17 en horario de verano.

## 12. Errores comunes

### No aparece el workflow en Actions

Confirma que el archivo esté exactamente en:

```text
.github/workflows/monitor-legislativo.yml
```

También debe estar en la rama predeterminada `main`.

### Falla `git push` con error 403

Revisa `Settings` → `Actions` → `General` → `Workflow permissions` y habilita `Read and write permissions`. Si el repositorio pertenece a una organización, una política superior puede impedirlo.

### El correo dice `Username and Password not accepted`

Usa una clave de aplicación, no la contraseña de Gmail. Revisa que `SMTP_USER` corresponda a la misma cuenta que creó la clave y que `SMTP_PASSWORD` se haya pegado sin espacios.

### El correo aparece omitido

Confirma:

```text
MONITOR_EMAIL_ACTIVE=true
```

La primera ejecución normal no envía alertas porque crea la línea base. Para comprobar SMTP utiliza el workflow `Probar correo del monitor`.

### Pages no publica

Confirma que `Settings` → `Pages` use `Source: GitHub Actions`, y que el trabajo `Publicar dashboard` termine verde.

### El monitor falla en una fuente

Revisa `data/status.json` y los logs de la ejecución. El motor conserva el estado anterior si todas las fuentes fallan, para no interpretar una caída como un cambio legislativo.
