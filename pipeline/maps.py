"""Animated maps of the moving continents ("movie mode" map shots).

The coastlines of the Earth at any moment of deep time come from the GPlates Web Service (EarthByte, University
of Sydney): reconstructed coastlines of a published plate model, as GeoJSON. Plate models used here are open
data under CC BY 4.0, so the description credits them (credits()).

Each map shot is a short clip: the globe turning slowly under soft sunlight, land coloured by its age, with the
time and a place name lower left ("Hace 250 millones de años · Pangea"). If the service cannot be reached the
shot is dropped and the editor fills it with a still, so an episode never fails over a map.
"""
import json
import math
import os
import pathlib
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

GWS = "https://gws.gplates.org/reconstruct/coastlines/"
# (model, oldest age it covers in Ma). Tried in order; the first that covers the age and answers wins.
MODELS = [("MULLER2019", 250), ("MERDITH2021", 1000)]
CACHE = pathlib.Path(os.environ.get("PALEOMAP_CACHE", pathlib.Path.home() / ".cache" / "paleomaps"))
TEX_W, TEX_H = 2048, 1024

CREDITS = {
    "es": "Mapas paleogeográficos: GPlates Web Service (EarthByte) con los modelos de placas de Müller et al. 2019 "
          "y Merdith et al. 2021 (CC BY 4.0).",
    "en": "Palaeogeographic maps: GPlates Web Service (EarthByte), plate models by Müller et al. 2019 and "
          "Merdith et al. 2021 (CC BY 4.0).",
}


def credits(lang="es"):
    return CREDITS.get(lang, CREDITS["en"])


def coastlines(age):
    """GeoJSON FeatureCollection of the coastlines `age` million years ago (cached), or None."""
    import requests
    age = int(round(max(0.0, float(age))))
    CACHE.mkdir(parents=True, exist_ok=True)
    for model, oldest in MODELS:
        if age > oldest:
            continue
        f = CACHE / f"{model}_{age}.geojson"
        if f.exists():
            return json.loads(f.read_text())
        try:
            r = requests.get(GWS, params={"time": age, "model": model}, timeout=60)
            if r.status_code == 200:
                data = r.json()
                if data.get("features"):
                    f.write_text(json.dumps(data))
                    return data
            print(f"    paleomap {model} {age} Ma: HTTP {r.status_code} {r.text[:120]}")
        except Exception as exc:                          # noqa: BLE001
            print(f"    paleomap {model} {age} Ma: {exc}")
    return None


def _rings(geom):
    t = geom.get("type")
    c = geom.get("coordinates") or []
    if t == "Polygon":
        return c[:1]
    if t == "MultiPolygon":
        return [p[0] for p in c if p]
    if t == "LineString":
        return [c]
    if t == "MultiLineString":
        return list(c)
    return []


def land_mask(geo):
    """Equirectangular land mask (TEX_W x TEX_H, uint8) from the coastline polygons."""
    img = Image.new("L", (TEX_W, TEX_H), 0)
    d = ImageDraw.Draw(img)
    for feat in geo.get("features", []):
        for ring in _rings(feat.get("geometry") or {}):
            if len(ring) < 3:
                continue
            lon = np.unwrap(np.radians([p[0] for p in ring])) * 180 / np.pi    # no jumps across the dateline
            lat = np.array([p[1] for p in ring], float)
            for shift in (-360, 0, 360):                                        # draw the wrapped copies too
                xs = (lon + shift + 180) / 360 * TEX_W
                if xs.max() < 0 or xs.min() > TEX_W:
                    continue
                ys = (90 - lat) / 180 * TEX_H
                d.polygon(list(zip(xs.tolist(), ys.tolist())), fill=255)
    return np.array(img)


