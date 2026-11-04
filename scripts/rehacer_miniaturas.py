"""Rehace las 3 miniaturas DUERME de un viaje ya producido (desde su artefacto work-listo) y las publica en
web/miniaturas. Uso: python scripts/rehacer_miniaturas.py <video_id> [titulo]. Guarda también las imágenes
propias (thumb_*) en hero/ para revisarlas."""
import glob
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.thumbnail import make_thumbnails, publish_web  # noqa: E402

vid = sys.argv[1]
eps = sorted(glob.glob(str(ROOT / "outputs" / "*" / "script.json")), key=lambda p: pathlib.Path(p).stat().st_mtime)
ep = pathlib.Path(eps[-1]).parent
script = json.loads((ep / "script.json").read_text())
texts = script.get("thumbnail_texts") or [script["title"]]
heroes = [sorted(glob.glob(str(ep / "ai" / f"thumb_{i}_*.jpg"))) for i in (1, 2, 3)]
imgs = [p for p in sorted(glob.glob(str(ep / "ai" / "*.jpg"))) if not pathlib.Path(p).name.startswith("thumb_")]
out = ROOT / "rehechas"
out.mkdir(exist_ok=True)
thumbs = make_thumbnails(imgs, texts, out, heroes=heroes)
title = sys.argv[2] if len(sys.argv) > 2 else script["title"]
publish_web(thumbs, title, vid, ROOT)
hero_dir = ROOT / "hero"
hero_dir.mkdir(exist_ok=True)
for h in sum(heroes, []):
    shutil.copy(h, hero_dir / pathlib.Path(h).name)
print("textos", texts, "\nsujetos", script.get("thumbnail_subjects"), "\nhéroes", [len(h) for h in heroes])
