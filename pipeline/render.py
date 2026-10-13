"""Video assembly with FFmpeg: slow Ken Burns motion, soft dissolves through black, narration + ambient music."""
import itertools
import os
from concurrent.futures import ThreadPoolExecutor

from .common import run

TAIL = 4.0  # seconds of music after the last word


def _segment(job):
    img, frames, idx, cfg, out = job
    v = cfg["video"]
    w, h, fps = v["width"], v["height"], v["fps"]
    W, H = int(w * 1.5) // 2 * 2, int(h * 1.5) // 2 * 2
    dur = frames / fps
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    motion = [
        (f"1+0.12*on/{frames}", center_x, center_y),                 # slow push in
        (f"1.12-0.12*on/{frames}", center_x, center_y),              # slow pull out
        ("1.12", f"(iw-iw/zoom)*on/{frames}", center_y),             # drift left -> right
        ("1.12", f"(iw-iw/zoom)*(1-on/{frames})", center_y),         # drift right -> left
        ("1.12", center_x, f"(ih-ih/zoom)*(1-on/{frames})"),         # drift upward
    ][idx % 5]
    fade = min(1.2, dur / 4)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"zoompan=z='{motion[0]}':x='{motion[1]}':y='{motion[2]}':d={frames}:s={w}x{h}:fps={fps},"
          f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={dur - fade:.3f}:d={fade:.2f},format=yuv420p")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", img, "-vf", vf, "-frames:v", frames,
         "-c:v", "libx264", "-preset", v["preset"], "-crf", v["crf"], "-r", fps, out])


def build_timeline(timing, chapter_images, cfg):
    """One (image, start, end) per shot; each chapter shows its own images."""
    spi, shots = cfg["video"]["seconds_per_image"], []
    for i, (mark, images) in enumerate(zip(timing["chapters"], chapter_images)):
        start = mark["start"]
        end = mark["end"] + (TAIL if i == len(timing["chapters"]) - 1 else 0)
        count = max(1, round((end - start) / spi))
        cycle = itertools.cycle(images)
        for k in range(count):
            shots.append((next(cycle)["path"], start + (end - start) * k / count,
                          start + (end - start) * (k + 1) / count))
    return shots


def render(timing, chapter_images, narration, music, out_dir, cfg):
    fps = cfg["video"]["fps"]
    seg_dir = out_dir / "segments"
    seg_dir.mkdir(exist_ok=True)
    shots = build_timeline(timing, chapter_images, cfg)
    jobs = []
    for idx, (img, a, b) in enumerate(shots):
        frames = round(b * fps) - round(a * fps)     # frame-exact, no drift
        jobs.append((img, frames, idx, cfg, seg_dir / f"{idx:04d}.mp4"))
    print(f"  rendering {len(jobs)} shots...")
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        list(pool.map(_segment, jobs))

    listing = out_dir / "segments.txt"
    listing.write_text("".join(f"file '{j[4].resolve()}'\n" for j in jobs))
    total = timing["duration"] + TAIL
    final = out_dir / "video.mp4"
    vol = cfg["video"]["music_volume"]
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", listing,
         "-i", narration,
         "-stream_loop", "-1", "-i", music,
         "-filter_complex",
         f"[1:a]aresample=48000,apad=pad_dur={TAIL}[n];"
         f"[2:a]aresample=48000,volume={vol},afade=t=in:d=6[m];"
         f"[n][m]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
         f"afade=t=out:st={total - 4}:d=4,loudnorm=I=-16:TP=-1.5:LRA=11[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-ar", "48000", "-t", f"{total:.3f}", "-movflags", "+faststart", final])
    for j in jobs:
        j[4].unlink(missing_ok=True)
    return final
