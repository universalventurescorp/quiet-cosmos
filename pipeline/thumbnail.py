"""Three 1280x720 thumbnail variants for YouTube Studio's "Test & compare".

  thumbnail_1.jpg  "quiet"  - brand style: real image, dark side fade, serif title. Uploaded by default.
  thumbnail_2.jpg  "centre" - brand style: image full frame, centred serif title on a low band.
  thumbnail_3.jpg  "bold"   - the original high-contrast style (heavy sans, yellow second line),
                              kept as the challenger so the test shows which one viewers click.

Brand palette and fonts come from branding/ (make_branding.py and branding/fonts/).
If those files are missing, every variant falls back to the bold style.
"""
import importlib.util
import pathlib

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from .fonts import font

W, H = 1280, 720
ROOT = pathlib.Path(__file__).resolve().parents[1]
_BRAND = None


def _brand():
    """Load branding/make_branding.py once (palette, fonts, logo mark)."""
    global _BRAND
    if _BRAND is None:
        path = ROOT / "branding" / "make_branding.py"
        try:
            spec = importlib.util.spec_from_file_location("qc_brand", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod.font("CormorantGaramond.ttf", 20, 600)        # fail early if fonts are missing
            _BRAND = mod
        except Exception as exc:                              # noqa: BLE001
            print(f"    brand assets unavailable, using bold thumbnails: {exc}")
            _BRAND = False
    return _BRAND


def thumb_score(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((256, 256))
    hsv = ImageStat.Stat(im.convert("HSV"))
    gray = np.asarray(im.convert("L"), np.float32)
    # a bright subject surrounded by darkness reads well at small sizes
    contrast = gray.std()
    peak = np.percentile(gray, 99) - np.percentile(gray, 30)
    return hsv.mean[1] * 0.5 + contrast * 0.8 + peak * 0.4


def _subject_side(im):
    g = np.asarray(im.convert("L").resize((64, 36)), np.float32)
    cols = g.mean(axis=0)
    cx = (cols * np.arange(64)).sum() / max(cols.sum(), 1)
    return "left" if cx < 32 else "right"


def _split(text):
    words = text.upper().split()
    if len(words) >= 3:
        mid = (len(words) + 1) // 2
        return [" ".join(words[:mid]), " ".join(words[mid:])]
    return [" ".join(words)]


def _base(image_path, saturation, brightness):
    im = ImageOps.fit(Image.open(image_path).convert("RGB"), (W, H), Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.1)
    im = ImageEnhance.Color(im).enhance(saturation)
    im = ImageEnhance.Brightness(im).enhance(brightness)
    return ImageEnhance.Sharpness(im).enhance(1.2)


def _fit(b, lines, max_w, start, tracking_em, weight=600, name="CormorantGaramond.ttf"):
    size = start
    while size > 48:
        f = b.font(name, size, weight)
        if max(b.tracked_width(l, f, size * tracking_em) for l in lines) <= max_w:
            return f, size
        size -= 4
    return b.font(name, size, weight), size


def _glow(layer, radius, strength):
    a = layer.split()[3].filter(ImageFilter.GaussianBlur(radius))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(a.point(lambda v: int(v * strength)))
    return shadow


def _signature(b, img, x, y, align="left"):
    """Small logo mark + QUIET COSMOS wordmark, the constant element across thumbnails."""
    from .common import load_config
    ch = load_config()["channel"]
    f = b.font("Jost.ttf", 22, 500)
    word = ch.get("wordmark", "QUIET COSMOS")
    tw = b.tracked_width(word, f, 22 * 0.3)
    show_mark = ch.get("mark", "quiet-cosmos") == "quiet-cosmos"     # the moon mark is Quiet Cosmos's own logo
    mark = 46 if show_mark else -12
    total = mark + 12 + tw
    x0 = x if align == "left" else (x - total if align == "right" else x - total / 2)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    if show_mark:
        b.draw_mark(lay, x0 + mark / 2, y, mark * 1.6)
    b.tracked(ImageDraw.Draw(lay), (x0 + mark + 12, y - 15), word, f, b.STAR + (235,), 22 * 0.3)
    img.alpha_composite(_glow(lay, 6, 0.9))
    img.alpha_composite(lay)


def make_quiet(image_path, text, out_path):
    b = _brand()
    im = _base(image_path, 1.05, 0.92)
    side = "right" if _subject_side(im) == "left" else "left"
    # slide the photo away from the title so the subject stays visible
    moved = Image.new("RGB", (W, H), b.INK)
    moved.paste(im, (int(-0.22 * W) if side == "right" else int(0.22 * W), 0))
    im = moved
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    span = int(W * 0.9)                    # solid behind the title, then a long soft fade
    for i in range(span):
        x = i if side == "left" else W - 1 - i
        t = i / span
        v = 252 if t < 0.5 else 252 * (1 - (t - 0.5) / 0.5) ** 1.4
        d.line([(x, 0), (x, H)], fill=int(v))
    img = Image.composite(Image.new("RGB", (W, H), b.INK), im, shade).convert("RGBA")

    lines = _split(text)
    f, size = _fit(b, lines, W * 0.5, 150, 0.05)
    track = size * 0.05
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    cap = f.getbbox("H")[3] - f.getbbox("H")[1]
    gap = int(size * 0.28)
    block = len(lines) * cap + (len(lines) - 1) * gap
    y = (H - block) / 2 + 20
    margin = 72
    for i, line in enumerate(lines):
        lw = b.tracked_width(line, f, track)
        x = margin if side == "left" else W - margin - lw
        b.tracked(ld, (x, y - f.getbbox("H")[1]), line, f, b.STAR if i == 0 else b.ACCENT, track)
        y += cap + gap
    # thin gold rule under the title
    rx = margin if side == "left" else W - margin - 120
    ld.line([(rx, y + 6), (rx + 120, y + 6)], fill=b.ACCENT + (220,), width=3)
    img.alpha_composite(_glow(lay, 16, 0.85))
    img.alpha_composite(lay)
    _signature(b, img, margin if side == "left" else W - margin, 64, side)
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def make_centre(image_path, text, out_path):
    b = _brand()
    im = _base(image_path, 1.1, 0.95)
    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    start = int(H * 0.38)
    for yy in range(start, H):
        d.line([(0, yy), (W, yy)], fill=int(225 * ((yy - start) / (H - start)) ** 0.9))
    for yy in range(0, 120):                                  # light top fade for the signature
        d.line([(0, yy), (W, yy)], fill=max(shade.getpixel((0, yy)), int(150 * (1 - yy / 120))))
    img = Image.composite(Image.new("RGB", (W, H), b.INK), im, shade).convert("RGBA")

    lines = [" ".join(_split(text))]
    f, size = _fit(b, lines, W * 0.86, 140, 0.08)
    if size < 92 and len(_split(text)) > 1:                   # too long for one line: use two
        lines = _split(text)
        f, size = _fit(b, lines, W * 0.86, 120, 0.08)
    track = size * 0.08
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    cap = f.getbbox("H")[3] - f.getbbox("H")[1]
    gap = int(size * 0.26)
    y = H - 92 - len(lines) * cap - (len(lines) - 1) * gap
    for i, line in enumerate(lines):
        lw = b.tracked_width(line, f, track)
        fill = b.STAR if (i == 0 or len(lines) == 1) else b.ACCENT
        b.tracked(ld, ((W - lw) / 2, y - f.getbbox("H")[1]), line, f, fill, track)
        y += cap + gap
    ld.line([(W / 2 - 60, y + 4), (W / 2 + 60, y + 4)], fill=b.ACCENT + (220,), width=3)
    img.alpha_composite(_glow(lay, 16, 0.85))
    img.alpha_composite(lay)
    _signature(b, img, W / 2, 58, "centre")
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def make_bold(image_path, text, out_path):
    im = _base(image_path, 1.3, 1.0)
    side = "right" if _subject_side(im) == "left" else "left"     # text goes opposite the subject

    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    span = int(W * 0.62)
    for i in range(span):
        x = i if side == "left" else W - 1 - i
        d.line([(x, 0), (x, H)], fill=int(215 * (1 - i / span) ** 1.5))
    im = Image.composite(Image.new("RGB", (W, H), (2, 3, 12)), im, shade)

    lines = _split(text)
    size = 180
    while size > 60:
        f = font("black", size)
        if max(f.getlength(l) for l in lines) <= W * 0.56:
            break
        size -= 6
    f = font("black", size)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    y = (H - len(lines) * size * 1.02) / 2 - 10
    for i, line in enumerate(lines):
        lw = f.getlength(line)
        x = 64 if side == "left" else W - 64 - lw
        fill = (255, 255, 255, 255) if i == 0 else (255, 210, 90, 255)
        ld.text((x, y), line, font=f, fill=fill, stroke_width=6, stroke_fill=(0, 0, 0, 255))
        y += size * 1.02
    out = Image.alpha_composite(Image.alpha_composite(im.convert("RGBA"), _glow(layer, 18, 0.8)), layer)
    out.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


# Marca "DUERME" (Estrato Nocturno, 1-nov-2026). Copia del estilo que ganó el Test & Compare del maratón
# (C, ~44 % del tiempo de visualización): fondo negro, astro a la derecha, "DUERME" en Inter Black crema,
# segunda línea en lila y el sello fijo del canal (media luna lila + nombre) arriba a la izquierda.
# La esquina inferior derecha queda libre para la duración de YouTube.
CREAM, LILAC, NIGHT = (242, 238, 228), (142, 147, 217), (4, 6, 18)
LILAC_TEXT = (176, 180, 242)     # 2-nov: la 2.ª línea en un lila más claro (sobre imagen brillante no se leía)


def duerme_score(path):
    """Qué tan bien sirve una imagen para la miniatura DUERME: un astro nítido y brillante en un lado,
    el otro lado oscuro y vacío (el texto va ahí). Más alto = mejor. Mira los dos lados (se puede voltear)."""
    im = Image.open(path).convert("L")
    im.thumbnail((320, 320))
    g = np.asarray(im, np.float32)
    h, w = g.shape
    left, right = g[:, : int(w * 0.45)], g[:, int(w * 0.55):]
    if left.mean() > right.mean():
        left, right = right, left
    edges = np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean()      # nitidez
    subject = np.percentile(right, 97) - np.percentile(right, 40)                       # un astro que destaca
    return subject * 0.6 + edges * 2.0 - left.mean() * 1.6 - left.std() * 0.8


def _crescent(r):
    m = Image.new("L", (4 * r, 4 * r), 0)
    d = ImageDraw.Draw(m)
    d.ellipse([r, r, 3 * r, 3 * r], fill=255)
    d.ellipse([r + int(0.8 * r), r - int(0.25 * r), 3 * r + int(0.8 * r), 3 * r - int(0.25 * r)], fill=0)
    return m


def _reframe(im):
    """Astro sobre fondo oscuro: lo agranda (si se ve chico) y lo lleva al tercio derecho, como la luna ganadora.
    Solo si el fondo es oscuro de verdad (el relleno es negro y no se nota)."""
    g = np.asarray(im.convert("L"), np.float32)
    border = np.concatenate([g[:8].ravel(), g[-8:].ravel(), g[:, :8].ravel(), g[:, -8:].ravel()])
    if np.percentile(border, 90) > 40:
        return im
    mask = g > max(45.0, np.percentile(g, 99) * 0.35)
    ys, xs = np.nonzero(mask)
    if len(xs) < 200:
        return im
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    bw, bh, cx, cy = max(x1 - x0, 1), max(y1 - y0, 1), (x0 + x1) / 2, (y0 + y1) / 2
    # grande pero sin pasar de ~la mitad del cuadro (el texto ocupa la izquierda)
    k = max(0.6, min(2.2, 0.9 * H / bh, 0.42 * W / bw))
    big = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    bg = tuple(int(v) for v in np.median(np.asarray(im)[:8].reshape(-1, 3), axis=0))
    canvas = Image.new("RGB", (W, H), bg)
    # bordes fundidos con el fondo: si la imagen no cubre el cuadro, no se ve el rectángulo
    feather = Image.new("L", big.size, 0)
    fd = ImageDraw.Draw(feather)
    m = max(8, int(min(big.size) * 0.08))
    for i in range(m):
        fd.rectangle([i, i, big.width - 1 - i, big.height - 1 - i], outline=int(255 * (i + 1) / m))
    fd.rectangle([m, m, big.width - 1 - m, big.height - 1 - m], fill=255)
    canvas.paste(big, (round(0.795 * W - cx * k), round(0.5 * H - cy * k)), feather)
    return canvas


class ThumbnailError(RuntimeError):
    """La miniatura DUERME no se pudo hacer con una imagen real (todas planas, lisas o sin astro)."""


MIN_TEXTURE = 3.0          # 13-nov: detalle mínimo dentro del astro (círculo liso ≈ 0; Sol y Luna reales ≈ 8-20)


def _object_box(im):
    """Astro sobre fondo oscuro → (cx, cy, diámetro, máscara) en píxeles de `im`; None si no hay astro claro."""
    g = np.asarray(im.convert("L"), np.float32)
    border = np.concatenate([g[:8].ravel(), g[-8:].ravel(), g[:, :8].ravel(), g[:, -8:].ravel()])
    if np.median(border) > 40:                          # fondo claro: no es un astro aislado
        return None
    mask = g > max(30.0, np.percentile(g, 99) * 0.25)
    ys, xs = np.nonzero(mask)
    if len(xs) < 0.01 * g.size:
        return None
    x0, x1 = np.percentile(xs, [0.5, 99.5])
    y0, y1 = np.percentile(ys, [0.5, 99.5])
    return (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0, 1), mask


def texture_score(im, box=None):
    """Detalle real dentro del astro (cráteres, granulación, nubes…). Una forma plana da casi 0."""
    box = box or _object_box(im)
    if box is None:
        return 0.0
    g = np.asarray(im.convert("L"), np.float32)
    mask = Image.fromarray((box[3] * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(15))   # sin el borde
    inside = np.asarray(mask) > 0
    if inside.sum() < 500:
        return 0.0
    blur = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)), np.float32)
    return float(np.abs(g - blur)[inside].mean() * 4)


