"""Full episode: topic -> script -> voice -> images -> music -> video -> thumbnail -> YouTube.
Resumable: if a run dies, rerun with the same --topic and finished steps are skipped."""
import argparse
import datetime as dt
import math
import os
import zlib

from .common import (DATA, LANG_NAMES, ROOT, load_config, read_json, slugify,
                     timestamp, write_json)

CREDITS = {
    "en": "Imagery: NASA Image and Video Library (public domain; NASA does not endorse this channel).\n"
          "Narration: AI voice. Script researched and written for this channel. Music: original ambient score.",
    "es": "Imágenes: NASA Image and Video Library (dominio público; la NASA no respalda este canal).\n"
          "Narración: voz IA. Guion escrito para este canal. Música: banda sonora ambiental original.",
}


def build_description(script, timing, lang):
    chapters = "\n".join(f"{timestamp(c['start'] if i else 0)} {c['title']}"
                         for i, c in enumerate(timing["chapters"]))
    label = "Chapters" if lang == "en" else "Capítulos"
    return f"{script['description']}\n\n{label}\n{chapters}\n\n{CREDITS[lang]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    lang = cfg["channel"]["language"]
    assert lang in LANG_NAMES, f"unsupported language {lang}"
    from .topics import next_topic
    topic = args.topic or os.environ.get("TOPIC") or next_topic(cfg)
    do_upload = not args.no_upload and os.environ.get("UPLOAD", "").lower() != "false"
    out = ROOT / "outputs" / slugify(topic)
    out.mkdir(parents=True, exist_ok=True)
    print(f"== {topic}\n   -> {out}")

    # 1. script
    script = read_json(out / "script.json", None)
    if not script:
        from .script import write_script
        print("[1/7] writing script with Claude")
        script = write_script(topic, cfg)
        write_json(out / "script.json", script)

    # 2. voice + captions
    timing = read_json(out / "timing.json", None)
    if not timing or not (out / "narration.wav").exists():
        from .voice import synthesize
        print("[2/7] narrating")
        timing = synthesize(script["chapters"], cfg, out)
        write_json(out / "timing.json", timing)
    print(f"   narration: {timing['duration'] / 60:.1f} min")

    # 3. images, per chapter, never reusing an image already used on the channel
    chapter_images = read_json(out / "images.json", None)
    if not chapter_images:
        from .assets import fetch_images
        print("[3/7] fetching NASA imagery")
        used = set(read_json(DATA / "used_assets.json", []))
        spi, chapter_images = cfg["video"]["seconds_per_image"], []
        for i, (ch, mark) in enumerate(zip(script["chapters"], timing["chapters"])):
            want = max(3, math.ceil((mark["end"] - mark["start"]) / spi * 0.7))
            imgs = fetch_images(ch.get("image_queries", []), want, out / "images", used)
            if not imgs:
                raise RuntimeError(f"no images for chapter {i + 1}")
            chapter_images.append(imgs)
            print(f"   chapter {i + 1}: {len(imgs)} images")
        write_json(out / "images.json", chapter_images)
        write_json(DATA / "used_assets.json", sorted(used))

    # 4. music
    music = out / "music.wav"
    if not music.exists():
        from .music import make_ambient
        print("[4/7] composing ambient score")
        make_ambient(music, seed=zlib.crc32(topic.encode()))

    # 5. video
    video = out / "video.mp4"
    if not video.exists():
        from .render import render
        print("[5/7] rendering video")
        render(timing, chapter_images, out / "narration.wav", music, out, cfg)

    # 6. thumbnail + metadata
    from .thumbnail import make_thumbnail
    print("[6/7] thumbnail + metadata")
    make_thumbnail([img["path"] for img in chapter_images[0]], script["thumbnail_text"],
                   out / "thumbnail.jpg")
    meta = {"title": script["title"], "tags": script.get("tags", []),
            "description": build_description(script, timing, lang)}
    write_json(out / "metadata.json", meta)

    # 7. upload
    video_id = None
    from .upload import has_credentials, upload
    if do_upload and has_credentials():
        print("[7/7] uploading to YouTube")
        video_id = upload(video, out / "thumbnail.jpg", out / "captions.srt", meta, cfg)
        print(f"   https://youtu.be/{video_id}")
    else:
        print("[7/7] upload skipped (no credentials or --no-upload)")

    done = read_json(DATA / "done.json", [])
    done.append({"topic": topic, "title": script["title"], "video_id": video_id,
                 "minutes": round(timing["duration"] / 60, 1), "date": dt.date.today().isoformat()})
    write_json(DATA / "done.json", done)
    print("done.")


if __name__ == "__main__":
    main()
