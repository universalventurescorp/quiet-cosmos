"""Movie mode, part 2: the shot list (pipeline/shotlist.py) placed on the narration and turned into the edit.

    slots(plan, timing, cues)        every shot gets its exact start/end, anchored to the sentence it belongs to
    fetch_media(slots, ...)          real footage (Pixabay) and continent maps, cut to the exact slot length
    build(slots, media, ai, ...)     engine shots + overlays: hard-ish cuts every ~5 s, fallbacks for anything missing

Episode layout stays the channel's: cold open (fast cuts) · opening title · chapters with chapter cards · end card.
"""
from . import cards, engine
from .render import ai_labels
from .scenes import find_anchor, word_times

MIN_SHOT = 2.2          # shorter slots are merged into the previous shot


def _spans(timing):
    spans = {}
    if timing.get("cold_open"):
        spans["cold_open"] = (0.0, timing["title_card"]["start"])
    for i, ch in enumerate(timing["chapters"], 1):
        start = ch["start"] if i > 1 else timing["chapters"][0]["start"] + 0.2
        spans[f"chapter_{i}"] = (start, ch["end"])
    return spans


def slots(plan, timing, cues):
    """-> list of {sid, sec, type, start, end, shot}: contiguous inside each section, in narration order."""
    words = word_times(cues)
    spans = _spans(timing)
    out = []
    for sec in plan["sections"]:
        if sec["id"] not in spans or not sec["shots"]:
            continue
        t0, t1 = spans[sec["id"]]
        items, after = [], t0
        for k, s in enumerate(sec["shots"]):
            at = find_anchor(words, s.get("anchor", ""), t0, t1, after)
            if at is not None:
                after = at
            items.append({"sid": f"{sec['id']}_{k:03d}", "sec": sec["id"], "type": s["type"], "shot": s, "at": at})
        # the first shot starts with the section; unknown anchors share the gap of their group
        items[0]["at"] = t0
        groups, cur = [], [items[0]]
        for it in items[1:]:
            if it["at"] is None or it["at"] <= cur[0]["at"] + 0.05:
                cur.append(it)
            else:
                groups.append(cur)
                cur = [it]
        groups.append(cur)
        for g, grp in enumerate(groups):
            a = grp[0]["at"]
            b = groups[g + 1][0]["at"] if g + 1 < len(groups) else t1
            total = sum(it["shot"]["seconds"] for it in grp) or 1
            t = a
            for it in grp:
                d = (b - a) * it["shot"]["seconds"] / total
                it["start"], it["end"] = t, t + d
                t += d
        # merge slivers into the previous shot
        kept = []
        for it in items:
            if kept and it["end"] - it["start"] < MIN_SHOT:
                kept[-1]["end"] = it["end"]
                continue
            kept.append(it)
        if len(kept) > 1 and kept[0]["end"] - kept[0]["start"] < MIN_SHOT:
            kept[1]["start"] = kept[0]["start"]
            kept.pop(0)
        for it in kept:
            it.pop("at", None)
            it["start"], it["end"] = round(it["start"], 3), round(it["end"], 3)
        out += kept
    return out


def fetch_media(slot_list, out, used, cfg):
    """Real footage and maps cut to each slot's exact length. -> {sid: {"path", "duration"}}"""
    v = cfg["video"]
    lang = cfg["channel"].get("language", "es")
    media = {}
    pad = engine.XFADE + 0.3
    real = [s for s in slot_list if s["type"] == "real"]
    if real:
        from . import pixabay
        if not pixabay.configured():
            print("   PIXABAY_API_KEY missing: real shots will be filled with stills")
        else:
            for s in real:
                need = s["end"] - s["start"] + pad
                clips = pixabay.fetch_clips([s["shot"]["query"]], 1, out / "real", used, seconds=need,
                                            W=v["width"], H=v["height"], fps=v["fps"], shots_per_clip=1, per_query=1)
                if clips:
                    media[s["sid"]] = clips[0]
            print(f"   real footage: {sum(1 for s in real if s['sid'] in media)}/{len(real)} shots")
    maps_ = [s for s in slot_list if s["type"] == "map"]
    if maps_:
        from .maps import render_map_clip
        (out / "maps").mkdir(parents=True, exist_ok=True)
        for s in maps_:
            need = s["end"] - s["start"] + pad
            path = out / "maps" / f"{s['sid']}.mp4"
            d = render_map_clip(s["shot"]["age_myr"], s["shot"].get("label", ""), path, seconds=need,
                                W=v["width"], H=v["height"], fps=v["fps"], lang=lang)
            if d:
                media[s["sid"]] = {"path": str(path), "duration": d, "source": "map"}
        print(f"   maps: {sum(1 for s in maps_ if s['sid'] in media)}/{len(maps_)} shots")
    return media


