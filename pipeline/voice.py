"""Narration + exact subtitle timings.

Two engines (voice.engine in the channel config):
  kokoro  open-source TTS (Apache-2.0) on the CPU of the GitHub runner
  qwen    Qwen3-TTS (Apache-2.0) cloning the channel's narrator voice, run on Kaggle's GPUs together with the
          AI scenes (pipeline/gpu.py); here we only read back one wav per sentence (PrecomputedVoice)

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


class PrecomputedVoice:
    """Sentences already voiced on the GPU: say(text) returns that sentence's audio at SR."""

    def __init__(self, folder, items, fallback=None):
        self.folder, self.fallback = folder, fallback
        self.index = {text: idx for idx, text in items}
        self.missing = []

    def path(self, text):
        idx = self.index.get(" ".join(text.split()))
        return None if idx is None else self.folder / f"{idx:05d}.wav"

    def say(self, text, speed=None):
        import soundfile as sf
        p = self.path(text)
        if p is None or not p.exists():
            self.missing.append(text)
            if self.fallback is None:
                raise RuntimeError(f"no narration for: {text[:80]}")
            return self.fallback.say(text, speed)
        a, sr = sf.read(p, dtype="float32")
        if a.ndim > 1:
            a = a.mean(axis=1)
        if sr != SR:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(sr, SR)
            a = resample_poly(a, SR // g, sr // g).astype(np.float32)
        return _trim(a)


def narration_items(script, unit="sentence", inner_end=None):
    """Every text unit the episode will speak (episode + Shorts), each once, numbered. A unit is one sentence, or
    with unit="paragraph" up to 3 sentences of the same paragraph voiced in ONE generation (see units())."""
    texts = []
    blocks = [script.get("cold_open", "")] + [c["text"] for c in script["chapters"]]
    blocks += [s.get("narration", "") for s in script.get("shorts", [])]
    seen = set()
    for b in blocks:
        for p in paragraphs(b or ""):
            for u in units(p, unit):
                t = spoken(u, inner_end)
                if t not in seen:
                    seen.add(t)
                    texts.append(t)
    return list(enumerate(texts))


UNIT_MAX_SENTENCES = 3
UNIT_MAX_CHARS = 330


def units(paragraph, unit="sentence"):
    """Group a paragraph's sentences into the pieces voiced in one generation.

    Sentence by sentence, the TTS ends EVERY sentence with a full final fall (~-5 st, measured), so each one sounds
    like the last and the narration feels boxed in. A real documentary narrator keeps the voice suspended across a
    thought (Planeta Antiguo: ~-0.6 st at phrase ends) - voicing 2-3 sentences together gives the model the context
    to do the same. Long paragraphs are split into balanced groups (no 1-sentence leftovers when avoidable)."""
    sents = split_sentences(paragraph)
    if unit != "paragraph" or len(sents) < 2:
        return [[s] for s in sents]
    groups, cur = [], []
    for s in sents:
        if cur and (len(cur) >= UNIT_MAX_SENTENCES or len(" ".join(cur + [s])) > UNIT_MAX_CHARS):
            groups.append(cur)
            cur = []
        cur.append(s)
    if cur:
        groups.append(cur)
    if len(groups) > 1 and len(groups[-1]) == 1 and len(groups[-2]) == 3:
        groups[-1].insert(0, groups[-2].pop())          # 3+1 -> 2+2
    return groups


def spoken(group, inner_end=None):
    """The text actually sent to the TTS for a group of sentences. With inner_end (",", ";" or "..."), the inner
    periods are read as that mark, so the narrator keeps the thought open instead of closing every sentence;
    captions always show the real sentences."""
    out = []
    for k, x in enumerate(group):
        if inner_end and k < len(group) - 1 and x.endswith("."):
            x = x[:-1] + inner_end
        out.append(x)
    return " ".join(out)


def tighten(a, max_gap=0.85, keep=0.6):
    """Shorten any silence inside a multi-sentence take longer than max_gap to `keep` seconds."""
    hop = int(SR * 0.01)
    n = len(a) // hop
    if n < 20:
        return a
    e = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    quiet = e < e.max() - 42
    out, i = [], 0
    while i < n:
        j = i
        while j < n and quiet[j] == quiet[i]:
            j += 1
        if quiet[i] and 0 < i and j < n and (j - i) / 100 > max_gap:
            k = int(keep * 100 / 2)
            head, tail = a[i * hop:(i + k) * hop].copy(), a[(j - k) * hop:j * hop].copy()
            x = min(len(head), len(tail), int(0.03 * SR))          # 30 ms equal-power crossfade, no click
            r = np.linspace(0, np.pi / 2, x)
            mid = head[-x:] * np.cos(r) + tail[:x] * np.sin(r)
            out += [head[:-x], mid, tail[x:]]
        else:
            out.append(a[i * hop:j * hop])
        i = j
    out.append(a[n * hop:])
    return np.concatenate(out)


def sentence_bounds(a, sents):
    """Where each sentence of a multi-sentence take starts/ends (for the captions): the expected split by text
    length, snapped to the nearest real pause in the audio."""
    dur = len(a) / SR
    if len(sents) < 2:
        return [(0.0, dur)]
    hop = int(SR * 0.01)
    n = len(a) // hop
    e = 20 * np.log10(np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    quiet = e < e.max() - 35
    gaps, i = [], 0
    while i < n:
        if quiet[i]:
            j = i
            while j < n and quiet[j]:
                j += 1
            if j - i >= 12 and i > 0 and j < n:          # >= 120 ms inside the take
                gaps.append(((i + j) / 200, i / 100, j / 100))
            i = j
        else:
            i += 1
    total = sum(len(s) + 1 for s in sents)
    cuts, acc, used = [], 0, set()
    for s in sents[:-1]:
        acc += len(s) + 1
        want = dur * acc / total
        near = [g for k, g in enumerate(gaps) if k not in used and abs(g[0] - want) < max(0.8, 0.15 * dur)]
        if near:
            g = min(near, key=lambda g: abs(g[0] - want))
            used.add(gaps.index(g))
            cuts.append((g[1], g[2]))
        else:
            cuts.append((want, want))
    cuts.sort()
    bounds, t = [], 0.0
    for c0, c1 in cuts:
        bounds.append((t, max(t + 0.1, c0)))
        t = c1
    bounds.append((t, dur))
    return bounds


def _trim(a, thresh=0.004):
    """Remove leading/trailing near-silence so our own pauses are exact. Keeps 50 ms before the first sound and
    150 ms after the last (soft consonants and the natural decay), with short fades so a join never clicks."""
    idx = np.where(np.abs(a) > thresh)[0]
    if len(idx) == 0:
        return a
    s, e = max(0, idx[0] - int(0.05 * SR)), min(len(a), idx[-1] + int(0.15 * SR))
    return _edge_fades(a[s:e].astype(np.float32))


def _edge_fades(a, fade_in=0.01, fade_out=0.06):
    a = a.copy()
    fi, fo = min(len(a) // 4, int(fade_in * SR)), min(len(a) // 4, int(fade_out * SR))
    if fi:
        a[:fi] *= np.sin(np.linspace(0, np.pi / 2, fi)) ** 2
    if fo:
        a[-fo:] *= np.cos(np.linspace(0, np.pi / 2, fo)) ** 2
    return a


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


def is_reveal(paragraph, index):
    """A "reveal line": a paragraph that is ONE short sentence (the writer isolates the payoff of a build-up this
    way, prompts/chapter.md). The narrator pauses a little longer before it and the sound design breathes into it."""
    s = split_sentences(paragraph)
    return index > 0 and len(s) == 1 and len(s[0].split()) <= 14


class Track:
    def __init__(self):
        self.parts, self.n, self.cues, self.reveals = [], 0, [], []

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

    def text(self, voice, text, pause_sentence, pause_paragraph, max_chars=84, unit="sentence", inner_end=None,
             pitch_edit=None, reveal_pause=0.0):
        paras = paragraphs(text)
        for pi, p in enumerate(paras):
            if reveal_pause and is_reveal(p, pi):
                self.silence(reveal_pause)          # the beat before the payoff
                self.reveals.append(round(self.t, 3))
            groups = units(p, unit)
            for gi, g in enumerate(groups):
                if len(g) == 1:
                    self.speech(voice.say(g[0]), g[0], max_chars)
                else:
                    a = tighten(voice.say(spoken(g, inner_end)))
                    if pitch_edit:
                        from .prosody import edit
                        a = edit(a, SR, pitch_edit)
                    start = self.t
                    self.parts.append(a)
                    self.n += len(a)
                    for s, (b0, b1) in zip(g, sentence_bounds(a, g)):
                        self.cues += timed_chunks(start + b0, start + b1, s, max_chars)
                last = gi == len(groups) - 1
                if not (last and pi == len(paras) - 1):
                    self.silence(pause_paragraph if last else pause_sentence)

    def audio(self, peak=0.89, quiet_breaths=False):
        a = np.concatenate(self.parts) if self.parts else np.zeros(1, np.float32)
        if quiet_breaths:
            a = quiet_pauses(a)
        return a / max(1e-6, np.abs(a).max()) * peak


def quiet_pauses(x, below=24, min_ms=120, atten_db=-24, hold_ms=160, pre_ms=70, close_ms=140, open_ms=40):
    """Breaths and noise INSIDE pauses (> `below` dB under the speech level for >= min_ms) turned down (Luis: "se
    escucha como que toma aire"), without ever chopping a word: the natural decay of the last syllable is kept for
    hold_ms and then faded down over close_ms; the gain is fully back pre_ms before the next word (soft onsets like
    "s", "f", "h" stay whole). 18-oct: the first version kept only 20 ms and closed in 15 ms, which cut the tails
    of words at every join ("suena como que algo se corta")."""
    hop = int(SR * 0.01)
    n = len(x) // hop
    if n < 10:
        return x
    e = 20 * np.log10(np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
    q = e < np.percentile(e, 90) - below
    speech = ~q
    # short quiet runs are part of speech
    i = 0
    while i < n:
        if q[i]:
            j = i
            while j < n and q[j]:
                j += 1
            if (j - i) * 10 < min_ms:
                speech[i:j] = True
            i = j
        else:
            i += 1
    # keep the word tails and the run-up to the next word
    keep = speech.copy()
    hold, pre = hold_ms // 10, pre_ms // 10
    idx = np.where(speech)[0]
    for k in idx:
        keep[k:k + hold + 1] = True
        keep[max(0, k - pre):k] = True
    target = np.where(keep, 0.0, float(atten_db))
    # gain in dB moves at most this fast per 10 ms frame: slow close, quicker open (finished before the word)
    down, up = -atten_db / max(1, close_ms // 10), -atten_db / max(1, open_ms // 10)
    g = np.zeros(n)
    cur = 0.0
    for k in range(n):
        cur = max(target[k], cur - down) if target[k] < cur else min(target[k], cur + up)
        g[k] = cur
    centers = (np.arange(n) + 0.5) * hop
    gs = 10 ** (np.interp(np.arange(len(x)), centers, g) / 20)
    return (x * gs).astype(np.float32)


def srt_time(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def write_srt(cues, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (a, b, text) in enumerate(cues, 1):
            f.write(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n")


def synthesize(script, cfg, out_dir, voice=None):
    import soundfile as sf

    v = cfg["voice"]
    voice = voice or Voice(v["id"], v["speed"])
    tr = Track()
    timing = {"chapters": []}
    unit = v.get("unit", "sentence") if isinstance(voice, PrecomputedVoice) else "sentence"
    inner_end = v.get("inner_end") if unit == "paragraph" else None
    pitch_edit = v.get("pitch_edit") if unit == "paragraph" else None

    tr.silence(LEAD)
    if script.get("cold_open"):
        s = tr.t
        tr.text(voice, script["cold_open"], v["pause_sentence"] * 0.8, v["pause_paragraph"] * 0.8, unit=unit,
                inner_end=inner_end, pitch_edit=pitch_edit, reveal_pause=v.get("pause_reveal", 0.0))
        timing["cold_open"] = {"start": s, "end": tr.t}
        print(f"  voiced cold open ({tr.t:.0f} s)")
    s = tr.t + 0.6
    tr.silence(TITLE_GAP)
    timing["title_card"] = {"start": s, "end": tr.t}

    for ci, ch in enumerate(script["chapters"]):
        start = tr.t
        tr.silence(CHAPTER_LEAD)
        tr.text(voice, ch["text"], v["pause_sentence"], v["pause_paragraph"], unit=unit,
                inner_end=inner_end, pitch_edit=pitch_edit, reveal_pause=v.get("pause_reveal", 0.0))
        if ci < len(script["chapters"]) - 1:
            tr.silence(v["pause_chapter"])
        timing["chapters"].append({"title": ch["title"], "start": start, "end": tr.t})
        print(f"  voiced chapter {ci + 1}/{len(script['chapters'])} -> {tr.t / 60:.1f} min")

    s = tr.t
    tr.silence(OUTRO)
    timing["outro"] = {"start": s, "end": tr.t}
    timing["duration"] = tr.t
    timing["reveals"] = tr.reveals
    sf.write(out_dir / "narration.wav", tr.audio(quiet_breaths=v.get("quiet_breaths", False)), SR)
    write_srt(tr.cues, out_dir / "captions.srt")
    return timing


def synthesize_short(text, cfg, out_wav, speed=1.0, voice=None):
    """Shorts voice: normal pace, tight pauses. Returns (duration, caption cues)."""
    import soundfile as sf

    voice = voice or Voice(cfg["voice"]["id"], speed)
    tr = Track()
    tr.silence(0.25)
    unit = cfg["voice"].get("unit", "sentence") if isinstance(voice, PrecomputedVoice) else "sentence"
    inner_end = cfg["voice"].get("inner_end") if unit == "paragraph" else None
    pitch_edit = cfg["voice"].get("pitch_edit") if unit == "paragraph" else None
    tr.text(voice, text, 0.22, 0.35, max_chars=22, unit=unit, inner_end=inner_end, pitch_edit=pitch_edit)
    tr.silence(0.9)
    sf.write(out_wav, tr.audio(quiet_breaths=cfg["voice"].get("quiet_breaths", False)), SR)
    return tr.t, tr.cues
