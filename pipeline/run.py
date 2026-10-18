"""Full episode, end to end (v3):
topic -> script (+review) -> AI scene plan -> [Kaggle GPU paints scenes, in parallel] -> voice -> NASA footage
-> score -> mix -> collect AI scenes (depth maps, clips) -> render -> thumbnails -> Shorts -> QA -> YouTube

Resumable: if a run dies, rerun with the same --topic and finished steps are skipped.
"""
import argparse
import json
import datetime as dt
import math
import os
import time
import zlib

from .common import (DATA, LANG_NAMES, ROOT, load_config, read_json, slugify,
                     timestamp, write_json)
from .scenes import credits_line

CREDITS = {
    "en": "Imagery and footage: NASA Image and Video Library (public domain; NASA does not endorse this channel).\n"
          "Narration: AI voice. Script researched, written and science-checked for this channel. "
          "Music: original ambient score.",
    "es": "Imágenes y video: NASA Image and Video Library (dominio público; la NASA no respalda este canal).\n"
          "Narración: voz IA. Guion investigado, escrito y revisado para este canal. "
          "Música: banda sonora ambiental original.",
}


def build_description(script, timing, lang, used_ai=False):
    intro = "Intro" if lang == "en" else "Introducción"
    lines = [f"00:00 {intro}"] + [f"{timestamp(c['start'])} {c['title']}" for c in timing["chapters"]]
    label = "Chapters" if lang == "en" else "Capítulos"
    credits = CREDITS[lang] + (f"\n{credits_line(lang)}" if used_ai else "")
    return f"{script['description']}\n\n{label}\n" + "\n".join(lines) + f"\n\n{credits}"


