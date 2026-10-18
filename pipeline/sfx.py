"""Cinematic sound design, generated from math (royalty-free by construction, like the score).

Two layers, mixed with the music under the voice (so they duck while the narrator speaks):
  beds    a quiet ambience per chapter, chosen by the writer in the outline (chapters[].ambience):
          deep_space, wind, storm, sea, ice, sun, lava, none
  hits    film-trailer punctuation in the moments without voice:
          boom    deep cinematic hit when the opening title appears (and a soft one on the end card)
          whoosh  air sweep across every chapter change, panned left to right
          swell   a reversed-cymbal rise into each "reveal line" (pipeline/voice.py is_reveal)

Everything is rendered in blocks straight to disk, so a 90-minute episode stays light on memory.
"""
import numpy as np
import soundfile as sf

SR = 48000
LOOP = 48          # seconds of each ambience bed (seamless loop: built with circular FFT)
BED_RMS = 10 ** (-37 / 20)   # beds sit ~4 dB under the score (measured: score ~-33 dBFS RMS at music_volume 0.16)
HIT_PEAK = {"boom": 10 ** (-9 / 20), "boom_soft": 10 ** (-17 / 20), "whoosh": 10 ** (-17 / 20),
            "swell": 10 ** (-20 / 20)}
FADE = 5.0         # seconds of crossfade between chapter ambiences


# ---------- building blocks (all periodic over the loop) ----------

def _shaped_noise(rng, n, shape):
    """White noise shaped in the frequency domain; shape(f) -> gain. Periodic over n samples."""
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    return np.fft.irfft(spec * shape(np.maximum(f, 1.0)), n)


def _band(lo, hi, slope=4):
    return lambda f: 1 / np.sqrt((1 + (lo / f) ** (2 * slope)) * (1 + (f / hi) ** (2 * slope)))


def _lfo(rng, n, period_lo, period_hi):
    """Slow 0..1 modulation with a whole number of cycles in the loop (seamless)."""
    t = np.arange(n) / SR
    secs = n / SR
    cycles = max(1, round(secs / rng.uniform(period_lo, period_hi)))
    return 0.5 + 0.5 * np.sin(2 * np.pi * cycles / secs * t + rng.uniform(0, 6.283))


def _norm_rms(x, rms):
    return x * (rms / max(1e-9, np.sqrt(np.mean(x ** 2))))


def _reverb(rng, x, seconds=3.0, dark=3000):
    """Circular convolution with a decaying noise tail (keeps loops seamless)."""
    n = len(x)
    t = np.arange(n) / SR
    ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)
    ir[0] = 0
    spec = np.fft.rfft(ir) / (1 + (np.fft.rfftfreq(n, 1 / SR) / dark) ** 2)
    wet = np.fft.irfft(np.fft.rfft(x) * spec, n)
    return wet / max(1e-9, np.abs(wet).max()) * np.abs(x).max()


def _events(rng, n, rate_per_s, make):
    """Sparse one-shot sounds scattered over the loop (wrapping around the end)."""
    out = np.zeros(n)
    count = rng.poisson(rate_per_s * n / SR)
    for _ in range(count):
        ev = make(rng)
        s = rng.integers(n)
        idx = (s + np.arange(len(ev))) % n
        out[idx] += ev
    return out


# ---------- ambience beds (mono layers made stereo by two decorrelated renders) ----------

