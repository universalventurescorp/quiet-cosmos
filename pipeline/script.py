"""Script writing with Claude Code in headless mode (`claude -p`), using your Claude Pro plan."""
import json
import re
import subprocess
import time

from .common import ROOT, LANG_NAMES, extract_json

PROMPTS = ROOT / "prompts"


def ask_claude(prompt, timeout=1200, retries=3):
    last = ""
    for attempt in range(retries):
        try:
            r = subprocess.run(["claude", "-p", prompt], capture_output=True,
                               text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.strip()
            last = (r.stderr or r.stdout)[-1500:]
        except subprocess.TimeoutExpired:
            last = "timeout"
        time.sleep(30 * (attempt + 1))
    raise RuntimeError(f"claude -p failed: {last}")


def fill(name, **values):
    text = (PROMPTS / name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"<<{key}>>", str(value))
    return text


def clean(text):
    text = re.sub(r"```.*?\n|```", "", text)
    lines = [l for l in text.splitlines() if not l.lstrip().startswith(("#", "---"))]
    text = "\n".join(lines).replace("*", "").replace("_", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write_script(topic, cfg):
    ch, minutes = cfg["channel"], cfg["video"]["target_minutes"]
    n_chapters = max(5, round(minutes / 6))
    lang = LANG_NAMES[ch["language"]]

    outline = None
    for _ in range(3):
        try:
            outline = extract_json(ask_claude(fill(
                "outline.md", CHANNEL=ch["name"], LANGUAGE=lang, TOPIC=topic,
                MINUTES=minutes, CHAPTERS=n_chapters)))
            if outline.get("chapters") and outline.get("title"):
                break
        except (ValueError, json.JSONDecodeError):
            outline = None
    if not outline:
        raise RuntimeError("Could not get a valid outline from Claude")

    chapters = outline["chapters"]
    words = int(minutes * cfg["voice"]["wpm"] / len(chapters))
    plan = json.dumps({"title": outline["title"],
                       "chapters": [{"title": c["title"], "beats": c["beats"]} for c in chapters]},
                      ensure_ascii=False)
    previous = "(this is the opening of the episode)"
    for i, c in enumerate(chapters, 1):
        last = i == len(chapters)
        ending = ("This is the final chapter: close the journey with a slow, peaceful reflection "
                  "and a soft goodnight. Do not ask for likes or subscriptions." if last else
                  "Do not wrap up or summarize the episode; flow naturally toward the next chapter.")
        text = clean(ask_claude(fill(
            "chapter.md", CHANNEL=ch["name"], LANGUAGE=lang, OUTLINE=plan, N=i,
            TOTAL=len(chapters), CHAPTER_TITLE=c["title"], BEATS="; ".join(c["beats"]),
            WORDS=words, PREVIOUS=previous, ENDING_RULE=ending)))
        c["text"] = text
        previous = text.split("\n\n")[-1][-500:]
        print(f"  chapter {i}/{len(chapters)}: {len(text.split())} words")
    outline["topic"] = topic
    return outline
