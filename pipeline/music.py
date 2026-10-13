"""Original ambient pad generated from math: royalty-free by construction, different every episode,
and a perfectly seamless loop (all frequencies fit a whole number of cycles in the loop)."""
import numpy as np
import soundfile as sf


def make_ambient(path, seed, seconds=240, sr=22050):
    rng = np.random.default_rng(seed)
    n = seconds * sr
    t = np.arange(n) / sr
    q = lambda f: max(1, round(f * seconds)) / seconds          # loop-safe frequency

    root = rng.choice([49.0, 51.91, 55.0, 58.27, 61.74, 65.41])
    chords = [[1, 1.5, 2, 3, 4], [1, 1.2, 1.5, 2, 3], [1, 1.5, 2.25, 3, 4.5], [1, 1.333, 2, 2.667, 4]]
    ratios = chords[rng.integers(len(chords))]

    pad = np.zeros(n)
    for k, ratio in enumerate(ratios):
        for detune in (-0.18, 0.18):
            lfo = 0.55 + 0.45 * np.sin(2 * np.pi * q(rng.uniform(1 / 70, 1 / 25)) * t + rng.uniform(0, 6.28))
            pad += np.sin(2 * np.pi * q(root * ratio + detune) * t + rng.uniform(0, 6.28)) * lfo / (1 + 0.6 * k)
    shimmer = sum(np.sin(2 * np.pi * q(root * m) * t) for m in (6, 8))
    shimmer *= 0.5 + 0.5 * np.sin(2 * np.pi * q(1 / 45) * t)

    # soft "space air": shaped noise built in the frequency domain (periodic -> loops seamlessly)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / sr)
    shape = 1 / np.maximum(f, 20) ** 0.8
    shape *= np.exp(-np.maximum(f - 900, 0) / 400)
    air = np.fft.irfft(spec * shape, n)

    norm = lambda x: x / max(1e-9, np.abs(x).max())
    out = 0.7 * norm(pad) + 0.06 * norm(shimmer) + 0.24 * norm(air)
    sf.write(path, (norm(out) * 0.6).astype(np.float32), sr)
