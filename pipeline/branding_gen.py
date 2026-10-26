"""Paint photoreal candidates for the Estrato network's avatars and banners on Kaggle's free GPU.

    python -m pipeline.branding_gen        # run by .github/workflows/branding.yml

Uses the same worker as the episodes (kaggle/generate.py, SDXL RealVisXL + Real-ESRGAN x2) but under its
own Kaggle script name, so it never replaces an episode job that is still running. The raw candidates go
to branding/candidates/<slot>/; branding/estrato.py then adds the colored ring, titles and safe areas.
"""
import datetime as dt
import json
import os
import zlib

from PIL import Image

from . import gpu
from .common import ROOT, load_config, write_json

NEG_SPACE = ("text, letters, watermark, logo, signature, frame, border, cartoon, anime, illustration, painting, "
             "lowres, blurry, oversaturated, deformed, people, person, face, hands, spacecraft, satellite")
NEG_DINO = ("text, letters, watermark, logo, signature, frame, border, cartoon, anime, illustration, toy, "
            "lowres, blurry, oversaturated, deformed, extra legs, extra heads, two heads, mutated, people, person, "
            "buildings, roads, power lines, modern objects")
STYLE_SPACE = ("photorealistic NASA astronaut photograph, high detail, deep blacks, soft indigo and blue tones, "
               "calm, 35mm film")
STYLE_DINO = ("cinematic nature documentary photograph, photorealistic, golden hour backlight, amber and black, "
              "volumetric haze, high detail, 35mm film")

SQUARE = {"width": 1024, "height": 1024}
WIDE = {"width": 1344, "height": 768}

STYLE_COSMOS = ("photorealistic deep space astrophotography, high detail, deep blacks, warm starlight, "
                "soft gold highlights, calm, 35mm film")

SLOTS = {
    "cosmos_avatar": (SQUARE, STYLE_COSMOS, NEG_SPACE, [
        "a dark planet seen as a thin bright crescent against black space, a delicate glowing golden ring "
        "circling it, a few faint stars, centered composition",
        "Saturn seen from its night side as a thin crescent, its rings backlit and glowing gold, black space, "
        "centered composition",
        "a crescent planet half in shadow with a thin tilted golden ring, deep black space, soft starlight, "
        "minimal, centered composition",
    ]),
    "cosmos_banner": (WIDE, STYLE_COSMOS, NEG_SPACE, [
        "a crescent Saturn with backlit glowing golden rings on the far right side, vast black starry space "
        "elsewhere, wide cinematic composition with dark empty space in the center",
        "a thin crescent planet with a faint golden ring at the right edge, the Milky Way softly glowing across "
        "black space, wide cinematic composition with dark empty space in the center",
    ]),
    "nocturno_avatar": (SQUARE, STYLE_SPACE, NEG_SPACE, [
        "the planet Earth at night seen from deep space, golden city lights across the continents, thin glowing "
        "blue atmosphere rim, the Moon small in the upper right, black starry background, centered composition",
        "a crescent Earth half in shadow, night side sparkling with city lights, the full Moon beside it, "
        "deep black space, centered composition",
        "the Moon rising above Earth's curved night horizon seen from orbit, city lights below, thin glowing "
        "blue airglow line, black sky with faint stars, centered composition",
    ]),
    "salvaje_avatar": (SQUARE, STYLE_DINO, NEG_DINO, [
        "silhouette of one long-necked sauropod dinosaur standing on a ridge in front of a huge glowing orange "
        "setting sun, erupting volcano far behind, ash clouds, centered composition",
        "silhouette of a single sauropod dinosaur wading through shallow water at dusk, enormous amber sun low "
        "on the horizon behind it, distant smoking volcanoes, mirror reflections, centered composition",
        "backlit profile of a brachiosaurus head and long neck against a fiery volcanic sky, glowing embers "
        "drifting in the air, centered composition",
    ]),
    "nocturno_banner": (WIDE, STYLE_SPACE, NEG_SPACE, [
        "panoramic view of Earth's night side from orbit, city lights along a coastline, faint green aurora on "
        "the horizon, the Milky Way above, wide cinematic composition with dark empty sky in the center",
        "wide view of the Moon rising over the dark curve of Earth at night seen from orbit, thin blue airglow, "
        "scattered city lights, stars, wide cinematic composition with dark empty sky in the center",
    ]),
    "salvaje_banner": (WIDE, STYLE_DINO, NEG_DINO, [
        "wide prehistoric valley at sunset, a distant herd of sauropod dinosaurs silhouetted walking along a "
        "river, smoking volcanoes on the horizon, amber sky, cycads and tree ferns, wide cinematic panorama",
        "vast prehistoric coastline at golden hour, distant volcano with a smoke plume, small flock of pterosaurs "
        "silhouetted in the sky, misty conifer forest, wide cinematic panorama",
    ]),
}

