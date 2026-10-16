"""Benchmark of open TTS voices in Spanish on Kaggle's free T4s (to replace Kokoro on Estrato Nocturno).

Production path being tested: a narrator voice is DESIGNED once from a text description (fixed reference
clip for the channel), then every sentence is CLONED from that clip, sentence by sentence, as the episode
pipeline does. Each engine runs in its own virtualenv (their pinned torch/transformers versions clash).

Lanes (one per GPU, in parallel):
  GPU 0: VoxCPM2 (design F/M + clone)  -> Chatterbox Multilingual V3 (clones the VoxCPM refs)
  GPU 1: Kokoro (current baseline)     -> Qwen3-TTS (VoiceDesign F/M + 1.7B Base clone)
Then scoring on GPU 1: Whisper large-v3-turbo (CER per sentence, catches mispronunciations and
hallucinations) + UTMOS22 (predicted naturalness, 1-5).

Output: /kaggle/working/ai/<variant>.mp3, ref_*.wav, scores.json, manifest.json, log.txt
"""
import base64
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import traceback

JOB_B64 = "__JOB_B64__"
OUT = pathlib.Path(os.environ.get("QC_OUT", "/kaggle/working/ai"))
WORK = pathlib.Path("/kaggle/tmp/voicebench")
T0 = time.time()

REF_TEXT = ("Esta noche viajaremos despacio, sin ninguna prisa, hacia el planeta más grande de nuestro "
            "sistema solar, mientras todo a nuestro alrededor se queda en calma.")
DESIGN = {
    "f": "A warm, calm, soft-spoken female narrator in her forties, speaking neutral Latin American Spanish "
         "slowly and gently, with a soothing low voice, like a bedtime nature documentary.",
    "m": "A deep, warm, calm male narrator in his fifties, speaking neutral Latin American Spanish slowly and "
         "softly, with a rich velvety voice, like a bedtime nature documentary.",
}
SENTENCES = [
    "Imagina que flotas en silencio, muy lejos de casa, mientras un mundo inmenso aparece poco a poco frente a ti.",
    "Es Júpiter, el planeta más grande de nuestro sistema solar, tan enorme que en su interior cabrían más de mil "
    "trescientas Tierras.",
    "Sus nubes forman franjas de color crema, ocre y marrón, que giran sin descanso alrededor del planeta.",
    "Y entre ellas, como un ojo que nunca se cierra, gira la Gran Mancha Roja: una tormenta más ancha que nuestro "
    "propio mundo.",
    "Los astrónomos la observan desde hace más de 150 años, y quizá lleva girando mucho más tiempo.",
    "En enero de 1610, Galileo Galilei apuntó su pequeño telescopio hacia Júpiter y descubrió cuatro lunas que "
    "giraban a su alrededor.",
    "Hoy las llamamos Ío, Europa, Ganímedes y Calisto.",
    "Bajo el hielo de Europa podría esconderse un océano de agua líquida, más profundo que cualquier mar de la Tierra.",
    "La sonda Juno, lanzada por la NASA, sigue dando vueltas a su alrededor, enviándonos imágenes que nadie había "
    "visto antes.",
    "Respira despacio. Aquí, a casi ochocientos millones de kilómetros del Sol, el tiempo parece avanzar más lento.",
]

