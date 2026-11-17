"""Muestra de sonido: rehace el diseño sonoro y la mezcla de un episodio ya producido con otros ajustes y arma
una muestra de los primeros minutos (video de la vista previa + audio nuevo), sin GPU.
Uso: python scripts/muestra_sonido.py MINUTOS  (los ajustes nuevos llegan por la variable AJUSTES en JSON)"""
import glob, json, os, pathlib, subprocess, sys, zlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, read_json  # noqa: E402
from pipeline.mix import mix  # noqa: E402
from pipeline.scenes import read_srt  # noqa: E402
from pipeline.sfx import make_sfx, paragraph_starts, plan  # noqa: E402

mins = float(sys.argv[1])
cfg = load_config()
new = json.loads(os.environ.get("AJUSTES", "{}"))
ep = pathlib.Path(sorted(glob.glob(str(ROOT / "outputs" / "*" / "timing.json")))[-1]).parent
timing, script = read_json(ep / "timing.json"), read_json(ep / "script.json")
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
sfx = out / "sfx.wav"
make_sfx(sfx, timing, script, seed=zlib.crc32(topic.encode()) % 100000, pauses=pauses,
         max_gap=m.get("sfx_max_gap", 0), hook=m.get("sfx_hook"))
music = ep / "music.wav"
audio = out / "audio.wav"
mix(ep / "narration.wav", music, audio, timing["duration"], music_volume=m["music_volume"], lufs=m["lufs"],
    voice_eq=m.get("voice_eq", "clean"), voice_pitch_st=m.get("voice_pitch_st", 0.0),
    voice_size_st=m.get("voice_size_st", 0.0), sfx=sfx, sfx_volume=m.get("sfx_volume", 1.0),
    soft_spans=[(e["start"], e["end"]) for e in timing.get("events", []) if e["kind"] in ("companion", "gift")],
    soft_db=(cfg.get("companion") or {}).get("soft_db", -4.0))
prev = sorted(glob.glob(str(ROOT / "ep" / "**" / "preview-10min.mp4"), recursive=True))[0]
t = str(min(mins * 60, 600))
for name, a in (("despues", ["-i", str(audio), "-map", "0:v", "-map", "1:a"]), ("antes", ["-map", "0:v", "-map", "0:a"])):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", prev, *a, "-t", t, "-vf", "scale=854:-2",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "160k",
                    str(out / f"muestra_{name}.mp4")], check=True)
json.dump(rep, open(out / "muestra.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
