"""Font lookup. Inter (SIL Open Font License) is installed on the runner via apt (fonts-inter)."""
import pathlib

from PIL import ImageFont

DIRS = ["/usr/share/fonts/opentype/inter", "/usr/share/fonts/truetype/inter",
        "/usr/local/share/fonts", str(pathlib.Path.home() / ".fonts")]
FALLBACK = {
    "light": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-ExtraLight.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
    "bold": ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
}
NAMES = {
    "thin": ["InterDisplay-ExtraLight.otf", "InterDisplay-Thin.otf", "Inter-ExtraLight.otf"],
    "light": ["InterDisplay-Light.otf", "Inter-Light.otf"],
    "regular": ["InterDisplay-Regular.otf", "Inter-Regular.otf"],
    "semibold": ["InterDisplay-SemiBold.otf", "Inter-SemiBold.otf"],
    "bold": ["InterDisplay-Bold.otf", "Inter-Bold.otf"],
    "black": ["InterDisplay-Black.otf", "Inter-Black.otf", "InterDisplay-ExtraBold.otf"],
}
_cache = {}


def font(weight, size):
    key = (weight, size)
    if key in _cache:
        return _cache[key]
    candidates = [pathlib.Path(d) / n for n in NAMES[weight] for d in DIRS]
    candidates += [pathlib.Path(p) for p in FALLBACK["bold" if weight in ("semibold", "bold", "black") else "light"]]
    for c in candidates:
        if c.exists():
            _cache[key] = ImageFont.truetype(str(c), size)
            return _cache[key]
    _cache[key] = ImageFont.load_default(size)
    return _cache[key]
