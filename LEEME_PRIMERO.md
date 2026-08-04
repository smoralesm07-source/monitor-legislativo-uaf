# Actualización coherente v1.1.1

Esta actualización reemplaza el conjunto completo de módulos Python para evitar mezclas de versiones.

1. Descomprima el ZIP.
2. Suba todo su contenido a la raíz del repositorio, aceptando reemplazar los archivos existentes.
3. No elimine ni reemplace manualmente `data/state.json`, `data/alerts.json`, `data/history.jsonl` o `data/discovery_index.json`. Este ZIP no los contiene.
4. Ejecute `Actions → Monitor legislativo UAF → Run workflow`.
5. Verifique que pasen `Verificar compatibilidad interna`, `Compactar estado heredado`, `Ejecutar pruebas` y `Ejecutar barrido legislativo`.

No se requieren nuevos Secrets.
