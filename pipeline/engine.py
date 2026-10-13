"""Frame-accurate compositor.

Every frame is composed in Python/OpenCV and piped to FFmpeg:
- stills get smooth, sub-pixel camera moves (no zoompan jitter)
- real video clips play inside the same timeline
- procedural star fields add depth between sections
- consecutive shots cross-dissolve; text cards fade over the picture
FFmpeg then applies a light film finish (grade, vignette, grain) and muxes the audio.
"""
import math
import subprocess

import cv2
import numpy as np

from .procedural import StarField

XFADE = 1.6  # seconds of cross-dissolve between shots


def ease(x):
    """Gentle ease-in-out (sine) clamped to 0..1."""
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


# ---------------------------------------------------------------- sources
class StillSource:
    """A photo with a slow camera move. `move` picks one of several move styles."""
    MOVES = 6

    def __init__(self, path, W, H, duration, move, travel=1.0):
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cannot read {path}")
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self.W, self.H, self.d = W, H, max(0.1, duration)
        # cover-fit the image to 1.22x the frame, so zooms/pans never show edges
        k = max(W * 1.22 / img.shape[1], H * 1.22 / img.shape[0])
        interp = cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC
        self.img = cv2.resize(img, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=interp)
        self.sw, self.sh = self.img.shape[1], self.img.shape[0]
        zin, zout = 1.0, 1.0 + 0.16 * travel
        span = 0.5 * travel
        # (zoom0, zoom1, (cx0, cy0), (cx1, cy1)) with centres in -1..1 of the free margin
        self.move = [
            (zin, zout, (0, 0), (0, 0)),                  # push in
            (zout, zin, (0, 0), (0, 0)),                  # pull back
            (1.06, 1.06, (-span, 0), (span, 0)),          # truck left -> right
            (1.06, 1.06, (span, 0), (-span, 0)),          # truck right -> left
            (zin, 1.0 + 0.1 * travel, (0, span), (0, -span * 0.4)),   # rise
            (1.0 + 0.1 * travel, zin, (-span * 0.6, -span * 0.3), (span * 0.3, span * 0.2)),  # drift
        ][move % self.MOVES]

    def frame(self, t):
        z0, z1, c0, c1 = self.move
        p = ease(t / self.d) * 0.85 + (t / self.d) * 0.15   # mostly eased, never fully stops
        z = z0 + (z1 - z0) * p
        cx = c0[0] + (c1[0] - c0[0]) * p
        cy = c0[1] + (c1[1] - c0[1]) * p
        # visible window in source pixels (always the output's aspect ratio, never beyond the image)
        base = min(self.sw / self.W, self.sh / self.H) / 1.22
        vw = self.W * base / z
        vh = self.H * base / z
        mx, my = (self.sw - vw) / 2, (self.sh - vh) / 2
        x0 = mx + cx * mx
        y0 = my + cy * my
        s = self.W / vw
        M = np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]])
        return cv2.warpAffine(self.img, M, (self.W, self.H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)

    def close(self):
        pass


class ClipSource:
    """A video file already prepared at the output size/fps; read sequentially through FFmpeg."""

    def __init__(self, path, W, H, fps, duration):
        self.W, self.H, self.d = W, H, duration
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
              f"fps={fps},format=rgb24")
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", vf, "-an",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=W * H * 3 * 4)
        self.size = W * H * 3
        self.last = np.zeros((H, W, 3), np.uint8)

    def frame(self, t):
        if self.proc:
            buf = self.proc.stdout.read(self.size)
            if len(buf) == self.size:
                self.last = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
            else:                       # clip ran out: hold the last frame
                self.close()
        return self.last

    def close(self):
        if self.proc:
            self.proc.stdout.close()
            self.proc.kill()
            self.proc.wait()
            self.proc = None


class StarsSource:
    """Procedural flight through a star field, optionally over a dimmed backdrop photo."""

    def __init__(self, W, H, duration, seed, backdrop=None, speed=1.0):
        self.field = StarField(W, H, seed=seed, speed=speed)
        self.bg = StillSource(backdrop, W, H, duration, 0, travel=0.6) if backdrop else None
        self.d = duration

    def frame(self, t):
        base = None
        if self.bg is not None:
            base = (self.bg.frame(t).astype(np.float32) * 0.42)
        return self.field.render(t, base)

    def close(self):
        pass


