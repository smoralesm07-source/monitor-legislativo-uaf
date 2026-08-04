# Migración a v1.0.4 — reparación de archivos sobredimensionados

## Problema corregido

La versión 1.0.3 persistía `evidence_text` dentro de `data/state.json`. En cada ejecución, el texto anterior podía volver a combinarse con la evidencia nueva. Luego ese contenido se copiaba a `data/projects.json` y se incrustaba en `docs/index.html`, generando archivos de decenas de megabytes.

La versión 1.0.4:

- utiliza la evidencia completa solo en memoria durante el barrido;
- no la guarda en `state.json` ni en el dashboard;
- limita y deduplica la evidencia de una misma ejecución;
- compacta automáticamente estados heredados;
- genera una proyección liviana para GitHub Pages;
- limita el historial a 2.000 alertas;
- cancela antes del commit si un archivo generado supera 8 MB;
- incorpora un workflow manual de reparación.

## Actualización del repositorio existente

1. Carga los archivos de `actualizacion_monitor_uaf_v1.0.4.zip` respetando sus rutas.
2. No reemplaces manualmente los archivos dentro de `data/`.
3. En GitHub abre `Actions`.
4. Ejecuta `Reparar archivos grandes del monitor`.
5. Verifica que los trabajos `repair` y `Publicar dashboard reparado` terminen en verde.
6. Luego ejecuta una vez `Monitor legislativo UAF` para efectuar un barrido normal.

## Tamaños esperados después de reparar

Los tamaños dependen del número de proyectos y alertas, pero normalmente deberían ser muy inferiores a 8 MB. Como referencia, el HTML base sin datos ocupa cerca de 40 KB.

## Sobre el commit grande anterior

La reparación reduce los archivos de la versión actual del repositorio. Los blobs grandes continúan en el historial Git del commit anterior. Esto no impide el funcionamiento. Si posteriormente se desea reducir también el peso histórico del repositorio, se puede reescribir el historial o crear un repositorio limpio, pero no es necesario para reactivar el monitor.
