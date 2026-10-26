"""Writing with Claude Code in headless mode (`claude -p`), using your Claude plan.

outline -> chapters -> cold open -> science/TTS review pass -> Shorts scripts
"""
import json
import re
import subprocess
import time

from .common import ROOT, LANG_NAMES, extract_json

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
    return re.sub(r"\n{3,}", "\n\n", text).strip()


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
             MINUTES=minutes, CHAPTERS=n_chapters),
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

    outline["topic"] = topic
    return outline


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
    text = "\n\n".join(c["text"] for c in script["chapters"])
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
