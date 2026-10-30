"""Long journeys for Estrato Nocturno (30-oct-2026): 3 h (Mon/Thu) and the whole night, 8 h (Sat).

GitHub stops every job at 6 h and one machine renders ~45 min of episode in that time, so a long journey runs
in stages (workflow .github/workflows/largo.yml), each one resuming from the files of the one before:

  STAGE=script   Claude writes the whole journey + designs the AI scenes, Kaggle is launched
  STAGE=prepare  waits for Kaggle (voice on both GPUs, then scenes), narration, NASA, music, mix, AI scenes
  STAGE=render   PART=i PARTS=k: each machine paints one slice of the picture (no audio), in parallel
  STAGE=finish   the slices are joined with the audio; thumbnails, Shorts, QA, upload

The AI scenes are concentrated in the first hour (when people are still watching); after that the journey
leans on NASA footage, and gets slower and softer towards the end (longer pauses, calmer chapters).
"""
import os

from .common import DATA, read_json


def mode():
    return (os.environ.get("LONG") or "").strip() or None


def stage():
    return (os.environ.get("STAGE") or "").strip() or None


def apply(cfg, name):
    lc = (cfg.get("long") or {}).get(name)
    if not lc:
        raise SystemExit(f"unknown long format {name!r} (see 'long:' in the channel config)")
    v = cfg["video"]
    v["target_minutes"] = lc["minutes"]
    v["chapters"] = lc.get("chapters") or max(5, round(lc["minutes"] / 6.5))
    ai = cfg.setdefault("ai", {})
    ai["max_images"] = lc.get("max_images", ai.get("max_images", 140))
    ai["full_minutes"] = lc.get("full_minutes", 60)
    kg = cfg.setdefault("kaggle", {})
    kg["gpu_budget_minutes"] = lc.get("gpu_budget_minutes", 200)
    kg["wait_minutes"] = lc.get("wait_minutes", 330)
    cfg["_long"] = dict(lc, name=name)
    return cfg


def next_topic(cfg):
    lc = cfg["_long"]
    done = {d["topic"] for d in read_json(DATA / "done.json", [])}
    for t in lc.get("topics", []):
        if t not in done:
            return t
    raise SystemExit(f"no topics left for the {lc['name']} journeys: add more under long.{lc['name']}.topics")


def taper(minute, full_minutes):
    """Share of AI scenes at this point of the journey: full in the first hour, then fewer and fewer."""
    if minute < full_minutes:
        return 1.0
    if minute < 2 * full_minutes:
        return 0.35
    return 0.12


def pause_factor(index, total, cfg):
    """Pauses grow slowly through the night: x1 at the start, up to x`slow_to` in the last chapter."""
    lc = cfg.get("_long") or {}
    end = lc.get("slow_to", 1.0)
    if total <= 1 or end == 1.0:
        return 1.0
    return 1.0 + (end - 1.0) * index / (total - 1)


def chapter_rule(index, total, cfg):
    """Extra instruction for chapter `index` (1-based) of a long journey; '' for normal episodes."""
    lc = cfg.get("_long")
    if not lc:
        return ""
    third = index / total
    if index == total:
        return lc.get("final_rule", "")
    if third > 0.66:
        return (" We are deep into the night and most listeners are asleep: shorter, simpler sentences, very few "
                "numbers, slower images, softer wonder. Keep telling the story, just more gently.")
    if third > 0.33:
        return " The night is advancing: a little slower and softer than the first chapters, fewer numbers."
    return ""


def title(base, cfg):
    lc = cfg.get("_long") or {}
    label = lc.get("title_label")
    if not label or "hora" in base.lower():
        return base
    full = f"{base} | {label}"
    return full if len(full) <= 100 else base
