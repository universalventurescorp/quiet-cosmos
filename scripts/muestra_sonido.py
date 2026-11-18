"""Muestra de sonido sin GPU: sobre un episodio ya producido, suma a la mezcla final la diferencia entre el diseño
sonoro actual y uno nuevo (mismos sonidos base, misma semilla) y arma muestras de varios tramos + un análisis.
Uso: python scripts/muestra_sonido.py   (AJUSTES = JSON con claves de mix; TRAMOS = "0,45,120" minutos; DUR = s)"""
import glob, json, os, pathlib, subprocess, sys, zlib
import numpy as np
import soundfile as sf
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline.common import load_config, read_json  # noqa: E402
from pipeline.scenes import read_srt  # noqa: E402
from pipeline.sfx import make_sfx, paragraph_starts, plan  # noqa: E402

cfg = load_config()
new = json.loads(os.environ.get("AJUSTES", "{}"))
tramos = [float(x) for x in os.environ.get("TRAMOS", "0").split(",")]
dur = float(os.environ.get("DUR", "240"))
ep = pathlib.Path(sorted(glob.glob(str(ROOT / "outputs" / "*" / "timing.json")))[-1]).parent
timing, script = read_json(ep / "timing.json", {}), read_json(ep / "script.json", {})
cues = read_srt(ep / "captions.srt")
pauses = paragraph_starts(cues, 0.7)
seed = zlib.crc32((script.get("topic") or ep.name).encode()) % 100000
out = ROOT / "muestra"; out.mkdir(exist_ok=True)
print("archivos del episodio:", sorted(p.name for p in ep.iterdir() if p.is_file())[:40])
o, m = cfg["mix"], {**cfg["mix"], **new}
args = lambda c: dict(pauses=pauses, max_gap=c.get("sfx_max_gap", 0), hook=c.get("sfx_hook"), cues=cues,
                      semantic=c.get("sfx_semantic", False), soft_boom=c.get("sfx_semantic", False),
                      zones=c.get("sfx_zones"))
make_sfx(out / "sfx_a.wav", timing, script, seed=seed, **args(o))
make_sfx(out / "sfx_b.wav", timing, script, seed=seed, **args(m))
rep = {"episodio": ep.name, "ajustes_nuevos": new, "tramos": {}}
for name, c in (("actual", o), ("nuevo", m)):
    _, hits = plan(timing, script, pauses, c.get("sfx_max_gap", 0), c.get("sfx_hook"), cues,
                   c.get("sfx_semantic", False), c.get("sfx_zones"))
    rep[name] = {f"min_{a:.0f}-{a + 10:.0f}": sum(1 for t, _ in hits if a * 60 <= t < (a + 10) * 60)
                 for a in (0, 10, 20, 30, 45, 60, 90, 120, 150)}
# fuente de la mezcla final: el video final si viene en el artefacto; si no, la vista previa (solo 10 min)
big = [p for p in ep.rglob("*.mp4") if p.stat().st_size > 5e8]
prev = sorted(glob.glob(str(ROOT / "ep" / "**" / "preview-10min.mp4"), recursive=True))
src = str(big[0]) if big else (prev[0] if prev else None)
audio_full = ep / "audio.wav"
print("fuente:", src, "| audio.wav:", audio_full.exists())


def analyze(wav):
    x, sr = sf.read(wav, dtype="float32")
    x = x.mean(1) if x.ndim > 1 else x
    w = int(0.4 * sr)
    fr = x[: len(x) // w * w].reshape(-1, w)
    db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
    base = np.array([np.median(db[max(0, i - 25):i]) if i > 3 else db[i] for i in range(len(db))])
    jumps = int(((db - base) > 6).sum())
    quiet = float((db < np.percentile(db, 50) - 25).mean() * 100)       # tramos casi en silencio
    spec = np.abs(np.fft.rfft(x[: sr * 60]))
    f = np.fft.rfftfreq(sr * 60, 1 / sr)
    return {"saltos_>6dB": jumps, "pct_casi_silencio": round(quiet, 1),
            "pct_energia_>4kHz": round(float(spec[f > 4000].sum() / spec.sum() * 100), 1),
            "nivel_medio_dB": round(float(db.mean()), 1)}


for a in tramos:
    if src is None or (a * 60 + dur > 600 and not big and not audio_full.exists()):
        print("sin fuente para el minuto", a); continue
    t0 = a * 60
    A = sf.read(str(out / "sfx_a.wav"), start=int(t0 * 48000), frames=int(dur * 48000), dtype="float32")[0]
    B = sf.read(str(out / "sfx_b.wav"), start=int(t0 * 48000), frames=len(A), dtype="float32")[0]
    g_o, g_n = float(o.get("sfx_volume", 1.0)), float(m.get("sfx_volume", 1.0))
    sf.write(str(out / "extra.wav"), B * g_n - A * g_o, 48000)
    base_in = ["-ss", str(t0), "-i", str(audio_full)] if (audio_full.exists() and not big and t0 + dur > 600) \
        else ["-ss", str(t0), "-i", src]
    tag = f"min{int(a):03d}"
    for name, extra in (("actual", False), ("nuevo", True)):
        wav = out / f"{tag}_{name}.wav"
        filt = ("[0:a]aresample=48000[x];[1:a]aresample=48000[e];[x][e]amix=inputs=2:duration=first:normalize=0,"
                "alimiter=limit=0.89[o]") if extra else "[0:a]aresample=48000[o]"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", *base_in] + (["-i", str(out / "extra.wav")] if extra else []) + \
              ["-t", str(dur), "-filter_complex", filt, "-map", "[o]", str(wav)]
        subprocess.run(cmd, check=True)
        rep["tramos"].setdefault(tag, {})[name] = analyze(str(wav))
        vid = ["-ss", str(t0), "-i", src] if src and (big or t0 + dur <= 600) else \
              ["-f", "lavfi", "-i", "color=c=0x04060f:s=854x480"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *vid, "-i", str(wav), "-t", str(dur), "-map", "0:v",
                        "-map", "1:a", "-vf", "scale=854:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "31",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(out / f"muestra_{tag}_{name}.mp4")], check=True)
        wav.unlink()
# referencia: el maratón (primer episodio) analizado igual
ref = glob.glob(str(ROOT / "m" / "*.mp4"))
if ref:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ref[0], "-t", str(dur), "-vn", "-ac", "2", "-ar", "48000",
                    str(out / "ref.wav")], check=True)
    rep["tramos"].setdefault("min000", {})["maraton"] = analyze(str(out / "ref.wav"))
for p in out.glob("*.wav"):
    p.unlink()
json.dump(rep, open(out / "muestra.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
