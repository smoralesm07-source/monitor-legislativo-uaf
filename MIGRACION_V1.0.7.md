# Migración a v1.0.7

Esta versión cambia las fuentes, la estructura del dashboard y el historial legislativo.

## Cambio principal

Se eliminan BCN y LeyChile. El monitor consulta únicamente Cámara y Senado.

## Recomendación de instalación

Para evitar que los proyectos históricos de versiones anteriores sigan apareciendo, reemplaza también los archivos de estado incluidos en el paquete de actualización. Esto crea una nueva línea base.

La primera ejecución posterior a la actualización:

- no enviará correos históricos;
- volverá a descubrir iniciativas vigentes;
- construirá el historial oficial de los últimos tres años;
- descartará proyectos terminados o sin actividad reciente.

No reemplaces `data/email_log.json` si deseas conservar el registro de alertas ya enviadas.
