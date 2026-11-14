"""Rehace los Shorts de un episodio ya producido (desde su artefacto work-listo) con el sistema actual
(sonido lleno + imágenes de cine) y deja los .mp4 en shorts_rehechos/. Uso: python scripts/rehacer_shorts.py"""
import glob, json, pathlib, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, read_json  # noqa: E402
from pipeline.shorts import produce_short  # noqa: E402
from pipeline.voice import PrecomputedVoice  # noqa: E402

cfg = load_config()
eps = sorted(glob.glob(str(ROOT / "outputs" / "*" / "script.json")), key=lambda p: pathlib.Path(p).stat().st_mtime)
ep = pathlib.Path(eps[-1]).parent
script = json.loads((ep / "script.json").read_text())
items = [tuple(x) for x in (read_json(ep / "gpu_job.json", {}).get("narration") or {}).get("items", [])]
voice = PrecomputedVoice(ep / "ai" / "narration", items) if items else None
music = ep / "music.wav"
ai = sorted(str(p) for p in (ep / "ai").glob("*.jpg"))
print("episodio", ep.name, "| shorts", len(script.get("shorts", [])), "| imágenes IA", len(ai), "| voz", bool(voice))
out = ROOT / "shorts_rehechos"
out.mkdir(exist_ok=True)
work = ep / "shorts_v2"
shutil.rmtree(work, ignore_errors=True)
res = []
for k, s in enumerate(script.get("shorts", []), 1):
    try:
        r = produce_short(s, k, cfg, work, set(), music, [], voice=voice, ai_images=ai)
    except Exception as exc:                                   # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"short {k} falló: {exc}")
        continue
    if r:
        dst = out / f"short_{k}.mp4"
        shutil.copy(r["path"], dst)
        res.append({"archivo": dst.name, "titulo": r["title"], "duracion": r["duration"], "texto": r["narration"],
                    "fuente": r.get("source", "")})
json.dump(res, open(out / "shorts.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
