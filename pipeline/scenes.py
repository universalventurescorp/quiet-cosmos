"""AI scenes (v3): Claude designs them, Kaggle paints them, the narration places them.

plan_scenes   Claude writes image prompts anchored to sentences of the narration (+ motion for video scenes)
build_job     the job sent to the Kaggle GPU worker (prompts, seeds, models, budget)
place_scenes  after narration: each scene gets the exact time its sentence is spoken
"""
import json
import re
import unicodedata
import zlib

from .common import extract_json
from .script import ask_claude, fill

GROUP = 3            # chapters per Claude call


def _counts(script, cfg):
    """How many AI scenes each section gets, from the expected narration length."""
    ai, v = cfg["ai"], cfg["video"]
    wpm, spi, share = cfg["voice"]["wpm"], v["seconds_per_image"], ai.get("share", 0.45)
    raw = []
    for c in script["chapters"]:
        seconds = len(c["text"].split()) / wpm * 60
        raw.append(max(2, round(seconds / spi * share)))
    cap = ai.get("max_images", 140) - 3
    if sum(raw) > cap:
        raw = [max(2, int(n * cap / sum(raw))) for n in raw]
    return raw


def plan_scenes(script, cfg):
    ai = cfg["ai"]
    counts = _counts(script, cfg)
    vpc = ai.get("videos_per_chapter", 1)
    sections = []
    if script.get("cold_open"):
        sections.append({"id": "cold_open", "count": 3, "videos": 1, "text": script["cold_open"],
                         "title": "Cold open (the hook before the title)"})
    for i, (c, n) in enumerate(zip(script["chapters"], counts), 1):
        sections.append({"id": f"chapter_{i}", "count": n, "videos": min(vpc, n), "text": c["text"],
                         "title": c["title"]})

    result = {}
    for g in range(0, len(sections), GROUP):
        group = sections[g:g + GROUP]
        body = "\n\n".join(
            f'### Section id "{s["id"]}" — {s["title"]}\nScenes: {s["count"]} · videos: {s["videos"]}\n'
            f'Narration:\n{s["text"]}' for s in group)
        want = {s["id"]: s for s in group}

        def ok(d):
            got = {x.get("id"): x.get("scenes") for x in d.get("sections", [])} if isinstance(d, dict) else {}
            return all(isinstance(got.get(k), list) and got[k] for k in want)

        for attempt in range(3):
            try:
                data = extract_json(ask_claude(fill("scenes.md", CHANNEL=cfg["channel"]["name"],
                                                    STYLE=ai["style"], SECTIONS=body)))
                if ok(data):
                    for x in data["sections"]:
                        if x.get("id") in want:
                            result[x["id"]] = [s for s in x["scenes"] if s.get("prompt")][: want[x["id"]]["count"] + 1]
                    break
            except Exception as exc:                           # noqa: BLE001
                print(f"    scene plan attempt {attempt + 1} failed: {exc}")
        print(f"  scenes {', '.join(f'{k}:{len(result.get(k, []))}' for k in want)}")
    return {"sections": [{"id": s["id"], "scenes": result.get(s["id"], [])} for s in sections]}


def build_job(plan, cfg, job_id, topic):
    ai, kg = cfg["ai"], cfg.get("kaggle", {})
    images, videos = [], []
    for sec in plan["sections"]:
        for k, sc in enumerate(sec["scenes"]):
            sid = f"{sec['id']}_{k:02d}"
            seed = zlib.crc32(f"{topic}|{sid}".encode()) % 2_000_000_000
            images.append({"id": sid, "prompt": sc["prompt"], "seed": seed,
                           "video": bool(sc.get("video"))})
            if sc.get("video"):
                videos.append({"id": sid, "image": sid, "prompt": f"{sc['prompt']} {sc.get('motion', '')}".strip(),
                               "seed": seed})
    # priority: video sources first, then round-robin across sections (a short run still covers every chapter)
    by_sec = {}
    for im in images:
        by_sec.setdefault(im["id"].rsplit("_", 1)[0], []).append(im)
    order = [im for im in images if im["video"]]
    queues = [[im for im in q if not im["video"]] for q in by_sec.values()]
    while any(queues):
        for q in queues:
            if q:
                order.append(q.pop(0))
    return {
        "job_id": job_id,
        "style": ai["style"],
        "negative": ai.get("negative", ""),
        "image_model": ai.get("image_model", "stabilityai/stable-diffusion-xl-base-1.0"),
        "video_model": ai.get("video_model", "Lightricks/LTX-Video") if ai.get("videos_per_chapter", 1) else "",
        "steps": ai.get("steps", 30),
        "width": 1344, "height": 768,
        "video_width": 960, "video_height": 544, "video_frames": 121, "video_steps": ai.get("video_steps", 40),
        "upscale": True,
        "budget_minutes": kg.get("gpu_budget_minutes", 150),
        "images": order,
        "videos": videos,
    }


# ---------------------------------------------------------------- placing scenes on the timeline
def _norm(word):
    word = unicodedata.normalize("NFKD", word.lower())
    return "".join(ch for ch in word if ch.isalnum())


def read_srt(path):
    cues = []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        a, b = (_srt_seconds(x.strip()) for x in lines[1].split("-->"))
        cues.append((a, b, " ".join(lines[2:])))
    return cues


def _srt_seconds(s):
    h, m, rest = s.split(":")
    sec, ms = rest.replace(".", ",").split(",")
    return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000


