"""Narration with Kokoro (open-source TTS, Apache-2.0, runs on CPU) + exact subtitle timings."""
import re

import numpy as np

SR = 24000
SENTENCE = re.compile(r"(?<=[.!?…])\s+")


def _to_np(audio):
    if hasattr(audio, "detach"):
        audio = audio.detach().cpu().numpy()
    return np.asarray(audio, dtype=np.float32).reshape(-1)


def _say(pipe, text, voice, speed):
    chunks = []
    for result in pipe(text, voice=voice, speed=speed, split_pattern=None):
        audio = getattr(result, "audio", None)
        if audio is None:
            _, _, audio = result
        if audio is not None:
            chunks.append(_to_np(audio))
    return np.concatenate(chunks) if chunks else np.zeros(int(SR * 0.1), np.float32)


def _cue_lines(start, end, sentence, max_chars=84):
    """Split long sentences into readable caption chunks, timed by length."""
    words, chunks, cur = sentence.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    total = sum(len(c) for c in chunks)
    t, out = start, []
    for c in chunks:
        d = (end - start) * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def _srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def synthesize(chapters, cfg, out_dir):
    import soundfile as sf
    from kokoro import KPipeline

    v = cfg["voice"]
    pipe = KPipeline(lang_code=v["id"][0])  # Kokoro voice prefix = language code
    gap = lambda s: np.zeros(int(SR * s), np.float32)
    parts, cues, marks, n = [], [], [], 0

    for ci, ch in enumerate(chapters):
        start = n
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", ch["text"]) if p.strip()]
        for p in paragraphs:
            sentences = [s.strip() for s in SENTENCE.split(" ".join(p.split())) if s.strip()]
            for si, s in enumerate(sentences):
                audio = _say(pipe, s, v["id"], v["speed"])
                parts.append(audio)
                cues += _cue_lines(n / SR, (n + len(audio)) / SR, s)
                n += len(audio)
                pause = gap(v["pause_paragraph"] if si == len(sentences) - 1 else v["pause_sentence"])
                parts.append(pause)
                n += len(pause)
        pause = gap(v["pause_chapter"])
        parts.append(pause)
        n += len(pause)
        marks.append({"title": ch["title"], "start": start / SR, "end": n / SR})
        print(f"  voiced chapter {ci + 1}/{len(chapters)} -> {n / SR / 60:.1f} min")

    audio = np.concatenate(parts)
    audio = audio / max(1e-6, np.abs(audio).max()) * 0.89
    sf.write(out_dir / "narration.wav", audio, SR)

    with open(out_dir / "captions.srt", "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n\n")

    return {"duration": n / SR, "chapters": marks}
