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
    f = b.font("Jost.ttf", 22, 500)
    word = "QUIET COSMOS"
    tw = b.tracked_width(word, f, 22 * 0.3)
    mark = 46
    total = mark + 12 + tw
    x0 = x if align == "left" else (x - total if align == "right" else x - total / 2)
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
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


# kept for any caller that used the old name
make_thumbnail = make_bold


def make_thumbnails(images, texts, out_dir):
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
    styles = [make_quiet, make_centre, make_bold] if _brand() else [make_bold] * 3
    paths = []
    for i, style in enumerate(styles):
        p = out_dir / f"thumbnail_{i + 1}.jpg"
        style(ranked[i % len(ranked)], texts[i % len(texts)], p)
        paths.append(p)
    return paths
