import json
import os
import pathlib
import re
import subprocess

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
# One repo, several channels. CHANNEL picks channels/<name>.yaml (merged over config.yaml) and its own
# data folder (topic queue, episodes done, media already used). Quiet Cosmos keeps the original paths.
DEFAULT_CHANNEL = "quiet-cosmos"
CHANNEL = (os.environ.get("CHANNEL") or DEFAULT_CHANNEL).strip()
DATA = ROOT / "data" if CHANNEL == DEFAULT_CHANNEL else ROOT / "data" / "channels" / CHANNEL
LANG_NAMES = {"en": "English", "es": "Spanish (neutral Latin American)"}


def _merge(base, over):
    for k, v in (over or {}).items():
        base[k] = _merge(base.get(k, {}), v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


def load_config():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    if CHANNEL != DEFAULT_CHANNEL:
        path = ROOT / "channels" / f"{CHANNEL}.yaml"
        if not path.exists():
            raise SystemExit(f"unknown channel '{CHANNEL}': {path} not found")
        cfg = _merge(cfg, yaml.safe_load(path.read_text(encoding="utf-8")))
    return cfg


def read_json(path, default):
    p = pathlib.Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def write_json(path, obj):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "episode"


def run(cmd):
    subprocess.run([str(c) for c in cmd], check=True)


def media_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def extract_json(text):
    """Pull the first JSON object/array out of a model reply."""
    text = re.sub(r"```(?:json)?", "", text)
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ValueError("no JSON found")
    start = min(starts)
    closer = "}" if text[start] == "{" else "]"
    end = text.rfind(closer)
    return json.loads(text[start:end + 1])


def timestamp(seconds):
    s = int(seconds)
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"
