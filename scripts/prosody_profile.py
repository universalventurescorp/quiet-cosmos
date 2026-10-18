"""Prosody profile of a narration track (numpy/scipy + ffmpeg only) - used to compare our narrator with a reference documentary narrator.

Usage: python3 prosody.py file.wav|mp3 [--json out.json]
Measures: F0 (YIN), phrase segmentation by pauses, per-phrase pitch mean/range/declination/final movement,
pause distribution, syllable rate (de Jong-style intensity peaks), loudness per phrase, spectral tilt.
"""
import json, subprocess, sys
import numpy as np
from scipy.signal import butter, sosfiltfilt, find_peaks

SR = 16000
HOP = 160      # 10 ms
WIN = 640      # 40 ms (enough for 60 Hz)


def load(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def frames(x, win=WIN, hop=HOP):
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    return x[idx]


def yin(x, fmin=60, fmax=300, thr=0.15):
    fr = frames(x)
    fr = fr - fr.mean(1, keepdims=True)
    W = WIN // 2
    tmax = SR // fmin
    tmin = SR // fmax
    # difference function via FFT
    nfft = 2 * WIN
    F = np.fft.rfft(fr, nfft)
    ac = np.fft.irfft(F * np.conj(F), nfft)[:, :tmax + 1]
    cs = np.cumsum(np.concatenate([np.zeros((fr.shape[0], 1)), fr ** 2], 1), 1)
    e0 = cs[:, W] - cs[:, 0]
    taus = np.arange(tmax + 1)
    et = cs[:, np.minimum(taus + W, WIN)] - cs[:, taus]
    d = e0[:, None] + et - 2 * ac
    d[:, 0] = 0
    cm = d[:, 1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[:, 1:], 1), 1e-12)
    cm = np.concatenate([np.ones((len(cm), 1)), cm], 1)
    f0 = np.zeros(len(cm)); ap = np.ones(len(cm))
    sub = cm[:, tmin:tmax]
    below = sub < thr
    first = np.where(below.any(1), below.argmax(1), sub.argmin(1))
    for i, t in enumerate(first):           # walk to local min
        while t + 1 < sub.shape[1] and sub[i, t + 1] < sub[i, t]:
            t += 1
        first[i] = t
    vals = sub[np.arange(len(sub)), first]
    tau = first + tmin
    # parabolic interpolation
    f0 = SR / tau.astype(float)
    ap = vals
    return f0, ap


def bandpass(x, lo, hi):
    return sosfiltfilt(butter(4, [lo, hi], "band", fs=SR, output="sos"), x)


def db(x):
    return 10 * np.log10(np.maximum(x, 1e-10))


def semitones(f, ref):
    return 12 * np.log2(f / ref)


