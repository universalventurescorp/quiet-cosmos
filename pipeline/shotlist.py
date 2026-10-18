"""Movie mode: the episode as a shot list (fast cutting, ~5 s per shot).

plan_shots   Claude turns the narration into shots: real footage / animal in motion / still / map
gpu_job      animal + still shots → the Kaggle job (images; animals also get an image→video clip)
fetch_real   real shots → Pixabay footage, cut to each shot's length
summary      counts and seconds per type (diagnostics and QA)

Config (config.yaml → movie:):
  seconds_per_shot: 5      average cut length, decides how many shots each section asks for
  mix: {real: 35, animal: 25, still: 25, map: 15}   target share of shots, in %
  max_animals: 170         cap on animal clips per episode (GPU time)
"""
import zlib

from .common import extract_json
from .script import ask_claude, fill

GROUP = 3                     # sections per Claude call
TYPES = ("real", "animal", "still", "map")
LENGTH = {"real": (4, 8), "animal": (3, 4), "still": (5, 8), "map": (6, 10)}
DEFAULT_MIX = {"real": 35, "animal": 25, "still": 25, "map": 15}


def _sections(script, cfg):
    m = cfg.get("movie", {})
    wpm, sps = cfg["voice"]["wpm"], m.get("seconds_per_shot", 5)
    out = []
    if script.get("cold_open"):
        secs = len(script["cold_open"].split()) / wpm * 60
        out.append({"id": "cold_open", "title": "Cold open (the hook, cut fast)", "text": script["cold_open"],
                    "count": max(4, round(secs / 3.5))})
    for i, c in enumerate(script["chapters"], 1):
        secs = len(c["text"].split()) / wpm * 60
        out.append({"id": f"chapter_{i}", "title": c["title"], "text": c["text"], "count": max(3, round(secs / sps))})
    return out


def _clean(shot):
    t = shot.get("type")
    if t not in TYPES or not shot.get("anchor"):
        return None
    if t == "real" and not shot.get("query"):
        return None
    if t in ("animal", "still") and not shot.get("prompt"):
        return None
    if t == "map":
        try:
            shot["age_myr"] = float(shot.get("age_myr"))
        except (TypeError, ValueError):
            return None
    lo, hi = LENGTH[t]
    try:
        s = float(shot.get("seconds", (lo + hi) / 2))
    except (TypeError, ValueError):
        s = (lo + hi) / 2
    shot["seconds"] = min(max(s, lo if t != "real" else 3), hi)
    return shot


def plan_shots(script, cfg):
    m = cfg.get("movie", {})
    mix = {**DEFAULT_MIX, **m.get("mix", {})}
    lang = "Spanish" if cfg["channel"].get("language") == "es" else "English"
    sections = _sections(script, cfg)
    result = {}
    for g in range(0, len(sections), GROUP):
        group = sections[g:g + GROUP]
        want = {s["id"]: s for s in group}
        body = "\n\n".join(f'### Section id "{s["id"]}" — {s["title"]}\nShots: about {s["count"]}\n'
                           f'Narration:\n{s["text"]}' for s in group)
        prompt = fill("shotlist.md", CHANNEL=cfg["channel"]["name"], LANGUAGE=lang, SECTIONS=body,
                      REAL=mix["real"], ANIMAL=mix["animal"], STILL=mix["still"], MAP=mix["map"])
        for attempt in range(3):
            try:
                data = extract_json(ask_claude(prompt))
                got = {x.get("id"): x.get("shots") for x in data.get("sections", [])}
                if all(isinstance(got.get(k), list) and got[k] for k in want):
                    for k in want:
                        result[k] = [s for s in (_clean(dict(x)) for x in got[k]) if s]
                    break
            except Exception as exc:                           # noqa: BLE001
                print(f"    shot list attempt {attempt + 1} failed: {exc}")
        print(f"  shots {', '.join(f'{k}:{len(result.get(k, []))}' for k in want)}")
    plan = {"sections": [{"id": s["id"], "shots": result.get(s["id"], [])} for s in sections]}
    _cap_animals(plan, m.get("max_animals", 170))
    return plan


def _cap_animals(plan, cap):
    """Over the GPU budget: the surplus animal shots become stills (same prompt, parallax instead of motion),
    dropping evenly across the episode so no chapter loses all its animals."""
    animals = [s for sec in plan["sections"] for s in sec["shots"] if s["type"] == "animal"]
    extra = len(animals) - cap
    if extra <= 0:
        return
    step = len(animals) / extra
    for k in range(extra):
        s = animals[int(k * step)]
        s["type"], s["seconds"] = "still", max(s["seconds"], 5)


def gpu_job(plan, cfg, job_id, topic):
    """Kaggle job in the same format as scenes.build_job: animal shots first (they also need a clip)."""
    from .scenes import build_job
    scene_plan = {"sections": []}
    for sec in plan["sections"]:
        scenes = []
        for s in sec["shots"]:
            if s["type"] in ("animal", "still"):
                s["ai_id"] = f"{sec['id']}_{len(scenes):02d}"        # the id build_job gives this scene
                scenes.append({"prompt": s["prompt"], "motion": s.get("motion", ""), "video": s["type"] == "animal"})
        scene_plan["sections"].append({"id": sec["id"], "scenes": scenes})
    job = build_job(scene_plan, cfg, job_id, topic)
    m = cfg.get("movie", {})
    job.update({"video_frames": m.get("video_frames", 97),          # 97 frames @24 fps = 4 s, one shot
                "video_kind": m.get("video_kind", "distilled"),
                "video_style": m.get("video_style", "Natural, realistic movement, steady cinematic camera."),
                "max_videos": len(job["videos"])})
    return job


def fetch_real(plan, out_dir, used, cfg):
    """Pixabay footage for every real shot; each shot gets its own cut at its own length.
    Shots that find nothing are marked missing (the editor fills them with a still)."""
    from . import pixabay
    v = cfg["video"]
    if not pixabay.configured():
        print("   PIXABAY_API_KEY missing: real shots will be filled with stills")
        return {}
    got = {}
    for sec in plan["sections"]:
        for k, s in enumerate(sec["shots"]):
            if s["type"] != "real":
                continue
            sid = f"{sec['id']}_{k:03d}"
            clips = pixabay.fetch_clips([s["query"]], 1, out_dir, used, seconds=s["seconds"],
                                        W=v["width"], H=v["height"], fps=v["fps"], shots_per_clip=1, per_query=1)
            if clips:
                got[sid] = clips[0]
    return got


def summary(plan):
    out = {t: {"shots": 0, "seconds": 0.0} for t in TYPES}
    for sec in plan["sections"]:
        for s in sec["shots"]:
            out[s["type"]]["shots"] += 1
            out[s["type"]]["seconds"] += s["seconds"]
    total = sum(x["seconds"] for x in out.values()) or 1
    for x in out.values():
        x["seconds"] = round(x["seconds"], 1)
        x["share"] = round(100 * x["seconds"] / total)
    return out
