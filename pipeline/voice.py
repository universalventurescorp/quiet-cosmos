"""Narration with Kokoro (open-source TTS, Apache-2.0, runs on CPU) + exact subtitle timings.

Episode layout:
  [lead] cold open  [opening title card + music]  chapter 1 ... chapter N  [end card]
"""
import re

import numpy as np

SR = 24000
SENTENCE = re.compile(r"(?<=[.!?…])\s+")
LEAD = 1.2          # silence before the first word
TITLE_GAP = 8.0     # opening title card (no narration)
CHAPTER_LEAD = 1.4  # chapter card fades in before the voice starts
OUTRO = 12.0        # end card + music tail


class Voice:
    def __init__(self, voice_id, speed):
        from kokoro import KPipeline
        self.pipe = KPipeline(lang_code=voice_id[0])   # Kokoro voice prefix = language code
        self.voice, self.speed = voice_id, speed

    def say(self, text, speed=None):
        chunks = []
        for result in self.pipe(text, voice=self.voice, speed=speed or self.speed, split_pattern=None):
            audio = getattr(result, "audio", None)
            if audio is None:
                _, _, audio = result
            if audio is not None:
                if hasattr(audio, "detach"):
                    audio = audio.detach().cpu().numpy()
                chunks.append(np.asarray(audio, dtype=np.float32).reshape(-1))
        audio = np.concatenate(chunks) if chunks else np.zeros(int(SR * 0.1), np.float32)
        return _trim(audio)


def _trim(a, thresh=0.004):
    """Remove leading/trailing near-silence so our own pauses are exact."""
    idx = np.where(np.abs(a) > thresh)[0]
    if len(idx) == 0:
        return a
    s, e = max(0, idx[0] - int(0.02 * SR)), min(len(a), idx[-1] + int(0.08 * SR))
    return a[s:e]


def split_sentences(paragraph):
    return [s.strip() for s in SENTENCE.split(" ".join(paragraph.split())) if s.strip()]


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def chunk_words(sentence, max_chars):
    words, chunks, cur = sentence.split(), [], ""
    for w in words:
        if cur and len(cur) + len(w) + 1 > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def timed_chunks(start, end, sentence, max_chars):
    """Split a sentence into caption chunks, timed proportionally to their length."""
    chunks = chunk_words(sentence, max_chars)
    total = sum(len(c) + 1 for c in chunks)
    t, out = start, []
    for c in chunks:
        d = (end - start) * (len(c) + 1) / total
        out.append((t, t + d, c))
        t += d
    return out


class Track:
    def __init__(self):
        self.parts, self.n, self.cues = [], 0, []

    @property
    def t(self):
        return self.n / SR

    def silence(self, seconds):
        a = np.zeros(int(SR * seconds), np.float32)
        self.parts.append(a)
        self.n += len(a)

    def speech(self, audio, sentence, max_chars=84):
        start = self.t
        self.parts.append(audio)
        self.n += len(audio)
        self.cues += timed_chunks(start, self.t, sentence, max_chars)

    def text(self, voice, text, pause_sentence, pause_paragraph, max_chars=84):
        paras = paragraphs(text)
        for pi, p in enumerate(paras):
            sents = split_sentences(p)
            for si, s in enumerate(sents):
                self.speech(voice.say(s), s, max_chars)
                last_s = si == len(sents) - 1
                if not (last_s and pi == len(paras) - 1):
                    self.silence(pause_paragraph if last_s else pause_sentence)

    def audio(self, peak=0.89):
        a = np.concatenate(self.parts) if self.parts else np.zeros(1, np.float32)
        return a / max(1e-6, np.abs(a).max()) * peak


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n")


def synthesize(script, cfg, out_dir):
    import soundfile as sf

    v = cfg["voice"]
    voice = Voice(v["id"], v["speed"])
    tr = Track()
    timing = {"chapters": []}

    tr.silence(LEAD)
    if script.get("cold_open"):
        s = tr.t
        tr.text(voice, script["cold_open"], v["pause_sentence"] * 0.8, v["pause_paragraph"] * 0.8)
        timing["cold_open"] = {"start": s, "end": tr.t}
        print(f"  voiced cold open ({tr.t:.0f} s)")
    s = tr.t + 0.6
    tr.silence(TITLE_GAP)
    timing["title_card"] = {"start": s, "end": tr.t}

    for ci, ch in enumerate(script["chapters"]):
        start = tr.t
        tr.silence(CHAPTER_LEAD)
        tr.text(voice, ch["text"], v["pause_sentence"], v["pause_paragraph"])
        if ci < len(script["chapters"]) - 1:
            tr.silence(v["pause_chapter"])
        timing["chapters"].append({"title": ch["title"], "start": start, "end": tr.t})
        print(f"  voiced chapter {ci + 1}/{len(script['chapters'])} -> {tr.t / 60:.1f} min")

    s = tr.t
    tr.silence(OUTRO)
    timing["outro"] = {"start": s, "end": tr.t}
    timing["duration"] = tr.t
    sf.write(out_dir / "narration.wav", tr.audio(), SR)
    write_srt(tr.cues, out_dir / "captions.srt")
    return timing


def synthesize_short(text, cfg, out_wav, speed=1.0):
    """Shorts voice: normal pace, tight pauses. Returns (duration, caption cues)."""
    import soundfile as sf

    voice = Voice(cfg["voice"]["id"], speed)
    tr = Track()
    tr.silence(0.25)
    tr.text(voice, text, 0.22, 0.35, max_chars=22)
    tr.silence(0.9)
    sf.write(out_wav, tr.audio(), SR)
    return tr.t, tr.cues
