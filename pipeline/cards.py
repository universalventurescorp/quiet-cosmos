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


# ---------- language-free QR panel (30-oct-2026) ----------
# No words on screen (YouTube dubs the channel into many languages). Each panel shows two paths: on the left the
# slow way (4 steps + hourglass, small and faded); on the right the QR as the obvious bargain (phone camera →
# lightning → result, 1 step). Dimmed for night viewing.
_NAVY = (22, 28, 70, 255)
_LAV = (178, 174, 206)
_GOLD = (255, 214, 120, 255)


def _p_phone(d, x, y, s, c, w):
    d.rounded_rectangle((x, y, x + s * 0.6, y + s), radius=s * 0.1, outline=c, width=w)
    d.line((x + s * 0.22, y + s * 0.08, x + s * 0.38, y + s * 0.08), fill=c, width=w)


def _p_keyboard(d, x, y, s, c, w):
    _p_phone(d, x, y, s, c, w)
    for r in range(3):
        for k in range(3):
            cx, cy = x + s * (0.13 + k * 0.13), y + s * (0.55 + r * 0.12)
            d.rectangle((cx, cy, cx + s * 0.08, cy + s * 0.07), fill=c)


def _p_camera(d, x, y, s, c, w):
    _p_phone(d, x, y, s, c, w)
    cx, cy, r = x + s * 0.3, y + s * 0.5, s * 0.13
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=c, width=w)
    d.ellipse((cx - s * 0.06, cy - s * 0.06, cx + s * 0.06, cy + s * 0.06), fill=c)


def _p_magnifier(d, x, y, s, c, w):
    r = s * 0.3
    d.ellipse((x, y, x + 2 * r, y + 2 * r), outline=c, width=w + 1)
    d.line((x + 1.7 * r, y + 1.7 * r, x + s * 0.9, y + s * 0.9), fill=c, width=w + 3)


def _p_list(d, x, y, s, c, w):
    for i in range(3):
        yy = y + s * (0.15 + i * 0.3)
        d.rectangle((x, yy, x + s * 0.2, yy + s * 0.18), fill=c)
        d.line((x + s * 0.3, yy + s * 0.09, x + s * 0.9, yy + s * 0.09), fill=c, width=w + 1)


def _p_bell(d, x, y, s, c, w):
    d.pieslice((x + s * 0.15, y + s * 0.1, x + s * 0.85, y + s * 0.9), 180, 360, fill=c)
    d.rectangle((x + s * 0.15, y + s * 0.5, x + s * 0.85, y + s * 0.72), fill=c)
    d.polygon([(x + s * 0.05, y + s * 0.78), (x + s * 0.95, y + s * 0.78),
               (x + s * 0.85, y + s * 0.68), (x + s * 0.15, y + s * 0.68)], fill=c)
    d.ellipse((x + s * 0.42, y + s * 0.8, x + s * 0.58, y + s * 0.96), fill=c)
    d.ellipse((x + s * 0.44, y, x + s * 0.56, y + s * 0.12), fill=c)


def _p_hourglass(d, x, y, s, c, w):
    d.line((x, y, x + s * 0.6, y), fill=c, width=w + 1)
    d.line((x, y + s, x + s * 0.6, y + s), fill=c, width=w + 1)
    d.polygon([(x + s * 0.05, y), (x + s * 0.55, y), (x + s * 0.3, y + s * 0.5)], outline=c, width=w)
    d.polygon([(x + s * 0.05, y + s), (x + s * 0.55, y + s), (x + s * 0.3, y + s * 0.5)], fill=c)


def _p_bolt(d, x, y, s, c, w):
    d.polygon([(x + s * 0.55, y), (x + s * 0.1, y + s * 0.58), (x + s * 0.45, y + s * 0.58),
               (x + s * 0.3, y + s), (x + s * 0.9, y + s * 0.38), (x + s * 0.55, y + s * 0.38)], fill=c)


def _p_chevron(d, x, y, s, c, w):
    d.line((x, y, x + s * 0.4, y + s * 0.5, x, y + s), fill=c, width=w + 1, joint="curve")


def _p_link(d, x, y, s, c, w):
    d.rounded_rectangle((x, y + s * 0.3, x + s * 0.55, y + s * 0.7), radius=s * 0.2, outline=c, width=w + 1)
    d.rounded_rectangle((x + s * 0.4, y + s * 0.3, x + s * 0.95, y + s * 0.7), radius=s * 0.2, outline=c, width=w + 1)


def _p_contacts(d, x, y, s, c, w):
    for i in range(2):
        ox = x + i * s * 0.42
        d.ellipse((ox + s * 0.12, y + s * 0.15, ox + s * 0.4, y + s * 0.43), fill=c)
        d.pieslice((ox, y + s * 0.5, ox + s * 0.52, y + s * 1.05), 180, 360, fill=c)


