"""Full episode, end to end:
topic -> script (+review) -> voice -> footage -> score -> mix -> render -> thumbnails -> Shorts -> QA -> YouTube

Resumable: if a run dies, rerun with the same --topic and finished steps are skipped.
"""
import argparse
import datetime as dt
import math
import os
import zlib

from .common import (DATA, LANG_NAMES, ROOT, load_config, read_json, slugify,
                     timestamp, write_json)

CREDITS = {
    "en": "Imagery and footage: NASA Image and Video Library (public domain; NASA does not endorse this channel).\n"
          "Narration: AI voice. Script researched, written and science-checked for this channel. "
          "Music: original ambient score.",
    "es": "Imágenes y video: NASA Image and Video Library (dominio público; la NASA no respalda este canal).\n"
          "Narración: voz IA. Guion investigado, escrito y revisado para este canal. "
          "Música: banda sonora ambiental original.",
}


def build_description(script, timing, lang):
    intro = "Intro" if lang == "en" else "Introducción"
    lines = [f"00:00 {intro}"] + [f"{timestamp(c['start'])} {c['title']}" for c in timing["chapters"]]
    label = "Chapters" if lang == "en" else "Capítulos"
    return f"{script['description']}\n\n{label}\n" + "\n".join(lines) + f"\n\n{CREDITS[lang]}"