# ---------------------------------------------------------------- worker (runs inside each engine's venv)
WORKER = r'''
import json, os, sys, time, traceback, pathlib
import numpy as np
import soundfile as sf

cfg = json.load(open(sys.argv[1]))
OUT = pathlib.Path(cfg["out"])
engine = cfg["engine"]
res = {"engine": engine, "variants": {}, "errors": []}

def log(msg):
    print(f"[{engine}] {msg}", flush=True)

def to_np(w):
    try:
        import torch
        if isinstance(w, torch.Tensor):
            w = w.detach().float().cpu().numpy()
    except Exception:
        pass
    w = np.asarray(w, dtype=np.float32).squeeze()
    return w

def finish(variant, chunks, sr, gen_seconds, extra=None):
    pause = np.zeros(int(sr * 0.8), dtype=np.float32)
    parts = []
    for c in chunks:
        c = to_np(c)
        peak = float(np.max(np.abs(c))) if c.size else 0
        if peak > 0:
            c = c / peak * 0.89
        parts += [c, pause]
    audio = np.concatenate(parts) if parts else np.zeros(1, np.float32)
    d = OUT / variant
    d.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(chunks):
        sf.write(d / f"s{i:02d}.wav", to_np(c), sr)
    sf.write(OUT / f"{variant}.wav", audio, sr)
    secs = sum(len(to_np(c)) for c in chunks) / sr
    res["variants"][variant] = {"sr": sr, "speech_seconds": round(secs, 1), "gen_seconds": round(gen_seconds, 1),
                                "rtf": round(gen_seconds / max(secs, 0.1), 3), **(extra or {})}
    json.dump(res, open(OUT / f"res_{engine}.json", "w"), indent=1)
    log(f"{variant}: {secs:.0f} s of speech in {gen_seconds:.0f} s (RTF {gen_seconds / max(secs, .1):.2f})")

def run_variant(variant, fn, sentences, sr):
    try:
        t = time.time()
        chunks = [fn(s) for s in sentences]
        finish(variant, chunks, sr() if callable(sr) else sr, time.time() - t)
    except Exception:
        err = traceback.format_exc()[-1500:]
        res["errors"].append(f"{variant}: {err}")
        log(f"{variant} FAILED: {err[-600:]}")
        json.dump(res, open(OUT / f"res_{engine}.json", "w"), indent=1)

S, REF_TEXT, DESIGN = cfg["sentences"], cfg["ref_text"], cfg["design"]

try:
    import torch
    res["torch"] = torch.__version__
    res["cuda"] = torch.cuda.is_available()
    log(f"torch {torch.__version__} cuda={torch.cuda.is_available()}")

    if engine == "kokoro":
        from kokoro import KPipeline
        pipe = KPipeline(lang_code="e")
        for variant, voice in (("kokoro_dora", "ef_dora"), ("kokoro_alex", "em_alex")):
            def fn(s, voice=voice):
                return np.concatenate([to_np(a) for _, _, a in pipe(s, voice=voice, speed=0.8)])
            run_variant(variant, fn, S, 24000)

    elif engine == "voxcpm":
        from voxcpm import VoxCPM
        model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
        sr = model.tts_model.sample_rate
        log(f"loaded, sr={sr}")
        for g in ("f", "m"):
            ref = OUT / f"ref_voxcpm_{g}.wav"
            try:
                best = None
                for seed in range(3):   # design a few takes, keep the one closest to the target length
                    torch.manual_seed(seed)
                    w = to_np(model.generate(text=f"({DESIGN[g]}){REF_TEXT}", cfg_value=2.0, inference_timesteps=10))
                    if best is None or abs(len(w) / sr - 11) < abs(len(best) / sr - 11):
                        best = w
                sf.write(ref, best, sr)
            except Exception:
                res["errors"].append(f"voxcpm design {g}: {traceback.format_exc()[-1200:]}")
                continue
            def fn(s, ref=ref):
                for kw in ({"prompt_wav_path": str(ref), "prompt_text": REF_TEXT, "reference_wav_path": str(ref)},
                           {"prompt_wav_path": str(ref), "prompt_text": REF_TEXT},
                           {"reference_wav_path": str(ref)}):
                    try:
                        return model.generate(text=s, cfg_value=2.0, inference_timesteps=10, **kw)
                    except TypeError:
                        continue
                raise RuntimeError("no clone signature worked")
            run_variant(f"voxcpm2_{g}", fn, S, sr)

    elif engine == "qwen":
        from qwen_tts import Qwen3TTSModel
        dtype = torch.float16
        kw = dict(device_map="cuda:0", dtype=dtype, attn_implementation="sdpa")
        design = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign", **kw)
        log(f"design model loaded; languages={getattr(design, 'get_supported_languages', lambda: '?')()}")
        refs = {}
        for g in ("f", "m"):
            try:
                wavs, sr = design.generate_voice_design(text=REF_TEXT, language="Spanish", instruct=DESIGN[g])
                w = to_np(wavs[0])
                if not np.isfinite(w).all() or np.max(np.abs(w)) < 1e-3:
                    raise RuntimeError("fp16 produced NaN/silence")
                refs[g] = OUT / f"ref_qwen_{g}.wav"
                sf.write(refs[g], w, sr)
            except Exception:
                res["errors"].append(f"qwen design {g}: {traceback.format_exc()[-1200:]}")
        del design
        torch.cuda.empty_cache()
        base = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", **kw)
        log("base model loaded")
        clone_sr = {}
        for g, ref in refs.items():
            def fn(s, ref=ref):
                wavs, sr = base.generate_voice_clone(text=s, language="Spanish", ref_audio=str(ref), ref_text=REF_TEXT)
                clone_sr["sr"] = sr
                return wavs[0]
            run_variant(f"qwen3_{g}", fn, S, lambda: clone_sr["sr"])
        # the same engine cloning the VoxCPM refs (same timbre, different engine)
        for g in ("f", "m"):
            ref = OUT / f"ref_voxcpm_{g}.wav"
            if ref.exists():
                def fn(s, ref=ref):
                    wavs, sr = base.generate_voice_clone(text=s, language="Spanish", ref_audio=str(ref), ref_text=REF_TEXT)
                    clone_sr["sr"] = sr
                    return wavs[0]
                run_variant(f"qwen3_voxref_{g}", fn, S, lambda: clone_sr["sr"])

    elif engine == "chatterbox":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        try:
            model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
            res["version"] = "v3"
        except TypeError:
            model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
            res["version"] = "v2 (installed package has no v3)"
        log(f"loaded {res['version']}")
        for g in ("f", "m"):
            ref = OUT / f"ref_voxcpm_{g}.wav"
            if not ref.exists():
                ref = OUT / f"ref_qwen_{g}.wav"
            if not ref.exists():
                res["errors"].append(f"chatterbox {g}: no reference clip")
                continue
            def fn(s, ref=ref):
                try:
                    return model.generate(s, language_id="es", audio_prompt_path=str(ref), exaggeration=0.4,
                                          cfg_weight=0.4)
                except TypeError:
                    return model.generate(s, language_id="es", audio_prompt_path=str(ref))
            run_variant(f"chatterbox_{g}", fn, S, model.sr)

    elif engine == "score":
        import re, unicodedata
        from num2words import num2words
        from transformers import pipeline as hf_pipeline
        asr = hf_pipeline("automatic-speech-recognition", model="openai/whisper-large-v3-turbo",
                          torch_dtype=torch.float16, device="cuda:0")
        mos = torch.hub.load("tarepan/SpeechMOS:v1.2.0", "utmos22_strong", trust_repo=True).cuda().eval()
        import librosa

        def norm(t):
            t = t.lower().replace(".", "") if re.search(r"\d\.\d{3}", t) else t.lower()
            t = re.sub(r"\d+", lambda m: " " + num2words(int(m.group()), lang="es") + " ", t)
            t = unicodedata.normalize("NFD", t)
            t = "".join(c for c in t if unicodedata.category(c) != "Mn")
            t = re.sub(r"[^a-zñ ]", " ", t)
            return " ".join(t.split())

        def cer(ref, hyp):
            r, h = norm(ref), norm(hyp)
            d = list(range(len(h) + 1))
            for i in range(1, len(r) + 1):
                prev, d[0] = d[0], i
                for j in range(1, len(h) + 1):
                    cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
                    prev, d[j] = d[j], cur
            return d[len(h)] / max(len(r), 1)

        scores = {}
        for vdir in sorted(p for p in OUT.iterdir() if p.is_dir()):
            rows = []
            for i, s in enumerate(S):
                f = vdir / f"s{i:02d}.wav"
                if not f.exists():
                    continue
                w, sr = sf.read(f, dtype="float32")
                w16 = librosa.resample(w, orig_sr=sr, target_sr=16000) if sr != 16000 else w
                hyp = asr({"raw": w16, "sampling_rate": 16000},
                          generate_kwargs={"language": "spanish", "task": "transcribe"})["text"]
                with torch.no_grad():
                    m = float(mos(torch.from_numpy(w16).unsqueeze(0).cuda(), 16000).item())
                rows.append({"i": i, "cer": round(cer(s, hyp), 4), "mos": round(m, 3), "heard": hyp.strip(),
                             "seconds": round(len(w) / sr, 1)})
            if rows:
                wpm = 60 * sum(len(S[r["i"]].split()) for r in rows) / max(sum(r["seconds"] for r in rows), .1)
                scores[vdir.name] = {"mean_cer": round(sum(r["cer"] for r in rows) / len(rows), 4),
                                     "max_cer": max(r["cer"] for r in rows),
                                     "mean_mos": round(sum(r["mos"] for r in rows) / len(rows), 3),
                                     "words_per_min": round(wpm), "sentences": rows}
                log(f"{vdir.name}: CER {scores[vdir.name]['mean_cer']:.3f}  MOS {scores[vdir.name]['mean_mos']:.2f}")
        json.dump(scores, open(OUT / "scores.json", "w"), indent=1, ensure_ascii=False)
        res["scored"] = list(scores)
except Exception:
    res["errors"].append(traceback.format_exc()[-2000:])
    log(res["errors"][-1][-800:])
json.dump(res, open(OUT / f"res_{engine}.json", "w"), indent=1)
'''

