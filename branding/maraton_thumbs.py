"""Miniaturas B y C del maratón de Nocturno para Test & Compare (A = la actual, mosaico + "3 HORAS").

    python branding/maraton_thumbs.py sheet                  # hoja de contacto de los candidatos (para elegir)
    python branding/maraton_thumbs.py render maraton_b_p1_s2 maraton_c_p2_s1

Mismo estilo de letra que la miniatura A (pipeline/marathon.py): Inter Black grande en crema con sombra,
segunda línea Inter SemiBold en el lila de Nocturno. El texto va en la mitad izquierda (los prompts dejan
ese lado oscuro y vacío) y lejos de la esquina inferior derecha, donde YouTube pone la duración.
Candidatos en branding/candidates/<slot>/ (rama branding-candidates); finales en branding/maraton/.
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from pipeline.fonts import font  # noqa: E402

CAND = HERE / "candidates"
OUT = HERE / "maraton"
W, H = 1280, 720
CREAM, LILAC = (242, 238, 228), (142, 147, 217)
TEXT = {"maraton_b": [("3 HORAS", 168), ("PARA DORMIR", 76)],
        "maraton_c": [("DUERME", 168), ("EN MINUTOS", 84)]}


def cover(im):
    s = max(W / im.width, H / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x, y, x + W, y + H))


def compose(src, slot):
    im = cover(Image.open(src).convert("RGB"))
    im = ImageEnhance.Contrast(im).enhance(1.06)
    # degradado oscuro suave a la izquierda para que el texto se lea en el celular
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=int(170 * max(0.0, 1 - x / (W * 0.62)) ** 1.4))
    im = Image.composite(Image.new("RGB", (W, H), (4, 6, 18)), im, shade)
    big, small = TEXT[slot]
    fb, fs = font("black", big[1]), font("semibold", small[1])
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    x, y = 64, 190
    d.text((x, y), big[0], font=fb, fill=CREAM)
    y2 = y + big[1] + 22
    d.text((x + 4, y2), small[0], font=fs, fill=LILAC)
    glow = layer.split()[3].filter(ImageFilter.GaussianBlur(10))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.putalpha(glow.point(lambda a: int(a * 0.8)))
    im = Image.alpha_composite(im.convert("RGBA"), shadow)
    im = Image.alpha_composite(im, layer).convert("RGB")
    return im


def sheet():
    OUT.mkdir(parents=True, exist_ok=True)
    for slot in TEXT:
        files = sorted((CAND / slot).glob("*.jpg"))
        if not files:
            continue
        cols, tw, th = 3, 640, 360
        rows = (len(files) + cols - 1) // cols
        canvas = Image.new("RGB", (cols * tw, rows * th), (0, 0, 0))
        d = ImageDraw.Draw(canvas)
        for k, f in enumerate(files):
            t = compose(f, slot).resize((tw, th))
            canvas.paste(t, ((k % cols) * tw, (k // cols) * th))
            d.text(((k % cols) * tw + 8, (k // cols) * th + th - 34), f.stem, font=font("bold", 24), fill=(255, 220, 0))
        canvas.save(OUT / f"sheet_{slot}.jpg", quality=85)
        print("sheet", OUT / f"sheet_{slot}.jpg")


def render(ids):
    OUT.mkdir(parents=True, exist_ok=True)
    for iid in ids:
        slot = iid.split("_p")[0]
        out = OUT / f"{slot}.jpg"
        compose(CAND / slot / f"{iid}.jpg", slot).save(out, quality=92)
        print("final", out, out.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sheet"]:
        sheet()
    elif sys.argv[1:2] == ["render"]:
        render(sys.argv[2:])
    else:
        print(__doc__)
