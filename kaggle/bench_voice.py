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

# ---------------------------------------------------------------- emotion bench ("voz dirigida")
# One short chapter with a dramatic arc: calm -> mystery -> tension -> revelation (peak) -> wonder -> calm.
# Each line: text, Step-Audio-EditX edit (type, info) or None, pause after (s), gain (dB).
# The flat narration is the production voice (Qwen3 clone of assets/voices/estrato_narrador.mp3); the edit
# model re-performs each tagged line with that emotion while keeping the timbre.
EMO_SCRIPT = [
    ("Imagina que flotas en silencio, muy lejos de casa, y frente a ti aparece un pequeño punto de luz.",
     None, 1.0, 0),
    ("Al principio parece una estrella más.", None, 0.7, 0),
    ("Pero no lo es.", ("style", "serious"), 1.1, 0),
    ("Es Europa, una luna de Júpiter cubierta por una corteza de hielo blanco, cruzada por grietas color óxido.",
     ("emotion", "admiration"), 0.9, 0.5),
    ("Durante siglos, nadie imaginó lo que escondía.", ("style", "murmur"), 1.2, -2),
    ("En 1979, las sondas Voyager pasaron cerca y tomaron fotografías que desconcertaron a los científicos.",
     ("style", "story"), 0.8, 0),
    ("Aquel hielo era demasiado liso. No tenía cráteres, como si algo lo renovara desde abajo.",
     ("emotion", "surprised"), 1.0, 0.5),
    ("Años después, la sonda Galileo midió algo extraño: el campo magnético de Júpiter se torcía al pasar por Europa.",
     ("style", "vivid"), 0.9, 1),
    ("Y solo había una explicación posible.", ("style", "whisper"), 1.6, -3),
    ("Bajo el hielo hay un océano. Un océano de agua salada, más profundo que cualquier mar de la Tierra.",
     ("emotion", "excited"), 1.2, 2),
    ("Contiene más del doble de agua que todos los océanos de nuestro planeta juntos.",
     ("emotion", "admiration"), 1.1, 1),
    ("Allí abajo, en la oscuridad total, quizá exista vida.", ("style", "soulful"), 1.5, -1),
    ("Nadie lo sabe todavía.", ("style", "gentle"), 1.2, -2),
    ("Respira despacio. La luz de Europa sigue ahí, esperando.", ("style", "comfort"), 1.5, -2),
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
EMO = cfg.get("emo") or []          # [[edit_type, edit_info] | None, pause_s, gain_db] per sentence

def resample(w, sr, to=24000):
    w = to_np(w)
    if sr == to:
        return w
    import librosa
    return librosa.resample(w, orig_sr=sr, target_sr=to).astype(np.float32)

def assemble(variant, chunks, sr, directed=True):
    """Join sentences like the episode does: each line levelled to the same loudness, then the director's
    gain and pause for that line (uniform 0.8 s pauses and no gain for the flat take)."""
    parts = []
    for i, c in enumerate(chunks):
        c = to_np(c)
        rms = float(np.sqrt(np.mean(c ** 2))) if c.size else 0
        gain = EMO[i][2] if directed and i < len(EMO) else 0
        pause = EMO[i][1] if directed and i < len(EMO) else 0.8
        if rms > 0:
            c = c * (10 ** ((-20 + gain) / 20) / rms)
        parts += [np.clip(c, -0.98, 0.98), np.zeros(int(sr * pause), np.float32)]
    sf.write(OUT / f"{variant}.wav", np.concatenate(parts), sr)

def save_emo(variant, chunks, sr, gen_seconds, directed=True, extra=None):
    d = OUT / variant
    d.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(chunks):
        sf.write(d / f"s{i:02d}.wav", to_np(c), sr)
    assemble(variant, chunks, sr, directed)
    secs = sum(len(to_np(c)) for c in chunks) / sr
    res["variants"][variant] = {"sr": sr, "speech_seconds": round(secs, 1), "gen_seconds": round(gen_seconds, 1),
                                **(extra or {})}
    json.dump(res, open(OUT / f"res_{engine}.json", "w"), indent=1)
    log(f"{variant}: {secs:.0f} s of speech in {gen_seconds:.0f} s")

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
        for g in DESIGN:
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
        if cfg.get("design_only"):
            refs = {}
        # the same engine cloning the VoxCPM refs (same timbre, different engine)
        for g in ("f", "m"):
            ref = OUT / f"ref_voxcpm_{g}.wav"
            if ref.exists():
                def fn(s, ref=ref):
                    wavs, sr = base.generate_voice_clone(text=s, language="Spanish", ref_audio=str(ref), ref_text=REF_TEXT)
                    clone_sr["sr"] = sr
                    return wavs[0]
                run_variant(f"qwen3_voxref_{g}", fn, S, lambda: clone_sr["sr"])

    elif engine == "qwenref":
        # the production narrator exactly as episodes use it: Qwen3 1.7B Base cloning the channel's reference clip
        from qwen_tts import Qwen3TTSModel
        base = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0",
                                             dtype=torch.float16, attn_implementation="sdpa")
        ref = OUT / "ref_narrador.wav"
        t, chunks, srs = time.time(), [], []
        for s in S:
            wavs, sr = base.generate_voice_clone(text=s, language="Spanish", ref_audio=str(ref),
                                                 ref_text=cfg["narrator_ref_text"])
            chunks.append(resample(wavs[0], sr))
        save_emo("emo_plana", chunks, 24000, time.time() - t, directed=False)

    elif engine == "qwenbank":
        from qwen_tts import Qwen3TTSModel
        base = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-1.7B-Base", device_map="cuda:0",
                                             dtype=torch.float16, attn_implementation="sdpa")
        t, chunks, used = time.time(), [], []
        for i, s in enumerate(S):
            tag = EMO[i][0] if i < len(EMO) else None
            ref = OUT / f"bank_{tag[1]}.wav" if tag else None
            if not ref or not ref.exists():
                ref = OUT / "ref_narrador.wav"
            wavs, sr = base.generate_voice_clone(text=s, language="Spanish", ref_audio=str(ref),
                                                 ref_text=cfg["narrator_ref_text"])
            chunks.append(resample(wavs[0], sr))
            used.append(ref.stem)
        save_emo("emo_banco", chunks, 24000, time.time() - t, extra={"lines": used})

    elif engine == "stepedit":
        # Step-Audio-EditX (Apache-2.0) re-performs each tagged line of the flat take with an emotion/style
        sys.path.insert(0, cfg["stepx_dir"])
        os.chdir(cfg["stepx_dir"])
        from types import SimpleNamespace
        from tokenizer import StepAudioTokenizer
        import tts as stepx_tts
        mdir = cfg["models_dir"]
        import torchaudio

        def _load(path, *a, **k):          # soundfile instead of torchcodec (gave empty audio for some files)
            w, sr = sf.read(str(path), dtype="float32", always_2d=True)
            return torch.from_numpy(np.ascontiguousarray(w.T)), sr
        torchaudio.load = _load
        stepx_tts.torchaudio.load = _load
        tok = StepAudioTokenizer(f"{mdir}/Step-Audio-Tokenizer", model_source="local")
        log("audio tokenizer loaded")
        kw = dict(model_source="local", dtype="float16", gpu_memory_utilization=0.55, max_model_len=4096,
                  enforce_eager=True, cosyvoice_dtype="float32", cosyvoice_cuda_graph=False)

        class HFShim:
            """transformers fallback for the 3B LLM if vLLM won't run on this GPU (slower: no KV cache)."""
            def __init__(self, path):
                from src.model.step1_causal_lm import Step1ForCausalLM
                self.m = Step1ForCausalLM.from_pretrained(path, torch_dtype=torch.float16).cuda().eval()

            @torch.no_grad()
            def generate(self, prompts, sp, use_tqdm=False):
                ids = torch.tensor([prompts[0]["prompt_token_ids"]], device="cuda")
                out = []
                for _ in range(min(sp.max_tokens, 1600)):
                    logits = self.m(input_ids=ids).logits[0, -1].float()
                    nxt = torch.multinomial(torch.softmax(logits / max(sp.temperature, 1e-3), -1), 1)
                    out.append(int(nxt))
                    if out[-1] == 3:
                        break
                    ids = torch.cat([ids, nxt.view(1, 1)], 1)
                return [SimpleNamespace(outputs=[SimpleNamespace(token_ids=out)])]

        model = None
        for backend in ("TRITON_ATTN", "FLEX_ATTENTION"):    # FlashInfer has no ALiBi-sqrt; FA2 needs sm80
            os.environ["VLLM_ATTENTION_BACKEND"] = backend
            try:
                model = stepx_tts.StepAudioTTS(f"{mdir}/Step-Audio-EditX", tok, **kw)
                res["backend"] = f"vllm/{backend}"
                break
            except Exception:
                res["errors"].append(f"vllm {backend}: " + traceback.format_exc()[-1200:])
                log(f"vLLM with {backend} failed")
                import gc
                gc.collect()
                torch.cuda.empty_cache()
        if model is None:
            log("vLLM failed, falling back to transformers")
            torch.cuda.empty_cache()
            from transformers import AutoTokenizer
            def hf_load(model_path, **_):
                return HFShim(model_path), AutoTokenizer.from_pretrained(model_path, trust_remote_code=True), model_path
            stepx_tts.model_loader.load_model = hf_load
            model = stepx_tts.StepAudioTTS(f"{mdir}/Step-Audio-EditX", tok, **kw)
            res["backend"] = "transformers"
        log(f"Step-Audio-EditX loaded ({res['backend']})")
        # emotion bank: the channel's reference clip re-performed in each emotion; Qwen then clones every line
        # from the matching clip (the emotion rides on the reference, the timbre stays Qwen's clone)
        for tag in {tuple(e[0]) for e in EMO if e[0]}:
            try:
                ts = time.time()
                audio, osr = model.edit(prompt_wav_path=str(OUT / "ref_narrador.wav"),
                                        prompt_text=cfg["narrator_ref_text"], edit_type=tag[0], edit_info=tag[1])
                sf.write(OUT / f"bank_{tag[1]}.wav", resample(audio, osr), 24000)
                log(f"bank {tag[1]}: {time.time() - ts:.0f}s")
            except Exception:
                res["errors"].append(f"bank {tag[1]}: {traceback.format_exc()[-2500:]}")
                log(f"bank {tag[1]} failed: {traceback.format_exc()[-1500:]}")
        flat = OUT / "emo_plana"
        for variant, src_dir in (("emo_dirigida", flat), ("emo_fuerte", OUT / "emo_dirigida")):
            t, chunks, per = time.time(), [], []
            for i, s in enumerate(S):
                src = src_dir / f"s{i:02d}.wav"
                tag = EMO[i][0] if i < len(EMO) else None
                w, sr = sf.read(src, dtype="float32")
                if not tag:
                    chunks.append(resample(w, sr))
                    per.append("plana")
                    continue
                try:
                    ts = time.time()
                    audio, osr = model.edit(prompt_wav_path=str(src), prompt_text=s, edit_type=tag[0], edit_info=tag[1])
                    chunks.append(resample(audio, osr))
                    per.append(f"{tag[1]} {time.time() - ts:.0f}s")
                except Exception:
                    res["errors"].append(f"{variant} s{i}: {traceback.format_exc()[-2500:]}")
                    log(f"{variant} s{i} failed: {traceback.format_exc()[-1500:]}")
                    chunks.append(resample(w, sr))
                    per.append("error->sin cambio")
            save_emo(variant, chunks, 24000, time.time() - t, extra={"lines": per, "backend": res["backend"]})

    elif engine == "chatterbox":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
        try:
            model = ChatterboxMultilingualTTS.from_pretrained(device="cuda", t3_model="v3")
            res["version"] = "v3"
        except TypeError:
            model = ChatterboxMultilingualTTS.from_pretrained(device="cuda")
            res["version"] = "v2 (installed package has no v3)"
        log(f"loaded {res['version']}")
        for name in ("voxcpm_f", "voxcpm_m", "qwen_f", "qwen_m"):
            ref = OUT / f"ref_{name}.wav"
            if not ref.exists():
                continue
            def fn(s, ref=ref):
                try:
                    return model.generate(s, language_id="es", audio_prompt_path=str(ref), exaggeration=0.4,
                                          cfg_weight=0.4)
                except TypeError:
                    return model.generate(s, language_id="es", audio_prompt_path=str(ref))
            run_variant(f"chatterbox_{name.split('_')[0]}ref_{name[-1]}", fn, S, model.sr)

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

        # speaker similarity to the channel narrator (emotion bench: an edit must not turn him into someone else)
        spk, ref_emb = None, None
        ref_wav = OUT / "ref_narrador.wav"
        if EMO and ref_wav.exists():
            try:
                from speechbrain.inference.speaker import EncoderClassifier
                spk = EncoderClassifier.from_hparams("speechbrain/spkrec-ecapa-voxceleb", run_opts={"device": "cuda"},
                                                     savedir=str(OUT.parent / "ecapa"))
                rw, rsr = sf.read(ref_wav, dtype="float32")
                rw = librosa.resample(rw if rw.ndim == 1 else rw.mean(1), orig_sr=rsr, target_sr=16000)
                ref_emb = spk.encode_batch(torch.from_numpy(rw).unsqueeze(0)).squeeze().float()
            except Exception:
                res["errors"].append("speaker sim: " + traceback.format_exc()[-800:])
                spk = None

        def sentence_f0(w16):
            f0, vflag, _ = librosa.pyin(w16, fmin=55, fmax=320, sr=16000, frame_length=1024)
            f0 = f0[vflag & np.isfinite(f0)]
            return f0

        def score_rows(vdir):
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
                row = {"i": i, "cer": round(cer(s, hyp), 4), "mos": round(m, 3), "heard": hyp.strip(),
                       "seconds": round(len(w) / sr, 1)}
                if EMO:
                    f0 = sentence_f0(w16)
                    if f0.size:
                        row["f0_hz"] = round(float(np.median(f0)), 1)
                        st = 12 * np.log2(f0 / np.median(f0))
                        row["range_st"] = round(float(np.percentile(st, 95) - np.percentile(st, 5)), 1)
                    row["db"] = round(float(20 * np.log10(np.sqrt(np.mean(w16 ** 2)) + 1e-9)), 1)
                    if spk is not None:
                        with torch.no_grad():
                            e = spk.encode_batch(torch.from_numpy(w16).unsqueeze(0)).squeeze().float()
                        row["sim"] = round(float(torch.nn.functional.cosine_similarity(e, ref_emb, dim=0)), 3)
                rows.append(row)
            return rows

        scores = {}
        dirs = sorted(p for p in OUT.iterdir() if p.is_dir() and (p / "s00.wav").exists())
        all_rows = {vdir.name: score_rows(vdir) for vdir in dirs}
        if EMO and "emo_plana" in all_rows:
            # "voz dirigida segura": per line, the strongest take that is still as clear, as natural and as much
            # the same narrator as the flat take; otherwise the flat line (an episode can never get worse)
            base = {r["i"]: r for r in all_rows["emo_plana"]}
            pick, chunks = [], []
            for i in range(len(S)):
                choice = "emo_plana"
                for cand in ("emo_banco", "emo_fuerte", "emo_dirigida"):
                    r = next((x for x in all_rows.get(cand, []) if x["i"] == i), None)
                    b = base.get(i)
                    if not r or not b or EMO[i][0] is None:
                        continue
                    ok = (r["cer"] <= b["cer"] + 0.03 and r["mos"] >= b["mos"] - 0.35
                          and r.get("sim", 1) >= b.get("sim", 1) - 0.08)
                    if ok:
                        choice = cand
                        break
                pick.append(choice)
                w, sr = sf.read(OUT / choice / f"s{i:02d}.wav", dtype="float32")
                chunks.append(librosa.resample(w, orig_sr=sr, target_sr=24000) if sr != 24000 else w)
            d = OUT / "emo_segura"
            d.mkdir(exist_ok=True)
            for i, c in enumerate(chunks):
                sf.write(d / f"s{i:02d}.wav", c, 24000)
            assemble("emo_segura", chunks, 24000, directed=True)
            all_rows["emo_segura"] = score_rows(d)
            res["segura_pick"] = pick
        for name, rows in all_rows.items():
            vdir = OUT / name
            if rows:
                wpm = 60 * sum(len(S[r["i"]].split()) for r in rows) / max(sum(r["seconds"] for r in rows), .1)
                pitch = {}
                try:
                    full, fsr = sf.read(OUT / f"{vdir.name}.wav", dtype="float32")
                    full = librosa.resample(full, orig_sr=fsr, target_sr=16000)[:16000 * 60]
                    f0, vflag, _ = librosa.pyin(full, fmin=55, fmax=320, sr=16000, frame_length=1024)
                    f0 = f0[vflag & np.isfinite(f0)]
                    st = 12 * np.log2(f0 / np.median(f0))
                    pitch = {"f0_median_hz": round(float(np.median(f0))),
                             "pitch_var_st": round(float(np.std(st)), 2),
                             "pitch_range_st": round(float(np.percentile(st, 95) - np.percentile(st, 5)), 1)}
                except Exception as e:
                    pitch = {"pitch_error": str(e)[:200]}
                if EMO:
                    # the "rectangle": how much the voice moves BETWEEN lines (pitch level and loudness), not
                    # only inside each line
                    f0s = [r["f0_hz"] for r in rows if r.get("f0_hz")]
                    if len(f0s) > 2:
                        lv = 12 * np.log2(np.array(f0s) / np.median(f0s))
                        pitch["between_lines_st"] = round(float(np.std(lv)), 2)
                        pitch["between_lines_span_st"] = round(float(lv.max() - lv.min()), 1)
                    pitch["within_line_range_st"] = round(float(np.mean([r.get("range_st", 0) for r in rows])), 1)
                    pitch["loudness_span_db"] = round(max(r["db"] for r in rows) - min(r["db"] for r in rows), 1)
                    if any("sim" in r for r in rows):
                        pitch["mean_sim"] = round(float(np.mean([r["sim"] for r in rows if "sim" in r])), 3)
                        pitch["min_sim"] = min(r["sim"] for r in rows if "sim" in r)
                scores[vdir.name] = {**pitch, "mean_cer": round(sum(r["cer"] for r in rows) / len(rows), 4),
                                     "max_cer": max(r["cer"] for r in rows),
                                     "mean_mos": round(sum(r["mos"] for r in rows) / len(rows), 3),
                                     "words_per_min": round(wpm), "sentences": rows}
                log(f"{vdir.name}: CER {scores[vdir.name]['mean_cer']:.3f}  MOS {scores[vdir.name]['mean_mos']:.2f}")
        if res.get("segura_pick") and "emo_segura" in scores:
            scores["emo_segura"]["pick"] = res["segura_pick"]
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
    "chatterbox": ("3.11", ["chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git", "setuptools<81",
                            "soundfile"], []),
    "score": ("3.11", ["torch", "torchaudio", "transformers>=4.45", "accelerate", "librosa", "num2words", "soundfile",
                       "speechbrain"], []),
    # emotion bench
    "qwenref": ("3.12", ["qwen-tts", "soundfile", "librosa"], ["sox"]),
    "qwenbank": ("3.12", ["qwen-tts", "soundfile", "librosa"], ["sox"]),
    "stepedit": ("3.12", [], ["sox", "git-lfs"]),     # installed from its own repo + uv.lock (see install_stepedit)
}
STEPX_REPO = "https://github.com/stepfun-ai/Step-Audio-EditX.git"


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
        if engine == "stepedit":
            pyexe = install_stepedit()
        else:
            venv = WORK / f"venv_{engine}"
            r = subprocess.run([sys.executable, "-m", "uv", "venv", "-q", "--python", py, str(venv)], capture_output=True,
                               text=True)
            if r.returncode:
                raise RuntimeError(f"uv venv: {r.stderr[-800:]}")
            pyexe = str(venv / "bin" / "python")
            r = subprocess.run([sys.executable, "-m", "uv", "pip", "install", "-q", "--python", pyexe, *pkgs],
                               capture_output=True, text=True, timeout=1800)
            if r.returncode:
                raise RuntimeError(f"pip: {r.stderr[-1500:]}")
        M["engines"][engine]["install_min"] = round((time.time() - t) / 60, 1)
        M["engines"][engine]["status"] = "running"
        save()
        log(f"{engine}: installed in {(time.time() - t) / 60:.1f} min on GPU {gpu}")
        cfgf = WORK / f"cfg_{engine}.json"
        cfgf.write_text(json.dumps({"engine": engine, "out": str(OUT), "sentences": M["sentences"], "ref_text": REF_TEXT,
                                    "design": M["design"], "design_only": M.get("design_only", False),
                                    "emo": M.get("emo"), "narrator_ref_text": M.get("narrator_ref_text"),
                                    "stepx_dir": str(WORK / "stepx"), "models_dir": str(WORK / "stepx_models")},
                                   ensure_ascii=False))
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": str(gpu), "HF_HUB_ENABLE_HF_TRANSFER": "0",
               "PYTHONUNBUFFERED": "1",
               # keep vLLM's engine in this process (a spawned engine would re-run the worker script)
               "VLLM_ENABLE_V1_MULTIPROCESSING": "0", "TOKENIZERS_PARALLELISM": "false"}
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