def video_bench(cfg, kind="video"):
    """Kaggle benchmarks (no episode). kind: "video" (image-to-video models) or "voice" (Spanish TTS voices)."""
    import shutil
    import subprocess
    from . import gpu
    out = ROOT / "outputs" / f"{kind}-bench"
    out.mkdir(parents=True, exist_ok=True)
    job = {"job_id": f"{kind}-bench-{dt.datetime.utcnow():%Y%m%d%H%M%S}"}
    prev = ROOT / "data" / "diagnostics" / f"{kind}_bench"
    if kind == "voice" and os.environ.get("BENCH_ENGINES"):
        # partial rerun: only these engines, reusing the designed reference voices already in the repo
        import base64
        job["engines"] = os.environ["BENCH_ENGINES"].split(",")
        job["refs"] = {p.stem[4:]: base64.b64encode(p.read_bytes()).decode() for p in prev.glob("ref_*.mp3")}
        if os.environ.get("BENCH_DESIGNS") == "true":     # round 2: new narrator voices from kaggle/voice_designs.json
            job["design"] = read_json(ROOT / "kaggle" / "voice_designs.json", {})
            job["refs"] = {}
        if os.environ.get("BENCH_MEJOR4") == "true":        # strong melody edit: PSOLA vs WORLD, no tremor
            os.environ["BENCH_EMOTION"] = "true"
            job.update(mejor4=True, prosody_src=(ROOT / "pipeline" / "prosody.py").read_text(encoding="utf-8"))
        if os.environ.get("BENCH_MEJOR3") == "true":        # re-intoned reference clip, untouched episode audio
            os.environ["BENCH_EMOTION"] = "true"
            job.update(mejor3=True, prosody_src=(ROOT / "pipeline" / "prosody.py").read_text(encoding="utf-8"))
        if os.environ.get("BENCH_MEJOR2") == "true":        # many takes + production melody edit, no tremor
            os.environ["BENCH_EMOTION"] = "true"
            job.update(mejor2=True, prosody_src=(ROOT / "pipeline" / "prosody.py").read_text(encoding="utf-8"))
        if os.environ.get("BENCH_MEJOR") == "true":         # paragraphs + FireRedTTS3 + pitch-contour editing
            os.environ["BENCH_EMOTION"] = "true"
            job["mejor"] = True
        if os.environ.get("BENCH_PARRAFO") == "true":       # same narrator, voiced paragraph by paragraph
            os.environ["BENCH_EMOTION"] = "true"
            job["parrafo"] = True
        if os.environ.get("BENCH_NOCTURNO") == "true":
            os.environ["BENCH_NATIVE"] = "true"
            job["nocturno"] = True
        if os.environ.get("BENCH_NATIVE") == "true":
            os.environ["BENCH_EMOTION"] = "true"
            job["native"] = True
        if os.environ.get("BENCH_EMOTION") == "true":     # "voz dirigida": the channel narrator + emotion edits
            import yaml
            ch = yaml.safe_load((ROOT / "channels" / "estrato-nocturno.yaml").read_text(encoding="utf-8"))
            job.update(emotion=True, narrator_ref_text=ch["voice"]["ref_text"],
                       refs={"narrador": base64.b64encode((ROOT / ch["voice"]["ref_audio"]).read_bytes()).decode()})
    prev_state = read_json(ROOT / "data" / "diagnostics" / f"{kind}_bench" / "manifest.json", {}).get("push") or {}
    if (prev_state.get("ok") and not prev_state.get("reused") and not job.get("engines")
            and time.time() - prev_state.get("pushed_at", 0) < 4 * 3600):
        # a bench pushed in the last 4 h may still be running (or finished) on Kaggle: collect it
        # instead of spending GPU quota on a new one
        state = {**prev_state, "reused": True}      # reuse once; if it yields nothing, the next run pushes anew
        write_json(out / "kaggle.json", state)
        print(f"   collecting the bench already on Kaggle: {state['job_id']}")
    else:
        state = gpu.launch(job, out, cfg, worker=ROOT / "kaggle" / f"bench_{kind}.py") if gpu.configured() else {}
    manifest = gpu.collect(out, cfg, wait_minutes=330 if job.get("native") else 180) if state.get("ok") else None
    prev.mkdir(parents=True, exist_ok=True)
    old_scores = read_json(prev / "scores.json", {})
    for f in prev.glob("*"):
        if not (job.get("engines") and f.suffix == ".mp3"):     # a partial voice rerun keeps the earlier audio
            f.unlink()
    ai = out / "ai"
    if manifest is not None:
        manifest["push"] = state
    for p in (sorted(ai.glob("*.mp3")) + sorted(ai.glob("scores.json")) + sorted(ai.glob("refpick.json")) + sorted(ai.glob("*.log"))
              + sorted(ai.glob("log.txt"))) if ai.exists() else []:
        shutil.copy(p, prev / p.name)          # voice bench: listening files, scores, per-engine logs
    if job.get("engines") and (prev / "scores.json").exists():
        write_json(prev / "scores.json", {**old_scores, **read_json(prev / "scores.json", {})})
    for p in sorted(ai.glob("*.jpg")) if ai.exists() else []:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", "scale=640:-2", str(prev / p.name)])
    for p in sorted(ai.glob("*.mp4")) if ai.exists() else []:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf",
                        "fps=2,scale=320:-2,tile=4x2", "-frames:v", "1", str(prev / f"{p.stem}_frames.jpg")])
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vf", "scale=480:-2",
                        "-c:v", "libx264", "-crf", "30", "-an", str(prev / f"{p.stem}.mp4")])
    if not manifest:
        # keep whatever Kaggle left (its own .log has the stdout/stderr of the crash) so we can read it from git
        for f in list((out / "kaggle_output").rglob("*.log")) + list((out / "kaggle_output").rglob("log.txt")):
            lines = f.read_text(errors="ignore").splitlines()
            (prev / f"kaggle_{f.name}.txt").write_text("\n".join(lines[-300:]))
        try:
            state = {**state, "final_status": gpu.status(state["kernel"])[1][-800:]} if state.get("kernel") else state
        except Exception:
            pass
    write_json(prev / "manifest.json", manifest or {"error": "no result", "push": state})
    print(json.dumps(manifest or {}, indent=1)[:4000])


