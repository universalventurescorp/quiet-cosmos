"""1280x720 thumbnail: the most vivid image of the episode + big, readable text."""
import pathlib

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, ImageStat

FONTS = [
    "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/roboto/hinted/Roboto-Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
W, H = 1280, 720


def _font(size):
    for f in FONTS:
        if pathlib.Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default(size)


def _vividness(path):
    im = Image.open(path).convert("RGB")
    im.thumbnail((256, 256))
    stat = ImageStat.Stat(im.convert("HSV"))
    return stat.mean[1] * 0.6 + stat.stddev[2] * 1.0 + stat.mean[2] * 0.3


def make_thumbnail(image_paths, text, out_path):
    best = max(image_paths, key=_vividness)
    im = ImageOps.fit(Image.open(best).convert("RGB"), (W, H), Image.LANCZOS)
    im = ImageEnhance.Color(ImageEnhance.Contrast(im).enhance(1.18)).enhance(1.25)

    shade = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(shade)
    for x in range(int(W * 0.7)):
        d.line([(x, 0), (x, H)], fill=int(205 * (1 - x / (W * 0.7)) ** 1.4))
    im = Image.composite(Image.new("RGB", (W, H), (0, 0, 8)), im, shade)

    words = text.upper().split()
    mid = (len(words) + 1) // 2
    lines = [" ".join(words[:mid]), " ".join(words[mid:])] if len(words) > 2 else [" ".join(words)]
    size = 170
    while size > 60:
        font = _font(size)
        if max(font.getlength(l) for l in lines) <= W * 0.6:
            break
        size -= 6
    draw = ImageDraw.Draw(im)
    y = (H - len(lines) * size * 1.05) / 2
    for i, line in enumerate(lines):
        fill = (255, 255, 255) if i == 0 else (255, 214, 92)
        draw.text((60, y), line, font=font, fill=fill, stroke_width=7, stroke_fill=(0, 0, 0))
        y += size * 1.05
    im.save(out_path, "JPEG", quality=90)
    return out_path