def profile(path):
    x = load(path)
    xs = bandpass(x, 80, 4000)
    f0, ap = yin(xs)
    fr = frames(bandpass(x, 300, 3400))
    en = db((fr ** 2).mean(1))
    n = min(len(f0), len(en)); f0, ap, en = f0[:n], ap[:n], en[:n]
    ref_level = np.percentile(en, 90)
    active = en > ref_level - 25
    voiced = (ap < 0.25) & active & (f0 > 65) & (f0 < 260)
    # octave-jump cleanup: compare to running median
    fv = np.where(voiced, f0, np.nan)
    med = np.nanmedian(fv)
    fv = np.where(np.abs(semitones(np.where(np.isnan(fv), med, fv), med)) > 9, np.nan, fv)
    voiced = ~np.isnan(fv)
    # speech/pause segmentation: smooth activity (speech = energy within 18 dB of loud level)
    sp = en > ref_level - 18
    k = 15
    sp_s = np.convolve(sp.astype(float), np.ones(k) / k, "same") > 0.3
    # runs
    edges = np.flatnonzero(np.diff(np.concatenate([[0], sp_s.astype(int), [0]])))
    runs = list(zip(edges[::2], edges[1::2]))
    # merge gaps < 180 ms into one phrase; phrases separated by pauses >= 180 ms
    phrases = []
    for s, e in runs:
        if phrases and s - phrases[-1][1] < 18:
            phrases[-1][1] = e
        else:
            phrases.append([s, e])
    phrases = [p for p in phrases if p[1] - p[0] >= 40]  # >= 0.4 s
    pauses = [(phrases[i + 1][0] - phrases[i][1]) / 100 for i in range(len(phrases) - 1)]
    # syllable nuclei: peaks in smoothed intensity, voiced, prominence >= 2 dB
    en_s = np.convolve(en, np.ones(5) / 5, "same")
    pk, _ = find_peaks(en_s, prominence=2.0, distance=8)
    pk = [p for p in pk if voiced[max(0, p - 2):p + 3].any() and sp_s[p]]
    speech_time = sum(e - s for s, e in phrases) / 100
    rows = []
    for s, e in phrases:
        seg = fv[s:e]; ok = ~np.isnan(seg)
        if ok.sum() < 15:
            continue
        st = semitones(seg[ok], med)
        t = np.flatnonzero(ok)
        slope = np.polyfit(t / 100, st, 1)[0]   # st per second
        q = max(3, ok.sum() // 5)
        head, tail = np.median(st[:q]), np.median(st[-q:])
        nsyl = sum(1 for p in pk if s <= p < e)
        rows.append(dict(t0=s / 100, dur=(e - s) / 100, mean_st=float(np.mean(st)), mean_hz=float(np.median(seg[ok])),
                         range_st=float(np.percentile(st, 95) - np.percentile(st, 5)),
                         slope=float(slope), head_tail=float(tail - head), level_db=float(np.mean(en[s:e])),
                         syl_rate=nsyl / ((e - s) / 100)))
    allst = semitones(fv[voiced], med)
    means = np.array([r["mean_st"] for r in rows])
    levels = np.array([r["level_db"] for r in rows])
    durs = np.array([r["dur"] for r in rows])
    pz = np.array(pauses) if pauses else np.zeros(1)
    # spectral balance of voiced speech
    spec = np.abs(np.fft.rfft(frames(x, 1024, 512) * np.hanning(1024), axis=1)) ** 2
    freqs = np.fft.rfftfreq(1024, 1 / SR)
    m = spec.mean(0)
    def band(a, b): return db(m[(freqs >= a) & (freqs < b)].sum())
    tilt = {"low_100_300": band(100, 300) - band(300, 1000), "pres_2k_4k": band(2000, 4000) - band(300, 1000),
            "air_4k_8k": band(4000, 8000) - band(300, 1000)}
    out = dict(
        file=path, seconds=len(x) / SR, phrases=len(rows),
        f0_median_hz=float(med), f0_sd_st=float(np.std(allst)),
        f0_range_p5_p95_st=float(np.percentile(allst, 95) - np.percentile(allst, 5)),
        between_phrase_sd_st=float(np.std(means)),
        within_phrase_range_st=float(np.median([r["range_st"] for r in rows])),
        declination_st_per_s=float(np.median([r["slope"] for r in rows])),
        final_fall_st=float(np.median([r["head_tail"] for r in rows])),
        pct_phrases_final_rise=float(np.mean([r["head_tail"] > 1 for r in rows]) * 100),
        syllables_per_s_articulation=float(len(pk) / speech_time),
        est_words_per_min=float(len(pk) / speech_time * speech_time / (len(x) / SR) * 60 / 2.0),
        phrase_dur_median_s=float(np.median(durs)), phrase_dur_p90_s=float(np.percentile(durs, 90)),
        pause_median_s=float(np.median(pz)), pause_p90_s=float(np.percentile(pz, 90)),
        pct_pauses_long_gt_0p7=float(np.mean(pz > 0.7) * 100),
        speech_ratio=float(speech_time / (len(x) / SR)),
        phrase_level_sd_db=float(np.std(levels)), spectral_tilt_db=tilt,
        rows=rows)
    return out


if __name__ == "__main__":
    p = profile(sys.argv[1])
    if "--json" in sys.argv:
        json.dump(p, open(sys.argv[sys.argv.index("--json") + 1], "w"), indent=1)
    print(json.dumps({k: (round(v, 2) if isinstance(v, float) else v) for k, v in p.items() if k != "rows"}, indent=1))
