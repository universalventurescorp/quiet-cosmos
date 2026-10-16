"""Automatic quality gate before anything is uploaded."""
import json
import re
import subprocess

from .common import media_duration


def loudness(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                        "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"I:\s+(-?\d+\.\d+) LUFS", r.stderr)
    return float(m[-1]) if m else None


def black_spans(path, shots):
    """Near-pure black for >3 s on a still/clip shot (star-field shots are dark by design)."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:v:0",
                        "-vf", "blackdetect=d=3:pix_th=0.02:pic_th=0.995", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    spans = [(float(a), float(b)) for a, b in
             re.findall(r"black_start:(\d+\.?\d*) black_end:(\d+\.?\d*)", r.stderr)]
    bad = []
    for a, b in spans:
        for s in shots:
            if s["kind"] != "stars" and s["start"] < b and a < s["end"]:
                bad.append((round(a, 1), round(b, 1)))
                break
    return bad


def check_episode(out, script, timing, media, shots, video, ai_media=None):
    fails, warns = [], []
    dur = media_duration(video)
    if abs(dur - timing["duration"]) > 2.5:
        fails.append(f"video is {dur:.1f}s but narration timeline is {timing['duration']:.1f}s")
    lufs = loudness(video)
    if lufs is None:
        fails.append("no audio stream")
    elif not -22 <= lufs <= -11:
        fails.append(f"loudness {lufs} LUFS outside safe range")
    for i, m in enumerate(media, 1):
        if len(m["images"]) < 3:
            warns.append(f"chapter {i}: only {len(m['images'])} images")
    for i, c in enumerate(script["chapters"], 1):
        if re.search(r"(?im)^\s*(chapter|cap[ií]tulo)\s+\w+", c["text"]):
            fails.append(f"chapter {i}: heading left in narration")
        if re.search(r"\d", c["text"]):
            warns.append(f"chapter {i}: contains digits (TTS may read them oddly)")
        if len(c["text"].split()) < 150:
            fails.append(f"chapter {i}: suspiciously short ({len(c['text'].split())} words)")
    bad = black_spans(video, shots)
    if bad:
        warns.append(f"black frames at {bad}")
    ai_media = ai_media or {}
    if ai_media.get("status") not in (None, "ok", "off"):
        warns.append(f"AI scenes: {ai_media['status']} (episode used NASA imagery only)")
    for e in ai_media.get("errors", [])[:3]:
        warns.append(f"Kaggle: {e[-300:]}")
    minutes = dur / 60
    report = {"ok": not fails, "fails": fails, "warnings": warns, "minutes": round(minutes, 1),
              "lufs": lufs, "shots": len(shots), "clips": sum(s["kind"] == "clip" for s in shots),
              "ai_scenes": sum(bool(s.get("ai")) for s in shots),
              "ai_clips": sum(bool(s.get("ai")) and s["kind"] == "clip" for s in shots),
              "ai_status": ai_media.get("status"), "gpu_minutes": ai_media.get("gpu_minutes")}
    (out / "qa.json").write_text(json.dumps(report, indent=2))
    return report
