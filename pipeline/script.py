"""Writing with Claude Code in headless mode (`claude -p`), using your Claude plan.

outline -> chapters -> cold open -> science/TTS review pass -> Shorts scripts
"""
import json
import re
import subprocess
import time

from .common import DATA, ROOT, LANG_NAMES, extract_json, read_json

PROMPTS = ROOT / "prompts"
INSTRUCTION = ("Follow the instructions in the input exactly. Reply with only the requested output, "
               "without any preamble or commentary.")


MODEL = "sonnet"            # set from config.yaml (claude.model) by write_script
AMBIENCES = ("deep_space", "wind", "storm", "sea", "ice", "sun", "lava", "none")   # pipeline/sfx.py beds
LIMIT_WORDS = ("hit your weekly limit", "hit your usage limit", "usage limit reached", "limit · resets")


def ask_claude(prompt, timeout=1500, retries=3):
    last = ""
    for attempt in range(retries):
        try:
            r = subprocess.run(["claude", "-p", "--model", MODEL, INSTRUCTION], input=prompt,
                               capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            last = (r.stderr or r.stdout)[-1500:]
            if any(w in last.lower() for w in LIMIT_WORDS):   # retrying will not help
                raise RuntimeError(f"Claude plan usage limit reached, no episode today: {last.strip()}")
        except subprocess.TimeoutExpired:
            last = "timeout"
        time.sleep(45 * (attempt + 1))
    raise RuntimeError(f"claude -p failed: {last}")


def ask_json(prompt, check, tries=3):
    for _ in range(tries):
        try:
            data = extract_json(ask_claude(prompt))
            if check(data):
                return data
        except (ValueError, json.JSONDecodeError):
            pass
    raise RuntimeError("Claude did not return valid JSON")


def fill(name, **values):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"<<{key}>>", str(value))
    return text


def clean(text, chapter_title=""):
    text = re.sub(r"```.*?\n|```", "", text)
    title = chapter_title.strip().lower().rstrip(".:")
    kept = []
    for line in text.splitlines():
        s = line.strip()
        bare = s.strip("*_# ").rstrip(".:").lower()
        if s.startswith(("#", "---")):
            continue                                   # markdown headings / rules
        if re.match(r"^(chapter|cap[ií]tulo)\s+\w+\s*[:.\-]", bare) or re.match(r"^(chapter|cap[ií]tulo)\s+\w+$", bare):
            continue                                   # "Chapter 5: ..." would be read aloud
        if title and bare == title:
            continue                                   # chapter title repeated as a line
        kept.append(line)
    text = "\n".join(kept).replace("*", "").replace("_", " ")
    text = text.replace("!", ".")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # a "moment of silence" written as a word would be read aloud ("Silencio." in the 28-oct cold open)
    paras = [p for p in text.split("\n\n") if not STAGE_WORD.match(p.strip())]
    return "\n\n".join(paras).strip()


STAGE_WORD = re.compile(r"^[\(\[]?\s*(silencio|silence|pausa|pause|\.{3}|…)\s*[\.\)\]]*\s*$", re.I)


def _first_words(text, n=8):
    return " ".join(text.split()[:n])


def apply_fixes(sections, fixes):
    """sections: dict id -> text. Applies exact find/replace fixes; returns count applied."""
    applied = 0
    for fx in fixes if isinstance(fixes, list) else []:
        sid, find, rep = fx.get("section"), fx.get("find", ""), fx.get("replace", "")
        if sid in sections and find and len(find) >= 12 and find in sections[sid] and "\n" not in rep:
            sections[sid] = sections[sid].replace(find, rep, 1)
            applied += 1
    return applied


def clean_sources(items, limit=8):
    """Agency / mission names from the science review: plain short names only (no links, no invented detail)."""
    out = []
    for s in items if isinstance(items, list) else []:
        s = " ".join(str(s).split()).strip(" .;,-")
        low = s.lower()
        if not s or len(s) > 50 or "http" in low or "www." in low:
            continue
        if low not in (o.lower() for o in out):
            out.append(s)
    return out[:limit]