def gpu_test(cfg):
    from . import gpu
    from .scenes import build_job
    out = ROOT / "outputs" / "gpu-test"
    out.mkdir(parents=True, exist_ok=True)
    plan = {"sections": [{"id": "chapter_1", "scenes": [
        {"anchor": "", "prompt": "the surface of Titan under an orange hazy sky, methane lakes and icy pebbles, "
                                 "wide establishing shot from the ground", "motion": "slow push in, haze drifting",
         "video": True},
        {"anchor": "", "prompt": "Saturn with its rings seen from orbit, sunlight glinting on the ring plane"},
        {"anchor": "", "prompt": "the Milky Way core rising over a dark rocky alien horizon, long exposure"},
        {"anchor": "", "prompt": "a black hole with a glowing accretion disk bending light around it"}]}]}
    job = build_job(plan, cfg, f"gpu-test-{dt.datetime.utcnow():%Y%m%d%H%M%S}", "gpu test")
    job["budget_minutes"] = 45
    write_json(out / "gpu_job.json", job)
    print(f"GPU test: configured={gpu.configured()}")
    state = gpu.launch(job, out, cfg) if gpu.configured() else {}
    manifest = gpu.collect(out, cfg, wait_minutes=90) if state.get("ok") else None
    if manifest:
        from .scenes import prepare_ai_files
        files = prepare_ai_files(out / "ai", cfg)
        print(f"GPU test result: {len(files['images'])} images, {len(files['clips'])} clips")
        # small previews committed to the repo, to judge quality without downloading artifacts
        import subprocess
        from PIL import Image
        prev = ROOT / "data" / "diagnostics" / "gpu_test"
        prev.mkdir(parents=True, exist_ok=True)
        for f in prev.glob("*"):
            f.unlink()
        for k, path in files["images"].items():
            im = Image.open(path).convert("RGB")
            im.thumbnail((960, 960))
            im.save(prev / f"{k}.jpg", quality=80)
        for k, c in files["clips"].items():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", c["path"], "-vf",
                            "fps=1/2,scale=480:-2,tile=4x2", "-frames:v", "1", str(prev / f"{k}_frames.jpg")])
    save_diagnostics(out, {"gpu_test": True}, {"status": "ok" if manifest else "failed",
                                               "errors": (manifest or {}).get("errors", [])})
    print(json.dumps(read_json(DATA / "diagnostics" / "last_episode.json", {}), indent=1)[:6000])


def save_diagnostics(out, report=None, ai_media=None):
    """Small report committed to the repo (data/diagnostics/) so problems can be read without
    downloading Actions artifacts."""
    def tail(path, n=60):
        return path.read_text(errors="ignore").splitlines()[-n:] if path.exists() else []
    plan = read_json(out / "scenes.json", {"sections": []})
    diag = {
        "episode": out.name,
        "date": dt.datetime.utcnow().isoformat(timespec="seconds"),
        "qa": {k: v for k, v in (report or {}).items()},
        "ai_status": (ai_media or {}).get("status"),
        "ai_errors": [e[-1500:] for e in (ai_media or {}).get("errors", [])],
        "scene_plan": {sec["id"]: len(sec["scenes"]) for sec in plan.get("sections", [])},
        "gpu_job_images": len(read_json(out / "gpu_job.json", {}).get("images", [])),
        "kaggle_push": read_json(out / "kaggle.json", {}),
        "kaggle_manifest": read_json(out / "ai" / "manifest.json", None),
        "kaggle_log": tail(out / "ai" / "log.txt"),
        "voice": (ai_media or {}).get("voice"),
        "voice_logs": {f.name: tail(f, 25) for f in sorted((out / "ai").glob("voice_gpu*.log"))},
        "sample": os.environ.get("SAMPLE", "").lower() == "true",
    }
    write_json(DATA / "diagnostics" / "last_episode.json", diag)


