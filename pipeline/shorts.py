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


def produce_short(short, idx, cfg, out_dir, used, music, fallback_images):
    d = out_dir / f"short_{idx}"
    d.mkdir(parents=True, exist_ok=True)
    sc = cfg.get("shorts", {})
    speed = sc.get("voice_speed", 1.0)
    wav = d / "voice.wav"
    dur, cues = synthesize_short(short["narration"], cfg, wav, speed)
    if dur > MAX_SECONDS:                                  # keep it a Short
        speed = speed * dur / (MAX_SECONDS - 1)
        dur, cues = synthesize_short(short["narration"], cfg, wav, speed)
    if dur > MAX_SECONDS + 2:
        print(f"    short {idx}: too long ({dur:.0f}s), skipped")
        return None

    spi = sc.get("seconds_per_shot", 4.5)
    imgs = fetch_images(short.get("image_queries", []), math.ceil(dur / spi * 0.8), d / "images", used, 2)
    if len(imgs) < 4:
        imgs += fallback_images[: 6 - len(imgs)]
    clips = fetch_clips(short.get("video_queries", []), 2, d / "clips", used, seconds=8, W=W, H=H, fps=FPS)

    shots = _fill(0.0, dur, imgs, clips, spi, 3)
    overlays = [cards.short_hook(W, H, short.get("hook", ""), 0.0, 3.0)] if short.get("hook") else []
    overlays += [cards.caption(W, H, text, a, b) for a, b, text in cues]
    audio = mix(wav, music, d / "audio.wav", dur, music_volume=0.22, lufs=-14, fade_out=1.0)
    out = d / "short.mp4"
    engine.render(shots, overlays, audio, out, W, H, FPS, dur, crf=21, preset="veryfast",
                  fade_in=0.15, fade_out=0.8, progress_every=0)
    return {"path": str(out), "title": short.get("title", "")[:95], "duration": round(dur, 1),
            "narration": short["narration"]}
