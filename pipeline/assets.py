"""Visuals from the NASA Image and Video Library (free API, no key; NASA media is generally public domain).

Stills: filtered for subject (no people/hardware/charts), size, orientation and visual interest.
Clips: real NASA footage (time-lapses from the ISS, solar observatory films, visualizations),
cut to a calm segment, slowed slightly and conformed to 1080p/24fps.
"""
import io
import json
import pathlib
import re
import subprocess

import numpy as np
import requests
from PIL import Image, ImageStat

from .common import slugify

API = "https://images-api.nasa.gov/search"
Image.MAX_IMAGE_PIXELS = None
MAX_IMG_BYTES = 60 * 1024 * 1024
MAX_VID_BYTES = 450 * 1024 * 1024
UA = {"User-Agent": "quiet-cosmos-pipeline/2.0"}

BLOCK = (
    "astronaut", "crew", "portrait", "logo", "insignia", "patch", "press conference", "briefing",
    "employee", "ceremony", "headshot", "meeting", "chart", "graph", "slide", "launch pad", "rollout",
    "worker", "technician", "visitor", "award", "interview", "panel", "q&a", "town hall", "students",
    "children", "parade", "tour", "museum", "exhibit", "plaque", "flag", "aircraft", "airplane",
    "helicopter", "wind tunnel", "laboratory", "clean room", "cleanroom", "assembly", "mockup",
    "training", "simulator", "engineer", "scientist", "administrator", "senator", "congress",
    "speaks", "speech", "news", "this week", "update", "countdown", "live coverage", "webcast",
    "podcast", "selfie", "signing", "test stand", "hot fire", "facility", "office", "director",
    "launch", "liftoff", "lift-off", "rocket", "telescope in space", "spacecraft illustration",
)
VIDEO_PREFER = (
    "animation", "visualization", "time-lapse", "timelapse", "time lapse", "flyover", "fly-over",
    "flyby", "fly-by", "flythrough", "fly-through", "zoom", "sdo", "solar dynamics", "4k", "uhd",
    "ultra hd", "earth from space", "views of earth", "hubble", "webb", "chandra", "spitzer",
    "juno", "cassini", "galaxy", "nebula", "aurora", "earth at night", "orbit", "planet",
    "sun", "moon", "mars", "saturn", "jupiter", "supernova", "black hole", "star",
)
FALLBACK_QUERIES = ["nebula Hubble", "spiral galaxy Hubble", "star cluster Hubble",
                    "Webb deep field", "Earth from space night", "Milky Way", "aurora from space"]


