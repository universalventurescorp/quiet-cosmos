"""Depth maps for the 2.5D camera (Depth Anything V2 Small, Apache-2.0, runs on the CPU in ~1-2 s/image)."""
import numpy as np
from PIL import Image

MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
_pipe = None


def _get():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline("depth-estimation", model=MODEL, device="cpu")
    return _pipe


def depth_map(image_path, out_path):
    """Writes an 8-bit PNG, bright = near. Returns the path, or None if depth is unavailable."""
    if out_path.exists():
        return str(out_path)
    try:
        im = Image.open(image_path).convert("RGB")
        im.thumbnail((1024, 1024))
        d = np.asarray(_get()(im)["depth"], np.float32)
        lo, hi = np.percentile(d, 1), np.percentile(d, 99)
        d = np.clip((d - lo) / max(hi - lo, 1e-6), 0, 1)
        Image.fromarray((d * 255).astype(np.uint8)).save(out_path)
        return str(out_path)
    except Exception as exc:                                    # noqa: BLE001
        print(f"    depth unavailable for {image_path}: {exc}")
        return None
