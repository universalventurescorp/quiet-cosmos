"""Narrator intonation editing (Praat PSOLA via parselmouth): the voice's timbre is untouched, only its melody.

Measured on a reference Spanish documentary narrator (Planeta Antiguo): inside a thought the voice stays up (phrase
ends ~-0.6 semitones, declination ~-0.35 st/s, ~30 % continuation rises), while a TTS closes every phrase as if it
were the last (-3 to -6 st). For each multi-sentence take we lift the end of every phrase except the last one
toward the level the phrase started at, with a continuation rise at comma-length pauses. The take's LAST phrase
keeps its natural final fall.

Mode "C" (17-oct) reached the reference numbers but Luis heard a TREMOR at the phrase endings: the whole take was
re-synthesized, the target melody copied every measurement wobble of the creaky, fading syllable at the end of a
phrase, and the biggest shifts (up to 4 st) landed exactly there. Modes "D"/"E" (18-oct):
  - the target melody is a smoothed, outlier-free version of the original (no jitter or octave errors copied);
  - nothing is moved in the quiet tail of a phrase (> 12 dB under its peak: creak/decay) - the lift is reached on
    the last full vowel and then held;
  - shifts are capped (D: 2.5 st, E: 1.8 st) and the rise is gentler;
  - only the edited spans take the re-synthesized audio (20 ms crossfades); everything else is the original take.
"""
import numpy as np

# mode: (strength, comma rise st, inner-end target st, max shift st, tilt halving, careful)
MODES = {
    "B": (1.0, None, -0.6, 4.0, False, False),
    "C": (0.8, 1.5, -0.6, 4.0, True, False),
    "D": (0.9, 1.2, -0.8, 2.5, True, True),
    "E": (0.7, 1.0, -1.0, 1.8, True, True),
}


def _phrases(w, sr):
    hop = int(sr * 0.01)
    n = len(w) // hop
    if n < 50:
        return [], None
    e = 20 * np.log10(np.sqrt((w[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    sp = np.convolve((e > np.percentile(e, 90) - 18).astype(float), np.ones(15) / 15, "same") > 0.3
    edges = np.flatnonzero(np.diff(np.concatenate([[0], sp.astype(int), [0]])))
    ph = []
    for a, b in zip(edges[::2], edges[1::2]):
        if ph and a - ph[-1][1] < 18:
            ph[-1][1] = b
        else:
            ph.append([a, b])
    return [(a / 100, b / 100) for a, b in ph if b - a >= 40], e


def _smooth_f0(times, f0):
    """Median-smoothed contour without octave errors (target melody must not copy measurement wobble)."""
    v = f0 > 0
    st = np.full(len(f0), np.nan)
    st[v] = 12 * np.log2(f0[v] / 100.0)
    out = st.copy()
    for i in np.flatnonzero(v):
        win = st[max(0, i - 3):i + 4]
        win = win[~np.isnan(win)]
        med = np.median(win)
        out[i] = med if abs(st[i] - med) > 2.5 else np.mean(win[np.abs(win - med) <= 2.5])
    return np.where(v, 100.0 * 2 ** (out / 12), 0.0)


def edit(w, sr, mode="E", seed=7):
    """Return the take with narrator intonation (float32, same length). Falls back to the input on any problem."""
    if mode not in MODES:
        return w
    strength, rise_st, inner_st, cap, tilt_half, careful = MODES[mode]
    try:
        import parselmouth
        from parselmouth.praat import call
    except ImportError:
        return w
    try:
        w = np.asarray(w, np.float32)
        rng = np.random.default_rng(seed)
        snd = parselmouth.Sound(w.astype(np.float64), sampling_frequency=sr)
        pitch = snd.to_pitch_ac(time_step=0.01, pitch_floor=60, pitch_ceiling=300)
        times = pitch.xs()
        f0 = pitch.selected_array["frequency"]
        if (f0 > 0).sum() < 30:
            return w
        if careful:
            f0 = _smooth_f0(times, f0)
        med = np.median(f0[f0 > 0])
        ph, e = _phrases(w, sr)
        if len(ph) < 2:
            return w
        eidx = np.clip((times * 100).astype(int), 0, len(e) - 1)
        shift = np.zeros_like(f0)
        for pi, (a, b) in enumerate(ph[:-1]):
            inph = (times >= a) & (times <= b + 0.05)
            m = inph & (f0 > 0)
            if careful:                                   # only full-voice frames count (no creaky decay)
                peak = e[int(a * 100):int(b * 100)].max()
                m &= e[eidx] > peak - 12
            if m.sum() < 15:
                continue
            st = 12 * np.log2(f0[m] / med)
            q = max(3, m.sum() // 5)
            head, end = np.median(st[:q]), np.median(st[-q:])
            nxt_pause = ph[pi + 1][0] - b
            if rise_st is not None:
                rise = nxt_pause < 0.45
                target = head + (rise_st if rise else inner_st)
            else:
                rise = rng.random() < 0.33 and nxt_pause < 0.7
                target = head + (1.0 if rise else inner_st)
            if tilt_half:
                tt = times[m] - a
                slope = np.polyfit(tt, st, 1)[0] if len(tt) > 5 else 0
                if slope < 0:
                    mid = (b - a) / 2
                    shift = np.where(inph, shift + np.clip(-0.5 * slope * ((times - a) - mid), -cap, cap), shift)
            delta = float(np.clip((target - end) * strength, 0, cap))
            if delta > 0.2:
                t0 = a + 0.55 * (b - a)
                t1 = times[m][-1] if careful else b      # lift reached on the last full vowel, then held
                r = np.clip((times - t0) / max(t1 - t0, 0.05), 0, 1)
                shift = np.where(inph, shift + delta * r, shift)
        shift = np.clip(shift, -cap, cap)
        if not np.any(np.abs(shift) > 0.05):
            return w
        manip = call(snd, "To Manipulation", 0.01, 60, 300)
        tier = call("Create PitchTier", "narrador", snd.xmin, snd.xmax)
        for t, f, d in zip(times, f0, shift):
            if f > 0:
                call(tier, "Add point", float(t), float(f * 2 ** (d / 12)))
        call([tier, manip], "Replace pitch tier")
        y = np.asarray(call(manip, "Get resynthesis (overlap-add)").values[0], np.float32)[:len(w)]
        if len(y) < len(w):
            y = np.concatenate([y, w[len(y):]])
        if not (np.isfinite(y).all() and np.abs(y).max() > 1e-3):
            return w
        if not careful:
            return y
        # splice: re-synthesized audio only where the melody moved, original take everywhere else
        hop = int(sr * 0.01)
        edited = np.zeros(len(w), np.float32)
        for t, d in zip(times, shift):
            if abs(d) > 0.05:
                i = int(t * sr)
                edited[max(0, i - 4 * hop):i + 4 * hop] = 1.0
        k = int(0.02 * sr)
        mix = np.convolve(edited, np.ones(k) / k, "same")
        return (mix * y + (1 - mix) * w).astype(np.float32)
    except Exception as exc:                    # noqa: BLE001 - a melody edit must never break an episode
        print(f"   pitch edit skipped: {str(exc)[:120]}")
        return w
