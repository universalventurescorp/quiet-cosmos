"""Muestra de sonido: rehace el diseño sonoro y la mezcla de un episodio ya producido con otros ajustes y arma
una muestra de los primeros minutos (video de la vista previa + audio nuevo), sin GPU.
Uso: python scripts/muestra_sonido.py MINUTOS  (los ajustes nuevos llegan por la variable AJUSTES en JSON)"""
import glob, json, os, pathlib, subprocess, sys, zlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, read_json  # noqa: E402
from pipeline.scenes import read_srt  # noqa: E402
from pipeline.sfx import make_sfx, paragraph_starts, plan  # noqa: E402

mins = float(sys.argv[1])
cfg = load_config()
new = json.loads(os.environ.get("AJUSTES", "{}"))
ep = pathlib.Path(sorted(glob.glob(str(ROOT / "outputs" / "*" / "timing.json")))[-1]).parent
timing, script = read_json(ep / "timing.json", {}), read_json(ep / "script.json", {})
topic = script.get("topic") or ep.name
pauses = paragraph_starts(read_srt(ep / "captions.srt"))
out = ROOT / "muestra"; out.mkdir(exist_ok=True)
rep = {"episodio": ep.name}
for name, m in (("antes", cfg["mix"]), ("despues", {**cfg["mix"], **new})):
    _, hits = plan(timing, script, pauses, m.get("sfx_max_gap", 0), m.get("sfx_hook"))
    first = [h for h in hits if h[0] < mins * 60]
    rep[name] = {"ajustes": {k: m.get(k) for k in ("sfx_volume", "sfx_max_gap", "sfx_hook")},
                 f"sonidos_primeros_{int(mins)}_min": len(first),
                 "cada_seg": round(mins * 60 / max(1, len(first)), 1)}
m = {**cfg["mix"], **new}
seed = zlib.crc32(topic.encode()) % 100000
prev = sorted(glob.glob(str(ROOT / "ep" / "**" / "preview-10min.mp4"), recursive=True))[0]
t = min(mins * 60, 600)
old, nsfx = out / "sfx_antes.wav", out / "sfx_despues.wav"
o = cfg["mix"]
make_sfx(old, timing, script, seed=seed, pauses=pauses, max_gap=o.get("sfx_max_gap", 0), hook=o.get("sfx_hook"))
make_sfx(nsfx, timing, script, seed=seed, pauses=pauses, max_gap=m.get("sfx_max_gap", 0), hook=m.get("sfx_hook"))
# el artefacto no guarda la voz ni la música sueltas: a la mezcla final de la vista previa se le suma la diferencia.
# Los sonidos y fondos son idénticos entre las dos versiones (misma semilla), así que (nuevo - viejo) son justo los
# sonidos agregados; y + viejo * (vol - 1) sube el volumen de todos los efectos.
import numpy as np, soundfile as sf
a, sr = sf.read(str(old), frames=int(t * 48000) + 48000, dtype="float32")
b, _ = sf.read(str(nsfx), frames=len(a), dtype="float32")
g_new, g_old = float(m.get("sfx_volume", 1.0)), float(o.get("sfx_volume", 1.0))
extra = (b - a) * g_new + a * (g_new - g_old)
sf.write(str(out / "extra.wav"), extra, sr)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", prev, "-i", str(out / "extra.wav"), "-t", str(t),
                "-filter_complex", "[0:a]aresample=48000[x];[1:a]aresample=48000[e];"
                "[x][e]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89[aout]",
                "-map", "0:v", "-map", "[aout]", "-vf", "scale=854:-2", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "30", "-c:a", "aac", "-b:a", "160k", str(out / "muestra_despues.mp4")], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", prev, "-t", str(t), "-vf", "scale=854:-2",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "160k",
                str(out / "muestra_antes.mp4")], check=True)
json.dump(rep, open(out / "muestra.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
