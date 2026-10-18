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
        fixes = extract_json(ask_claude(fill("review.md", CHANNEL=ch["name"], SCRIPT=full)))
        n = apply_fixes(sections, fixes)
        outline["review"] = {"suggested": len(fixes) if isinstance(fixes, list) else 0, "applied": n,
                             "fixes": fixes if isinstance(fixes, list) else []}
        print(f"    applied {n} fixes")
    except Exception as exc:
        print(f"    review skipped: {exc}")
    outline["cold_open"] = sections["cold_open"]
    for i, c in enumerate(chapters, 1):
        c["text"] = sections[f"chapter_{i}"]

    outline["topic"] = topic
    return outline


def write_shorts(script, cfg, count=2):
    ch = cfg["channel"]
    text = "\n\n".join(c["text"] for c in script["chapters"])
    try:
        shorts = ask_json(
            fill("shorts.md", CHANNEL=ch["name"], LANGUAGE=LANG_NAMES[ch["language"]],
                 TITLE=script["title"], SCRIPT=text[:60000], COUNT=count),
            lambda d: isinstance(d, list) and d and all(s.get("narration") for s in d))
    except Exception as exc:
        print(f"  shorts skipped: {exc}")
        return []
    for s in shorts:
        s["narration"] = clean(s["narration"])
    return shorts[:count]