def short_source(short, sources):
    """On-screen proof line for a Short: its own source if plausible, else the episode's main agency."""
    s = " ".join(str(short.get("source") or "").split()).strip(" .;,")
    if s and len(s) <= 40 and "http" not in s.lower():
        return s
    return sources[0] if sources else "NASA"


def with_subscribe_line(cold_open, line):
    """Fixed, calm subscribe request placed just before the cold open's last line (the lead-in to the
    title card): asked while the listener is still awake, never at the end when they are asleep."""
    if not line:
        return cold_open
    paras = [p for p in cold_open.split("\n\n") if p.strip()]
    return "\n\n".join(paras[:-1] + [line.strip()] + paras[-1:]) if paras else line.strip()


def told_before(limit=60):
    """30-oct-2026: what this channel already told (topics + chapter titles), so a new journey does not
    repeat it. Long journeys cover a lot of ground and the channel has already toured every planet."""
    done = read_json(DATA / "done.json", [])[-limit:]
    if not done:
        return ""
    lines = []
    for d in done:
        ch = "; ".join(d.get("chapters", []))
        lines.append(f"- {d.get('title') or d['topic']}" + (f" (chapters: {ch})" if ch else ""))
    return ("\n\nAlready told on this channel (the audience comes back every night). Do NOT repeat these "
            "episodes: choose other angles, other discoveries, other stories and other numbers. If a subject must "
            "come back, give it a NEW angle and only a brief callback, never the same explanation again:\n"
            + "\n".join(lines))


def write_script(topic, cfg):
    global MODEL
    MODEL = (cfg.get("claude") or {}).get("model", MODEL)
    ch, minutes = cfg["channel"], cfg["video"]["target_minutes"]
    n_chapters = cfg["video"].get("chapters") or max(5, round(minutes / 6.5))
    lang = LANG_NAMES[ch["language"]]
    style = ch.get("narrator_style", "").strip()
    style = f"\nNarrator persona for this channel (it overrides the generic style above where they differ):\n{style}" if style else ""

    print("  outline")
    outline = ask_json(
        fill("outline.md", CHANNEL=ch["name"], LANGUAGE=lang, TOPIC=topic,
             MINUTES=minutes, CHAPTERS=n_chapters) + told_before(),
        lambda d: isinstance(d, dict) and d.get("title") and len(d.get("chapters", [])) >= min(3, n_chapters))
    chapters = outline["chapters"]
    for c in chapters:
        c.setdefault("video_queries", [])
        c.setdefault("image_queries", [])
        if c.get("ambience") not in AMBIENCES:
            c["ambience"] = "deep_space"
    words = int(minutes * cfg["voice"]["wpm"] / len(chapters))
    plan = json.dumps({"title": outline["title"],
                       "chapters": [{"title": c["title"], "beats": c["beats"]} for c in chapters]},
                      ensure_ascii=False)

    previous, openings = "(this is the first chapter, right after the opening title)", []
    for i, c in enumerate(chapters, 1):
        last = i == len(chapters)
        ending = ("This is the final chapter: close the journey with a slow, peaceful reflection "
                  "and a soft goodnight. Do not ask for likes or subscriptions." if last else
                  "Do not wrap up or summarize the episode; flow naturally toward the next chapter.")
        from .longform import chapter_rule
        extra = chapter_rule(i, len(chapters), cfg)
        ending = extra.strip() if last and extra else ending + extra   # 8 h: the last chapter is the dawn
        text = clean(ask_claude(fill(
            "chapter.md", CHANNEL=ch["name"], LANGUAGE=lang, OUTLINE=plan, N=i,
            TOTAL=len(chapters), CHAPTER_TITLE=c["title"], BEATS="; ".join(c["beats"]),
            QUESTION=c.get("question") or "(choose one from the beats)",
            REVEAL=c.get("reveal") or "(the most surprising true point among the beats)",
            WORDS=words, PREVIOUS=previous, ENDING_RULE=ending,
            OPENINGS="; ".join(openings) or "(none yet)", STYLE=style)), c["title"])
        c["text"] = text
        previous = text.split("\n\n")[-1][-500:]
        openings.append(f'"{_first_words(text)}..."')
        print(f"  chapter {i}/{len(chapters)}: {len(text.split())} words")

    print("  cold open")
    outline["cold_open"] = clean(ask_claude(fill(
        "cold_open.md", CHANNEL=ch["name"], LANGUAGE=lang, TITLE=outline["title"],
        PROMISE=outline.get("hook_promise", ""), CHAPTERS="; ".join(c["title"] for c in chapters),
        FIRST=_first_words(chapters[0]["text"], 30), STYLE=style)))

    print("  science & TTS review")
    sections = {"cold_open": outline["cold_open"]}
    sections.update({f"chapter_{i}": c["text"] for i, c in enumerate(chapters, 1)})
    full = "\n\n".join(f"[{k}]\n{v}" for k, v in sections.items())
    try:
        reviewed = extract_json(ask_claude(fill("review.md", CHANNEL=ch["name"], SCRIPT=full)))
        fixes = reviewed.get("fixes", []) if isinstance(reviewed, dict) else reviewed
        outline["sources"] = clean_sources(reviewed.get("sources") if isinstance(reviewed, dict) else None)
        print(f"    sources: {', '.join(outline['sources']) or '(none)'}")
        n = apply_fixes(sections, fixes)
        outline["review"] = {"suggested": len(fixes) if isinstance(fixes, list) else 0, "applied": n,
                             "fixes": fixes if isinstance(fixes, list) else []}
        print(f"    applied {n} fixes")
    except Exception as exc:
        print(f"    review skipped: {exc}")
    outline["cold_open"] = with_subscribe_line(sections["cold_open"], ch.get("subscribe_line"))
    for i, c in enumerate(chapters, 1):
        c["text"] = sections[f"chapter_{i}"]
    if cfg.get("companion", {}).get("enabled"):
        add_companion(outline, cfg)

    outline["topic"] = topic
    return outline


