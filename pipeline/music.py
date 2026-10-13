"""Original ambient score generated from math: royalty-free by construction, different every episode.

A slow progression of soft pad chords with an airy shimmer, passed through a long stereo reverb.
Everything is built with periodic signals and circular (FFT) convolution, so the loop is seamless.
"""
import numpy as np
import soundfile as sf

PROGRESSIONS = [
    # semitone offsets from the root, one list per chord (pads sit an octave or two above the root)
    [[0, 7, 14, 16, 23], [-3, 4, 9, 12, 16], [-7, 0, 5, 9, 12], [-5, 2, 7, 11, 14]],
    [[0, 7, 12, 15, 19], [-4, 3, 8, 12, 15], [-2, 5, 10, 14, 17], [-5, 2, 7, 10, 14]],
    [[0, 7, 14, 19, 21], [2, 9, 14, 17, 21], [-3, 4, 9, 12, 19], [-7, 0, 7, 12, 16]],
    [[0, 4, 7, 11, 14], [-3, 0, 4, 7, 12], [5, 9, 12, 16, 19], [-5, 2, 7, 11, 14]],
]


def _reverb_ir(rng, n, sr, seconds=5.5):
    t = np.arange(n) / sr
    ir = rng.standard_normal(n) * np.exp(-t * 6.9 / seconds)     # -60 dB at `seconds`
    ir[: int(0.02 * sr)] *= np.linspace(0, 1, int(0.02 * sr))
    # darker tail: low-pass the IR in the frequency domain
    spec = np.fft.rfft(ir)
    f = np.fft.rfftfreq(n, 1 / sr)
    spec *= 1 / (1 + (f / 2500) ** 2)
    return np.fft.irfft(spec, n)


def make_ambient(path, seed, seconds=360, sr=22050):
    rng = np.random.default_rng(seed)
    n = seconds * sr
    t = np.arange(n) / sr
    q = lambda f: max(1, round(f * seconds)) / seconds          # loop-safe frequency (whole cycles)

    root = rng.choice([49.0, 51.91, 55.0, 58.27, 61.74, 65.41])
    prog = PROGRESSIONS[rng.integers(len(PROGRESSIONS))]
    k = len(prog)
    dry = np.zeros(n)
    for ci, chord in enumerate(prog):
        # raised-cosine window centred on this chord's slot, wrapping around the loop
        phase = 2 * np.pi * (t / seconds - (ci + 0.5) / k)
        env = np.clip(np.cos(phase / 2) ** 2 * 1.0, 0, 1) ** (k / 1.6)
        for vi, semi in enumerate(chord):
            f0 = root * 2 * 2 ** (semi / 12)
            amp = 1 / (1 + 0.45 * vi)
            lfo = 0.6 + 0.4 * np.sin(2 * np.pi * q(rng.uniform(1 / 40, 1 / 14)) * t + rng.uniform(0, 6.28))
            for det in (-0.15, 0.15):
                ph = rng.uniform(0, 6.28)
                fq = q(f0 + det)
                # soft "string pad": fundamental + a little 2nd harmonic
                dry += env * lfo * amp * (np.sin(2 * np.pi * fq * t + ph) + 0.18 * np.sin(4 * np.pi * fq * t + ph))
    # slow sub drone on the root
    dry += 0.35 * np.sin(2 * np.pi * q(root) * t) * (0.7 + 0.3 * np.sin(2 * np.pi * q(1 / 60) * t))
    # shimmer: sparse high partials that bloom and fade
    shimmer = np.zeros(n)
    for m in (4, 6, 8, 12):
        bloom = np.clip(np.sin(2 * np.pi * q(rng.uniform(1 / 90, 1 / 35)) * t + rng.uniform(0, 6.28)), 0, 1) ** 3
        shimmer += bloom * np.sin(2 * np.pi * q(root * m * 2) * t) / m
    # soft "space air"
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / sr)
    air = np.fft.irfft(spec / np.maximum(f, 30) ** 0.9 * np.exp(-np.maximum(f - 700, 0) / 350), n)

    norm = lambda x: x / max(1e-9, np.abs(x).max())
    dry = 0.72 * norm(dry) + 0.12 * norm(shimmer) + 0.16 * norm(air)

    # stereo reverb via circular convolution (keeps the loop seamless)
    D = np.fft.rfft(dry)
    chans = []
    for _ in range(2):
        wet = np.fft.irfft(D * np.fft.rfft(_reverb_ir(rng, n, sr)), n)
        chans.append(0.45 * norm(dry) + 0.55 * norm(wet))
    out = np.stack(chans, axis=1)
    out = out / np.abs(out).max() * 0.7
    sf.write(path, out.astype(np.float32), sr)