ENGINES = {
    # engine: (python version for uv, packages, apt packages)
    "kokoro": ("3.11", ["kokoro>=0.9.4", "soundfile", "misaki[en]"], ["espeak-ng"]),
    "voxcpm": ("3.11", ["voxcpm", "soundfile"], []),
    "qwen": ("3.12", ["qwen-tts", "soundfile"], ["sox"]),
    "chatterbox": ("3.11", ["chatterbox-tts", "soundfile"], []),
    "score": ("3.11", ["torch", "torchaudio", "transformers>=4.45", "accelerate", "librosa", "num2words", "soundfile"], []),
}


def log(msg):
    line = f"[{(time.time() - T0) / 60:6.1f} min] {msg}"
    print(line, flush=True)
    with open(OUT / "log.txt", "a") as f:
        f.write(line + "\n")


M = {}
LOCK = threading.Lock()


def save():
    with LOCK:
        M["minutes"] = round((time.time() - T0) / 60, 1)
        M["files"] = sorted(p.name for p in OUT.glob("*") if p.is_file())
        (OUT / "manifest.json").write_text(json.dumps(M, indent=1, ensure_ascii=False))


def run_engine(engine, gpu, timeout=60 * 60):
    py, pkgs, apt = ENGINES[engine]
    t = time.time()
    M["engines"][engine] = {"status": "installing", "gpu": gpu}
    save()
    try:
        if apt:
            subprocess.run(["apt-get", "install", "-y", "-qq", *apt], capture_output=True, timeout=600)
        venv = WORK / f"venv_{engine}"
        r = subprocess.run([sys.executable, "-m", "uv", "venv", "-q", "--python", py, str(venv)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"uv venv: {r.stderr[-800:]}")
        pyexe = str(venv / "bin" / "python")
        r = subprocess.run([sys.executable, "-m", "uv", "pip", "install", "-q", "--python", pyexe, *pkgs], capture_output=True, text=True,
                           timeout=1800)
        if r.returncode:
            raise RuntimeError(f"pip: {r.stderr[-1500:]}")
        M["engines"][engine]["install_min"] = round((time.time() - t) / 60, 1)
        M["engines"][engine]["status"] = "running"
        save()
        log(f"{engine}: installed in {(time.time() - t) / 60:.1f} min on GPU {gpu}")
        cfgf = WORK / f"cfg_{engine}.json"
        cfgf.write_text(json.dumps({"engine": engine, "out": str(OUT), "sentences": SENTENCES, "ref_text": REF_TEXT,
                                    "design": DESIGN}, ensure_ascii=False))
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu), "HF_HUB_ENABLE_HF_TRANSFER": "0",
               "PYTHONUNBUFFERED": "1"}
        with open(OUT / f"stdout_{engine}.log", "w") as fo:
            r = subprocess.run([pyexe, str(WORK / "worker.py"), str(cfgf)], stdout=fo, stderr=subprocess.STDOUT,
                               env=env, timeout=timeout)
        res = json.loads((OUT / f"res_{engine}.json").read_text()) if (OUT / f"res_{engine}.json").exists() else {}
        M["engines"][engine].update(status="done" if res.get("variants") or res.get("scored") else "failed",
                                    returncode=r.returncode, minutes=round((time.time() - t) / 60, 1),
                                    variants=res.get("variants", {}), errors=res.get("errors", [])[-3:],
                                    torch=res.get("torch"), cuda=res.get("cuda"), version=res.get("version"))
        if M["engines"][engine]["status"] == "failed":
            tail = (OUT / f"stdout_{engine}.log").read_text(errors="ignore").splitlines()[-40:]
            M["engines"][engine]["stdout_tail"] = "\n".join(tail)[-3000:]
        log(f"{engine}: {M['engines'][engine]['status']} in {(time.time() - t) / 60:.1f} min")
    except Exception:
        M["engines"][engine].update(status="failed", error=traceback.format_exc()[-1500:])
        log(f"{engine} failed: {traceback.format_exc()[-500:]}")
    save()


