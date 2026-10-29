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


_LABELS = {}


def ai_label(W, H, text, start, end):
    """Small, quiet lower-right note on AI-generated scenes (honest labelling, never distracting)."""
    key = (W, H, text)
    if key not in _LABELS:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        s = H / 1080
        f = font("regular", int(19 * s))
        label = text.upper()
        w = _spaced_width(label, f, 3 * s)
        _spaced(d, (W - 70 * s - w, H - 70 * s), label, f, (230, 234, 242, 175), 3 * s)
        _LABELS[key] = _to_overlay(img, 0, 0, 1.0, 0.8)
    ov = dict(_LABELS[key])
    ov.update(start=start, end=end)
    return ov


def source_line(W, H, text, start, end, y_frac=0.775):
    """Small "Source: NASA / Curiosity" pill near the end of a Short: proof without stealing focus.
    Sits above YouTube's bottom title area and left of the action buttons' column."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = W / 1080
    f = font("bold", int(40 * s))
    tw = f.getlength(text)
    while tw > W * 0.74 and f.size > 24 * s:
        f = font("bold", f.size - 2)
        tw = f.getlength(text)
    px, py = 30 * s, 16 * s
    x, y = (W - tw) / 2, H * y_frac
    asc, desc = f.getmetrics()
    d.rounded_rectangle((x - px, y - py, x + tw + px, y + asc + desc + py), radius=int(26 * s),
                        fill=(0, 0, 0, 165))
    d.text((x, y), text, font=f, fill=(255, 255, 255, 240))
    return _to_overlay(img, start, end, 0.4, 0.3, shadow=False)


def _qr_image(url, px, dark=(20, 24, 54, 255), light=(214, 216, 238, 255)):
    """QR code as an RGBA square of about px pixels (OpenCV's encoder: no extra dependency), quiet zone included."""
    import cv2
    p = cv2.QRCodeEncoder_Params()
    p.correction_level = cv2.QRCodeEncoder_CORRECT_LEVEL_L
    q = cv2.QRCodeEncoder.create(p).encode(url)          # 0 = dark module, 255 = light, with a 2-module border
    n = q.shape[0]
    k = max(2, int(px // n))
    img = Image.new("RGBA", (n * k, n * k), light)
    d = ImageDraw.Draw(img)
    for y in range(n):
        for x in range(n):
            if q[y, x] < 128:
                d.rectangle((x * k, y * k, x * k + k - 1, y * k + k - 1), fill=dark)
    return img


def qr_card(W, H, url, label, start, end, moon=False, opacity=0.74):
    """Small, quiet QR in the lower-left corner (the AI note lives lower-right). moon=True sets it inside a
    crescent moon ("regala una noche tranquila"). Shown once, for a few seconds, never bright."""
    s = H / 1080
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    qr = _qr_image(url, 224 * s)
    q = qr.size[0]
    x0, y_bottom = int(96 * s), int(H - 92 * s)
    f = font("light", int(23 * s))
    if moon:
        r = int(q * 0.86)                                  # crescent cradling the code on its left side
        cx, cy = x0 + r, y_bottom - int(46 * s) - r
        disc = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(disc).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
        cut = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(cut).ellipse((int(r * 0.42), -int(r * 0.08), int(r * 0.42) + 2 * r, int(r * 0.08) + 2 * r), fill=255)
        mask = Image.fromarray(np.clip(np.array(disc, np.int16) - np.array(cut, np.int16), 0, 255).astype(np.uint8))
        m = int(30 * s)                                    # room for the glow (no clipped edges)
        big = Image.new("L", (2 * r + 2 * m, 2 * r + 2 * m), 0)
        big.paste(mask, (m, m))
        glow = big.filter(ImageFilter.GaussianBlur(radius=int(16 * s)))
        layer = Image.new("RGBA", big.size, (246, 236, 205, 0))
        layer.putalpha(glow.point(lambda v: int(v * 0.28)))
        img.alpha_composite(layer, (cx - r - m, cy - r - m))
        moon_l = Image.new("RGBA", (2 * r, 2 * r), (240, 230, 200, 0))
        moon_l.putalpha(mask.point(lambda v: int(v * 0.62)))
        img.alpha_composite(moon_l, (cx - r, cy - r))
        qx, qy = cx - q // 2 + int(r * 0.30), cy - q // 2
        ty = cy + r + int(14 * s)
    else:
        qx, qy = x0, y_bottom - int(46 * s) - q
        ty = qy + q + int(14 * s)
    plate = Image.new("L", (q, q), 0)
    ImageDraw.Draw(plate).rounded_rectangle((0, 0, q - 1, q - 1), radius=int(10 * s), fill=255)
    qr.putalpha(plate)
    img.alpha_composite(qr, (qx, qy))
    d.text((x0, ty), label, font=f, fill=(236, 238, 245, 230))
    if opacity < 1:
        a = img.split()[3].point(lambda v: int(v * opacity))
        img.putalpha(a)
    return _to_overlay(img, start, end, 1.6, 1.6, shadow=False)