def open_source(shot, W, H, fps):
    d = shot["end"] - shot["start"] + XFADE
    if shot["kind"] == "still":
        return StillSource(shot["path"], W, H, d, shot.get("move", 0), shot.get("travel", 1.0))
    if shot["kind"] == "clip":
        return ClipSource(shot["path"], W, H, fps, d)
    if shot["kind"] == "stars":
        return StarsSource(W, H, d, shot.get("seed", 1), shot.get("backdrop"), shot.get("speed", 1.0))
    raise ValueError(shot["kind"])


# ---------------------------------------------------------------- overlays
def blend_overlay(frame, ov, alpha):
    """Alpha-blend an RGBA overlay (same size as frame, cropped to its bbox) onto frame."""
    x0, y0, x1, y1 = ov["bbox"]
    rgba = ov["rgba"]
    a = rgba[:, :, 3:4].astype(np.float32) * (alpha / 255.0)
    region = frame[y0:y1, x0:x1].astype(np.float32)
    region = region * (1 - a) + rgba[:, :, :3].astype(np.float32) * a
    frame[y0:y1, x0:x1] = region.astype(np.uint8)


def overlay_alpha(ov, t):
    if t < ov["start"] or t > ov["end"]:
        return 0.0
    fi, fo = ov.get("fade_in", 1.0), ov.get("fade_out", 1.0)
    a = 1.0
    if fi > 0:
        a = min(a, (t - ov["start"]) / fi)
    if fo > 0:
        a = min(a, (ov["end"] - t) / fo)
    return max(0.0, min(1.0, a))


# ---------------------------------------------------------------- main loop
def render(shots, overlays, audio, out, W, H, fps, total, crf=20, preset="veryfast",
           finish=True, fade_in=1.5, fade_out=3.0, progress_every=60):
    """shots: list of dicts sorted by start, contiguous (shot[i].end == shot[i+1].start).
    Each shot is drawn from start - XFADE/2 to end + XFADE/2 and dissolves into the next."""
    shots = sorted(shots, key=lambda s: s["start"])
    n_frames = int(round(total * fps))
    vf = ["format=yuv420p"]
    if finish:
        vf = ["eq=contrast=1.04:saturation=1.06:gamma=0.98",
              "vignette=angle=PI/5.5",
              "noise=c0s=3:c0f=t",
              f"fade=t=in:st=0:d={fade_in}",
              f"fade=t=out:st={max(0, total - fade_out):.3f}:d={fade_out}",
              "format=yuv420p"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
           "-i", str(audio),
           "-vf", ",".join(vf),
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-tune", "film",
           "-g", str(fps * 4), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    half = XFADE / 2
    active = {}            # shot index -> source
    overlays = sorted(overlays, key=lambda o: o["start"])
    black = np.zeros((H, W, 3), np.uint8)
    try:
        for f in range(n_frames):
            t = f / fps
            # which shots are visible at time t
            vis = [i for i, s in enumerate(shots) if s["start"] - half <= t < s["end"] + half]
            for i in vis:
                if i not in active:
                    active[i] = open_source(shots[i], W, H, fps)
            for i in [k for k in active if k not in vis]:
                active.pop(i).close()

            if not vis:
                frame = black.copy()
            elif len(vis) == 1:
                i = vis[0]
                frame = active[i].frame(t - (shots[i]["start"] - half))
            else:
                a, b = vis[0], vis[1]
                fa = active[a].frame(t - (shots[a]["start"] - half))
                fb = active[b].frame(t - (shots[b]["start"] - half))
                w = ease((t - (shots[b]["start"] - half)) / XFADE)
                frame = cv2.addWeighted(fa, 1 - w, fb, w, 0)
                for extra in vis[2:]:          # very short shots: keep the stream advancing
                    active[extra].frame(t - (shots[extra]["start"] - half))
            if not frame.flags.writeable:
                frame = frame.copy()

            for ov in overlays:
                if ov["start"] > t:
                    break
                al = overlay_alpha(ov, t)
                if al > 0:
                    blend_overlay(frame, ov, al)

            enc.stdin.write(frame.tobytes())
            if progress_every and f % (fps * progress_every) == 0:
                print(f"    {t / 60:5.1f} / {total / 60:.1f} min", flush=True)
    finally:
        for s in active.values():
            s.close()
        enc.stdin.close()
        rc = enc.wait()
    if rc != 0:
        raise RuntimeError("ffmpeg encode failed")
    return out
