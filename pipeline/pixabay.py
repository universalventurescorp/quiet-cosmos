"""Real nature footage from Pixabay (free API key in PIXABAY_API_KEY; Pixabay Content License:
free for commercial use, no attribution required — we still keep the author for the credits).

Built for "movie mode": short real shots (sea, rivers, volcanoes, forests, skies) cut to 4-10 s.
For prehistory topics we drop anything that shows people or the modern world (boats, roads,
buildings...), judged on Pixabay's tags. One long download can yield several distinct shots
(cut from different parts of the clip), so a 5-second cutting rhythm does not need 500 downloads.

Pixabay API rules we follow: cache search results for 24 h, stay under 100 requests/min,
download the files (no hotlinking).
"""
import hashlib
import json
import os
import pathlib
import re
import time

import requests

from .assets import _download_file, _probe, conform_clip

API = "https://pixabay.com/api/videos/"
CACHE = pathlib.Path(os.environ.get("PIXABAY_CACHE", pathlib.Path.home() / ".cache" / "pixabay"))
CACHE_TTL = 24 * 3600
MAX_BYTES = 400 * 1024 * 1024
UA = {"User-Agent": "quiet-cosmos-pipeline/3.0"}

# Things that break the illusion of a world without humans (prehistory, deep time, the far future).
MODERN = (
    "people", "person", "man", "men", "woman", "women", "girl", "boy", "child", "children", "kid",
    "family", "couple", "human", "tourist", "tourists", "hiker", "surfer", "surfing", "swimmer",
    "swimming", "diver", "diving", "fisherman", "fishing", "kayak", "boat", "boats", "ship", "sailboat",
    "yacht", "ferry", "car", "cars", "road", "street", "traffic", "highway", "bridge", "city",
    "town", "village", "building", "buildings", "house", "houses", "skyscraper", "tower", "church",
    "castle", "ruins", "pier", "harbor", "harbour", "port", "lighthouse", "farm", "tractor", "fence",
    "field", "agriculture", "airplane", "plane", "aircraft", "helicopter", "train", "railway",
    "power line", "wind turbine", "windmill", "dam", "pipe", "cable", "wire", "text", "logo",
    "christmas", "wedding", "party", "flag", "dog", "cat", "horse", "cow", "sheep", "chicken",
    "animation", "cartoon", "3d", "render", "abstract", "background", "loop", "particles", "bokeh",
    "green screen", "greenscreen", "chroma",
)


def configured():
    return bool(os.environ.get("PIXABAY_API_KEY"))


def _tag_re(words):
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b") if words else None


_last_call = [0.0]


def search(query, per_page=50, order="popular"):
    """Pixabay video search with a 24 h disk cache (required by the API terms)."""
    params = {"q": query[:100], "video_type": "film", "safesearch": "true",
              "per_page": per_page, "order": order}
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    cached = CACHE / f"{key}.json"
    if cached.exists() and time.time() - cached.stat().st_mtime < CACHE_TTL:
        return json.loads(cached.read_text())
    wait = 0.7 - (time.time() - _last_call[0])          # ≤ ~85 requests/min, under the 100 limit
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()
    r = requests.get(API, params={**params, "key": os.environ["PIXABAY_API_KEY"]}, headers=UA, timeout=30)
    if r.status_code == 429:
        time.sleep(30)
        r = requests.get(API, params={**params, "key": os.environ["PIXABAY_API_KEY"]}, headers=UA, timeout=30)
    r.raise_for_status()
    hits = r.json().get("hits", [])
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(hits))
    return hits


def _best_rendition(hit, min_width):
    """Largest rendition that is at least min_width wide (Pixabay 'large' is often 4K or empty)."""
    best = None
    for name in ("large", "medium", "small"):
        v = (hit.get("videos") or {}).get(name) or {}
        if not v.get("url") or v.get("width", 0) < min_width:
            continue
        if v.get("size", 0) > MAX_BYTES:
            continue
        # prefer the smallest one that is still big enough: 4K files are slow to download and add nothing at 1080p
        if best is None or v.get("width", 0) < best.get("width", 0):
            best = v
    return best