def _p_chat_heart(d, x, y, s, c, w):
    d.ellipse((x, y, x + s, y + s * 0.85), fill=c)
    d.polygon([(x + s * 0.15, y + s * 0.65), (x + s * 0.05, y + s), (x + s * 0.45, y + s * 0.8)], fill=c)
    hx, hy, hs = x + s * 0.27, y + s * 0.22, s * 0.46
    d.ellipse((hx, hy, hx + hs * 0.55, hy + hs * 0.55), fill=_GOLD)
    d.ellipse((hx + hs * 0.45, hy, hx + hs, hy + hs * 0.55), fill=_GOLD)
    d.polygon([(hx + hs * 0.02, hy + hs * 0.36), (hx + hs * 0.98, hy + hs * 0.36), (hx + hs * 0.5, hy + hs * 0.95)],
              fill=_GOLD)


def _p_dots(d, x, y, n, s, c):
    r, gap = 7 * s, 24 * s
    for i in range(n):
        d.ellipse((x + i * gap, y, x + i * gap + 2 * r, y + 2 * r), fill=c)


def qr_panel(W, H, url, kind, start, end):
    """kind="subscribe": slow path keyboard→search→list→bell vs QR→bell. kind="gift": slow path
    link→app→contacts→message vs QR inside a crescent moon → message with a heart. No text at all."""
    s = H / 1080
    w = max(2, int(round(4 * s)))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    X = int(60 * s)
    gift = kind == "gift"
    pw, ph = (760 if gift else 720) * s, (380 if gift else 330) * s
    Y = int(H - 50 * s - ph)
    ImageDraw.Draw(img).rounded_rectangle((X, Y, X + pw, Y + ph), radius=int(28 * s), fill=_LAV + (170,))

    # slow path, faded
    slow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(slow)
    i = 52 * s
    x0, y0 = X + 30 * s, Y + (120 if gift else 95) * s
    if gift:
        _p_link(d, x0, y0 + 4 * s, i, _NAVY, w); _p_chevron(d, x0 + 58 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_phone(d, x0 + 86 * s, y0, i, _NAVY, w); _p_chevron(d, x0 + 128 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_contacts(d, x0 + 156 * s, y0 + 2 * s, i, _NAVY, w); _p_chevron(d, x0 + 236 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_chat_heart(d, x0 + 262 * s, y0 + 2 * s, 46 * s, _NAVY, w)
    else:
        _p_keyboard(d, x0, y0, i, _NAVY, w); _p_chevron(d, x0 + 42 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_magnifier(d, x0 + 70 * s, y0 + 4 * s, i, _NAVY, w); _p_chevron(d, x0 + 128 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_list(d, x0 + 156 * s, y0 + 4 * s, i, _NAVY, w); _p_chevron(d, x0 + 214 * s, y0 + 14 * s, 22 * s, _NAVY, w)
        _p_bell(d, x0 + 240 * s, y0, i, _NAVY, w)
    _p_dots(d, x0 + 70 * s, y0 + 95 * s, 4, s, _NAVY)
    _p_hourglass(d, x0 + 180 * s, y0 + 85 * s, 34 * s, _NAVY, w)
    slow.putalpha(slow.split()[3].point(lambda v: v * 95 // 255))
    img.alpha_composite(slow)

    d = ImageDraw.Draw(img)
    d.line((X + (360 if gift else 345) * s, Y + 40 * s, X + (360 if gift else 345) * s, Y + ph - 40 * s),
           fill=_NAVY[:3] + (70,), width=max(1, int(2 * s)))
    light = _LAV + (255,)
    if gift:
        cx, cy, R = int(X + 530 * s), int(Y + 190 * s), int(165 * s)
        moon = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        md = ImageDraw.Draw(moon)
        mc = (196, 193, 214, 255)
        md.ellipse((cx - R, cy - R, cx + R, cy + R), fill=mc)
        md.ellipse((cx - R + 40 * s, cy - R - 10 * s, cx + R + 40 * s, cy + R - 10 * s), fill=(0, 0, 0, 0))
        md.ellipse((cx - R, cy - R, cx + R, cy + R), outline=mc, width=max(2, int(6 * s)))
        img.alpha_composite(moon)
        qr = _qr_image(url, 210 * s, dark=_NAVY, light=light)
        img.alpha_composite(qr, (int(cx - qr.size[0] / 2 + 10 * s), int(cy - qr.size[1] / 2)))
        d = ImageDraw.Draw(img)
        _p_camera(d, X + 700 * s, Y + 60 * s, 56 * s, _NAVY, w)
        _p_bolt(d, X + 702 * s, Y + 145 * s, 38 * s, _NAVY, w)
        _p_chat_heart(d, X + 695 * s, Y + 215 * s, 54 * s, _NAVY, w)
        _p_dots(d, X + 713 * s, Y + 300 * s, 1, s, _NAVY)
    else:
        qr = _qr_image(url, 270 * s, dark=_NAVY, light=light)
        img.alpha_composite(qr, (int(X + 370 * s), int(Y + 30 * s)))
        d = ImageDraw.Draw(img)
        _p_camera(d, X + 655 * s, Y + 40 * s, 62 * s, _NAVY, w)
        _p_bolt(d, X + 660 * s, Y + 130 * s, 40 * s, _NAVY, w)
        _p_bell(d, X + 650 * s, Y + 205 * s, 52 * s, _NAVY, w)
        _p_dots(d, X + 668 * s, Y + 285 * s, 1, s, _NAVY)
    return _to_overlay(img, start, end, 1.6, 1.6, shadow=False)