def narration_job(script, cfg):
    """What Kaggle needs to voice the episode with the channel's narrator (Qwen3-TTS voice clone)."""
    import base64
    from .voice import narration_items
    vc = cfg["voice"]
    ref = ROOT / vc["ref_audio"]
    return {"model": vc.get("model", "Qwen/Qwen3-TTS-12Hz-1.7B-Base"),
            "language": {"es": "Spanish", "en": "English"}[cfg["channel"]["language"]],
            "ref_text": vc["ref_text"], "ref_b64": base64.b64encode(ref.read_bytes()).decode(),
            "items": narration_items(script, vc.get("unit", "sentence"),
                                            vc.get("inner_end") if vc.get("unit") == "paragraph" else None)}


def load_gpu_voice(out, cfg, gpu_state):
    """Wait for Kaggle and return (voice, info). Falls back to Kokoro if the GPU narration is incomplete."""
    from . import gpu
    from .voice import PrecomputedVoice, Voice
    vc = cfg["voice"]
    job = read_json(out / "gpu_job.json", {})
    items = [tuple(x) for x in (job.get("narration") or {}).get("items", [])]
    fb = vc.get("fallback_id", "em_alex")
    if not (gpu_state and gpu_state.get("ok") and items):
        print(f"   GPU narration not available: Kokoro {fb}")
        vc["id"] = fb
        return None, {"engine": "kokoro (fallback)", "reason": "kaggle not launched"}
    print("   waiting for the narrator voice from Kaggle", flush=True)
    gpu.collect(out, cfg)
    folder = out / "ai" / "narration"
    have = sum((folder / f"{i:05d}.wav").exists() for i, _ in items)
    info = {"engine": "qwen", "sentences": len(items), "voiced": have}
    if have == len(items):
        return PrecomputedVoice(folder, items), info
    if have >= 0.97 * len(items):
        print(f"   {len(items) - have} sentences missing: Kokoro {fb} fills them")
        info["filled_with_kokoro"] = len(items) - have
        return PrecomputedVoice(folder, items, fallback=Voice(fb, vc.get("speed", 0.8))), info
    print(f"   GPU narration incomplete ({have}/{len(items)}): whole episode with Kokoro {fb}")
    vc["id"] = fb
    return None, {**info, "engine": "kokoro (fallback)", "reason": "incomplete GPU narration"}