# ------------------------------------------------------------------ visual guard
# Pixabay tags are written by uploaders and are often wrong ("volcano" on a city skyline), so every
# clip is also checked with CLIP (CPU, ~150 MB model) on 3 frames before we cut shots from it.
GOOD = ["untouched wild nature landscape", "a wild ocean or sea", "a wild forest or jungle", "a volcano or lava",
        "sky and clouds", "an underwater scene", "a desert", "wild mountains", "a river or waterfall in the wild",
        "wild animals in nature"]
BAD = ["a city with buildings", "houses, roads or a village", "a person or people", "a car, boat or airplane",
       "a plain studio background", "text, a logo or a graphic", "a farm field or fences", "a beach resort"]
_clip = {}


def _frames(path, n=3):
    from PIL import Image
    import io
    import subprocess
    dur = _probe(path)[2]
    out = []
    for k in range(n):
        t = dur * (k + 1) / (n + 1)
        r = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                            "-vf", "scale=448:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
        if r.stdout:
            out.append(Image.open(io.BytesIO(r.stdout)).convert("RGB"))
    return out


def visual_check(path, threshold=0.30):
    """(ok, worst_bad_label, worst_bad_prob). If CLIP is unavailable, accepts the clip (tags still apply)."""
    try:
        import torch
        from transformers import CLIPModel, CLIPProcessor
    except Exception:
        return True, None, 0.0
    if "m" not in _clip:
        name = "openai/clip-vit-base-patch32"
        _clip["m"], _clip["p"] = CLIPModel.from_pretrained(name).eval(), CLIPProcessor.from_pretrained(name)
    frames = _frames(path)
    if not frames:
        return False, "unreadable", 1.0
    labels = GOOD + BAD
    with torch.no_grad():
        inp = _clip["p"](text=[f"a photo of {l}" for l in labels], images=frames, return_tensors="pt", padding=True)
        probs = _clip["m"](**inp).logits_per_image.softmax(dim=-1)   # frames x labels
    bad = probs[:, len(GOOD):]
    per_frame = bad.sum(dim=-1)
    worst = int(per_frame.argmax())
    label = BAD[int(bad[worst].argmax())]
    p_bad = float(per_frame[worst])
    return p_bad < threshold, label, round(p_bad, 3)


