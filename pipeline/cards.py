"""Typography overlays: opening title, chapter cards, end card, Shorts captions.
Each overlay is an RGBA patch (cropped to its bounding box) with timing, for engine.blend_overlay."""
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .fonts import font


def _spaced(draw, xy, text, fnt, fill, spacing):
    """Draw text with letter-spacing (tracking)."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += fnt.getlength(ch) + spacing
    return x


def _spaced_width(text, fnt, spacing):
    return sum(fnt.getlength(c) for c in text) + spacing * max(0, len(text) - 1)


def _to_overlay(img, start, end, fade_in=1.2, fade_out=1.2, shadow=True, scrim=0):
    """Add a soft shadow (and optionally a feathered dark scrim) for legibility; crop to the drawn area."""
    if scrim:
        bb = img.getbbox()
        if bb:
            m = int(img.height * 0.11)
            sc = Image.new("L", img.size, 0)
            ImageDraw.Draw(sc).rounded_rectangle(
                (bb[0] - m, bb[1] - m, bb[2] + m, bb[3] + m), radius=m, fill=scrim)
            sc = sc.filter(ImageFilter.GaussianBlur(radius=m * 0.8))
            layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
            layer.putalpha(sc)
            img = Image.alpha_composite(layer, img)
    if shadow:
        a = img.split()[3].filter(ImageFilter.GaussianBlur(radius=max(4, img.width // 300)))
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sh.putalpha(a.point(lambda v: int(v * 0.75)))
        img = Image.alpha_composite(sh, img)
    bbox = img.getbbox() or (0, 0, 2, 2)
    pad = 24 if not scrim else int(img.height * 0.2)
    x0, y0 = max(0, bbox[0] - pad), max(0, bbox[1] - pad)
    x1, y1 = min(img.width, bbox[2] + pad), min(img.height, bbox[3] + pad)
    arr = np.array(img.crop((x0, y0, x1, y1)))
    return {"rgba": arr, "bbox": (x0, y0, x1, y1), "start": start, "end": end,
            "fade_in": fade_in, "fade_out": fade_out}


def _wrap(text, fnt, max_w, spacing=0):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if cur and _spaced_width(test, fnt, spacing) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def opening_title(W, H, channel, title, start, end):
    """Centered: CHANNEL NAME (tracked caps), thin rule, episode title."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = H / 1080
    f1 = font("light", int(30 * s))
    track = 14 * s
    name = channel.upper()
    w1 = _spaced_width(name, f1, track)
    y = H * 0.40
    _spaced(d, ((W - w1) / 2, y), name, f1, (235, 238, 245, 255), track)
    y += 62 * s
    d.line([(W / 2 - 70 * s, y), (W / 2 + 70 * s, y)], fill=(235, 238, 245, 170), width=max(1, int(2 * s)))
    y += 34 * s
    main = title.split("|")[0].strip()
    f2 = font("thin", int(66 * s))
    for line in _wrap(main, f2, W * 0.7):
        lw = f2.getlength(line)
        d.text(((W - lw) / 2, y), line, font=f2, fill=(255, 255, 255, 255))
        y += 80 * s
    return _to_overlay(img, start, end, 1.8, 1.8)


def chapter_card(W, H, number, title, start, end):
    """Lower-left: small tracked 'CHAPTER ONE', title below."""
    words = ["ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE", "TEN",
             "ELEVEN", "TWELVE", "THIRTEEN", "FOURTEEN", "FIFTEEN"]
    label = f"CHAPTER {words[number - 1] if number <= len(words) else number}"
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = H / 1080
    x, y = 110 * s, H - 250 * s
    f1 = font("regular", int(22 * s))
    _spaced(d, (x, y), label, f1, (225, 230, 240, 230), 8 * s)
    d.line([(x, y + 42 * s), (x + 46 * s, y + 42 * s)], fill=(225, 230, 240, 200), width=max(1, int(2 * s)))
    f2 = font("light", int(54 * s))
    y += 62 * s
    for line in _wrap(title, f2, W * 0.55)[:2]:
        d.text((x, y), line, font=f2, fill=(255, 255, 255, 255))
        y += 64 * s
    return _to_overlay(img, start, end, 1.4, 1.6, scrim=120)


def end_card(W, H, channel, line, start, end):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = H / 1080
    f1 = font("light", int(30 * s))
    name = channel.upper()
    w1 = _spaced_width(name, f1, 14 * s)
    _spaced(d, ((W - w1) / 2, H * 0.45), name, f1, (235, 238, 245, 255), 14 * s)
    f2 = font("thin", int(30 * s))
    lw = f2.getlength(line)
    d.text(((W - lw) / 2, H * 0.45 + 60 * s), line, font=f2, fill=(220, 225, 235, 220))
    return _to_overlay(img, start, end, 2.0, 2.0)


def caption(W, H, text, start, end, y_frac=0.66):
    """Bold, high-contrast caption for vertical Shorts."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = W / 1080
    f = font("black", int(74 * s))
    lines = _wrap(text, f, W * 0.84)
    y = H * y_frac - len(lines) * 44 * s
    for line in lines:
        lw = f.getlength(line)
        d.text(((W - lw) / 2, y), line, font=f, fill=(255, 255, 255, 255),
               stroke_width=int(7 * s), stroke_fill=(0, 0, 0, 255))
        y += 90 * s
    return _to_overlay(img, start, end, 0.08, 0.08, shadow=False)


def short_hook(W, H, text, start, end):
    """Big top-of-frame hook for the first seconds of a Short."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = W / 1080
    f = font("black", int(68 * s))
    y = H * 0.12
    for line in _wrap(text.upper(), f, W * 0.86):
        lw = f.getlength(line)
        d.text(((W - lw) / 2, y), line, font=f, fill=(255, 214, 92, 255),
               stroke_width=int(6 * s), stroke_fill=(0, 0, 0, 255))
        y += 82 * s
    return _to_overlay(img, start, end, 0.2, 0.4, shadow=False)
