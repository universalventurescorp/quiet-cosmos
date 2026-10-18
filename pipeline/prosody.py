"""Narrator intonation editing (Praat PSOLA via parselmouth): the voice's timbre is untouched, only its melody.

Measured on a reference Spanish documentary narrator (Planeta Antiguo): inside a thought the voice stays up (phrase
ends ~-0.6 semitones, declination ~-0.35 st/s, ~30 % continuation rises), while a TTS closes every phrase as if it
were the last (-3 to -6 st). For each multi-sentence take we lift the end of every phrase except the last one
toward the level the phrase started at; mode "C" also gives a continuation rise at comma-length pauses and halves
the downward tilt inside each phrase. The take's LAST phrase keeps its natural final fall.
"""
import numpy as np

MODES = {"B": (1.0, False), "C": (0.8, True)}


def _phrases(w, sr):
    hop = int(sr * 0.01)
    n = len(w) // hop
    if n < 50:
        return []
    e = 20 * np.log10(np.sqrt((w[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    sp = np.convolve((e > np.percentile(e, 90) - 18).astype(float), np.ones(15) / 15, "same") > 0.3
    edges = np.flatnonzero(np.diff(np.concatenate([[0], sp.astype(int), [0]])))
    ph = []
    for a, b in zip(edges[::2], edges[1::2]):
        if ph and a - ph[-1][1] < 18:
            ph[-1][1] = b
        else:
            ph.append([a, b])
    return [(a / 100, b / 100) for a, b in ph if b - a >= 40]


def edit(w, sr, mode="C", seed=7):
    """Return the take with narrator intonation (float32, same length scale). Falls back to the input on error."""
    if mode not in MODES:
        return w
    strength, comma_rise = MODES[mode]
    try:
        import parselmouth
        from parselmouth.praat import call
    except ImportError:
        return w
    try:
        rng = np.random.default_rng(seed)
        snd = parselmouth.Sound(np.asarray(w, np.float64), sampling_frequency=sr)
        pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=60, pitch_ceiling=300)
        times = pitch.xs()
        f0 = pitch.selected_array["frequency"]
        if (f0 > 0).sum() < 30:
            return w
        med = np.median(f0[f0 > 0])
        ph = _phrases(np.asarray(w, np.float32), sr)
        if len(ph) < 2:
            return w
        shift = np.zeros_like(f0)
        for pi, (a, b) in enumerate(ph[:-1]):
            m = (times >= a) & (times <= b) & (f0 > 0)
            if m.sum() < 15:
                continue
            st = 12 * np.log2(f0[m] / med)
            q = max(3, m.sum() // 5)
            head, end = np.median(st[:q]), np.median(st[-q:])
            nxt_pause = ph[pi + 1][0] - b
            inph = (times >= a) & (times <= b + 0.05)
            if comma_rise:
                rise = nxt_pause < 0.45
                target = head + (1.5 if rise else -0.6)
                tt = times[m] - a
                slope = np.polyfit(tt, st, 1)[0] if len(tt) > 5 else 0
                if slope < 0:
                    mid = (b - a) / 2
                    shift = np.where(inph, shift + np.clip(-0.5 * slope * ((times - a) - mid), -2.0, 2.0), shift)
            else:
                rise = rng.random() < 0.33 and nxt_pause < 0.7
                target = head + (1.0 if rise else -0.6)
            delta = float(np.clip((target - end) * strength, 0, 4.0))
            if delta <= 0.2:
                continue
            t0 = a + 0.55 * (b - a)
            r = np.clip((times - t0) / max(b - t0, 0.05), 0, 1)
            shift = np.where(inph, shift + delta * r, shift)
        if not np.any(shift):
            return w
        manip = call(snd, "To Manipulation", 0.01, 60, 300)
        tier = call("Create PitchTier", "narrador", snd.xmin, snd.xmax)
        for t, f, d in zip(times, f0, shift):
            if f > 0:
                call(tier, "Add point", float(t), float(f * 2 ** (d / 12)))
        call([tier, manip], "Replace pitch tier")
        out = call(manip, "Get resynthesis (overlap-add)")
        y = np.asarray(out.values[0], np.float32)
        return y if np.isfinite(y).all() and np.abs(y).max() > 1e-3 else w
    except Exception as exc:                    # noqa: BLE001 - a melody edit must never break an episode
        print(f"   pitch edit skipped: {str(exc)[:120]}")
        return w
