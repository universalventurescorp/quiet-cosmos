"""Episode edit: turns timing + media into a shot list and overlays, then renders with the engine.

Structure of every episode:
  cold open      the AI hero clip (or the best real footage) under the hook narration, quick cuts
  opening title  flight through stars over a dimmed nebula, channel name + episode title
  chapters       real NASA stills/clips, with AI scenes landing on the exact sentence they illustrate
                 (2.5D depth parallax on stills, image-to-video clips at key moments), chapter card
  end card       stars, channel name
"""
import itertools

from . import cards, engine

MIN_SHOT = 3.0


class Filler:
    """Stateful NASA filler: keeps cycling stills and spacing real clips across many short gaps."""

    def __init__(self, stills, clips, spi, clip_every, move_offset=0, parallax_nasa=False):
        self.stills, self.clips = list(stills), list(clips)
        self.cyc = itertools.cycle(self.stills) if self.stills else None
        self.spi, self.clip_every = spi, clip_every
        self.k, self.move_offset, self.last = 0, move_offset, None
        self.parallax_nasa = parallax_nasa

    def _still(self):
        if not self.cyc:
            return {"kind": "stars", "seed": self.k + 7}
        img = next(self.cyc)
        if img["path"] == self.last and len(self.stills) > 1:
            img = next(self.cyc)
        shot = {"kind": "still", "path": img["path"], "move": self.k + self.move_offset}
        if self.parallax_nasa and img.get("depth"):
            shot.update(depth=img["depth"], parallax=0.6)
        return shot

    def fill(self, start, end, spi=None):
        spi = spi or self.spi
        shots, t = [], start
        while end - t > 0.01:
            remaining = end - t
            if self.clips and self.k % self.clip_every == self.clip_every - 1:
                c = self.clips.pop(0)
                shot = {"kind": "clip", "path": c["path"]}
                d = min(c["duration"] - engine.XFADE - 0.2, spi * 1.15)
            else:
                shot, d = self._still(), spi
            if remaining - d < MIN_SHOT:          # absorb a tiny remainder into this shot
                d = remaining
                if shot["kind"] == "clip":        # clips cannot stretch: finish on a still instead
                    self.clips.insert(0, c)
                    shot = self._still()
            shot.update(start=t, end=t + d)
            shots.append(shot)
            self.last = shot.get("path")
            t += d
            self.k += 1
        return shots


def _fill(start, end, stills, clips, spi, clip_every, move_offset=0):
    """Contiguous shots covering [start, end) (used by Shorts)."""
    return Filler(stills, clips, spi, clip_every, move_offset).fill(start, end)


def ai_shot(item, n, max_len, spi):
    """One AI scene: an image-to-video clip if there is one, else the still with depth parallax."""
    clip = item.get("clip")
    if clip and clip.get("duration", 0) > MIN_SHOT + engine.XFADE:
        return {"kind": "clip", "path": clip["path"], "ai": True}, min(clip["duration"] - engine.XFADE - 0.2, max_len)
    shot = {"kind": "still", "path": item["path"], "move": n, "ai": True}
    if item.get("depth"):
        shot["depth"] = item["depth"]
    return shot, min(spi * 1.1, max_len)


def section_shots(start, end, filler, ai_items, spi, counter, fill_spi=None):
    """NASA footage from `filler`, with each AI scene starting at its anchor time."""
    marks, last = [], None
    for it in sorted(ai_items, key=lambda x: x["at"]):
        if start <= it["at"] < end - MIN_SHOT and (last is None or it["at"] - last >= MIN_SHOT + 0.5):
            marks.append(it)
            last = it["at"]
    shots, t = [], start
    for j, it in enumerate(marks):
        at = it["at"] if it["at"] - t >= MIN_SHOT else t   # a gap too short for NASA: AI starts earlier
        if at > t:
            shots += filler.fill(t, at, fill_spi)
        nxt = marks[j + 1]["at"] if j + 1 < len(marks) else end
        shot, d = ai_shot(it, counter[0], nxt - at, spi)
        counter[0] += 1
        if (nxt - at) - d < MIN_SHOT:
            if shot["kind"] == "clip" and (nxt - at) - d >= 0.5:   # clip can't stretch: add its still
                still = {"kind": "still", "path": it["path"], "move": counter[0], "ai": True,
                         **({"depth": it["depth"]} if it.get("depth") else {})}
                shots.append({**shot, "start": at, "end": at + d})
                shots.append({**still, "start": at + d, "end": nxt})
                t = nxt
                continue
            d = nxt - at
        shots.append({**shot, "start": at, "end": at + d})
        t = at + d
    if end - t > 0.01:
        shots += filler.fill(t, end, fill_spi)
    return shots


def best_images(images, n):
    return sorted(images, key=lambda i: -i.get("score", 0))[:n]


def ai_labels(shots, W, H, lang):
    text = {"en": "AI artist's impression", "es": "Recreación artística con IA"}.get(lang, "AI artist's impression")
    out = []
    for s in shots:
        if s.get("ai") and s["end"] - s["start"] > 4:
            out.append(cards.ai_label(W, H, text, s["start"] + 0.9, s["end"] - 0.5))
    return out