def _paras(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def _norm(p):
    return " ".join(p.split())


def _single(p):
    return len([s for s in re.split(r"(?<=[.?…])\s+", p.strip()) if s]) == 1


def companion_slots(chapters, every_min, wpm, first_min=None):
    """Where the narrator steps out of the story to speak to the listener: about every `every_min` minutes of
    narration, always at a paragraph break inside a chapter (never right after the chapter card, never at its
    very end, never next to a one-line reveal). Returns [(chapter_index, paragraph_index_to_insert_before)]."""
    first_min = every_min if first_min is None else first_min
    marks, words = [], 0
    for ci, c in enumerate(chapters):
        ps = _paras(c["text"])
        for pi, p in enumerate(ps):
            if 2 <= pi <= len(ps) - 2 and not (_single(ps[pi - 1]) or _single(p)):
                marks.append((words / wpm, ci, pi))
            words += len(p.split())
    slots, target, total = [], first_min, words / wpm
    while target < total - 1.5:
        cands = [m for m in marks if abs(m[0] - target) <= every_min * 0.5 and (m[1], m[2]) not in slots]
        if cands:
            best = min(cands, key=lambda m: abs(m[0] - target))
            slots.append((best[1], best[2]))
        target += every_min
    return slots


def add_companion(outline, cfg):
    """Nocturno, 29-oct-2026 (Luis: "que me sienta acompañado"): short moments where the narrator speaks
    directly to the one listener awake at night, about every companion.every_minutes, plus the fixed "gift"
    line once (QR to share the channel by WhatsApp). The inserted paragraphs are listed in
    chapter["companion"] so the voice can say them softer and the video can time the QR on the gift line."""
    comp, ch = cfg["companion"], cfg["channel"]
    chapters, wpm = outline["chapters"], cfg["voice"]["wpm"]
    starts, words = {}, 0
    for ci, c in enumerate(chapters):
        for pi, p in enumerate(_paras(c["text"])):
            starts[(ci, pi)] = words / wpm
            words += len(p.split())
    total = words / wpm
    slots = companion_slots(chapters, comp.get("every_minutes", 12), wpm, comp.get("first_minute"))
    if not slots:
        return
    blocks = []
    for k, (ci, pi) in enumerate(slots, 1):
        ps = _paras(chapters[ci]["text"])
        blocks.append(f"Place {k}:\nBEFORE: {ps[pi - 1]}\nAFTER: {ps[pi]}")
    try:
        lines = ask_json(fill("companion.md", CHANNEL=ch["name"], LANGUAGE=LANG_NAMES[ch["language"]],
                              TITLE=outline["title"], COUNT=len(slots), SLOTS="\n\n".join(blocks)),
                         lambda d: isinstance(d, list) and len(d) == len(slots) and all(isinstance(x, str) for x in d))
    except Exception as exc:
        print(f"  companion skipped: {exc}")
        return
    gift = (comp.get("gift_line") or "").strip()
    gift_slot = None
    if gift:   # the gift line rides on the companion moment nearest to gift_minute (asked once, still awake)
        gift_at = min(comp.get("gift_minute", 30), total * 0.55)
        gift_slot = min(range(len(slots)), key=lambda k: abs(starts[slots[k]] - gift_at))
    for k in sorted(range(len(slots)), key=lambda k: slots[k], reverse=True):   # insert back to front
        ci, pi = slots[k]
        ps = _paras(chapters[ci]["text"])
        new = [x for x in [clean(lines[k]).replace("\n", " ").strip(), gift if k == gift_slot else ""] if x]
        chapters[ci]["text"] = "\n\n".join(ps[:pi] + new + ps[pi:])
        chapters[ci].setdefault("companion", []).extend(new)
        if k == gift_slot:
            chapters[ci]["gift"] = gift
    times = sorted(round(starts[s], 1) for s in slots)
    outline["companion"] = {"count": len(slots), "minutes": times,
                            "gift_minute": round(starts[slots[gift_slot]], 1) if gift else None}
    print(f"  companion: {len(slots)} moments at ~{times} min" + (" + gift line" if gift else ""))


def story_text(chapter):
    """A chapter's narration without the companion moments (for Shorts and anything that is not the episode)."""
    soft = {_norm(p) for p in chapter.get("companion", [])}
    return "\n\n".join(p for p in _paras(chapter["text"]) if _norm(p) not in soft)


DEFAULT_SHORT_ENDING = ('End with a short line inviting them to the full journey on the channel, phrased naturally '
                        '(for example: "The full journey to the edge of the universe is waiting on the channel.").')


def with_closing(narration, closing):
    """Fixed follow call at the very end of a Short (Nocturno, 26-oct-2026: Shorts must win subscribers)."""
    if not closing:
        return narration
    return narration.rstrip() + " " + closing.strip()


def write_shorts(script, cfg, count=2):
    ch = cfg["channel"]
    closing = (cfg.get("shorts") or {}).get("closing_line", "")
    ending = ("End on the payoff itself, with no invitation, no call to action and no mention of the channel: "
              "a fixed closing line is added after your text automatically." if closing else DEFAULT_SHORT_ENDING)
    text = "\n\n".join(story_text(c) for c in script["chapters"])
    try:
        shorts = ask_json(
            fill("shorts.md", CHANNEL=ch["name"], LANGUAGE=LANG_NAMES[ch["language"]],
                 TITLE=script["title"], SCRIPT=text[:60000], COUNT=count, ENDING=ending,
                 SOURCES=", ".join(script.get("sources") or []) or "NASA"),
            lambda d: isinstance(d, list) and d and all(s.get("narration") for s in d))
    except Exception as exc:
        print(f"  shorts skipped: {exc}")
        return []
    for s in shorts:
        s["narration"] = with_closing(clean(s["narration"]), closing)
        s["source"] = short_source(s, script.get("sources") or [])
    return shorts[:count]
