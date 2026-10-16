"""Estrato network identity: turn the photoreal candidates painted on Kaggle into upload-ready files.

    python branding/estrato.py sheets                 # contact sheets of every candidate (to choose)
    python branding/estrato.py render nocturno_avatar_p1_s2 ...   # finals for the chosen candidates

Every channel shares one recipe so the network reads as a family: photoreal picture, a ring in the
channel's color around the avatar, and the same title lockup on the banner
(ESTRATO small in the channel color, the channel word large in Cormorant Garamond).
Candidates live in branding/candidates/<slot>/ (branch branding-candidates); finals go to branding/estrato/.
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

HERE = pathlib.Path(__file__).resolve().parent
CAND = HERE / "candidates"
OUT = HERE / "estrato"

STAR = (232, 228, 216)
SOFT = (214, 209, 197)
CHANNELS = {
    "nocturno": {"word": "NOCTURNO", "color": "#8E93D9",
                 "tag": "Documentales del espacio para relajarte y dormir",
                 "sched": "NUEVOS EPISODIOS CADA SEMANA"},
    "salvaje": {"word": "SALVAJE", "color": "#E0A43A",
                "tag": "La historia de la Tierra, contada como una película",
                "sched": "NUEVOS EPISODIOS CADA SEMANA"},
    "cosmos": {"word": "QUIET COSMOS", "top": None, "big": 124, "color": "#E9B872",
               "tag": "Slow space documentaries to relax, wonder and fall asleep",
               "sched": "NEW EPISODES EVERY WEEK"},
    "perdido": {"word": "PERDIDO", "color": "#D27A4B", "tag": "Civilizaciones perdidas",
                "sched": "PRÓXIMAMENTE"},
    "vivo": {"word": "VIVO", "color": "#7BB662", "tag": "La vida en la Tierra hoy", "sched": "PRÓXIMAMENTE"},
    "futuro": {"word": "FUTURO", "color": "#4FC3D9", "tag": "Lo que viene", "sched": "PRÓXIMAMENTE"},
}


def rgb(hexcode):
    h = hexcode.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(name, size, weight):
    f = ImageFont.truetype(str(HERE / "fonts" / name), round(size))
    f.set_variation_by_axes([weight])
    return f


def cover(img, w, h, focus=(0.5, 0.5)):
    k = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    x = round((img.width - w) * focus[0])
    y = round((img.height - h) * focus[1])
    return img.crop((x, y, x + w, y + h))


def tracked(draw, x, y, text, f, fill, tracking):
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking


def tracked_width(text, f, tracking):
    return sum(f.getlength(c) for c in text) + tracking * (len(text) - 1)


# ---------------------------------------------------------------- avatar
def avatar(src, channel, ss=3, zoom=1.0, focus=(0.5, 0.5)):
    """800x800; YouTube shows it as a circle, so the ring sits right at the circle's edge."""
    color = rgb(CHANNELS[channel]["color"])
    S = 800 * ss
    img = Image.open(src).convert("RGB")
    pic = cover(img, round(S * zoom), round(S * zoom), focus)
    if zoom != 1.0:
        pic = cover(pic, S, S)
    pic = ImageEnhance.Contrast(pic).enhance(1.05).convert("RGBA")

    base = Image.new("RGBA", (S, S), (10, 12, 20, 255))
    r_out = S / 2
    ring_w, gap = 26 * ss, 6 * ss
    r_pic = r_out - ring_w - gap
    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse((S / 2 - r_pic, S / 2 - r_pic, S / 2 + r_pic, S / 2 + r_pic), fill=255)
    base.paste(pic, (0, 0), m)

    lay = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(lay)
    d.ellipse((0, 0, S - 1, S - 1), outline=color + (255,), width=ring_w)
    # a hairline of light on the ring's inner edge, like a planet's rim
    ri = r_out - ring_w
    d.ellipse((S / 2 - ri, S / 2 - ri, S / 2 + ri, S / 2 + ri), outline=STAR + (90,), width=max(1, ss))
    base.alpha_composite(lay)
    return base.resize((800, 800), Image.LANCZOS).convert("RGB")


