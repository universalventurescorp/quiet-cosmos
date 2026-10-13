"""Episode edit: turns timing + media into a shot list and overlays, then renders with the engine.

Structure of every episode:
  cold open      fast-ish montage of the episode's best footage under the hook narration
  opening title  flight through stars over a dimmed nebula, channel name + episode title
  chapters       each chapter's own footage: stills with camera moves, real NASA clips every few shots,
                 chapter card at the start
  end card       stars, channel name
"""
import itertools

from . import cards, engine

MIN_SHOT = 3.0


def _fill(start, end, stills, clips, spi, clip_every, move_offset=0):
    """Contiguous shots covering [start, end): stills of ~spi seconds, a clip every `clip_every` shots."""
    shots, t, k = [], start, 0
    clips = list(clips)
    stills = list(stills)
    cyc = itertools.cycle(stills) if stills else None
    last_path = None
    while end - t > 0.01:
        remaining = end - t
        use_clip = clips and (k % clip_every == clip_every - 1)
        if use_clip:
            c = clips.pop(0)
            d = min(c["duration"] - engine.XFADE - 0.2, spi * 1.15)
            shot = {"kind": "clip", "path": c["path"]}
        elif cyc:
            img = next(cyc)
            if img["path"] == last_path and len(stills) > 1:
                img = next(cyc)
            shot = {"kind": "still", "path": img["path"], "move": k + move_offset}
            d = spi
        else:
            shot = {"kind": "stars", "seed": k + 7}
            d = spi
        if remaining - d < MIN_SHOT:          # absorb a tiny remainder into this shot
            d = remaining
            if shot["kind"] == "clip":        # clips cannot stretch: finish on a still instead
                if cyc:
                    img = next(cyc)
                    shot = {"kind": "still", "path": img["path"], "move": k + move_offset}
                else:
                    shot = {"kind": "stars", "seed": k + 7}
        shot.update(start=t, end=t + d)
        shots.append(shot)
        last_path = shot.get("path")
        t += d
        k += 1
    return shots


def best_images(images, n):
    return sorted(images, key=lambda i: -i.get("score", 0))[:n]


def build_episode(timing, script, media, cfg, W=None, H=None):
    v = cfg["video"]
    W, H = W or v["width"], H or v["height"]
    spi = v["seconds_per_image"]
    shots, overlays = [], []
    all_images = [img for m in media for img in m["images"]]
    all_clips = [c for m in media for c in m["clips"]]

    # 1) cold open: the best of every chapter, quicker cuts, opens on motion when possible
    co = timing.get("cold_open")
    t0 = 0.0
    if co:
        hero = [best_images(m["images"], 1)[0] for m in media if m["images"]]
        end = co["end"] + 0.6
        t = 0.0
        if all_clips:                                   # motion in the very first second
            c = all_clips[0]
            d = min(c["duration"] - engine.XFADE - 0.2, spi * 0.8, end - MIN_SHOT)
            if d >= MIN_SHOT:
                shots.append({"kind": "clip", "path": c["path"], "start": 0.0, "end": d})
                t = d
        shots += _fill(t, end, hero, [], spi * 0.6, 99)
        t0 = end

    # 2) opening title
    tc = timing["title_card"]
    tc_end = timing["chapters"][0]["start"] + 0.2
    backdrop = best_images(all_images, 2)[-1]["path"] if all_images else None
    shots.append({"kind": "stars", "seed": 3, "backdrop": backdrop, "start": t0, "end": tc_end})
    overlays.append(cards.opening_title(W, H, cfg["channel"]["name"], script["title"],
                                        tc["start"] + 0.6, tc["end"] - 0.2))

    # 3) chapters
    used_clips = {shots[0]["path"]} if shots and shots[0]["kind"] == "clip" else set()
    for i, (mark, m) in enumerate(zip(timing["chapters"], media)):
        start = tc_end if i == 0 else mark["start"]
        end = mark["end"]
        clips = [c for c in m["clips"] if c["path"] not in used_clips]
        imgs = m["images"] or all_images
        shots += _fill(start, end, imgs, clips, spi, v.get("clip_every", 3), move_offset=i * 2)
        overlays.append(cards.chapter_card(W, H, i + 1, mark["title"], mark["start"] + 0.4, mark["start"] + 7.5))

    # 4) end card
    oc = timing["outro"]
    shots.append({"kind": "stars", "seed": 9, "backdrop": backdrop, "start": oc["start"], "end": timing["duration"],
                  "speed": 0.6})
    overlays.append(cards.end_card(W, H, cfg["channel"]["name"], "Rest well.", oc["start"] + 1.5,
                                   timing["duration"] - 1.0))
    _validate(shots, timing["duration"])
    return shots, overlays


def _validate(shots, total):
    shots.sort(key=lambda s: s["start"])
    for a, b in zip(shots, shots[1:]):
        if abs(a["end"] - b["start"]) > 0.05:
            raise ValueError(f"gap/overlap in edit at {a['end']:.2f}")
    if abs(shots[-1]["end"] - total) > 0.05:
        raise ValueError("edit does not cover the full duration")


def render_episode(timing, script, media, audio, out, cfg):
    v = cfg["video"]
    shots, overlays = build_episode(timing, script, media, cfg)
    print(f"  {len(shots)} shots, {sum(s['kind'] == 'clip' for s in shots)} clips, {len(overlays)} cards")
    engine.render(shots, overlays, audio, out, v["width"], v["height"], v["fps"], timing["duration"],
                  crf=v["crf"], preset=v["preset"], fade_out=4.0)
    return out
