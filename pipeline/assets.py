"""Visuals from the NASA Image and Video Library (free API, no key, NASA imagery is generally public domain)."""
import io

import requests
from PIL import Image

from .common import slugify

API = "https://images-api.nasa.gov/search"
Image.MAX_IMAGE_PIXELS = None
MAX_BYTES = 60 * 1024 * 1024
BLOCK = ("astronaut", "crew", "portrait", "logo", "insignia", "patch", "press conference",
         "employee", "ceremony", "headshot", "meeting", "chart", "graph", "slide", "launch pad",
         "rollout", "worker", "technician", "visitor", "award")
FALLBACK_QUERIES = ["nebula Hubble", "spiral galaxy Hubble", "star cluster Hubble",
                    "Webb deep field", "Earth from space night", "Milky Way"]


def _search(query):
    r = requests.get(API, params={"q": query, "media_type": "image", "page_size": 40}, timeout=30)
    r.raise_for_status()
    return r.json()["collection"]["items"]


def _best_url(item):
    manifest = requests.get(item["href"], timeout=30).json()
    urls = [u.replace(" ", "%20").replace("http://", "https://") for u in manifest
            if u.lower().endswith((".jpg", ".jpeg", ".png"))]
    for tag in ("~orig.", "~large."):
        for u in urls:
            if tag in u:
                return u
    return urls[0] if urls else None


def _download(url, path):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        buf = io.BytesIO()
        for chunk in r.iter_content(1 << 20):
            buf.write(chunk)
            if buf.tell() > MAX_BYTES:
                return False
    im = Image.open(buf).convert("RGB")
    w, h = im.size
    if w < 1400 or w / h < 0.9:          # too small, or portrait (crops badly to 16:9)
        return False
    im.thumbnail((3840, 3840), Image.LANCZOS)
    im.save(path, "JPEG", quality=92)
    return True


def fetch_images(queries, want, out_dir, used):
    """Download up to `want` fresh images for one chapter; `used` = NASA ids already used on the channel."""
    out_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for query in list(queries) + FALLBACK_QUERIES:
        if len(got) >= want:
            break
        try:
            items = _search(query)
        except Exception as exc:
            print(f"  search failed '{query}': {exc}")
            continue
        taken = 0
        for item in items:
            if taken >= 2 or len(got) >= want:   # max 2 per query keeps visuals varied
                break
            try:
                d = item["data"][0]
                nid = d["nasa_id"]
                text = (d.get("title", "") + " " + " ".join(d.get("keywords", []))).lower()
                if nid in used or any(b in text for b in BLOCK):
                    continue
                url = _best_url(item)
                path = out_dir / f"{slugify(nid)}.jpg"
                if url and _download(url, path):
                    used.add(nid)
                    got.append({"path": str(path), "nasa_id": nid, "title": d.get("title", "")})
                    taken += 1
            except Exception:
                continue
    return got
