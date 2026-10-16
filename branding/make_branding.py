"""Render the Quiet Cosmos channel identity as upload-ready PNGs.

    python branding/make_branding.py          # writes branding/out/*.png

Outputs (YouTube Studio > Customisation > Profile):
  profile_800.png    profile picture, 800x800 (shown as a circle)
  banner_2560x1440.png  banner; all text sits inside the 1546x423 safe area
  watermark_150.png  video watermark, transparent PNG

Fonts: Cormorant Garamond and Jost (SIL Open Font License), in branding/fonts/.
"""
import math
import pathlib
import random

from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"

INK = (11, 15, 26)          # night sky
PLANET = (20, 27, 46)       # unlit planet
STAR = (232, 228, 216)      # warm starlight
SOFT = (201, 196, 182)      # secondary text
ACCENT = (233, 184, 114)    # soft gold


def font(name, size, weight):
    f = ImageFont.truetype(str(HERE / "fonts" / name), size)
    f.set_variation_by_axes([weight])
    return f


def _layer(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def draw_mark(base, cx, cy, size, accent=ACCENT, bg_disc=None):
    """Planet + crescent + tilted orbit. Geometry in an 800-unit box centred on (cx, cy)."""
    k = size / 800
    W, H = base.size

    def orbit_layer(width, alpha, front_only):
        lay = _layer((W, H))
        d = ImageDraw.Draw(lay)
        box = (cx - 312 * k, cy - 80 * k, cx + 312 * k, cy + 80 * k)
        col = accent + (int(255 * alpha),)
        if front_only:
            d.arc(box, 0, 180, fill=col, width=max(1, round(width * k)))
            r = 13 * k * (width / 5)
            sx, sy = cx + 250 * k, cy + 47.8 * k
            d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=accent + (255,))
        else:
            d.ellipse(box, outline=col, width=max(1, round(width * k)))
        return lay.rotate(18, resample=Image.BICUBIC, center=(cx, cy))

    if bg_disc is not None:
        lay = _layer((W, H))
        r = 390 * k
        ImageDraw.Draw(lay).ellipse((cx - r, cy - r, cx + r, cy + r), fill=bg_disc)
        base.alpha_composite(lay)

    base.alpha_composite(orbit_layer(4 if bg_disc is None else 14, 0.55, False))

    lay = _layer((W, H))
    d = ImageDraw.Draw(lay)
    r = 196 * k
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PLANET + (255,))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=STAR + (46,), width=max(1, round(2 * k)))
    base.alpha_composite(lay)

    mask = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    r2, ox, oy = 186 * k, cx + 52 * k, cy - 48 * k
    md.ellipse((ox - r2, oy - r2, ox + r2, oy + r2), fill=0)
    lit = Image.new("RGBA", (W, H), STAR + (255,))
    lit.putalpha(mask)
    base.alpha_composite(lit)

    base.alpha_composite(orbit_layer(5 if bg_disc is None else 18, 1.0, True))


def starfield(img, n, seed, avoid=None, dim=None, scale=1.0):
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    W, H = img.size
    for _ in range(n):
        x, y = rnd.random() * W, rnd.random() * H
        r = (0.6 + rnd.random() * rnd.random() * 2.4) * scale
        a = 0.18 + rnd.random() * 0.65
        if avoid and avoid(x, y):
            continue
        if dim and dim(x, y):
            a *= 0.35
        d.ellipse((x - r, y - r, x + r, y + r), fill=STAR + (int(255 * a),))