def _fit_disk(mask, seed=0):
    """Centro y radio del disco del astro: círculo (RANSAC) sobre el contorno de la máscara de brillo. Ignora
    contornos rectos (cortes de la imagen) y el terminador de una fase."""
    m = Image.fromarray((mask * 255).astype(np.uint8))
    edge = (np.asarray(m) > 0) & ~(np.asarray(m.filter(ImageFilter.MinFilter(3))) > 0)
    ys, xs = np.nonzero(edge)
    if len(xs) < 20:
        return None
    pts = np.stack([xs, ys], 1).astype(np.float64)
    mys, mxs = np.nonzero(mask)
    span = max(np.ptp(mxs), np.ptp(mys), 1)            # tamaño de lo visible
    rng = np.random.default_rng(seed)
    best, best_n = None, 0
    tol = max(2.0, 0.006 * max(mask.shape))
    for _ in range(400):
        a, b, c = pts[rng.choice(len(pts), 3, replace=False)]
        d = 2 * (a[0] * (b[1] - c[1]) + b[0] * (c[1] - a[1]) + c[0] * (a[1] - b[1]))
        if abs(d) < 1e-6:
            continue
        ux = ((a @ a) * (b[1] - c[1]) + (b @ b) * (c[1] - a[1]) + (c @ c) * (a[1] - b[1])) / d
        uy = ((a @ a) * (c[0] - b[0]) + (b @ b) * (a[0] - c[0]) + (c @ c) * (b[0] - a[0])) / d
        r = np.hypot(a[0] - ux, a[1] - uy)
        if not (0.25 * span < r < 0.8 * span):        # ni diminuto ni un "círculo" casi recto (corte)
            continue
        n = int((np.abs(np.hypot(pts[:, 0] - ux, pts[:, 1] - uy) - r) < tol).sum())
        if n > best_n:
            best, best_n = (ux, uy, r), n
    if best is None:
        return None
    ux, uy, r = best                                   # ajuste fino por mínimos cuadrados con los inliers
    inl = pts[np.abs(np.hypot(pts[:, 0] - ux, pts[:, 1] - uy) - r) < tol]
    A = np.c_[2 * inl, np.ones(len(inl))]
    sol, *_ = np.linalg.lstsq(A, (inl ** 2).sum(1), rcond=None)
    ux, uy = sol[0], sol[1]
    return ux, uy, float(np.sqrt(sol[2] + ux ** 2 + uy ** 2))