def step(n, total, text):
    print(f"[{n}/{total}] {text}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--no-shorts", action="store_true")
    ap.add_argument("--no-ai", action="store_true", help="v2 look: NASA imagery only, no Kaggle GPU")
    ap.add_argument("--gpu-test", action="store_true", help="only test Kaggle: 4 images + 1 clip (~20 min)")
    ap.add_argument("--video-bench", action="store_true", help="benchmark image-to-video models on Kaggle")
    ap.add_argument("--voice-bench", action="store_true", help="benchmark Spanish TTS voices on Kaggle")
    ap.add_argument("--sample", action="store_true",
                    help="short preview episode (SAMPLE_MINUTES, 2 chapters, no Shorts), uploaded private as MUESTRA")
    args = ap.parse_args()
    sample = args.sample or os.environ.get("SAMPLE", "").lower() == "true"
    if sample:
        os.environ["SAMPLE"] = "true"
    if args.video_bench:
        return video_bench(load_config())
    if args.voice_bench:
        return video_bench(load_config(), kind="voice")
    if args.gpu_test:
        return gpu_test(load_config())

    cfg = load_config()
    v = cfg["video"]
    lang = cfg["channel"]["language"]
    assert lang in LANG_NAMES, f"unsupported language {lang}"
    from .topics import next_topic
    topic = args.topic or os.environ.get("TOPIC") or (None if sample else next_topic(cfg))
    if not topic:
        raise SystemExit("a sample needs an explicit topic (TOPIC)")
    do_upload = not args.no_upload and os.environ.get("UPLOAD", "").lower() != "false"
    do_shorts = not args.no_shorts and cfg.get("shorts", {}).get("count", 0) > 0 and not sample
    if sample:
        v["target_minutes"] = float(os.environ.get("SAMPLE_MINUTES") or 5)
        v["chapters"] = 2
        cfg.setdefault("kaggle", {})["gpu_budget_minutes"] = 60
    voice_cfg = cfg["voice"]
    opt = os.environ.get("BENCH_ENGINES", "")
    if not args.voice_bench and opt.startswith("voz="):
        # try a narration mode on one run without touching the channel config: bench_engines = "voz=parrafo" or
        # "voz=parrafo..." (paragraphs, inner sentence ends read as a suspension)
        mode, _, pe = opt[4:].partition("+")       # "voz=parrafo...+C" also edits the melody (pipeline/prosody.py)
        voice_cfg["pitch_edit"] = pe or None
        voice_cfg["unit"] = "paragraph" if mode.startswith("parrafo") else "sentence"
        voice_cfg["inner_end"] = mode[len("parrafo"):] or None if mode.startswith("parrafo") else None
        print(f"   voice mode for this run: {voice_cfg['unit']} {voice_cfg.get('inner_end') or ''} "
              f"pitch edit {voice_cfg.get('pitch_edit')}")
    gpu_voice = voice_cfg.get("engine", "kokoro") == "qwen"
    out = ROOT / "outputs" / (slugify(topic) + ("-muestra" if sample else ""))
    out.mkdir(parents=True, exist_ok=True)
    N = 12
    ai_cfg = cfg.get("ai", {})
    use_ai = ai_cfg.get("enabled", False) and not args.no_ai
    print(f"== {topic}\n   -> {out}")

    # 1. script
    script = read_json(out / "script.json", None)
    if not script:
        from .script import write_script, write_shorts
        step(1, N, "writing script with Claude")
        script = write_script(topic, cfg)
        script["shorts"] = write_shorts(script, cfg, cfg.get("shorts", {}).get("count", 2)) if do_shorts else []
        write_json(out / "script.json", script)

    # 2. AI scenes: Claude designs them, Kaggle starts painting while everything else runs
    gpu_state = None
    if use_ai:
        from . import gpu
        from .scenes import build_job, plan_scenes
        plan = read_json(out / "scenes.json", None)
        if not plan:
            step(2, N, "designing AI scenes with Claude")
            plan = plan_scenes(script, cfg)
            write_json(out / "scenes.json", plan)
        gpu_state = read_json(out / "kaggle.json", None)
        if not gpu.configured():
            print("   Kaggle not configured (KAGGLE_USERNAME / KAGGLE_KEY): NASA imagery only")
        elif not gpu_state or not gpu_state.get("ok"):
            job = build_job(plan, cfg, f"{slugify(topic)}-{dt.datetime.utcnow():%Y%m%d%H%M%S}", topic)
            if gpu_voice:
                job["narration"] = narration_job(script, cfg)
            write_json(out / "gpu_job.json", job)
            print(f"   sending {len(job['images'])} images + {len(job['videos'])} clips"
                  + (f" + {len(job['narration']['items'])} sentences to voice" if gpu_voice else "") + " to Kaggle")
            if job["images"] or job.get("narration"):
                gpu_state = gpu.launch(job, out, cfg)
            else:
                print("   Claude returned no scene prompts: NASA imagery only")

    # 3. narration + captions
    timing = read_json(out / "timing.json", None)
    gpu_voice_obj, voice_info = None, {"engine": "kokoro"}
    if gpu_voice:
        gpu_voice_obj, voice_info = load_gpu_voice(out, cfg, gpu_state)
    if not timing or not (out / "narration.wav").exists():
        from .voice import synthesize
        step(3, N, f"narrating ({voice_info['engine']})")
        timing = synthesize(script, cfg, out, voice=gpu_voice_obj)
        write_json(out / "timing.json", timing)
    print(f"   narration: {timing['duration'] / 60:.1f} min")

    # 4. footage per chapter; never reuses media already used on the channel
    used = set(read_json(DATA / "used_assets.json", []))
    media = read_json(out / "media.json", None)
    if not media:
        from .assets import fetch_clips, fetch_images
        step(4, N, "fetching NASA imagery and footage")
        spi, media = v["seconds_per_image"], []
        nasa_share = 1.0 - (ai_cfg.get("share", 0.45) if gpu_state and gpu_state.get("ok") else 0.0)
        for i, (ch, mark) in enumerate(zip(script["chapters"], timing["chapters"])):
            seconds = mark["end"] - mark["start"]
            want = max(4, math.ceil(seconds / spi * 0.65 * max(nasa_share, 0.45)))
            imgs = fetch_images(ch.get("image_queries", []), want, out / "images", used)
            clips = fetch_clips(ch.get("video_queries", []), v.get("clips_per_chapter", 3),
                                out / "clips", used, seconds=14, W=v["width"], H=v["height"], fps=v["fps"])
            if not imgs and not clips:
                raise RuntimeError(f"no media for chapter {i + 1}")
            media.append({"images": imgs, "clips": clips})
            print(f"   chapter {i + 1}: {len(imgs)} images, {len(clips)} clips")
        write_json(out / "media.json", media)
        write_json(DATA / "used_assets.json", sorted(used))

    # 5. score
    music = out / "music.wav"
    if not music.exists():
        from .music import make_ambient, make_score
        step(5, N, "composing ambient score")
        if cfg["mix"].get("score") == "chapters":
            make_score(music, timing, seed=zlib.crc32(topic.encode()))
        else:
            make_ambient(music, seed=zlib.crc32(topic.encode()))

    # 6. final audio
    audio = out / "audio.wav"
    if not audio.exists():
        from .mix import mix
        step(6, N, "mixing voice and score")
        mix(out / "narration.wav", music, audio, timing["duration"],
            music_volume=cfg["mix"]["music_volume"], lufs=cfg["mix"]["lufs"],
            voice_eq=cfg["mix"].get("voice_eq", "clean"))

    # 7. AI scenes back from the GPU: depth maps for 2.5D, slowed clips, placed on their sentences
    ai_media = read_json(out / "ai_media.json", None)
    if ai_media is None:
        ai_media = {"placed": {}, "status": "off" if not use_ai else "not run"}
        if gpu_state and gpu_state.get("ok"):
            from . import gpu
            from .scenes import place_scenes, prepare_ai_files, read_srt
            step(7, N, "waiting for the Kaggle GPU and preparing AI scenes")
            manifest = gpu.collect(out, cfg)
            if manifest:
                files = prepare_ai_files(out / "ai", cfg)
                placed = place_scenes(read_json(out / "scenes.json", {"sections": []}), files,
                                      read_srt(out / "captions.srt"), timing, min_gap=v["seconds_per_image"])
                n_placed = sum(len(x) for x in placed.values())
                status = "ok" if n_placed else (
                    f"kaggle returned {len(files['images'])} images, {n_placed} placed")
                ai_media = {"placed": placed, "status": status, "errors": manifest.get("errors", []),
                            "gpus": manifest.get("gpus", []), "gpu_minutes": manifest.get("minutes"),
                            "images": len(files["images"]), "clips": len(files["clips"])}
            else:
                ai_media["status"] = "kaggle failed or timed out"
        elif use_ai:
            ai_media["status"] = "kaggle push failed" if gpu_state else "kaggle not configured"
        write_json(out / "ai_media.json", ai_media)
    ai_media["voice"] = voice_info
    placed = ai_media.get("placed", {})
    used_ai = any(placed.values())
    if use_ai and not used_ai:
        print(f"   no AI scenes this episode ({ai_media.get('status')}): NASA imagery only")

    # 8. picture
    video = out / "video.mp4"
    from .render import build_episode
    shots, _ = build_episode(timing, script, media, cfg, ai=placed)
    write_json(out / "shots.json", shots)
    if not video.exists():
        from .render import render_episode
        step(8, N, "rendering video")
        tmp = out / "video.partial.mp4"
        render_episode(timing, script, media, audio, tmp, cfg, ai=placed)
        tmp.rename(video)

    # 9. thumbnails + metadata
    from .thumbnail import make_thumbnails
    step(9, N, "thumbnails + metadata")
    # thumbnails come from the opening chapter (the episode's main subject), not side topics;
    # the AI hero scenes of the cold open and chapter one compete with the real photos
    all_imgs = [i["path"] for i in media[0]["images"]] or [i["path"] for m in media for i in m["images"]]
    all_imgs = [it["path"] for k in ("cold_open", "chapter_1") for it in placed.get(k, [])] + all_imgs
    texts = script.get("thumbnail_texts") or [script.get("thumbnail_text", script["title"])]
    thumbs = make_thumbnails(all_imgs, texts, out)
    title = f"MUESTRA · {script['title']}"[:100] if sample else script["title"]
    meta = {"title": title, "tags": script.get("tags", []),
            "description": build_description(script, timing, lang, used_ai), "synthetic": used_ai}
    write_json(out / "metadata.json", meta)

    # 10. Shorts
    shorts = read_json(out / "shorts.json", None)
    if shorts is None:
        shorts = []
        if do_shorts and script.get("shorts"):
            from .shorts import produce_short
            step(10, N, f"producing {len(script['shorts'])} Shorts")
            fallback = [i for m in media for i in m["images"]]
            for k, s in enumerate(script["shorts"], 1):
                try:
                    r = produce_short(s, k, cfg, out / "shorts", used, music, fallback, voice=gpu_voice_obj)
                    if r:
                        shorts.append(r)
                except Exception as exc:
                    print(f"   short {k} failed: {exc}")
            write_json(DATA / "used_assets.json", sorted(used))
        write_json(out / "shorts.json", shorts)

    # 11. QA gate
    from .qa import check_episode
    step(11, N, "quality check")
    report = check_episode(out, script, timing, media, shots, video, ai_media)
    print(f"   QA {'PASSED' if report['ok'] else 'FAILED'}: {report['minutes']} min, "
          f"{report['lufs']} LUFS, {report['clips']} clips, {report['ai_scenes']} AI scenes")
    for f in report["fails"]:
        print(f"   FAIL: {f}")
    for w in report["warnings"]:
        print(f"   warn: {w}")

    # 12. upload
    video_id, short_ids = None, []
    from .upload import has_credentials, upload
    if do_upload and has_credentials() and report["ok"]:
        step(12, N, "uploading to YouTube")
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
        step(12, N, f"upload skipped ({why})")

    save_diagnostics(out, report, ai_media)
    if sample:
        write_json(DATA / "diagnostics" / "last_sample.json",
                   {"topic": topic, "title": meta["title"], "video_id": video_id, "qa_ok": report["ok"],
                    "minutes": round(timing["duration"] / 60, 1), "voice": voice_info,
                    "date": dt.date.today().isoformat()})
        print(f"sample done: https://youtu.be/{video_id}" if video_id else "sample done (not uploaded)")
        return
    done = read_json(DATA / "done.json", [])
    done.append({"topic": topic, "title": script["title"], "video_id": video_id, "shorts": short_ids,
                 "minutes": round(timing["duration"] / 60, 1), "qa_ok": report["ok"],
                 "ai_scenes": report["ai_scenes"], "ai_status": ai_media.get("status"),
                 "date": dt.date.today().isoformat()})
    write_json(DATA / "done.json", done)
    if not report["ok"]:
        raise SystemExit("QA failed: see outputs/*/qa.json")
    print("done.")


def _main_with_crash_report():
    """Any crash leaves its traceback in data/.../diagnostics/last_crash.json (Actions logs are not
    readable from the Claude session, the repo is)."""
    import traceback
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        write_json(DATA / "diagnostics" / "last_crash.json",
                   {"date": dt.datetime.utcnow().isoformat(timespec="seconds"),
                    "sample": os.environ.get("SAMPLE", "").lower() == "true",
                    "topic": os.environ.get("TOPIC"), "traceback": traceback.format_exc()[-6000:]})
        raise


if __name__ == "__main__":
    _main_with_crash_report()