def tracked(draw, xy, text, f, fill, tracking):
    """Draw text with letter-spacing (tracking in px). Returns end x."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking
    return x - tracking


def tracked_width(text, f, tracking):
    return sum(f.getlength(c) for c in text) + tracking * (len(text) - 1)


def profile(ss=4):
    S = 800 * ss
    img = Image.new("RGBA", (S, S), INK + (255,))
    starfield(img, 70, 7, avoid=lambda x, y: math.hypot(x - S / 2, y - S / 2) < 240 * ss, scale=ss * 1.4)
    draw_mark(img, S / 2, S / 2, S)
    return img.resize((800, 800), Image.LANCZOS).convert("RGB")


def watermark(ss=8):
    S = 150 * ss
    img = _layer((S, S))
    draw_mark(img, S / 2, S / 2, S, bg_disc=INK + (217,))
    return img.resize((150, 150), Image.LANCZOS)


def banner(ss=2):
    W, H = 2560 * ss, 1440 * ss
    img = Image.new("RGBA", (W, H), INK + (255,))
    safe = (507 * ss, 508 * ss, 2053 * ss, 932 * ss)
    starfield(img, 520, 11, scale=ss,
              avoid=lambda x, y: safe[0] + 120 * ss < x < safe[2] - 40 * ss and safe[1] + 60 * ss < y < safe[3] - 60 * ss)

    # big planet bottom-right, outside the safe area (desktop/TV only)
    big = _layer((W, H))
    draw_mark(big, 2530 * ss, 1240 * ss, 1960 * ss)
    img.alpha_composite(big)

    # small moon top-left
    m = Image.new("L", (W, H), 0)
    md = ImageDraw.Draw(m)
    cx, cy, r = 360 * ss, 270 * ss, 78 * ss
    md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=140)
    md.ellipse((cx + 22 * ss - 74 * ss, cy - 16 * ss - 74 * ss, cx + 22 * ss + 74 * ss, cy - 16 * ss + 74 * ss), fill=0)
    moon = Image.new("RGBA", (W, H), STAR + (255,))
    moon.putalpha(m)
    img.alpha_composite(moon)

    # centred lockup inside the safe area
    title_f = font("CormorantGaramond.ttf", 124 * ss, 300)
    tag_f = font("Jost.ttf", 40 * ss, 300)
    sched_f = font("Jost.ttf", 28 * ss, 400)
    title, tag, sched = "QUIET COSMOS", "Slow space documentaries to relax, wonder and fall asleep", "NEW EPISODES EVERY WEEK"
    t_track, s_track = 124 * ss * 0.12, 28 * ss * 0.32
    tw = max(tracked_width(title, title_f, t_track), tag_f.getlength(tag), tracked_width(sched, sched_f, s_track))
    mark, gap = 330 * ss, 40 * ss
    total = mark + gap + tw
    x0 = (safe[0] + safe[2]) / 2 - total / 2
    cy = (safe[1] + safe[3]) / 2

    draw_mark(img, x0 + mark / 2, cy, mark)

    d = ImageDraw.Draw(img)
    tx = x0 + mark + gap
    t_asc, t_desc = title_f.getmetrics()
    cap_h = title_f.getbbox("Q")[3] - title_f.getbbox("Q")[1]
    block_h = cap_h + 34 * ss + 40 * ss + 30 * ss + 28 * ss
    top = cy - block_h / 2
    tracked(d, (tx, top - title_f.getbbox("Q")[1]), title, title_f, STAR, t_track)
    y = top + cap_h + 34 * ss
    d.text((tx, y - tag_f.getbbox("S")[1]), tag, font=tag_f, fill=SOFT)
    y += 40 * ss + 30 * ss
    tracked(d, (tx, y - sched_f.getbbox("N")[1]), sched, sched_f, ACCENT, s_track)

    assert x0 >= safe[0] and x0 + total <= safe[2], "lockup overflows the safe area"
    return img.resize((2560, 1440), Image.LANCZOS).convert("RGB")


def main():
    OUT.mkdir(exist_ok=True)
    profile().save(OUT / "profile_800.png", optimize=True)
    watermark().save(OUT / "watermark_150.png", optimize=True)
    banner().save(OUT / "banner_2560x1440.png", optimize=True)
    for p in sorted(OUT.glob("*.png")):
        print(f"{p.name}: {p.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