def _bed_layer(kind, rng, n):
    if kind == "deep_space":
        # the felt "hum" of open space in films: a slow sub rumble and a faint high air
        rumble = _shaped_noise(rng, n, _band(18, 80, 3)) * (0.55 + 0.45 * _lfo(rng, n, 14, 30))
        air = _shaped_noise(rng, n, _band(2500, 7000, 2)) * 0.05 * _lfo(rng, n, 10, 24)
        return rumble + air
    if kind == "wind":
        x = np.zeros(n)
        for lo, hi, g in ((150, 500, 1.0), (400, 1100, 0.7), (900, 2400, 0.35)):
            gust = _lfo(rng, n, 5, 16) ** 2
            x += g * _shaped_noise(rng, n, _band(lo, hi, 3)) * (0.15 + 0.85 * gust)
        x += 0.5 * _shaped_noise(rng, n, _band(25, 120, 3))
        return x
    if kind == "storm":
        wind = _bed_layer("wind", rng, n) * 0.7
        def thunder(r):
            d = int(SR * r.uniform(3.5, 6.0))
            t = np.arange(d) / SR
            env = (1 - np.exp(-t / r.uniform(0.15, 0.4))) * np.exp(-t / r.uniform(1.0, 1.8))
            body = np.convolve(r.standard_normal(d), np.ones(40) / 40, "same")   # dull
            return body * env * r.uniform(2.0, 4.0)
        rolls = _events(rng, n, 1 / 14, thunder)
        rolls = np.fft.irfft(np.fft.rfft(rolls) * _band(20, 180, 2)(np.maximum(np.fft.rfftfreq(n, 1 / SR), 1)), n)
        return wind + _norm_rms(rolls, np.sqrt(np.mean(wind ** 2)) * 1.2)
    if kind == "sea":
        t = np.arange(n) / SR
        x = np.zeros(n)
        for _ in range(3):
            cycles = max(1, round(LOOP / rng.uniform(7, 12)))
            ph = rng.uniform(0, 6.283)
            wave = np.clip(np.sin(2 * np.pi * cycles / LOOP * t + ph), 0, 1) ** 1.5   # surge then draw back
            x += wave * _shaped_noise(rng, n, _band(80, 1400, 2))
            x += 0.25 * wave ** 3 * _shaped_noise(rng, n, _band(2500, 9000, 2))        # foam
        return x + 0.4 * _shaped_noise(rng, n, _band(25, 90, 3))
    if kind == "ice":
        air = _shaped_noise(rng, n, _band(300, 1500, 2)) * (0.3 + 0.7 * _lfo(rng, n, 8, 20))
        def ping(r):
            d = int(SR * r.uniform(1.0, 2.2))
            t = np.arange(d) / SR
            f1 = r.uniform(1800, 5200)
            tone = np.sin(2 * np.pi * f1 * t) + 0.5 * np.sin(2 * np.pi * f1 * r.uniform(1.37, 2.71) * t)
            return tone * np.exp(-t / r.uniform(0.25, 0.6)) * r.uniform(0.3, 1.0)
        pings = _reverb(rng, _events(rng, n, 0.5, ping), seconds=2.5, dark=9000)
        return _norm_rms(air, 1.0) + _norm_rms(pings, 0.5)
    if kind == "sun":
        roar = _shaped_noise(rng, n, _band(30, 380, 2))
        crackle_env = np.abs(np.convolve(rng.standard_normal(n), np.ones(240) / 240, "same")) ** 3
        crackle = _shaped_noise(rng, n, _band(1500, 5000, 2)) * crackle_env / max(1e-9, crackle_env.mean())
        return roar * (0.6 + 0.4 * _lfo(rng, n, 6, 14)) + 0.12 * crackle
    if kind == "lava":
        rumble = _shaped_noise(rng, n, _band(20, 140, 3))
        def bloop(r):
            d = int(SR * r.uniform(0.12, 0.3))
            t = np.arange(d) / SR
            f = r.uniform(70, 130) * (1 + 1.5 * t / t[-1])
            return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.sin(np.pi * t / t[-1]) ** 2
        bubbles = _events(rng, n, 1.2, bloop)
        return _norm_rms(rumble, 1.0) + _norm_rms(bubbles, 0.45)
    return np.zeros(n)


def make_bed(kind, seed):
    """Stereo loop (LOOP s) normalised to the bed level; None for "none"."""
    if kind == "none":
        return None
    n = LOOP * SR
    rng = np.random.default_rng(seed)
    common = _bed_layer(kind, rng, n)
    chans = [0.6 * common + 0.4 * _norm_rms(_bed_layer(kind, rng, n), np.sqrt(np.mean(common ** 2)))
             for _ in range(2)]
    st = _norm_rms(np.stack(chans, 1), BED_RMS)
    cap = BED_RMS * 10 ** (14 / 20)              # no sudden spikes (crackles, thunder) above the bed
    return (cap * np.tanh(st / cap)).astype(np.float32)


# ---------- hits ----------

def _pan(mono, start_pan, end_pan):
    p = np.linspace(start_pan, end_pan, len(mono))           # -1 left .. +1 right (constant power)
    a = (p + 1) * np.pi / 4
    return np.stack([mono * np.cos(a), mono * np.sin(a)], 1)