def install_stepedit():
    """Step-Audio-EditX pins its own stack (torch 2.9, vLLM nightly): install it from its uv.lock in its own venv,
    then download the edit model and the audio tokenizer."""
    repo = WORK / "stepx"
    if not (repo / "tts.py").exists():
        r = subprocess.run(["git", "clone", "--depth", "1", STEPX_REPO, str(repo)], capture_output=True, text=True,
                           timeout=600)
        if r.returncode:
            raise RuntimeError(f"git clone: {r.stderr[-800:]}")
    skip = []
    for pkg in ("deepspeed", "wandb", "llmcompressor", "gradio", "spaces"):
        skip += ["--no-install-package", pkg]
    r = subprocess.run([sys.executable, "-m", "uv", "sync", "--frozen", "--python", "3.12", *skip], cwd=repo,
                       capture_output=True, text=True, timeout=2700)
    if r.returncode:
        log(f"stepedit: uv sync --frozen failed, retrying without --frozen: {r.stderr[-600:]}")
        r = subprocess.run([sys.executable, "-m", "uv", "sync", "--python", "3.12", *skip], cwd=repo,
                           capture_output=True, text=True, timeout=2700)
        if r.returncode:
            raise RuntimeError(f"uv sync: {r.stderr[-1500:]}")
    pyexe = str(repo / ".venv" / "bin" / "python")
    models = WORK / "stepx_models"
    dl = ("from huggingface_hub import snapshot_download as d\n"
          f"d('stepfun-ai/Step-Audio-EditX', local_dir='{models}/Step-Audio-EditX')\n"
          f"d('stepfun-ai/Step-Audio-Tokenizer', local_dir='{models}/Step-Audio-Tokenizer')\n")
    r = subprocess.run([pyexe, "-c", dl], capture_output=True, text=True, timeout=2400,
                       env={**os.environ, "HF_HUB_ENABLE_HF_TRANSFER": "0"})
    if r.returncode:
        raise RuntimeError(f"model download: {r.stderr[-1200:]}")
    return pyexe


