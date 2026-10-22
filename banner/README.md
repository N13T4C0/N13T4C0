# Banner del perfil

`generate.py` convierte una o varias imágenes en un retrato de puntos (dithering
Floyd–Steinberg a 1 bit) y lo coloca junto a una ficha con estética de terminal.
Genera `assets/banner-dark.svg` y `assets/banner-light.svg`, animados solo con
SVG, sin JavaScript.

## Cambiar algo

Edita `config.json` (se puede hacer desde la web de GitHub) y haz commit. La Action
`.github/workflows/banner.yml` regenera los SVG sola.

- `rows`: pares `[etiqueta, valor]` de la ficha. Caben unas 10–14 filas.
- `photo`: lista de imágenes de `source/`. Con varias, se alternan con un barrido
  cada `photo_seconds` segundos.
- `themes`: colores del tema oscuro y del claro.

Cada imagen de `photo` puede llevar sus propios ajustes:

```json
{"file": "source/foto1.png", "crop": [izq, arriba, der, abajo],
 "background": "auto", "contrast": 1.4, "brightness": 1.0, "light_mode": "auto"}
```

- `crop`: recorte en píxeles. Sin él se encuadra solo, centrado arriba.
- `background`: `"auto"` usa la transparencia del PNG si la tiene y, si no, una
  viñeta ovalada. Con `"none"` se usa la imagen entera.
- `light_mode`: en el tema claro se dibujan las sombras (`"shadows"`) o las zonas
  iluminadas (`"lights"`). Con `"auto"` se usan las luces si la imagen es muy oscura.

Las fotos de personas quedan mucho mejor en PNG con el fondo quitado.

## Añadir la foto del CV

1. Sube la foto a `banner/source/foto1.png`.
2. Añádela al principio de `photo` en `config.json`:
   ```json
   "photo": ["source/foto1.png", {"file": "source/foto2.jpg", ...}]
   ```

## Generarlo en local

```bash
cd banner
pip install -r requirements.txt
python generate.py
```

Con `python generate.py --demo` se prueba con una silueta sintética, sin fotos.