def _glow_radius(gray, cx, cy, r, bg):
    """Radio exterior del aro de brillo (corona/atmósfera): donde el brillo radial vuelve al fondo."""
    yy, xx = np.indices(gray.shape)
    dist = np.hypot(xx - cx, yy - cy)
    for rr in np.arange(r, 1.35 * r, max(1.0, r / 150)):
        ring = gray[(dist >= rr) & (dist < rr + max(1.0, r / 150))]
        if ring.size and ring.mean() < bg + 6:
            return rr + max(2.0, r / 100)
    return 1.35 * r


def make_duerme(image_path, line2, out_path, word="DUERME", wordmark="ESTRATO NOCTURNO", fill=1.56):
    """Formato C (13-nov-2026, Luis): astro REAL y detallado, ~120 % del alto, en los 2/3 derechos y cortado por
    arriba y abajo (como la luna del maratón qKVP9yXgbN0); puede pasar detrás del texto, que lleva una sombra
    oscura suave. Si la imagen es plana/lisa o no tiene un astro claro, lanza ThumbnailError (no se usa)."""
    name = pathlib.Path(image_path).name
    src = Image.open(image_path).convert("RGB")
    box = _object_box(src)
    if box is None:
        raise ThumbnailError(f"{name}: no hay un astro claro sobre fondo oscuro")
    tex = texture_score(src, box)
    if tex < MIN_TEXTURE:
        raise ThumbnailError(f"{name}: imagen plana o lisa (detalle {tex:.1f}, mínimo {MIN_TEXTURE})")
    cx, cy, diam, _ = box
    k = fill * H / diam
    # 13-nov: el negro de la imagen generada = el negro de la miniatura (se resta su fondo y se suma NIGHT)
    a_ = np.asarray(src, np.float32)
    srcbg = np.median(np.concatenate([a_[:8].reshape(-1, 3), a_[-8:].reshape(-1, 3),
                                      a_[:, :8].reshape(-1, 3), a_[:, -8:].reshape(-1, 3)]), axis=0)
    a_ = np.clip(a_ - srcbg, 0, 255)
    # 13-nov (Luis): el disco recortado en CÍRCULO con borde suave de ~8 px, incluyendo el aro de brillo;
    # fuera del círculo, el negro de la miniatura. Nunca una línea recta.
    gray = a_.mean(2)
    disk = _fit_disk(box[3])
    yy, xx = np.indices(gray.shape)
    if disk:
        dcx, dcy, r = disk
        r_out = _glow_radius(gray, dcx, dcy, r, 0.0)
        # el círculo tiene que contener todo lo brillante; si no, el ajuste no sirve
        if (np.hypot(xx - dcx, yy - dcy)[box[3]] <= r_out).mean() < 0.97:
            disk = None
    if disk:
        inside = np.hypot(xx - dcx, yy - dcy) < r
    else:                                              # fase sin disco claro: contorno de lo brillante
        inside = box[3]
    lit = inside & box[3]
    # interior muy oscuro (parte iluminada < 25 %): se sube con una curva hasta ver las texturas
    if lit.any() and gray[lit].mean() < 0.25 * 255:
        for gamma in np.arange(0.95, 0.45, -0.05):
            if (255 * (gray[lit] / 255) ** gamma).mean() >= 0.32 * 255:
                break
        a_ = 255 * (a_ / 255) ** gamma
    # 13-nov (Luis): MISMA posición y tamaño que la luna ganadora del maratón (branding/maraton/maraton_c.jpg,
    # medida): diámetro 1,56 × alto, borde derecho en 87 % del ancho, centro en 63 % del alto. El astro llena
    # el fondo y el texto va encima; se corta por arriba, abajo e izquierda.
    if disk:
        right, mid_y = dcx + r_out, dcy
    else:
        xs_ = np.nonzero(box[3])[1]
        right, mid_y = float(np.percentile(xs_, 99.5)), cy
    off_x = round(0.87 * W - right * k)
    off_y = round(0.63 * H - mid_y * k)
    big = Image.fromarray(np.clip(a_ + np.array(NIGHT, np.float32), 0, 255).astype(np.uint8))
    big = big.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS)
    yy, xx = np.indices((big.height, big.width))
    if disk:
        d = np.hypot(xx - dcx * k, yy - dcy * k)
        alpha = np.clip((r_out * k - d) / 8.0, 0, 1)    # borde suave de 8 px
    else:
        hull = Image.fromarray((box[3] * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
        hull = hull.resize(big.size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(4))
        alpha = np.asarray(hull, np.float32) / 255
    # bordes de la imagen pegada (si quedan dentro del cuadro): 8 px suaves
    e = np.minimum.reduce([xx, yy, big.width - 1 - xx, big.height - 1 - yy]).astype(np.float32)
    alpha *= np.clip(e / 8.0, 0, 1)
    feather = Image.fromarray((alpha * 255).astype(np.uint8))
    canvas = Image.new("RGB", (W, H), NIGHT)
    canvas.paste(big, (off_x, off_y), feather)
    im = ImageEnhance.Contrast(canvas).enhance(1.06)

    img = im.convert("RGBA")
    line2 = " ".join(line2.upper().split())
    big_f = font("black", 172)
    size2 = 86
    while size2 > 44 and font("semibold", size2).getlength(line2) > W * 0.58:
        size2 -= 4
    small = font("semibold", size2)
    x = 64
    bottom = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((x, 200), word, font=big_f)[3]

    # sombra oscura suave detrás de DUERME / EN MINUTOS para que se lea sobre el astro
    tmask = Image.new("L", (W, H), 0)
    td = ImageDraw.Draw(tmask)
    td.text((x, 200), word, font=big_f, fill=255)
    td.text((x + 4, bottom + 26), line2, font=small, fill=255)
    halo = tmask.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(38))
    halo = halo.point(lambda v: min(235, int(v * 1.6)))
    img = Image.composite(Image.new("RGBA", (W, H), NIGHT + (255,)), img, halo)

    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    cm = _crescent(20)
    lay.paste(Image.new("RGBA", cm.size, LILAC + (255,)), (x - 20, 24), cm)
    d.text((x + 44, 48), wordmark, font=font("semibold", 26), fill=LILAC + (235,))
    d.text((x, 200), word, font=big_f, fill=CREAM)
    d.text((x + 4, bottom + 26), line2, font=small, fill=LILAC_TEXT)
    img.alpha_composite(_glow(lay, 10, 0.8))
    img.alpha_composite(lay)
    img.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


# kept for any caller that used the old name
make_thumbnail = make_bold


def make_thumbnails(images, texts, out_dir, heroes=None):
    import hashlib
    seen, unique = set(), []
    for p in images:                                   # drop duplicate files
        h = hashlib.md5(open(p, "rb").read(1 << 20)).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(p)
    ranked = sorted(unique, key=thumb_score, reverse=True)
    if not ranked or not texts:
        return []
    from .common import load_config
    cfg = load_config()
    tc = cfg.get("thumbnail") or {}
    if tc.get("style") == "duerme":
        # 3 variantes de la misma marca para Test & Compare: cambia el astro y la frase, nunca el diseño
        # una imagen propia por variante (pintada para la miniatura); si falta, la mejor del episodio para DUERME
        pool = sorted(unique, key=duerme_score, reverse=True)
        fixed = tc.get("line2")
        wm = cfg["channel"].get("wordmark", cfg["channel"]["name"]).upper()
        if fixed:
            # 13-nov-2026 (formato C fijo): subtítulo siempre igual y UN astro real del tema, grande.
            # Primero las imágenes pintadas para la miniatura, luego las del episodio; las planas se descartan.
            own = [h for grp in (heroes or []) for h in grp if pathlib.Path(h).exists()]
            cands = sorted(own, key=duerme_score, reverse=True) + [p for p in pool if p not in own]
            paths, why = [], []
            for c in cands:
                p = out_dir / f"thumbnail_{len(paths) + 1}.jpg"
                try:
                    make_duerme(c, fixed, p, tc.get("word", "DUERME"), wm, tc.get("fill", 1.56))
                    paths.append(p)
                except ThumbnailError as exc:
                    why.append(str(exc))
                    print(f"   miniatura descartada: {exc}")
                if len(paths) == 3:
                    break
            if not paths:
                raise ThumbnailError("ninguna imagen sirve para la miniatura DUERME:\n  " + "\n  ".join(why[:12]))
            return paths
        picks = []
        for i in range(3):
            own = [h for h in (heroes or [[]] * 3)[i] if pathlib.Path(h).exists()] if heroes and i < len(heroes) else []
            if own:
                picks.append(max(own, key=duerme_score))
            else:
                picks.append(next((p for p in pool if p not in picks), pool[i % len(pool)]))
        paths = []
        for i in range(3):
            p = out_dir / f"thumbnail_{i + 1}.jpg"
            make_duerme(picks[i], texts[i % len(texts)], p, tc.get("word", "DUERME"),
                        cfg["channel"].get("wordmark", cfg["channel"]["name"]).upper())
            paths.append(p)
        return paths
    styles = [make_quiet, make_centre, make_bold] if _brand() else [make_bold] * 3
    paths = []
    for i, style in enumerate(styles):
        p = out_dir / f"thumbnail_{i + 1}.jpg"
        style(ranked[i % len(ranked)], texts[i % len(texts)], p)
        paths.append(p)
    return paths


def publish_web(thumbs, title, video_id, root, keep=12):
    """Copia las 3 miniaturas a web/miniaturas/ (Cloudflare Pages) y rehace la página con botones de descarga,
    para que Luis las baje desde el celular y las suba al Test & Compare de Studio."""
    import datetime
    import html
    import json
    import shutil
    base = pathlib.Path(root) / "web" / "miniaturas"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")
    folder = base / f"{stamp}-{video_id}"
    folder.mkdir(exist_ok=True)
    for i, t in enumerate(thumbs, 1):
        shutil.copy(t, folder / f"miniatura_{i}.jpg")
    index = base / "index.json"
    items = json.loads(index.read_text()) if index.exists() else []
    for old in [it for it in items if it["video_id"] == video_id]:      # una sola entrada por video (la última)
        if old["dir"] != folder.name:
            shutil.rmtree(base / old["dir"], ignore_errors=True)
    items = [it for it in items if it["video_id"] != video_id]
    items.insert(0, {"dir": folder.name, "title": title, "video_id": video_id, "n": len(thumbs),
                     "date": datetime.datetime.utcnow().strftime("%d-%m-%Y")})
    for old in items[keep:]:                                   # solo los últimos viajes, el repo no crece
        shutil.rmtree(base / old["dir"], ignore_errors=True)
    items = items[:keep]
    index.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    cards = []
    for it in items:
        imgs = "".join(
            f'<a class="t" href="{it["dir"]}/miniatura_{k}.jpg" download="miniatura_{k}.jpg">'
            f'<img src="{it["dir"]}/miniatura_{k}.jpg" loading="lazy"><span>Descargar {k}</span></a>'
            for k in range(1, it["n"] + 1))
        cards.append(f'<section><h2>{html.escape(it["title"])}</h2><p>{it["date"]} · '
                     f'<a href="https://studio.youtube.com/video/{it["video_id"]}/edit">Abrir en Studio</a></p>'
                     f'<div class="g">{imgs}</div></section>')
    (base / "index.html").write_text(
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        '<title>Miniaturas</title><style>body{margin:0;padding:16px;background:#05060f;color:#f2eee4;'
        'font-family:system-ui,sans-serif}h1{font-size:22px}h2{font-size:17px;margin:24px 0 4px}p{margin:0 0 10px;'
        'color:#8e93d9;font-size:14px}a{color:#8e93d9}.g{display:grid;grid-template-columns:repeat(auto-fit,'
        'minmax(240px,1fr));gap:10px}.t{display:block;text-decoration:none}.t img{width:100%;border-radius:8px;'
        'display:block}.t span{display:block;margin-top:6px;padding:10px;text-align:center;background:#8e93d9;'
        'color:#05060f;border-radius:8px;font-weight:700}</style></head><body><h1>Miniaturas para el A/B</h1>'
        + "".join(cards) + "</body></html>", encoding="utf-8")
    return folder