def _search(query, media_type):
    r = requests.get(API, params={"q": query, "media_type": media_type, "page_size": 50},
                     headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()["collection"]["items"]


def _manifest(item):
    urls = requests.get(item["href"], headers=UA, timeout=30).json()
    return [u.replace(" ", "%20").replace("http://", "https://") for u in urls]


def _text(d):
    return " ".join([d.get("title", ""), d.get("description", "")[:600],
                     " ".join(d.get("keywords", []) or [])]).lower()


def _blocked(text):
    return any(b in text for b in BLOCK)


_BLOCK_RE = re.compile(r"\b(" + "|".join(re.escape(b) for b in BLOCK) + r")\b")


def _blocked_video(d):
    """Videos: judge by title + keywords only, whole words. NASA video descriptions almost always mention
    a launch date or a 'news' page, which used to reject nearly every real clip (v2 bug)."""
    text = " ".join([d.get("title", ""), " ".join(d.get("keywords", []) or [])]).lower()
    return bool(_BLOCK_RE.search(text))


# ------------------------------------------------------------------ stills
def _interest(im):
    """Reject flat, washed-out or document-like images; prefer contrast and colour."""
    small = im.copy()
    small.thumbnail((256, 256))
    gray = ImageStat.Stat(small.convert("L"))
    hsv = ImageStat.Stat(small.convert("HSV"))
    std, mean, sat = gray.stddev[0], gray.mean[0], hsv.mean[1]
    if std < 14:
        return None                       # nearly uniform
    if mean > 185 and sat < 40:
        return None                       # white background: charts, documents, hardware shots
    return std + sat * 0.5


def _download_image(url, path):
    with requests.get(url, stream=True, headers=UA, timeout=60) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(1 << 20):
            buf.write(chunk)
            if buf.tell() > MAX_IMG_BYTES:
                return None
    im = Image.open(buf).convert("RGB")
    w, h = im.size
    if w < 1400 or w / h < 1.0:          # too small, or portrait (crops badly to 16:9)
        return None
    score = _interest(im)
    if score is None:
        return None
    im.thumbnail((3840, 3840), Image.LANCZOS)
    im.save(path, "JPEG", quality=92)
    return score


def _best_image_url(urls):
    imgs = [u for u in urls if u.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff"))]
    for tag in ("~orig.jpg", "~orig.png", "~orig.jpeg", "~large."):
        for u in imgs:
            if tag in u.lower():
                return u
    return imgs[0] if imgs else None


def fetch_images(queries, want, out_dir, used, per_query=3):
    out_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for allow_used in (False, True):           # second pass only if the channel exhausted a subject
        for query in list(queries) + FALLBACK_QUERIES:
            if len(got) >= want:
                break
            try:
                items = _search(query, "image")
            except Exception as exc:
                print(f"    image search failed '{query}': {exc}")
                continue
            taken = 0
            for item in items:
                if taken >= per_query or len(got) >= want:
                    break
                try:
                    d = item["data"][0]
                    nid = d["nasa_id"]
                    if (nid in used and not allow_used) or any(g["nasa_id"] == nid for g in got):
                        continue
                    if _blocked(_text(d)):
                        continue
                    url = _best_image_url(_manifest(item))
                    path = out_dir / f"{slugify(nid)}.jpg"
                    score = url and _download_image(url, path)
                    if score:
                        used.add(nid)
                        got.append({"path": str(path), "nasa_id": nid, "title": d.get("title", ""),
                                    "score": score})
                        taken += 1
                except Exception:
                    continue
        if len(got) >= want * 0.5:
            break
    return got


# ------------------------------------------------------------------ clips
def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    info = json.loads(out.stdout or "{}")
    st = (info.get("streams") or [{}])[0]
    return st.get("width", 0), st.get("height", 0), float(info.get("format", {}).get("duration", 0) or 0)


def _pick_video_url(urls):
    mp4 = [u for u in urls if u.lower().endswith(".mp4")]
    for tag in ("~large.mp4", "~orig.mp4", "~medium.mp4"):
        for u in mp4:
            if tag in u.lower():
                try:
                    size = int(requests.head(u, headers=UA, timeout=20, allow_redirects=True)
                               .headers.get("Content-Length", 0))
                except Exception:
                    size = 0
                if size <= MAX_VID_BYTES:      # 0 = size unknown: the streamed download enforces the cap
                    return u
    return None


def _download_file(url, path, limit):
    with requests.get(url, stream=True, headers=UA, timeout=120) as r:
        r.raise_for_status()
        n = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
                n += len(chunk)
                if n > limit:
                    return False
    return True


def conform_clip(src, dst, seconds, W=1920, H=1080, fps=24, slow=1.35, margin=3.0, start_at=None):
    """Take a calm middle segment, slow it slightly (frame blending), conform to WxH@fps.
    margin: seconds skipped at each end (NASA clips open/close with slates and logos).
    start_at: fraction 0..1 of where in the usable span to cut (None = the middle)."""
    w, h, dur = _probe(src)
    if w < 1200 or dur < 2 * margin + 1.5:
        return None
    usable = dur - 2 * margin
    need = seconds / slow
    if usable < need:
        slow = max(1.0, seconds / max(usable, 1))
        need = seconds / slow
        if slow > 2.2:
            return None
    frac = 0.5 if start_at is None else min(max(start_at, 0.0), 1.0)
    start = margin + max(0.0, (usable - need) * frac)
    vf = (f"setpts={slow:.3f}*PTS,framerate=fps={fps},"
          f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=yuv420p")
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{need:.2f}",
                        "-i", str(src), "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "18", "-r", str(fps), str(dst)])
    if r.returncode != 0:
        return None
    return _probe(dst)[2]


def fetch_clips(queries, want, out_dir, used, seconds=14, W=1920, H=1080, fps=24):
    out_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for query in queries:
        if len(got) >= want:
            break
        try:
            items = _search(query, "video")
        except Exception as exc:
            print(f"    video search failed '{query}': {exc}")
            continue
        for item in items[:25]:
            if len(got) >= want:
                break
            try:
                d = item["data"][0]
                nid = d["nasa_id"]
                text = _text(d)
                if nid in used or _blocked_video(d) or not any(p in text for p in VIDEO_PREFER):
                    continue
                url = _pick_video_url(_manifest(item))
                if not url:
                    continue
                raw = out_dir / f"{slugify(nid)}.raw.mp4"
                dst = out_dir / f"{slugify(nid)}.mp4"
                ok = _download_file(url, raw, MAX_VID_BYTES)
                dur = ok and conform_clip(raw, dst, seconds, W, H, fps)
                raw.unlink(missing_ok=True)
                if dur and dur >= seconds * 0.6:
                    used.add(nid)
                    got.append({"path": str(dst), "nasa_id": nid, "title": d.get("title", ""),
                                "duration": dur})
                    break                              # one clip per query keeps variety
            except Exception:
                continue
    return got


def frame_stats(path):
    """Mean brightness of an image (used to pick thumbnails and opening shots)."""
    im = Image.open(path).convert("L")
    im.thumbnail((128, 128))
    return float(np.asarray(im).mean())
