# Inventario de evidencia histórica

El [inventario SHA-256](evidence.sha256) identifica cada original por su ruta relativa al repositorio. La copia local verificada conserva esas mismas rutas. Solicita al responsable la ubicación de la copia y verifica el inventario desde su raíz:

```sh
cd "$BACKUP"
shasum -a 256 -c "$WORKSPACE/docs/evaluation/evidence.sha256"
```

Para recuperar un archivo, usa la ruta exacta que figura en el inventario. Las huellas corresponden a los originales, no a resúmenes o versiones normalizadas. El repositorio y el paquete distribuyen el inventario y los informes de síntesis.
