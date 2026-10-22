#!/usr/bin/env python3
"""
Generador del banner animado para el README de un perfil de GitHub.

Convierte una foto en un retrato de puntos (dithering a 1 bit) y lo coloca
junto a una ficha de datos con estética de terminal. El resultado son dos SVG
animados (tema oscuro y claro) que GitHub muestra según el tema del visitante.

Uso:
    pip install -r requirements.txt
    python generate.py                 # usa config.json
    python generate.py -c otro.json    # otra configuración
    python generate.py --demo          # sin foto: genera una silueta de prueba

Todo se anima con SMIL nativo de SVG (sin JavaScript), que GitHub sí renderiza
dentro de <img>.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from html import escape
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- #
# Lienzo
# --------------------------------------------------------------------------- #
W, H = 1200, 620
FONT = "ui-monospace,SFMono-Regular,Menlo,Consolas,'Liberation Mono',monospace"
CHAR_W = 0.6  # ancho aproximado de un carácter monoespaciado, en em

GRID_W, GRID_H = 300, 340  # resolución del retrato (1 celda = 1 posible punto)
SCALE = 1.2                # px de pantalla por celda
BANDS = 34                 # franjas horizontales para la animación de entrada

# Cajas principales
WIN = dict(x=12, y=12, w=W - 24, h=H - 24)
BAR_H = 46
LEFT = dict(x=36, y=82, w=420, h=H - 82 - 36)
RIGHT = dict(x=480, y=82, w=W - 480 - 36, h=H - 82 - 36)
HEAD_H = 34   # cabecera de cada panel
FOOT_H = 30   # pie de cada panel


# --------------------------------------------------------------------------- #
# Retrato
# --------------------------------------------------------------------------- #
def demo_photo() -> Image.Image:
    """Silueta sintética (cabeza + hombros) para probar sin foto real."""
    img = Image.new("RGBA", (600, 680), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 470, 540, 900), fill=(70, 80, 95, 255))            # hombros
    d.rectangle((250, 380, 350, 500), fill=(205, 165, 140, 255))      # cuello
    d.ellipse((180, 120, 420, 420), fill=(222, 182, 155, 255))        # cara
    d.pieslice((165, 85, 435, 330), 180, 360, fill=(40, 30, 25, 255))  # pelo
    d.ellipse((235, 240, 275, 262), fill=(40, 35, 35, 255))           # ojos
    d.ellipse((325, 240, 365, 262), fill=(40, 35, 35, 255))
    d.arc((260, 300, 340, 360), 20, 160, fill=(120, 60, 60, 255), width=6)
    # algo de volumen para que el dithering tenga medios tonos
    shade = Image.new("L", img.size, 0)
    ImageDraw.Draw(shade).ellipse((200, 100, 600, 700), fill=90)
    shade = shade.filter(ImageFilter.GaussianBlur(60))
    dark = Image.new("RGBA", img.size, (0, 0, 0, 255))
    dark.putalpha(ImageOps.invert(shade).point(lambda v: int(v * 0.35)))
    out = Image.alpha_composite(img, dark)
    out.putalpha(img.getchannel("A"))
    return out.filter(ImageFilter.GaussianBlur(1.5))


def fit_to_grid(img: Image.Image, crop) -> Image.Image:
    """Recorta (opcional) y encaja la imagen en la rejilla GRID_W×GRID_H."""
    img = img.convert("RGBA")
    if crop:
        img = img.crop(tuple(crop))
    # Encaje tipo "cover": rellena la rejilla, centrado arriba (caras)
    target = GRID_W / GRID_H
    w, h = img.size
    if w / h > target:            # demasiado ancha: recorta los lados
        nw = int(h * target)
        x0 = (w - nw) // 2
        img = img.crop((x0, 0, x0 + nw, h))
    else:                         # demasiado alta: recorta abajo
        nh = int(w / target)
        img = img.crop((0, 0, w, nh))
    return img.resize((GRID_W, GRID_H), Image.Resampling.LANCZOS)


def subject_mask(img: Image.Image, mode: str) -> np.ndarray:
    """Máscara 0..1 del sujeto: canal alfa, una elipse suave o nada."""
    alpha = np.asarray(img.getchannel("A"), dtype=np.float32) / 255.0
    has_alpha = alpha.min() < 0.98
    if mode == "none":
        return np.ones_like(alpha)
    if mode in ("auto", "alpha") and has_alpha:
        return alpha
    # Sin transparencia: viñeta elíptica para que el retrato "flote"
    yy, xx = np.mgrid[0:GRID_H, 0:GRID_W].astype(np.float32)
    cx, cy = GRID_W / 2, GRID_H * 0.55
    r = np.sqrt(((xx - cx) / (GRID_W * 0.5)) ** 2 + ((yy - cy) / (GRID_H * 0.56)) ** 2)
    return np.clip((1.0 - r) / 0.12, 0, 1)


def serpentine_dither(gray: np.ndarray) -> np.ndarray:
    """Difusión de error Floyd–Steinberg recorriendo filas en zigzag.

    Recibe valores 0..1 y devuelve un array booleano (True = blanco).
    El zigzag evita las "vetas" diagonales del recorrido siempre izq→der.
    """
    buf = gray.astype(np.float32).copy()
    h, w = buf.shape
    out = np.zeros((h, w), dtype=bool)
    for y in range(h):
        step = 1 if y % 2 == 0 else -1
        row = buf[y]
        nxt = buf[y + 1] if y + 1 < h else None
        for x in (range(w) if step == 1 else range(w - 1, -1, -1)):
            v = row[x]
            on = v >= 0.5
            out[y, x] = on
            e = v - (1.0 if on else 0.0)
            xf, xb = x + step, x - step
            if 0 <= xf < w:
                row[xf] += e * 0.4375          # 7/16 hacia delante
            if nxt is not None:
                if 0 <= xb < w:
                    nxt[xb] += e * 0.1875      # 3/16 abajo-detrás
                nxt[x] += e * 0.3125           # 5/16 abajo
                if 0 <= xf < w:
                    nxt[xf] += e * 0.0625      # 1/16 abajo-delante
    return out


def portrait_points(img: Image.Image, theme: str, opts: dict, seed: int) -> np.ndarray:
    """Devuelve las coordenadas (x, y) de rejilla de los puntos a dibujar."""
    mask = subject_mask(img, opts.get("background", "auto"))
    gray = ImageOps.grayscale(img.convert("RGB"))
    gray = ImageEnhance.Brightness(gray).enhance(opts.get("brightness", 1.0))

    # Estira el rango tonal mirando solo al sujeto (no al fondo)
    lum0 = np.asarray(gray, dtype=np.float32)
    inside = lum0[mask > 0.5] if (mask > 0.5).any() else lum0.ravel()
    lo, hi = np.percentile(inside, (1.5, 98.5))
    lum0 = np.clip((lum0 - lo) / max(1.0, hi - lo) * 255, 0, 255)
    gray = Image.fromarray(np.uint8(lum0), "L")
    gray = ImageEnhance.Contrast(gray).enhance(opts.get("contrast", 1.4))
    gray = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=2))
    lum = np.asarray(gray, dtype=np.float32) / 255.0

    # Una imagen muy oscura (fondo negro, ilustración nocturna) en el tema claro
    # sería un bloque de tinta; en ese caso se dibuja su luz, como en el oscuro.
    # "light_mode": "shadows" | "lights" | "auto" fuerza o deja decidir.
    mode = opts.get("light_mode", "auto")
    dark_image = float(np.mean(inside)) < 90
    draw_lights = theme == "dark" or mode == "lights" or (mode == "auto" and dark_image)

    if draw_lights:
        # Puntos claros sobre fondo oscuro: la luz del rostro se dibuja.
        lit = serpentine_dither(lum * mask)
        active = lit & (mask > 0.1)
    else:
        # Tinta sobre papel: las sombras se dibujan, el fondo queda blanco.
        lit = serpentine_dither(lum * mask + (1 - mask))
        active = ~lit & (mask > 0.1)

    ys, xs = np.nonzero(active)
    pts = np.column_stack((xs, ys))
    # Tope de seguridad para el tamaño del SVG. Quitar puntos al azar rompe el
    # patrón del dithering, así que solo se aplica si de verdad se pasa.
    cap = int(opts.get("max_points", 40000))
    if len(pts) > cap:
        rng = np.random.default_rng(seed)
        pts = pts[np.sort(rng.choice(len(pts), cap, replace=False))]
    return pts


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
def tw(text: str, size: float) -> float:
    return len(text) * size * CHAR_W


def clip_text(text: str, size: float, max_w: float) -> str:
    if tw(text, size) <= max_w:
        return text
    n = max(1, int(max_w / (size * CHAR_W)) - 1)
    return text[:n] + "…"


def t(x, y, s, size, fill, anchor="start", weight=None, ls=None, extra=""):
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    wgt = f' font-weight="{weight}"' if weight else ""
    spc = f' letter-spacing="{ls}"' if ls else ""
    return (f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{fill}"{a}{wgt}{spc}'
            f'{extra}>{escape(s)}</text>')


def band_paths(pts: np.ndarray) -> list[str]:
    """Agrupa los puntos en franjas horizontales; cada punto es 'Mx yh0'."""
    band_h = GRID_H / BANDS
    groups: list[list[str]] = [[] for _ in range(BANDS)]
    for x, y in pts:
        groups[min(BANDS - 1, int(y // band_h))].append(f"M{x} {y}h0")
    return ["".join(g) for g in groups]


INTRO = 0.3          # cuándo empieza a aparecer la primera foto
WIPE_STEP = 0.045    # retraso entre franjas consecutivas (efecto barrido)
FADE = 0.3           # duración del fundido de cada franja


def cycle_opacity(k: int, n: int, slot: float) -> tuple[str, str]:
    """values/keyTimes de opacidad para la foto k de n, en un ciclo de n*slot s.

    La foto k está visible en [k*slot, (k+1)*slot]. Cada cambio dura FADE y
    termina justo en el límite del hueco, de modo que al reiniciar el ciclo
    (t=0) la foto 0 ya está visible y no hay saltos.
    """
    T = n * slot
    if k == 0:
        pts = [(0, 1), (slot - FADE, 1), (slot, 0), (T - FADE, 0), (T, 1)]
    elif k == n - 1:
        pts = [(0, 0), (k * slot - FADE, 0), (k * slot, 1), (T - FADE, 1), (T, 0)]
    else:
        pts = [(0, 0), (k * slot - FADE, 0), (k * slot, 1),
               ((k + 1) * slot - FADE, 1), ((k + 1) * slot, 0), (T, 0)]
    values = ";".join(str(v) for _, v in pts)
    times = ";".join(f"{tt / T:.4f}" for tt, _ in pts)
    return values, times


def render(cfg: dict, theme: str, portraits: list[np.ndarray], seed: int) -> str:
    n = len(portraits)
    slot = float(cfg.get("photo_seconds", 6))
    intro_end = INTRO + BANDS * WIPE_STEP + FADE + 0.6  # primera foto ya completa
    c = cfg["themes"][theme]
    rnd = random.Random(seed)
    o: list[str] = []
    add = o.append

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" aria-labelledby="ti">')
    add(f'<title id="ti">{escape(cfg.get("handle", ""))} · perfil</title>')

    # --- defs ---------------------------------------------------------------
    px, py = LEFT["x"] + (LEFT["w"] - GRID_W * SCALE) / 2, LEFT["y"] + HEAD_H + 12
    add('<defs>')
    add(f'<linearGradient id="scan" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{c["accent"]}" stop-opacity="0"/>'
        f'<stop offset=".85" stop-color="{c["accent"]}" stop-opacity=".18"/>'
        f'<stop offset="1" stop-color="{c["accent"]}" stop-opacity=".55"/></linearGradient>')
    add(f'<clipPath id="pclip"><rect x="{LEFT["x"]+1}" y="{LEFT["y"]+HEAD_H}" '
        f'width="{LEFT["w"]-2}" height="{LEFT["h"]-HEAD_H-FOOT_H}"/></clipPath>')
    add('</defs>')

    # --- ventana -------------------------------------------------------------
    add(f'<rect width="{W}" height="{H}" rx="20" fill="{c["bg"]}"/>')
    add(f'<rect x="{WIN["x"]}" y="{WIN["y"]}" width="{WIN["w"]}" height="{WIN["h"]}" '
        f'rx="14" fill="{c["window"]}" stroke="{c["line"]}"/>')
    add(f'<path d="M{WIN["x"]} {WIN["y"]+BAR_H}H{WIN["x"]+WIN["w"]}" stroke="{c["line"]}"/>')
    for i, col in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        add(f'<circle cx="{38 + i*21}" cy="{WIN["y"]+BAR_H/2}" r="6" fill="{col}"/>')

    add(f'<g font-family="{FONT}">')
    add(t(W / 2, WIN["y"] + BAR_H / 2 + 4.5, cfg.get("window_title", ""), 13,
          c["muted"], anchor="middle", ls=".4"))

    # --- paneles -----------------------------------------------------------
    for box, title in ((LEFT, cfg.get("left_title", "")), (RIGHT, cfg.get("right_title", ""))):
        add(f'<rect x="{box["x"]}" y="{box["y"]}" width="{box["w"]}" height="{box["h"]}" '
            f'rx="7" fill="{c["panel"]}" stroke="{c["line"]}"/>')
        add(f'<path d="M{box["x"]} {box["y"]+HEAD_H}h{box["w"]}M{box["x"]} '
            f'{box["y"]+box["h"]-FOOT_H}h{box["w"]}" stroke="{c["line"]}"/>')
        add(t(box["x"] + 14, box["y"] + 22, title, 11.5, c["accent"], weight="700", ls="1.2"))

    # Cabecera izquierda: resolución
    add(t(LEFT["x"] + LEFT["w"] - 14, LEFT["y"] + 22, f"{GRID_W}×{GRID_H} · 1-BIT",
          10.5, c["muted"], anchor="end", ls=".6"))
    if n > 1:
        # Indicador "IMG k/n" que cambia a la vez que la foto
        ix = LEFT["x"] + LEFT["w"] - 14 - tw(f"{GRID_W}×{GRID_H} · 1-BIT", 10.5) - 8
        for k in range(n):
            vals, times = cycle_opacity(k, n, slot)
            vals = ";".join("1" if v == "1" else "0" for v in vals.split(";"))
            anim = (f'<animate attributeName="opacity" values="{vals}" keyTimes="{times}" '
                    f'calcMode="discrete" dur="{n*slot:g}s" begin="{intro_end + BANDS*WIPE_STEP/2:.2f}s" '
                    f'repeatCount="indefinite"/>')
            add(f'<text x="{ix:g}" y="{LEFT["y"]+22}" font-size="10.5" fill="{c["accent2"]}" '
                f'text-anchor="end" letter-spacing=".6" opacity="{1 if k == 0 else 0}">'
                f'IMG {k+1}/{n} ·{anim}</text>')
    # Pie izquierdo: nº de puntos que se va "contando"
    fy = LEFT["y"] + LEFT["h"] - 11
    add(t(LEFT["x"] + 14, fy, "DOTS", 10, c["muted"], ls=".8"))
    total = len(portraits[0])
    steps = 12
    vals = ";".join(str(round(total * (i / steps) ** 0.7)) for i in range(steps + 1))
    # El contador se simula con varios textos que se van mostrando en orden
    for i, v in enumerate(vals.split(";")):
        b = 0.3 + i * 0.13
        show = (f'<set attributeName="opacity" to="1" begin="{b:.2f}s"/>'
                f'<set attributeName="opacity" to="0" begin="{b+0.13:.2f}s"/>'
                if i < steps else f'<set attributeName="opacity" to="1" begin="{b:.2f}s"/>')
        add(f'<text x="{LEFT["x"]+52}" y="{fy}" font-size="10" fill="{c["text"]}" '
            f'opacity="0" letter-spacing=".8">{v}{show}</text>')
    add(t(LEFT["x"] + LEFT["w"] - 14, fy, "FS · SERPENTINE", 10, c["muted"],
          anchor="end", ls=".8"))

    # Esquinas de encuadre
    fx0, fy0 = LEFT["x"] + 12, LEFT["y"] + HEAD_H + 10
    fx1, fy1 = LEFT["x"] + LEFT["w"] - 12, LEFT["y"] + LEFT["h"] - FOOT_H - 10
    k = 12
    add(f'<path d="M{fx0} {fy0+k}V{fy0}H{fx0+k}M{fx1-k} {fy0}H{fx1}V{fy0+k}'
        f'M{fx1} {fy1-k}V{fy1}H{fx1-k}M{fx0+k} {fy1}H{fx0}V{fy1-k}" '
        f'fill="none" stroke="{c["muted"]}" stroke-opacity=".6"/>')
    add('</g>')

    # --- retrato -------------------------------------------------------------
    add('<g clip-path="url(#pclip)">')
    add(f'<g transform="translate({px:g} {py:g}) scale({SCALE})" stroke="{c["dots"]}" '
        f'stroke-width="1" stroke-linecap="round" fill="none">')
    # Glitch: unas pocas franjas se desplazan un instante de vez en cuando.
    glitch = {}
    for i in rnd.sample(range(BANDS), 4):
        off = rnd.choice((-1, 1)) * rnd.randint(4, 9)
        at = rnd.uniform(0.55, 0.9)
        glitch[i] = (f'<animateTransform attributeName="transform" type="translate" '
                     f'values="0 0;0 0;{off} 0;{-off/2:g} 0;0 0;0 0" '
                     f'keyTimes="0;{at:.3f};{at+.008:.3f};{at+.016:.3f};{at+.024:.3f};1" '
                     f'dur="8s" begin="{intro_end:.2f}s" repeatCount="indefinite"/>')

    T = n * slot
    for k, pts in enumerate(portraits):
        cyc = cycle_opacity(k, n, slot) if n > 1 else None
        for i, d in enumerate(band_paths(pts)):
            if not d:
                continue
            anim = ""
            if k == 0:  # entrada: la primera foto aparece franja a franja
                anim += (f'<animate attributeName="opacity" from="0" to="1" '
                         f'begin="{INTRO + i*WIPE_STEP:.3f}s" dur="{FADE}s" fill="freeze"/>')
            if cyc:     # alternancia: el retraso por franja crea el barrido
                anim += (f'<animate attributeName="opacity" values="{cyc[0]}" '
                         f'keyTimes="{cyc[1]}" dur="{T:g}s" '
                         f'begin="{intro_end + i*WIPE_STEP:.3f}s" repeatCount="indefinite"/>')
            anim += glitch.get(i, "")
            add(f'<g opacity="0"><path d="{d}"/>{anim}</g>')
    add('</g>')

    # Línea de escaneo: barre la entrada y luego acompaña cada cambio de foto
    # (o, con una sola foto, pasa de vez en cuando).
    sy0, sy1 = LEFT["y"] + HEAD_H - 60, LEFT["y"] + LEFT["h"] - FOOT_H
    sweep = BANDS * WIPE_STEP + 0.4
    period = slot if n > 1 else 7.0
    start = intro_end + slot - FADE - 0.2 if n > 1 else 3.0
    f = sweep / period
    add(f'<rect x="{LEFT["x"]}" y="{sy0}" width="{LEFT["w"]}" height="60" fill="url(#scan)" opacity="0">'
        f'<animate attributeName="y" values="{sy0};{sy1}" dur="{sweep:.2f}s" begin="{INTRO-0.05:g}s"/>'
        f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.05;.9;1" '
        f'dur="{sweep:.2f}s" begin="{INTRO-0.05:g}s"/>'
        f'<animate attributeName="y" values="{sy0};{sy1};{sy1}" keyTimes="0;{f:.3f};1" '
        f'dur="{period:g}s" begin="{start:.2f}s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values="0;.8;.8;0;0" '
        f'keyTimes="0;{f*.08:.3f};{f*.92:.3f};{f:.3f};1" '
        f'dur="{period:g}s" begin="{start:.2f}s" repeatCount="indefinite"/></rect>')
    add('</g>')

    # --- ficha de datos ------------------------------------------------------
    add(f'<g font-family="{FONT}">')
    rx0, rx1 = RIGHT["x"], RIGHT["x"] + RIGHT["w"]
    hy = RIGHT["y"] + HEAD_H / 2

    handle = cfg.get("handle", "")
    hw = tw(handle, 12) + 30
    add(f'<rect x="{rx1-12-hw:g}" y="{hy-11}" width="{hw:g}" height="22" rx="11" '
        f'fill="{c["accent"]}" fill-opacity=".14" stroke="{c["accent"]}" stroke-opacity=".35"/>')
    add(t(rx1 - 12 - hw / 2, hy + 4, handle, 12, c["accent"], anchor="middle", weight="700"))

    status = cfg.get("status_label", "LIVE")
    sx = rx1 - 12 - hw - 18 - tw(status, 10.5)
    add(f'<circle cx="{sx-10:g}" cy="{hy}" r="3.5" fill="{c["live"]}">'
        f'<animate attributeName="opacity" values="1;.25;1" dur="1.6s" repeatCount="indefinite"/></circle>')
    add(f'<circle cx="{sx-10:g}" cy="{hy}" r="3.5" fill="none" stroke="{c["live"]}">'
        f'<animate attributeName="r" values="3.5;9" dur="1.6s" repeatCount="indefinite"/>'
        f'<animate attributeName="opacity" values=".7;0" dur="1.6s" repeatCount="indefinite"/></circle>')
    add(t(sx, hy + 3.8, status, 10.5, c["live"], weight="700", ls="1"))

    rows = cfg["rows"]
    top = RIGHT["y"] + HEAD_H + 26
    avail = RIGHT["h"] - HEAD_H - FOOT_H - 40
    rh = min(36.0, avail / max(1, len(rows) + 1))  # +1: hueco para el cursor
    fs = 13.5 if rh >= 24 else 12.5
    lx, vx = rx0 + 18, rx1 - 18
    label_w = max(tw(r[0], fs) for r in rows)

    for i, (label, value) in enumerate(rows):
        y = top + i * rh
        b = 0.9 + i * 0.11
        value = clip_text(str(value), fs, vx - (lx + label_w + 40))
        vw = tw(value, fs)
        cid = f"v{i}"
        add(f'<clipPath id="{cid}"><rect x="{vx - vw - 2:g}" y="{y - fs}" width="0" height="{fs + 6}">'
            f'<animate attributeName="width" from="0" to="{vw + 4:g}" begin="{b+.15:.2f}s" '
            f'dur="{0.18 + 0.02*len(value):.2f}s" fill="freeze"/></rect></clipPath>')
        add(f'<g opacity="0"><animate attributeName="opacity" from="0" to="1" begin="{b:.2f}s" '
            f'dur=".2s" fill="freeze"/>')
        add(t(lx, y, str(label), fs, c["muted"]))
        x1, x2 = lx + tw(str(label), fs) + 10, vx - vw - 10
        if x2 > x1:
            add(f'<path d="M{x1:g} {y-4}H{x2:g}" stroke="{c["muted"]}" stroke-opacity=".45" '
                f'stroke-dasharray="1 4" stroke-linecap="round"/>')
        add(f'<g clip-path="url(#{cid})">'
            + t(vx, y, value, fs, c["text"], anchor="end", weight="600") + '</g>')
        add('</g>')

    # Cursor parpadeante tras la última fila
    cy = top + len(rows) * rh
    add(f'<g opacity="0"><set attributeName="opacity" to="1" begin="{0.9 + len(rows)*0.11 + .3:.2f}s"/>'
        + t(lx, cy, "$", fs, c["accent"], weight="700")
        + f'<rect x="{lx + tw("$ ", fs):g}" y="{cy - fs + 2}" width="{fs*CHAR_W:g}" height="{fs}" '
          f'fill="{c["accent"]}"><animate attributeName="opacity" values="1;1;0;0" '
          f'keyTimes="0;.5;.5;1" dur="1.05s" repeatCount="indefinite"/></rect></g>')

    # Pie derecho
    fy = RIGHT["y"] + RIGHT["h"] - 11
    add(t(rx0 + 14, fy, cfg.get("footer_left", ""), 10, c["accent"], weight="700", ls=".8"))
    add(t(rx1 - 14, fy, cfg.get("footer_right", ""), 10, c["muted"], anchor="end", ls=".8"))
    add('</g></svg>')
    return "".join(o)


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-c", "--config", default=str(HERE / "config.json"))
    ap.add_argument("--demo", action="store_true", help="usar una silueta de prueba")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    cfg_path = Path(args.config).resolve()
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = cfg_path.parent

    opts = cfg.get("portrait", {})
    # "photo" puede ser una ruta o una lista de rutas; con varias se alternan.
    # Cada entrada también puede ser {"file": ..., "crop": [...], "contrast": ...,
    # "brightness": ..., "background": ...} para ajustar esa foto por separado.
    entries = cfg["photo"] if isinstance(cfg["photo"], list) else [cfg["photo"]]
    grids, popts = [], []
    if args.demo:
        grids.append(fit_to_grid(demo_photo(), None))
        popts.append(opts)
    else:
        for e in entries:
            e = e if isinstance(e, dict) else {"file": e}
            o = {**opts, **{k: v for k, v in e.items() if k != "file"}}
            p = base / e["file"]
            if not p.exists():
                raise SystemExit(f"No encuentro la foto: {p}\n"
                                 f"Pon tu imagen ahí o prueba con --demo.")
            grids.append(fit_to_grid(ImageOps.exif_transpose(Image.open(p)), o.get("crop")))
            popts.append(o)

    out = base / cfg.get("output", "assets/banner")
    out.parent.mkdir(parents=True, exist_ok=True)

    for theme in ("dark", "light"):
        portraits = [portrait_points(g, theme, o, args.seed) for g, o in zip(grids, popts)]
        svg = render(cfg, theme, portraits, args.seed)
        dest = out.with_name(f"{out.name}-{theme}.svg")
        dest.write_text(svg, encoding="utf-8")
        dots = " + ".join(f"{len(p):,}" for p in portraits)
        print(f"{os.path.relpath(dest)}  ·  {dots} puntos  ·  {len(svg)/1024:.0f} KB")


if __name__ == "__main__":
    main()