def step(n, total, text):
    print(f"[{n}/{total}] {text}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-shorts", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    v = cfg["video"]
    lang = cfg["channel"]["language"]
    assert lang in LANG_NAMES, f"unsupported language {lang}"
    from .topics import next_topic
    topic = args.topic or os.environ.get("TOPIC") or next_topic(cfg)
    do_upload = not args.no_upload and os.environ.get("UPLOAD", "").lower() != "false"
    do_shorts = not args.no_shorts and cfg.get("shorts", {}).get("count", 0) > 0
    out = ROOT / "outputs" / slugify(topic)
    out.mkdir(parents=True, exist_ok=True)
    N = 10
    print(f"== {topic}\n   -> {out}")

    # 1. script
    script = read_json(out / "script.json", None)
    if not script:
        from .script import write_script, write_shorts
        step(1, N, "writing script with Claude")
        script = write_script(topic, cfg)
        script["shorts"] = write_shorts(script, cfg, cfg.get("shorts", {}).get("count", 2)) if do_shorts else []
        write_json(out / "script.json", script)

    # 2. narration + captions
    timing = read_json(out / "timing.json", None)
    if not timing or not (out / "narration.wav").exists():
        from .voice import synthesize
        step(2, N, "narrating")
        timing = synthesize(script, cfg, out)
        write_json(out / "timing.json", timing)
    print(f"   narration: {timing['duration'] / 60:.1f} min")

    # 3. footage per chapter; never reuses media already used on the channel
    used = set(read_json(DATA / "used_assets.json", []))
    media = read_json(out / "media.json", None)
    if not media:
        from .assets import fetch_clips, fetch_images
        step(3, N, "fetching NASA imagery and footage")
        spi, media = v["seconds_per_image"], []
        for i, (ch, mark) in enumerate(zip(script["chapters"], timing["chapters"])):
            seconds = mark["end"] - mark["start"]
            want = max(4, math.ceil(seconds / spi * 0.65))
            imgs = fetch_images(ch.get("image_queries", []), want, out / "images", used)
            clips = fetch_clips(ch.get("video_queries", []), v.get("clips_per_chapter", 3),
                                out / "clips", used, seconds=14, W=v["width"], H=v["height"], fps=v["fps"])
            if not imgs and not clips:
                raise RuntimeError(f"no media for chapter {i + 1}")
            media.append({"images": imgs, "clips": clips})
            print(f"   chapter {i + 1}: {len(imgs)} images, {len(clips)} clips")
        write_json(out / "media.json", media)
        write_json(DATA / "used_assets.json", sorted(used))

    # 4. score
    music = out / "music.wav"
    if not music.exists():
        from .music import make_ambient
        step(4, N, "composing ambient score")
        make_ambient(music, seed=zlib.crc32(topic.encode()))

    # 5. final audio
    audio = out / "audio.wav"
    if not audio.exists():
        from .mix import mix
        step(5, N, "mixing voice and score")
        mix(out / "narration.wav", music, audio, timing["duration"],
            music_volume=cfg["mix"]["music_volume"], lufs=cfg["mix"]["lufs"])

    # 6. picture
    video = out / "video.mp4"
    from .render import build_episode
    shots, _ = build_episode(timing, script, media, cfg)
    write_json(out / "shots.json", shots)
    if not video.exists():
        from .render import render_episode
        step(6, N, "rendering video")
        tmp = out / "video.partial.mp4"
        render_episode(timing, script, media, audio, tmp, cfg)
        tmp.rename(video)

    # 7. thumbnails + metadata
    from .thumbnail import make_thumbnails
    step(7, N, "thumbnails + metadata")
    # thumbnails come from the opening chapter (the episode's main subject), not side topics
    all_imgs = [i["path"] for i in media[0]["images"]] or [i["path"] for m in media for i in m["images"]]
    texts = script.get("thumbnail_texts") or [script.get("thumbnail_text", script["title"])]
    thumbs = make_thumbnails(all_imgs, texts, out)
    meta = {"title": script["title"], "tags": script.get("tags", []),
            "description": build_description(script, timing, lang)}
    write_json(out / "metadata.json", meta)

    # 8. Shorts
    shorts = read_json(out / "shorts.json", None)
    if shorts is None:
        shorts = []
        if do_shorts and script.get("shorts"):
            from .shorts import produce_short
            step(8, N, f"producing {len(script['shorts'])} Shorts")
            fallback = [i for m in media for i in m["images"]]
            for k, s in enumerate(script["shorts"], 1):
                try:
                    r = produce_short(s, k, cfg, out / "shorts", used, music, fallback)
                    if r:
                        shorts.append(r)
                except Exception as exc:
                    print(f"   short {k} failed: {exc}")
            write_json(DATA / "used_assets.json", sorted(used))
        write_json(out / "shorts.json", shorts)

    # 9. QA gate
    from .qa import check_episode
    step(9, N, "quality check")
    report = check_episode(out, script, timing, media, shots, video)
    print(f"   QA {'PASSED' if report['ok'] else 'FAILED'}: {report['minutes']} min, "
          f"{report['lufs']} LUFS, {report['clips']} clips")
    for f in report["fails"]:
        print(f"   FAIL: {f}")
    for w in report["warnings"]:
        print(f"   warn: {w}")

    # 10. upload
    video_id, short_ids = None, []
    from .upload import has_credentials, upload
    if do_upload and has_credentials() and report["ok"]:
        step(10, N, "uploading to YouTube")
        video_id = upload(video, meta, cfg, thumbnail=thumbs[0] if thumbs else None,
                          captions=out / "captions.srt")
        print(f"   https://youtu.be/{video_id}")
        for s in shorts:
            full = "Full documentary" if lang == "en" else "Documental completo"
            smeta = {"title": s["title"], "tags": script.get("tags", [])[:8],
                     "description": f"{s['narration'][:300]}\n\n{full}: https://youtu.be/{video_id}\n\n#Shorts #space"}
            try:
                sid = upload(s["path"], smeta, cfg)
                short_ids.append(sid)
                print(f"   short: https://youtu.be/{sid}")
            except Exception as exc:
                print(f"   short upload failed: {exc}")
    else:
        why = ("QA failed" if not report["ok"] else "no credentials" if not has_credentials()
               else "upload disabled")
        step(10, N, f"upload skipped ({why})")

    done = read_json(DATA / "done.json", [])
    done.append({"topic": topic, "title": script["title"], "video_id": video_id, "shorts": short_ids,
                 "minutes": round(timing["duration"] / 60, 1), "qa_ok": report["ok"],
                 "date": dt.date.today().isoformat()})
    write_json(DATA / "done.json", done)
    if not report["ok"]:
        raise SystemExit("QA failed: see outputs/*/qa.json")
    print("done.")


if __name__ == "__main__":
    main()