def _ai_still(item, n):
    shot = {"kind": "still", "path": item["path"], "move": n, "ai": True}
    if item.get("depth"):
        shot["depth"] = item["depth"]
    return shot


def build(slot_list, media, ai_files, timing, script, cfg, W=None, H=None):
    """Engine shots + overlays for the whole episode."""
    v = cfg["video"]
    W, H = W or v["width"], H or v["height"]
    images, clips, depth = ai_files.get("images", {}), ai_files.get("clips", {}), ai_files.get("depth", {})
    pool = [{"path": p, "depth": depth.get(k)} for k, p in sorted(images.items())]
    shots, overlays, n = [], [], 0

    def fallback(k):
        if pool:
            return _ai_still(pool[k % len(pool)], k)
        if media:
            m = list(media.values())[k % len(media)]
            return {"kind": "clip", "path": m["path"]}
        return {"kind": "stars", "seed": k + 3}

    for s in slot_list:
        sh, ai_id, d = s["shot"], s["shot"].get("ai_id"), s["end"] - s["start"]
        item = {"path": images[ai_id], "depth": depth.get(ai_id)} if ai_id in images else None
        if s["type"] in ("real", "map") and s["sid"] in media:
            shots.append({"kind": "clip", "path": media[s["sid"]]["path"], "start": s["start"], "end": s["end"],
                          "source": s["type"]})
        elif s["type"] == "animal" and ai_id in clips:
            c = clips[ai_id]
            usable = c["duration"] - engine.XFADE - 0.1
            if usable >= d or not item:
                shots.append({"kind": "clip", "path": c["path"], "ai": True, "start": s["start"], "end": s["end"]})
            else:                                        # the clip is shorter than its slot: finish on its own still
                cut = s["start"] + usable
                shots.append({"kind": "clip", "path": c["path"], "ai": True, "start": s["start"], "end": cut})
                shots.append({**_ai_still(item, n), "start": cut, "end": s["end"]})
        elif item:
            shots.append({**_ai_still(item, n), "start": s["start"], "end": s["end"]})
        else:
            shots.append({**fallback(n), "start": s["start"], "end": s["end"]})
        n += 1

    # opening title, chapter cards, end card (same look as the rest of the network)
    tc = timing["title_card"]
    tc_start = tc["start"] if timing.get("cold_open") else 0.0
    tc_end = timing["chapters"][0]["start"] + 0.2
    backdrop = pool[0]["path"] if pool else None
    shots.append({"kind": "stars", "seed": 3, "backdrop": backdrop, "start": tc_start, "end": tc_end})
    overlays.append(cards.opening_title(W, H, cfg["channel"]["name"], script["title"], tc["start"] + 0.6,
                                        tc["end"] - 0.2))
    for i, mark in enumerate(timing["chapters"], 1):
        overlays.append(cards.chapter_card(W, H, i, mark["title"], mark["start"] + 0.4, mark["start"] + 6.5))
    oc = timing["outro"]
    last_end = max((x["end"] for x in shots), default=0.0)
    shots.append({"kind": "stars", "seed": 9, "backdrop": backdrop, "start": last_end, "end": timing["duration"],
                  "speed": 0.6})
    overlays.append(cards.end_card(W, H, cfg["channel"]["name"], cfg["channel"].get("end_line", "Hasta pronto."),
                                   oc["start"] + 1.5, timing["duration"] - 1.0))
    shots.sort(key=lambda x: x["start"])
    _close_gaps(shots, timing["duration"])
    if cfg.get("ai", {}).get("label_on_screen", True):
        overlays += ai_labels(shots, W, H, cfg["channel"]["language"])
    return shots, overlays


def _close_gaps(shots, total):
    """The engine wants contiguous shots: stretch each shot to the next one's start (gaps are tiny rounding
    leftovers, or the cold-open/title seam)."""
    for a, b in zip(shots, shots[1:]):
        a["end"] = b["start"]
    if shots:
        shots[0]["start"] = 0.0
        shots[-1]["end"] = total


def summary(slot_list, media, ai_files):
    """What actually made it on screen, per type (diagnostics)."""
    out = {}
    clips = ai_files.get("clips", {})
    for s in slot_list:
        t = s["type"]
        r = out.setdefault(t, {"planned": 0, "on_screen": 0, "seconds": 0.0})
        r["planned"] += 1
        ok = (s["sid"] in media) if t in ("real", "map") else (
            s["shot"].get("ai_id") in clips if t == "animal" else s["shot"].get("ai_id") in ai_files.get("images", {}))
        if ok:
            r["on_screen"] += 1
            r["seconds"] = round(r["seconds"] + s["end"] - s["start"], 1)
    return out