# ---------------------------------------------------------------- banner
def banner(src, channel, ss=1, focus=(0.5, 0.5)):
    """2560x1440; title lockup inside the 1546x423 area that every device shows."""
    ch = CHANNELS[channel]
    color = rgb(ch["color"])
    W, H = 2560 * ss, 1440 * ss
    img = cover(Image.open(src).convert("RGB"), W, H, focus)
    img = ImageEnhance.Brightness(img).enhance(0.82).convert("RGBA")

    # soft dark ellipse behind the title so it reads on any picture
    shade = Image.new("L", (W, H), 0)
    ImageDraw.Draw(shade).ellipse((W * 0.27, H * 0.37, W * 0.73, H * 0.63), fill=170)
    shade = shade.filter(ImageFilter.GaussianBlur(110 * ss))
    dark = Image.new("RGBA", (W, H), (6, 8, 14, 255))
    dark.putalpha(shade)
    img.alpha_composite(dark)

    d = ImageDraw.Draw(img)
    cx, cy = W / 2, H / 2
    small = font("Jost.ttf", 34 * ss, 400)
    top = ch.get("top", "ESTRATO")
    big = font("CormorantGaramond.ttf", ch.get("big", 150) * ss, 300)
    tag = font("Jost.ttf", 40 * ss, 300)
    sched = font("Jost.ttf", 26 * ss, 400)
    s_tr, b_tr, c_tr = 34 * ss * 0.62, ch.get("big", 150) * ss * 0.1, 26 * ss * 0.34
    cap = lambda f, t: f.getbbox(t)[3] - f.getbbox(t)[1]
    h_small, h_big, h_tag, h_sched = cap(small, "E"), cap(big, "N"), cap(tag, "Dl"), cap(sched, "N")
    g1, g2, g3 = 30 * ss, 46 * ss, 28 * ss
    if not top:
        h_small = g1 = 0
    total = h_small + g1 + h_big + g2 + h_tag + g3 + h_sched
    y = cy - total / 2

    w = tracked_width(top or "", small, s_tr)
    if top:
        tracked(d, cx - w / 2, y - small.getbbox("E")[1], top, small, color, s_tr)
    # thin rules either side of ESTRATO, the network's signature
    for side in ((-1, 1) if top else ()):
        x1 = cx + side * (w / 2 + 28 * ss)
        x2 = x1 + side * 90 * ss
        d.line((min(x1, x2), y + h_small / 2, max(x1, x2), y + h_small / 2), fill=color + (200,), width=2 * ss)
    y += h_small + g1
    w = tracked_width(ch["word"], big, b_tr)
    tracked(d, cx - w / 2, y - big.getbbox("N")[1], ch["word"], big, STAR, b_tr)
    y += h_big + g2
    d.text((cx - tag.getlength(ch["tag"]) / 2, y - tag.getbbox("Dl")[1]), ch["tag"], font=tag, fill=SOFT)
    y += h_tag + g3
    w = tracked_width(ch["sched"], sched, c_tr)
    tracked(d, cx - w / 2, y - sched.getbbox("N")[1], ch["sched"], sched, color, c_tr)
    assert total < 423 * ss, "lockup taller than the safe area"
    assert tracked_width(ch["word"], big, b_tr) < 1500 * ss, "title wider than the safe area"
    return img.convert("RGB")


def safe_preview(banner_img):
    """What each device shows: TV = all, desktop = 2560x423 strip, phone = 1546x423 centre."""
    im = banner_img.copy()
    d = ImageDraw.Draw(im, "RGBA")
    d.rectangle((0, 508, 2559, 931), outline=(255, 255, 255, 140), width=4)
    d.rectangle((507, 508, 2052, 931), outline=(255, 210, 80, 220), width=4)
    return im


# ---------------------------------------------------------------- contact sheets
def sheets():
    OUT.mkdir(exist_ok=True)
    for slot_dir in sorted(p for p in CAND.iterdir() if p.is_dir()):
        files = sorted(slot_dir.glob("*.jpg"))
        if not files:
            continue
        channel = slot_dir.name.split("_")[0]
        is_avatar = slot_dir.name.endswith("avatar")
        tiles = []
        for f in files:
            t = avatar(f, channel, ss=1).resize((400, 400)) if is_avatar else \
                banner(f, channel).resize((640, 360), Image.LANCZOS)
            lab = ImageDraw.Draw(t)
            lab.rectangle((0, 0, 150, 30), fill=(0, 0, 0))
            lab.text((8, 6), f.stem.split("_", 2)[2], fill=(255, 255, 255))
            tiles.append(t)
        cols = 4
        tw, th = tiles[0].size
        rows = (len(tiles) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tw + (cols + 1) * 10, rows * th + (rows + 1) * 10), (30, 30, 30))
        for i, t in enumerate(tiles):
            sheet.paste(t, (10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 10)))
        sheet.save(OUT / f"sheet_{slot_dir.name}.jpg", quality=88)
        print(f"sheet_{slot_dir.name}.jpg  ({len(files)} candidates)")


def render(ids):
    OUT.mkdir(exist_ok=True)
    for cid in ids:
        slot = cid.split("_p")[0]
        channel = slot.split("_")[0]
        src = CAND / slot / f"{cid}.jpg"
        if slot.endswith("avatar"):
            avatar(src, channel).save(OUT / f"{cid}_avatar_800.png", optimize=True)
        else:
            b = banner(src, channel)
            b.save(OUT / f"{cid}_banner_2560x1440.jpg", quality=93)
            safe_preview(b).resize((1280, 720), Image.LANCZOS).save(OUT / f"{cid}_banner_safe_preview.jpg",
                                                                    quality=85)
        print("rendered", cid)


FINAL = HERE / "out"
NAMES = {"nocturno": "estrato_nocturno", "salvaje": "estrato_salvaje", "cosmos": "quiet_cosmos_photo"}


def final(ids):
    """Upload-ready files for the chosen candidates, kept in branding/out/ (tracked in git)."""
    for cid in ids:
        slot = cid.split("_p")[0]
        channel = slot.split("_")[0]
        src = CAND / slot / f"{cid}.jpg"
        name = NAMES[channel]
        if slot.endswith("avatar"):
            avatar(src, channel).save(FINAL / f"{name}_profile_800.png", optimize=True)
        else:
            banner(src, channel).save(FINAL / f"{name}_banner_2560x1440.jpg", quality=92)
        print("final", cid)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "final":
        final(sys.argv[2:])
        sys.exit()
    if len(sys.argv) > 1 and sys.argv[1] == "render":
        render(sys.argv[2:])
    else:
        sheets()