def lane(engines, gpu):
    for e in engines:
        run_engine(e, gpu)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    job = json.loads(base64.b64decode(JOB_B64))
    M.update({"job_id": job["job_id"], "errors": [], "engines": {}, "sentences": SENTENCES, "ref_text": REF_TEXT,
              "design": DESIGN})
    try:
        (WORK / "worker.py").write_text(WORKER)
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "uv"], capture_output=True)
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=600)
        try:
            import torch
            M["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
        except Exception:
            M["gpus"] = []
        log(f"GPUs {M['gpus']}")
        save()
        a = threading.Thread(target=lane, args=(["voxcpm", "chatterbox"], 0))
        b = threading.Thread(target=lane, args=(["kokoro", "qwen"], 1 if len(M["gpus"]) > 1 else 0))
        a.start()
        time.sleep(5)
        b.start()
        b.join()
        a.join()
        run_engine("score", 1 if len(M["gpus"]) > 1 else 0)
        sc = OUT / "scores.json"
        M["scores"] = {k: {kk: vv for kk, vv in v.items() if kk != "sentences"}
                       for k, v in json.loads(sc.read_text()).items()} if sc.exists() else {}
        # compact listening files
        for w in sorted(OUT.glob("*.wav")):
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(w), "-ac", "1", "-b:a", "96k",
                            str(w.with_suffix(".mp3"))])
    except Exception:
        M["errors"].append(traceback.format_exc()[-2000:])
    save()
    log("done")


if __name__ == "__main__":
    main()