def make_hit(kind, seed):
    rng = np.random.default_rng(seed)
    if kind in ("boom", "boom_soft"):
        d = int(SR * 6.5)
        t = np.arange(d) / SR
        f = 34 + 26 * np.exp(-t / 0.5)                         # sub drop 60 -> 34 Hz
        sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 1.6)
        thump = np.convolve(rng.standard_normal(d), np.ones(60) / 60, "same") * np.exp(-t / 0.07) * 6
        body = sub + thump
        tail = _reverb(rng, np.concatenate([body, np.zeros(SR)]), seconds=4.5, dark=900)[:d]
        mono = 0.75 * body + 0.5 * tail
        mono *= np.minimum(1, t / 0.004)                       # no click
        st = np.stack([mono, _reverb(rng, mono, 0.05, 2000) * 0.15 + mono * 0.9], 1)
    elif kind == "whoosh":
        d = int(SR * 2.6)
        t = np.arange(d) / SR
        mono = np.zeros(d)
        for k, (lo, hi) in enumerate(((200, 600), (500, 1500), (1200, 3500), (3000, 8000))):
            peak = 1.05 + 0.12 * k                             # higher bands peak a little later: a sweep
            env = np.exp(-((t - peak) / 0.42) ** 2)
            mono += _shaped_noise(rng, d, _band(lo, hi, 2)) * env / (1 + 0.4 * k)
        st = _pan(mono, -0.7, 0.7)
    elif kind == "swell":
        rise, fall = 1.6, 0.7                                  # rises into the reveal, then melts away under it
        d = int(SR * (rise + fall))
        t = np.arange(d) / SR
        env = np.where(t < rise, (t / rise) ** 3.2, np.cos(np.clip((t - rise) / fall, 0, 1) * np.pi / 2) ** 2)
        hiss = _shaped_noise(rng, d, _band(3000, 11000, 2)) + 0.5 * _shaped_noise(rng, d, _band(900, 3000, 2))
        sub = 0.6 * np.sin(2 * np.pi * 45 * t) * env
        mono = hiss * env + sub
        st = np.stack([mono, _shaped_noise(rng, d, _band(3000, 11000, 2)) * env + sub], 1)
    else:
        raise ValueError(kind)
    return (st / max(1e-9, np.abs(st).max()) * HIT_PEAK[kind]).astype(np.float32)


# ---------- the episode track ----------

def plan(timing, script):
    """(sections, hits): ambience per time range and one-shot hits with their start time in seconds."""
    chapters = timing.get("chapters", [])
    first = chapters[0]["start"] if chapters else timing["duration"]
    sections = [(0.0, first, "deep_space")]                   # cold open + title card over open space
    for ch, mark in zip(script.get("chapters", []), chapters):
        sections.append((mark["start"], mark["end"], ch.get("ambience") or "deep_space"))
    if chapters:
        sections.append((chapters[-1]["end"], timing["duration"], "deep_space"))
    hits = []
    if timing.get("title_card"):
        hits.append((max(0.0, timing["title_card"]["start"] - 0.05), "boom"))
    for mark in chapters[1:]:
        hits.append((max(0.0, mark["start"] - 1.3), "whoosh"))      # peaks as the chapter card appears
    for r in timing.get("reveals", []):
        hits.append((max(0.0, r - 1.6), "swell"))                    # peaks as the reveal line starts
    if timing.get("outro"):
        hits.append((timing["outro"]["start"] + 0.4, "boom_soft"))
    return sections, sorted(hits)


def make_sfx(path, timing, script, seed=0, block_s=30):
    sections, hits = plan(timing, script)
    total = int(timing["duration"] * SR) + SR
    beds = {k: make_bed(k, seed + 101 * i) for i, k in enumerate(sorted({s[2] for s in sections}))}
    shots = {k: make_hit(k, seed + 7 * i) for i, k in enumerate(("boom", "boom_soft", "whoosh", "swell"))}
    fade = int(FADE * SR)
    with sf.SoundFile(str(path), "w", SR, 2, subtype="FLOAT") as f:
        for b0 in range(0, total, block_s * SR):
            b1 = min(total, b0 + block_s * SR)
            out = np.zeros((b1 - b0, 2), np.float32)
            idx = np.arange(b0, b1)
            for a, b, kind in sections:
                bed = beds.get(kind)
                s0, s1 = int(a * SR) - fade // 2, int(b * SR) + fade // 2
                if bed is None or s1 <= b0 or s0 >= b1:
                    continue
                lo, hi = max(b0, s0), min(b1, s1)
                k = np.arange(lo, hi)
                env = np.clip(np.minimum(k - s0, s1 - k) / fade, 0, 1)
                env = np.sin(env * np.pi / 2) ** 2
                out[lo - b0:hi - b0] += bed[k % len(bed)] * env[:, None]
            for t0, kind in hits:
                h = shots[kind]
                s0 = int(t0 * SR)
                if s0 >= b1 or s0 + len(h) <= b0:
                    continue
                lo, hi = max(b0, s0), min(b1, s0 + len(h))
                out[lo - b0:hi - b0] += h[lo - s0:hi - s0]
            f.write(out)
    return {"beds": sorted(k for k in beds if beds[k] is not None),
            "hits": {k: sum(1 for _, x in hits if x == k) for k in shots}}
