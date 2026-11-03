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


def make_duerme(image_path, line2, out_path, word="DUERME", wordmark="ESTRATO NOCTURNO"):
    im = ImageOps.fit(Image.open(image_path).convert("RGB"), (W, H), Image.LANCZOS)
    if _subject_side(im) == "left":                  # el astro siempre a la derecha, lejos del texto
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    im = _reframe(im)
    im = ImageEnhance.Contrast(im).enhance(1.06)
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):                     # 2-nov: casi negro detrás del texto, sea cual sea la imagen
        t = x / W
        v = 238 if t < 0.34 else 238 * max(0.0, 1 - (t - 0.34) / 0.28) ** 1.5
        sd.line([(x, 0), (x, H)], fill=int(v))
    img = Image.composite(Image.new("RGB", (W, H), NIGHT), im, shade).convert("RGBA")

    line2 = " ".join(line2.upper().split())
    big = font("black", 172)
    size2 = 86
    while size2 > 44 and font("semibold", size2).getlength(line2) > W * 0.58:
        size2 -= 4
    small = font("semibold", size2)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    x = 64
    m = _crescent(20)
    lay.paste(Image.new("RGBA", m.size, LILAC + (255,)), (x - 20, 24), m)
    d.text((x + 44, 48), wordmark, font=font("semibold", 26), fill=LILAC + (235,))
    d.text((x, 200), word, font=big, fill=CREAM)
    bottom = d.textbbox((x, 200), word, font=big)[3]
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
