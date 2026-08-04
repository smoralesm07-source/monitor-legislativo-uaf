# Monitor Legislativo UAF v1.0.8

Monitor diario de proyectos de ley vigentes con impacto en la Unidad de Análisis Financiero de Chile.

## Fuentes

La versión 1.0.7 utiliza exclusivamente:

- Cámara de Diputadas y Diputados: datos abiertos XML y ficha oficial por boletín.
- Senado de la República: servicio XML de movimientos, XML de tramitación y ficha oficial por boletín.

BCN y LeyChile no se consultan ni se utilizan para descubrir o clasificar iniciativas.

## Estructura del dashboard

1. Proyectos que modifican directamente la Ley N.º 19.913.
2. Proyectos relacionados con prevención LA/FT o delitos base.
3. Historia legislativa de los últimos tres años.
4. Alertas materiales detectadas.
5. Salud de las fuentes oficiales.

Los boletines refundidos o relacionados se agrupan bajo un nombre corto de iniciativa.

## Historia legislativa

Cada ficha conserva hasta 18 hitos oficiales publicados durante los últimos tres años. El motor:

- toma la fecha individualizada en Cámara o Senado;
- excluye fechas de navegación, consulta o detección del monitor;
- deduplica un mismo hito publicado por ambas cámaras;
- genera un resumen breve basado en la descripción oficial;
- mantiene el texto oficial extraído y el enlace a la ficha.

## Ejecución

```bash
python monitor.py
```

Para reconstruir solo el dashboard:

```bash
python monitor.py --render-only
```

## GitHub Actions

El workflow `.github/workflows/monitor-legislativo.yml` ejecuta el barrido programado, guarda el estado, publica `docs/` en GitHub Pages y envía correo solo ante novedades legislativas materiales no informadas anteriormente.


## Corrección v1.0.8

Mantiene visibles los boletines de la cartera priorizada que fueron confirmados en fichas oficiales, aun cuando Cámara o Senado no entreguen una fecha estructurada. Los estados terminales continúan excluyéndose. Se eliminó el encabezado redundante del dashboard.