def build_episode(timing, script, media, cfg, W=None, H=None, ai=None):
    v = cfg["video"]
    W, H = W or v["width"], H or v["height"]
    spi = v["seconds_per_image"]
    ai = ai or {}
    aic = cfg.get("ai", {})
    shots, overlays = [], []
    all_images = [img for m in media for img in m["images"]]
    all_clips = [c for m in media for c in m["clips"]]
    counter = [0]

    # 1) cold open: AI hero clip first when there is one, else motion from real footage
    co = timing.get("cold_open")
    t0 = 0.0
    if co:
        hero = [best_images(m["images"], 1)[0] for m in media if m["images"]]
        end = co["end"] + 0.6
        co_ai = sorted(ai.get("cold_open", []), key=lambda x: (not x.get("clip"), x["at"]))
        if co_ai:
            co_ai[0] = {**co_ai[0], "at": 0.0}
            co_ai = sorted(co_ai, key=lambda x: x["at"])
        nasa = [] if co_ai and co_ai[0].get("clip") else all_clips[:1]
        filler = Filler(hero, nasa, spi * 0.6, 1 if nasa else 99)
        shots += section_shots(0.0, end, filler, co_ai, spi * 0.7, counter, fill_spi=spi * 0.6)
        t0 = end

    # 2) opening title
    tc = timing["title_card"]
    tc_end = timing["chapters"][0]["start"] + 0.2
    backdrop = best_images(all_images, 2)[-1]["path"] if all_images else None
    shots.append({"kind": "stars", "seed": 3, "backdrop": backdrop, "start": t0, "end": tc_end})
    overlays.append(cards.opening_title(W, H, cfg["channel"]["name"], script["title"],
                                        tc["start"] + 0.6, tc["end"] - 0.2))

    # 3) chapters
    used_clips = {s["path"] for s in shots if s["kind"] == "clip"}
    for i, (mark, m) in enumerate(zip(timing["chapters"], media)):
        start = tc_end if i == 0 else mark["start"]
        end = mark["end"]
        clips = [c for c in m["clips"] if c["path"] not in used_clips]
        filler = Filler(m["images"] or all_images, clips, spi, v.get("clip_every", 3), move_offset=i * 2,
                        parallax_nasa=aic.get("parallax_nasa", False))
        shots += section_shots(start, end, filler, ai.get(f"chapter_{i + 1}", []), spi, counter)
        overlays.append(cards.chapter_card(W, H, i + 1, mark["title"], mark["start"] + 0.4, mark["start"] + 7.5))

    # 4) end card
    oc = timing["outro"]
    shots.append({"kind": "stars", "seed": 9, "backdrop": backdrop, "start": oc["start"], "end": timing["duration"],
                  "speed": 0.6})
    rest = {"es": "Que descanses.", "en": "Rest well."}.get(cfg["channel"]["language"], "Rest well.")
    overlays.append(cards.end_card(W, H, cfg["channel"]["name"], rest, oc["start"] + 1.5,
                                   timing["duration"] - 1.0))
    overlays += qr_overlays(timing, cfg, W, H, script.get("share_code"))
    if aic.get("label_on_screen", True):
        overlays += ai_labels(shots, W, H, cfg["channel"]["language"])
    _validate(shots, timing["duration"])
    return shots, overlays


def qr_overlays(timing, cfg, W, H, share_code=None):
    """Nocturno, 29-oct-2026: QR 1 ("llévanos en tu celular", opens the channel with the subscribe prompt) while the
    narrator asks to subscribe; QR 2 (a crescent moon: opens WhatsApp with a ready message to gift the channel)
    on the gift line. Each one once, small and dim, lower-left."""
    qr = (cfg.get("companion") or {}).get("qr") or {}
    if not qr:
        return []
    from urllib.parse import quote
    out = []
    for e in timing.get("events", []):
        if e["kind"] == "subscribe" and qr.get("subscribe_url"):
            out.append(cards.qr_panel(W, H, qr["subscribe_url"], "subscribe", e["start"] - 0.5,
                                      e["start"] + qr.get("seconds", 22)))
        elif e["kind"] == "gift" and (qr.get("gift_page") or qr.get("gift_text")):
            # own page (Cloudflare Pages, web/r.html): opens WhatsApp with THIS video's link, in the phone's
            # language; without it, a plain WhatsApp message with the channel link
            url = (f"{qr['gift_page'].rstrip('/')}/r/{share_code}" if qr.get("gift_page") and share_code
                   else "https://wa.me/?text=" + quote(qr["gift_text"], safe=":/@,"))
            out.append(cards.qr_panel(W, H, url, "gift", e["start"] - 0.5,
                                      e["start"] + qr.get("seconds", 22) + 4))
    return out


def _validate(shots, total):
    shots.sort(key=lambda s: s["start"])
    for a, b in zip(shots, shots[1:]):
        if abs(a["end"] - b["start"]) > 0.05:
            raise ValueError(f"gap/overlap in edit at {a['end']:.2f}")
        if b["end"] - b["start"] < 0.3:
            raise ValueError(f"degenerate shot at {b['start']:.2f}")
    if abs(shots[-1]["end"] - total) > 0.05:
        raise ValueError("edit does not cover the full duration")


def render_episode(timing, script, media, audio, out, cfg, ai=None):
    v = cfg["video"]
    shots, overlays = build_episode(timing, script, media, cfg, ai=ai)
    print(f"  {len(shots)} shots, {sum(s['kind'] == 'clip' for s in shots)} clips, "
          f"{sum(bool(s.get('ai')) for s in shots)} AI scenes, {len(overlays)} overlays")
    engine.render(shots, overlays, audio, out, v["width"], v["height"], v["fps"], timing["duration"],
                  crf=v["crf"], preset=v["preset"], fade_out=4.0)
    return out