def word_times(cues):
    """(time, normalized word) for every spoken word; cue time spread evenly over its words."""
    out = []
    for a, b, text in cues:
        words = [w for w in (_norm(x) for x in text.split()) if w]
        for k, w in enumerate(words):
            out.append((a + (b - a) * k / max(1, len(words)), w))
    return out


def find_anchor(words, anchor, t0, t1, after):
    target = [w for w in (_norm(x) for x in anchor.split()) if w]
    if not target:
        return None
    seg = [(t, w) for t, w in words if t0 - 0.5 <= t < t1 and t >= after]
    ws = [w for _, w in seg]
    for n in (min(6, len(target)), 4, 3):
        if n > len(target) or n < 3:
            continue
        key = target[:n]
        for i in range(len(ws) - n + 1):
            if ws[i:i + n] == key:
                return seg[i][0]
    return None


def place_scenes(plan, ai_files, cues, timing, min_gap=6.0):
    """-> {"cold_open": [...], "chapter_1": [...]} items: {id, at, path, clip?}, sorted, spaced >= min_gap."""
    words = word_times(cues)
    spans = {"cold_open": (timing["cold_open"]["start"], timing["cold_open"]["end"])} if timing.get("cold_open") else {}
    for i, ch in enumerate(timing["chapters"], 1):
        spans[f"chapter_{i}"] = (ch["start"], ch["end"])
    placed = {}
    for sec in plan["sections"]:
        if sec["id"] not in spans:
            continue
        t0, t1 = spans[sec["id"]]
        items, after = [], t0
        for k, sc in enumerate(sec["scenes"]):
            sid = f"{sec['id']}_{k:02d}"
            if sid not in ai_files["images"]:
                continue
            at = find_anchor(words, sc.get("anchor", ""), t0, t1, after)
            items.append({"id": sid, "at": at, "path": ai_files["images"][sid],
                          "depth": ai_files.get("depth", {}).get(sid),
                          "clip": ai_files.get("clips", {}).get(sid)})
            if at is not None:
                after = at
        # scenes whose sentence was not found: spread evenly between their neighbours
        k = 0
        while k < len(items):
            if items[k]["at"] is not None:
                k += 1
                continue
            j = k
            while j < len(items) and items[j]["at"] is None:
                j += 1
            prev = items[k - 1]["at"] if k > 0 else t0
            nxt = items[j]["at"] if j < len(items) else t1
            for r, it in enumerate(items[k:j], 1):
                it["at"] = prev + (nxt - prev) * r / (j - k + 1)
            k = j
        items.sort(key=lambda x: x["at"])
        kept, last = [], t0 + (8.0 if sec["id"] != "cold_open" else 0.0)   # leave the chapter card on its own shot
        for it in items:
            if it["at"] >= last - 0.01 and it["at"] < t1 - 4.0:
                kept.append(it)
                last = it["at"] + (min_gap * 0.6 if sec["id"] == "cold_open" else min_gap)
        placed[sec["id"]] = kept
    return placed


def credits_line(lang):
    return {"en": "Some scenes are AI-generated artistic reconstructions (labelled on screen), "
                  "made to show what cameras cannot capture; they are based on current science.",
            "es": "Algunas escenas son recreaciones artísticas generadas con IA (señaladas en pantalla), "
                  "hechas para mostrar lo que ninguna cámara puede captar; se basan en la ciencia actual."}[lang]


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- files coming back from the GPU
def conform_ai_clip(src, dst, W, H, fps, slow, mode="mci"):
    """Slow the generated clip down (motion-interpolated, so it stays smooth) and conform to WxH@fps."""
    import subprocess

    from .common import media_duration
    if dst.exists():
        return media_duration(dst)
    interp = (f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" if mode == "mci"
              else f"framerate=fps={fps}")
    vf = (f"setpts={slow:.3f}*PTS,{interp},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
          f"crop={W}:{H},format=yuv420p")
    tmp = dst.with_suffix(".part.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, "-an",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-r", str(fps), str(tmp)])
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        return None
    tmp.rename(dst)
    return media_duration(dst)


def prepare_ai_files(ai_dir, cfg):
    """Depth maps for the stills, conformed clips. -> {"images": {id: path}, "depth": {...}, "clips": {...}}"""
    from .depth import depth_map
    ai, v = cfg["ai"], cfg["video"]
    files = {"images": {}, "depth": {}, "clips": {}}
    if not ai_dir.exists():
        return files
    for p in sorted(ai_dir.glob("*.jpg")):
        if p.name.startswith("."):
            continue
        files["images"][p.stem] = str(p)
        if ai.get("parallax", True):
            d = depth_map(p, ai_dir / f"{p.stem}.depth.png")
            if d:
                files["depth"][p.stem] = d
    clip_dir = ai_dir / "clips"
    clip_dir.mkdir(exist_ok=True)
    for p in sorted(ai_dir.glob("*.mp4")):
        if p.name.startswith("."):
            continue
        dur = conform_ai_clip(p, clip_dir / p.name, v["width"], v["height"], v["fps"],
                              ai.get("video_slowdown", 1.6), ai.get("video_interpolation", "mci"))
        if dur:
            files["clips"][p.stem] = {"path": str(clip_dir / p.name), "duration": dur}
    print(f"   AI: {len(files['images'])} stills ({len(files['depth'])} with depth), {len(files['clips'])} clips")
    return files
