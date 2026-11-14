"""Vertical Shorts (1080x1920) cut from each episode's best facts: fast hook, bold captions, real footage.
They exist to pull new viewers into the long episodes (and toward 1,000 subscribers)."""
import math

from . import cards, engine
from .assets import fetch_clips, fetch_images
from .mix import mix
from .render import _fill
from .voice import synthesize_short

W, H, FPS = 1080, 1920, 30
MAX_SECONDS = 58.0


def _tempo(wav, cues, dur, factor):
    """Speed up an already-voiced Short (GPU voice): ffmpeg atempo keeps the pitch; captions follow."""
    from .common import run
    tmp = wav.with_name("voice_tempo.wav")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", f"atempo={factor:.4f}", str(tmp)])
    tmp.replace(wav)
    return dur / factor, [(a / factor, b / factor, t) for a, b, t in cues]


def _short_sfx(path, dur, cues, seed, every=6.0):
    """14-nov-2026 (Luis): los Shorts se sentían vacíos (solo la voz). Fondo de espacio profundo todo el Short,
    golpe al empezar, barrido cada ~6 s (en una pausa entre frases) y una subida suave en medio de cada tramo."""
    from .sfx import make_sfx
    starts = [a for a, _, _ in cues] or [0.0]
    cuts, t = [0.0], every
    while t < dur - 6:
        nxt = min((a for a in starts if a >= t - 2), default=None)        # el inicio de frase más cercano
        if nxt is None or nxt > dur - 5:
            break
        cuts.append(nxt)
        t = nxt + every
    chapters = [{"start": a, "end": b} for a, b in zip(cuts, cuts[1:] + [dur])]
    reveals = [min(starts, key=lambda x: abs(x - (c["start"] + c["end"]) / 2)) for c in chapters]
    timing = {"duration": dur, "chapters": chapters, "reveals": sorted(set(reveals)), "title_card": {"start": 0.15}}
    script = {"chapters": [{"ambience": "deep_space"} for _ in chapters]}
    make_sfx(path, timing, script, seed=seed)
    return path


def produce_short(short, idx, cfg, out_dir, used, music, fallback_images, voice=None, ai_images=None):
    """ai_images: [(ruta, texto con el que se pintó)] de las escenas IA del episodio."""
    d = out_dir / f"short_{idx}"
    d.mkdir(parents=True, exist_ok=True)
    sc = cfg.get("shorts", {})
    speed = sc.get("voice_speed", 1.0)
    wav = d / "voice.wav"
    dur, cues = synthesize_short(short["narration"], cfg, wav, speed, voice=voice)
    if voice is not None:                                  # pre-voiced: pace set by time-stretch
        factor = max(sc.get("gpu_voice_tempo", 1.1), dur / (MAX_SECONDS - 1))
        dur, cues = _tempo(wav, cues, dur, factor)
    elif dur > MAX_SECONDS:                                # keep it a Short
        speed = speed * dur / (MAX_SECONDS - 1)
        dur, cues = synthesize_short(short["narration"], cfg, wav, speed)
    if dur > MAX_SECONDS + 2:
        print(f"    short {idx}: too long ({dur:.0f}s), skipped")
        return None

    spi = sc.get("seconds_per_shot", 4.5)
    need = math.ceil(dur / spi * 0.8)
    imgs = []
    if sc.get("cinematic") and ai_images:
        # 14-nov-2026 (Luis): imágenes grandes y de cine (las escenas pintadas por la GPU y los astros de la
        # miniatura), cada Short con las suyas; NASA solo completa si faltan
        # cada imagen con el texto con el que se pintó: se eligen las que hablan de lo mismo que el Short
        import re
        words = lambda t: {w for w in re.findall(r"[a-záéíóúñ]+", (t or "").lower()) if len(w) > 3}
        topic = words(" ".join(short.get("image_queries", []) + short.get("video_queries", []) +
                               [short.get("title", ""), short.get("hook", "")]))
        scored = sorted(((len(words(pr) & topic), q) for q, pr in ai_images), key=lambda x: -x[0])
        imgs = [{"path": q} for n, q in scored if n >= 1][:need]
    if len(imgs) < need:
        imgs += fetch_images(short.get("image_queries", []), need - len(imgs), d / "images", used, 2)
    if len(imgs) < 4:
        imgs += fallback_images[: 6 - len(imgs)]
    clips = [] if (sc.get("cinematic") and len(imgs) >= need) else \
        fetch_clips(short.get("video_queries", []), 2, d / "clips", used, seconds=8, W=W, H=H, fps=FPS)

    shots = _fill(0.0, dur, imgs, clips, spi, 3)
    overlays = [cards.short_hook(W, H, short.get("hook", ""), 0.0, 3.0)] if short.get("hook") else []
    overlays += [cards.caption(W, H, text, a, b) for a, b, text in cues]
    if (cfg.get("thumbnail") or {}).get("style") == "duerme":     # sello de marca durante todo el Short
        overlays.append(cards.brand_seal(W, H, cfg["channel"].get("wordmark", cfg["channel"]["name"]).upper(),
                                         0.0, dur))
    if short.get("source"):                                # proof line in the last seconds
        label = "Source" if cfg["channel"].get("language") == "en" else "Fuente"
        overlays.append(cards.source_line(W, H, f"{label}: {short['source']}", max(0.0, dur - 5.0), dur))
    sfx = None
    if sc.get("sound_design"):
        try:
            sfx = _short_sfx(d / "sfx.wav", dur, cues, seed=1000 + idx, every=sc.get("sfx_every", 6.0))
        except Exception as exc:                                       # noqa: BLE001
            print(f"    short {idx}: sin diseño de sonido ({exc})")
    audio = mix(wav, music, d / "audio.wav", dur, music_volume=sc.get("music_volume", 0.22), lufs=-14, fade_out=1.0,
                sfx=sfx, sfx_volume=sc.get("sfx_volume", 1.0),
                voice_eq=cfg.get("mix", {}).get("voice_eq", "clean"),
                voice_pitch_st=cfg.get("mix", {}).get("voice_pitch_st", 0.0),
                voice_size_st=cfg.get("mix", {}).get("voice_size_st", 0.0))
    out = d / "short.mp4"
    engine.render(shots, overlays, audio, out, W, H, FPS, dur, crf=21, preset="veryfast",
                  fade_in=0.15, fade_out=0.8, progress_every=0)
    return {"path": str(out), "title": short.get("title", "")[:95], "duration": round(dur, 1),
            "narration": short["narration"], "source": short.get("source", "")}
