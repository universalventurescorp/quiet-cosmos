"""Topic queue that refills itself with Claude when it runs low."""
import json

from .common import DATA, LANG_NAMES, extract_json, read_json, write_json
from .script import ask_claude


def next_topic(cfg):
    backlog = read_json(DATA / "topics.json", [])
    done = {d["topic"] for d in read_json(DATA / "done.json", [])}
    remaining = [t for t in backlog if t not in done]
    if len(remaining) < 5:
        fresh = [t for t in generate_topics(cfg, backlog) if t not in backlog]
        backlog += fresh
        write_json(DATA / "topics.json", backlog)
        remaining = [t for t in backlog if t not in done]
    if not remaining:
        raise SystemExit("No topics left")
    return remaining[0]


def generate_topics(cfg, existing):
    ch = cfg["channel"]
    prompt = f"""You plan episodes for "{ch['name']}", {ch.get('about', 'a YouTube channel of calm long-form space documentaries for relaxation and sleep')}, narrated in {LANG_NAMES[ch['language']]}.
Episodes already made or planned: {json.dumps(existing[-100:], ensure_ascii=False)}

Propose 20 NEW episode topics that (1) people actively search for on YouTube, (2) have enough real, well-established science for a {cfg['video']['target_minutes']}-minute episode, and (3) do not overlap with the list.
Return ONLY a JSON array of 20 strings, each a one-line topic brief."""
    try:
        return [str(t).strip() for t in extract_json(ask_claude(prompt))][:20]
    except Exception as exc:  # keep the pipeline alive; next run retries
        print(f"  topic refill failed: {exc}")
        return []
