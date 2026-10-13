"""Three 1280x720 thumbnail variants: vivid subject + big text on the calmer side of the frame.
Variant 1 is uploaded; the others are kept for YouTube Studio's "Test & compare"."""
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps, ImageStat

from .fonts import font

W, H = 1280, 720


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


def make_thumbnail(image_path, text, out_path):
    im = ImageOps.fit(Image.open(image_path).convert("RGB"), (W, H), Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.15)
    im = ImageEnhance.Color(im).enhance(1.3)
    im = ImageEnhance.Sharpness(im).enhance(1.3)
    side = "right" if _subject_side(im) == "left" else "left"     # text goes opposite the subject

    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    span = int(W * 0.62)
    for i in range(span):
        x = i if side == "left" else W - 1 - i
        d.line([(x, 0), (x, H)], fill=int(215 * (1 - i / span) ** 1.5))
    im = Image.composite(Image.new("RGB", (W, H), (2, 3, 12)), im, shade)

    words = text.upper().split()
    if len(words) >= 3:
        mid = (len(words) + 1) // 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
    else:
        lines = [" ".join(words)]
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
    glow = layer.split()[3].filter(ImageFilter.GaussianBlur(18))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(glow.point(lambda v: int(v * 0.8)))
    out = Image.alpha_composite(Image.alpha_composite(im.convert("RGBA"), shadow), layer)
    out.convert("RGB").save(out_path, "JPEG", quality=92)
    return out_path


def make_thumbnails(images, texts, out_dir):
    import hashlib
    seen, unique = set(), []
    for p in images:                                   # drop duplicate files
        h = hashlib.md5(open(p, "rb").read(1 << 20)).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(p)
    ranked = sorted(unique, key=thumb_score, reverse=True)
    paths = []
    for i, text in enumerate(texts[:3]):
        if not ranked:
            break
        p = out_dir / f"thumbnail_{i + 1}.jpg"
        make_thumbnail(ranked[i % len(ranked)], text, p)
        paths.append(p)
    return paths