def lane(engines, gpu):
    for e in engines:
        run_engine(e, gpu)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    job = json.loads(base64.b64decode(JOB_B64))
    M.update({"job_id": job["job_id"], "errors": [], "engines": {}, "sentences": SENTENCES, "ref_text": REF_TEXT,
              "design": job.get("design") or DESIGN, "design_only": bool(job.get("design"))})
    if job.get("emotion"):
        M.update({"sentences": [t for t, *_ in EMO_SCRIPT],
                  "emo": [[list(tag) if tag else None, pause, gain] for _, tag, pause, gain in EMO_SCRIPT],
                  "narrator_ref_text": job["narrator_ref_text"], "emotion": True})
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
        # reference clips from an earlier bench (lets a partial rerun clone the same designed voices)
        for name, b64 in job.get("refs", {}).items():
            mp3 = OUT / f"ref_{name}.mp3"
            mp3.write_bytes(base64.b64decode(b64))
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), str(mp3.with_suffix(".wav"))])
        if job.get("emotion"):
            # emotion bench: flat production voice -> directed re-performance -> scoring
            two = len(M["gpus"]) > 1
            run_engine("qwenref", 1 if two else 0, timeout=40 * 60)
            run_engine("stepedit", 0, timeout=150 * 60)
            run_engine("qwenbank", 1 if two else 0, timeout=40 * 60)
            run_engine("score", 1 if two else 0)
            want = []
        else:
            want = job.get("engines") or list(ENGINES)
        a = threading.Thread(target=lane, args=([e for e in ("voxcpm", "chatterbox") if e in want], 0))
        b = threading.Thread(target=lane, args=([e for e in ("kokoro", "qwen") if e in want],
                                                1 if len(M["gpus"]) > 1 else 0))
        if want:
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