def fetch_clips(queries, want, out_dir, used, seconds=6.0, W=1920, H=1080, fps=24, slow=1.0,
                block=MODERN, shots_per_clip=2, per_query=2, min_width=1920, visual=True, rejected=None):
    """Download real footage for `queries` and cut it into up to `want` shots of `seconds` each.

    used: set of ids already used on the channel ("pixabay:<id>"); updated in place.
    Returns [{path, source, pixabay_id, title, user, page_url, duration}].
    """
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    blocked = _tag_re(block)
    got = []
    for query in queries:
        if len(got) >= want:
            break
        try:
            hits = search(query)
        except Exception as exc:
            print(f"    pixabay search failed '{query}': {exc}")
            continue
        taken = 0
        for hit in hits:
            if len(got) >= want or taken >= per_query:
                break
            uid = f"pixabay:{hit.get('id')}"
            tags = (hit.get("tags") or "").lower()
            if uid in used or (blocked and blocked.search(tags)):
                continue
            if hit.get("duration", 0) < seconds / max(slow, 1.0) + 1.5:
                continue
            rend = _best_rendition(hit, min_width)
            if not rend:
                continue
            raw = out_dir / f"pixabay-{hit['id']}.raw.mp4"
            try:
                if not _download_file(rend["url"], raw, MAX_BYTES):
                    continue
                if visual:
                    ok, why, p_bad = visual_check(raw)
                    if not ok:
                        print(f"    pixabay {hit['id']} rejected by visual check: {why} ({p_bad})")
                        if rejected is not None:
                            rejected.append({"pixabay_id": hit["id"], "tags": tags, "why": why, "p": p_bad,
                                             "frames": _frames(raw)})
                        used.add(uid)          # never try it again
                        continue
                dur = _probe(raw)[2]
                # how many non-overlapping shots fit in this clip (skip 0.5 s at both ends)
                n = max(1, min(shots_per_clip, int((dur - 1.0) // (seconds / max(slow, 1.0) + 1.0))))
                spots = [0.5] if n == 1 else [i / (n - 1) for i in range(n)]
                cut = 0
                for k, frac in enumerate(spots):
                    if len(got) >= want:
                        break
                    dst = out_dir / f"pixabay-{hit['id']}-{k}.mp4"
                    d = conform_clip(raw, dst, seconds, W, H, fps, slow=slow, margin=0.5, start_at=frac)
                    if d and d >= seconds * 0.8:
                        got.append({"path": str(dst), "source": "pixabay", "pixabay_id": hit["id"],
                                    "title": hit.get("tags", ""), "user": hit.get("user", ""),
                                    "page_url": hit.get("pageURL", ""), "duration": d, "query": query})
                        cut += 1
                if cut:
                    used.add(uid)
                    taken += 1
            except Exception as exc:
                print(f"    pixabay clip {hit.get('id')} failed: {exc}")
            finally:
                raw.unlink(missing_ok=True)
    return got


def credits(clips, lang="es"):
    """One credits line listing the Pixabay authors used (not required by the license, but fair)."""
    users = sorted({c["user"] for c in clips if c.get("user")})
    if not users:
        return ""
    head = "Video real: Pixabay" if lang == "es" else "Real footage: Pixabay"
    return f"{head} ({', '.join(users[:30])}{'…' if len(users) > 30 else ''})"


def _self_test():
    """python -m pipeline.pixabay — quick check from GitHub Actions: searches prehistory-style footage,
    cuts a few shots and leaves contact sheets in data/diagnostics/pixabay_test/ (committed)."""
    import subprocess
    from .common import DATA, ROOT, write_json
    out = ROOT / "outputs" / "pixabay-test"
    diag = DATA / "diagnostics" / "pixabay_test"
    diag.mkdir(parents=True, exist_ok=True)
    for f in diag.glob("*"):
        f.unlink()
    queries = ["ocean waves aerial", "volcano lava", "river forest aerial", "fern forest",
               "storm clouds timelapse", "waterfall jungle", "desert dunes aerial", "underwater coral reef"]
    report = {"configured": configured(), "queries": {}}
    if not configured():
        write_json(diag / "manifest.json", report)
        print("PIXABAY_API_KEY missing")
        return
    used = set()
    for q in queries:
        try:
            hits = search(q)
            ok = [h for h in hits if not _tag_re(MODERN).search((h.get("tags") or "").lower())
                  and _best_rendition(h, 1920)]
            report["queries"][q] = {"hits": len(hits), "usable_1080p_no_people": len(ok)}
        except Exception as exc:
            report["queries"][q] = {"error": str(exc)[:300]}
    t = time.time()
    rejected = []
    clips = fetch_clips(queries, 12, out, used, seconds=6.0, shots_per_clip=2, per_query=1, rejected=rejected)
    from PIL import Image
    report["rejected"] = []
    for i, r in enumerate(rejected):
        fr = r.pop("frames")
        if fr:
            sheet = Image.new("RGB", (sum(f.width for f in fr), max(f.height for f in fr)))
            x = 0
            for f in fr:
                sheet.paste(f, (x, 0))
                x += f.width
            sheet.save(diag / f"rejected_{i:02d}.jpg", quality=75)
        report["rejected"].append(r)
    report["seconds"] = round(time.time() - t, 1)
    report["clips"] = [{k: c[k] for k in ("pixabay_id", "title", "user", "duration", "query")} for c in clips]
    for i, c in enumerate(clips):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", c["path"], "-vf",
                        "fps=1/1.5,scale=480:-2,tile=4x1", "-frames:v", "1", str(diag / f"{i:02d}_frames.jpg")])
    write_json(diag / "manifest.json", report)
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    _self_test()