def texture(mask, age, seed=7):
    """Colour texture: deep ocean, glowing shelves, land from green (young, wet) to ochre (old, dry interiors)."""
    rng = np.random.default_rng(seed)
    h, w = mask.shape
    m = mask.astype(np.float32) / 255
    # distance-like softness: coasts get a shallow-sea glow, interiors get drier
    soft = np.array(Image.fromarray(mask).filter(ImageFilter.GaussianBlur(10)), np.float32) / 255
    inland = np.array(Image.fromarray(mask).filter(ImageFilter.GaussianBlur(40)), np.float32) / 255
    noise = np.array(Image.fromarray((rng.random((h // 8, w // 8)) * 255).astype(np.uint8))
                     .resize((w, h), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6)), np.float32) / 255
    lat = np.abs(np.linspace(90, -90, h))[:, None] * np.ones((1, w))
    deep, shelf = np.array([12, 34, 66]), np.array([38, 112, 140])
    ocean = deep + (shelf - deep) * np.clip(soft * 1.6, 0, 1)[..., None]
    green, ochre, ice = np.array([62, 98, 52]), np.array([170, 138, 88]), np.array([226, 232, 236])
    dry = np.clip((inland - 0.55) * 2.2 + (noise - 0.5) * 0.6, 0, 1)    # coasts green, deep interiors dry
    if age > 200:                                   # Pangaea-era interiors were vast deserts
        dry = np.clip(dry * 1.25 + 0.05, 0, 1)
    land = green + (ochre - green) * dry[..., None]
    land = land * (0.85 + 0.3 * noise[..., None])
    polar = np.clip((lat - 72) / 10, 0, 1)[..., None] * (0.6 if age > 30 else 1.0)
    land = land + (ice - land) * polar
    tex = ocean * (1 - m[..., None]) + land * m[..., None]
    return np.clip(tex, 0, 255).astype(np.uint8)


def _label_layer(W, H, title, subtitle):
    from .fonts import font
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = H / 1080
    f1, f2 = font("semibold", int(46 * s)), font("light", int(30 * s))
    x, y = int(90 * s), int(H - 190 * s)
    for dx, dy in ((2, 2), (0, 0)):
        col = (0, 0, 0, 150) if dx else (244, 238, 226, 255)
        d.text((x + dx, y + dy), title, font=f1, fill=col)
        if subtitle:
            col2 = (0, 0, 0, 150) if dx else (224, 190, 120, 255)      # the amber of Estrato Salvaje
            d.text((x + dx, y + int(62 * s) + dy), subtitle, font=f2, fill=col2)
    return np.array(img)


def age_text(age, lang="es"):
    a = float(age)
    if a <= 0.01:
        return "Hoy" if lang == "es" else "Today"
    n = f"{a:,.0f}".replace(",", ".") if a >= 1 else f"{a:.1f}".replace(".", ",")
    return f"Hace {n} millones de años" if lang == "es" else f"{n} million years ago"


def render_map_clip(age, label, out, seconds=8.0, W=1920, H=1080, fps=24, lang="es", seed=7):
    """Turning globe at `age` Ma. Returns the clip duration, or None when no coastlines are available."""
    out = pathlib.Path(out)
    if out.exists():
        return seconds
    geo = coastlines(age)
    if not geo:
        return None
    tex = texture(land_mask(geo), age, seed).astype(np.float32)
    # the continents' centre of mass decides where the camera looks
    m = land_mask(geo).astype(np.float32)
    lon_c = (np.argmax(np.convolve(m.sum(0), np.ones(TEX_W // 4), "same")) / TEX_W) * 360 - 180
    R = int(H * 0.43)
    cx, cy = int(W * 0.56), H // 2
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx, ny = (xx - cx) / R, (cy - yy) / R
    r2 = nx ** 2 + ny ** 2
    disc = r2 <= 1
    nz = np.sqrt(np.clip(1 - r2, 0, 1))
    # stars + faint glow
    rng = np.random.default_rng(seed)
    bg = np.zeros((H, W, 3), np.float32) + np.array([4, 6, 12])
    sx, sy = rng.integers(0, W, 1600), rng.integers(0, H, 1600)
    bg[sy, sx] = (rng.random(1600)[:, None] ** 3) * 200 + 30
    dist = np.sqrt(r2)
    halo = np.exp(-np.clip(dist - 1, 0, None) * 28) * (~disc)          # thin atmosphere just outside the limb
    limb = ((1 - nz) ** 3 * disc)                                        # bluish haze toward the edge
    light = np.array([-0.62, 0.32, 0.55])
    light /= np.linalg.norm(light)
    lam = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0, 1)
    shade = (0.06 + 0.94 * lam ** 0.7)[..., None]
    sun_side = (0.25 + 0.75 * np.clip(lam * 1.5, 0, 1))[..., None]
    tilt = math.radians(18)
    labels = _label_layer(W, H, age_text(age, lang), label)
    la = labels[..., 3:4].astype(np.float32) / 255
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(seconds * fps)
    # tilted sphere coordinates (independent of the spin)
    y1 = ny * math.cos(tilt) + nz * math.sin(tilt)
    z1 = -ny * math.sin(tilt) + nz * math.cos(tilt)
    lat = np.degrees(np.arcsin(np.clip(y1, -1, 1)))
    lon0 = np.degrees(np.arctan2(nx, z1))
    rows = np.clip(((90 - lat) / 180 * TEX_H).astype(np.int32), 0, TEX_H - 1)
    fade_n = int(0.6 * fps)
    for k in range(n):
        spin = lon_c - 25 + 50 * k / max(1, n - 1)                 # 50 degrees across the shot: slow, calm
        cols = (((lon0 + spin + 180) / 360 % 1) * TEX_W).astype(np.int32) % TEX_W
        globe = tex[rows, cols] * shade
        frame = bg.copy()
        frame[disc] = globe[disc]
        frame += (limb[..., None] * np.array([70, 130, 210]) * 0.8) * sun_side
        frame += halo[..., None] * np.array([70, 125, 210]) * 0.55
        a = la * min(1.0, k / fade_n, (n - k) / fade_n)              # label fades in and out with the shot
        frame = frame * (1 - a) + labels[..., :3] * a
        enc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    enc.stdin.close()
    enc.wait()
    return seconds if enc.returncode == 0 and out.exists() else None
