"""Compara el audio de los primeros minutos de dos videos: silencios y ritmo de efectos.
Uso: python scripts/analisis_sonido.py <nombre> <video> <minutos> <outdir>"""
import json, subprocess, sys, numpy as np
name, src, mins, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
sr = 16000
raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", src, "-t", str(mins * 60), "-ac", "1", "-ar", str(sr),
                      "-f", "s16le", "-"], capture_output=True, check=True).stdout
x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
hop = int(0.05 * sr)
n = len(x) // hop
fr = x[: n * hop].reshape(n, hop)
db = 20 * np.log10(np.sqrt((fr ** 2).mean(1)) + 1e-9)
# voz: banda 300-3400 Hz vs resto, por FFT de cada cuadro de 50 ms
spec = np.abs(np.fft.rfft(fr * np.hanning(hop), axis=1))
f = np.fft.rfftfreq(hop, 1 / sr)
voice = 20 * np.log10(spec[:, (f > 300) & (f < 3400)].mean(1) + 1e-9)
hi = 20 * np.log10(spec[:, f > 4000].mean(1) + 1e-9)
ref = np.percentile(db, 90)
# "hueco": la voz baja >18 dB respecto a su nivel típico durante >= 1 s
vref = np.percentile(voice, 85)
quiet = voice < vref - 18
gaps, i = [], 0
while i < n:
    if quiet[i]:
        j = i
        while j < n and quiet[j]:
            j += 1
        if (j - i) * 0.05 >= 1.0:
            gaps.append((round(i * 0.05, 1), round((j - i) * 0.05, 1), round(float(db[i:j].mean() - ref), 1)))
        i = j
    else:
        i += 1
# efectos: subida brusca de energía en agudos (>4 kHz) sostenida, fuera de la voz típica
flux = np.convolve(np.diff(hi, prepend=hi[0]), np.ones(6) / 6, "same")
thr = np.percentile(flux, 99.3)
ev, last = [], -99
for k in np.where(flux > thr)[0]:
    t = k * 0.05
    if t - last > 8:
        ev.append(round(t, 1)); last = t
sil = sum(g[1] for g in gaps)
res = {"video": name, "minutos": mins, "huecos_voz": len(gaps), "segundos_sin_voz": round(sil, 1),
       "pct_sin_voz": round(100 * sil / (mins * 60), 1), "hueco_mas_largo": max((g[1] for g in gaps), default=0),
       "huecos_mayores_3s": sum(1 for g in gaps if g[1] >= 3), "nivel_fondo_en_huecos_db": round(float(np.mean([g[2] for g in gaps])) if gaps else 0, 1),
       "efectos_detectados": len(ev), "efectos_t": ev, "huecos": gaps[:400]}
json.dump(res, open(f"{out}/{name}.json", "w"), ensure_ascii=False, indent=1)
# imágenes: espectrograma + nivel por segundo
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-t", str(mins * 60), "-lavfi",
                "showspectrumpic=s=1800x500:legend=1:scale=log:fscale=log", f"{out}/{name}_espectro.png"], check=True)
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
sec = db[: (n // 20) * 20].reshape(-1, 20).mean(1)
vs = voice[: (n // 20) * 20].reshape(-1, 20).mean(1)
fig, ax = plt.subplots(figsize=(18, 4))
ax.plot(np.arange(len(sec)) / 60, sec - ref, lw=.8, label="nivel total")
ax.plot(np.arange(len(vs)) / 60, vs - vref, lw=.6, alpha=.6, label="banda de voz")
for t in ev: ax.axvline(t / 60, color="r", alpha=.4, lw=.8)
for g in gaps:
    if g[1] >= 3: ax.axvspan(g[0] / 60, (g[0] + g[1]) / 60, color="k", alpha=.15)
ax.set_xlabel("minuto"); ax.set_title(f"{name}: rojo = efecto detectado, gris = hueco sin voz >= 3 s"); ax.legend()
fig.tight_layout(); fig.savefig(f"{out}/{name}_nivel.png", dpi=80)
print(json.dumps({k: v for k, v in res.items() if k not in ("huecos", "efectos_t")}, ensure_ascii=False))