# Miniaturas para Test & Compare del maratón de Nocturno (B = persona durmiendo, C = luna minimalista).
# El texto se agrega después con branding/maraton_thumbs.py (mismo estilo de letra que la miniatura A).
STYLE_SLEEP = ("photorealistic cinematic photograph, very low light, soft indigo and deep blue moonlight, "
               "calm and cozy, gentle film grain, 35mm film, high detail")
NEG_SLEEP = ("text, letters, watermark, logo, signature, frame, border, cartoon, anime, illustration, painting, "
             "lowres, blurry, oversaturated, deformed, extra limbs, extra fingers, bad hands, bright lamp, "
             "daylight, phone, television, two heads, creepy")
NEG_MOON = ("text, letters, watermark, logo, signature, frame, border, cartoon, anime, illustration, lowres, "
            "blurry, oversaturated, people, person, clouds, landscape, buildings, trees, spacecraft, earth")
SLOTS["maraton_b"] = (WIDE, STYLE_SLEEP, NEG_SLEEP, [
    "a person peacefully asleep in bed under a thick soft blanket in a dark bedroom at night, seen from behind "
    "with the head on the pillow, a large window beside the bed showing a deep starry night sky, faint blue "
    "moonlight on the sheets, the bed in the lower right, dark empty wall in the upper left",
    "a young woman sleeping peacefully on her side in a dark cozy bedroom, face relaxed and partly hidden by "
    "the pillow and blanket, big window with stars and a crescent moon outside, soft indigo moonlight, "
    "the bed in the lower half, dark empty space in the upper left",
    "a cozy bed next to a big window at night, a person sound asleep curled under a fluffy duvet, through the "
    "window the Milky Way and countless stars, deep blue darkness, the bed on the right side, calm",
])
SLOTS["maraton_c"] = (WIDE, STYLE_SPACE, NEG_MOON, [
    "a thin glowing crescent Moon alone in a vast pitch black night sky, a few faint tiny stars, the Moon on "
    "the right third of the frame, huge empty dark space on the left, minimal",
    "the dark Moon almost entirely in shadow with only a delicate thin bright crescent edge, deep black sky, "
    "very faint stars, the Moon on the right side, minimal and calm",
])
SEEDS_PER_PROMPT = 4


def build_job(job_id, cfg):
    ai = cfg["ai"]
    images = []
    only = [x for x in os.environ.get("BRANDING_SLOTS", "").split(",") if x]
    for slot, (size, style, neg, prompts) in SLOTS.items():
        if only and slot not in only:
            continue
        for p, prompt in enumerate(prompts):
            for s in range(SEEDS_PER_PROMPT):
                iid = f"{slot}_p{p + 1}_s{s + 1}"
                images.append({"id": iid, "prompt": prompt, "style": style, "negative": neg,
                               "seed": zlib.crc32(iid.encode()) % 2_000_000_000, "video": False, **size})
    return {"job_id": job_id, "style": STYLE_SPACE, "negative": NEG_SPACE,
            "image_model": ai.get("image_model", "SG161222/RealVisXL_V5.0"), "video_model": "",
            "steps": 35, "width": 1024, "height": 1024, "upscale": True, "budget_minutes": 60,
            "images": images, "videos": []}


def main():
    cfg = load_config()
    cfg.setdefault("kaggle", {})["kernel"] = "estrato-branding"      # never the episode's script
    out = ROOT / "outputs" / "branding"
    out.mkdir(parents=True, exist_ok=True)
    job = build_job(f"branding-{dt.datetime.utcnow():%Y%m%d%H%M%S}", cfg)
    write_json(out / "job.json", job)
    print(f"branding: {len(job['images'])} candidates, Kaggle configured={gpu.configured()}")
    state = gpu.launch(job, out, cfg) if gpu.configured() else {}
    manifest = gpu.collect(out, cfg, wait_minutes=240) if state.get("ok") else None
    dst = ROOT / "branding" / "candidates"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for item in job["images"]:
        src = out / "ai" / f"{item['id']}.jpg"
        if not src.exists():
            continue
        slot = item["id"].split("_p")[0]
        (dst / slot).mkdir(exist_ok=True)
        im = Image.open(src).convert("RGB")
        im.thumbnail((2688, 2688))
        im.save(dst / slot / src.name, quality=92)
        n += 1
    log = out / "ai" / "log.txt"
    write_json(dst / "manifest.json", {"job_id": job["job_id"], "saved": n, "push": state,
                                       "worker": manifest or {"error": "no result"},
                                       "log": log.read_text(errors="ignore").splitlines()[-60:] if log.exists() else []})
    print(json.dumps({"saved": n, "errors": (manifest or {}).get("errors")}, indent=1)[:3000])


if __name__ == "__main__":
    main()
