"""Benchmark of image-to-video models on Kaggle's free T4 (for the "movie mode" decision).

Generates two prehistoric source stills with SDXL, then animates each with every video variant and
records seconds per clip. Output: /kaggle/working/ai/*.mp4 + manifest.json (job_id, timings, errors).
"""
import base64
import json
import os
import pathlib
import subprocess
import sys
import time
import traceback

JOB_B64 = "__JOB_B64__"
OUT = pathlib.Path(os.environ.get("QC_OUT", "/kaggle/working/ai"))
T0 = time.time()
NEG = "worst quality, inconsistent motion, blurry, jittery, distorted, deformed legs, extra limbs, morphing"
SOURCES = [
    ("herd", "a herd of long-necked sauropod dinosaurs walking across a sunlit river floodplain, wide shot, "
             "golden hour, cinematic nature documentary, photorealistic"),
    ("trike", "a triceratops walking through a fern meadow beside a forest, side view, morning mist, "
              "cinematic nature documentary, photorealistic"),
]
MOTION = {"herd": "the dinosaurs walk slowly forward, dust rising, the camera tracks gently",
          "trike": "the triceratops walks slowly to the right, ferns sway, the camera follows"}


def log(msg):
    line = f"[{(time.time() - T0) / 60:6.1f} min] {msg}"
    print(line, flush=True)
    with open(OUT / "log.txt", "a") as f:
        f.write(line + "\n")


def write_mp4(frames, path, fps=24):
    import imageio_ffmpeg
    w, h = frames[0].size
    p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                          "-crf", "18", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.convert("RGB").tobytes())
    p.stdin.close()
    p.wait()


def save(m):
    """Write the manifest after every step: if Kaggle kills the process (out of RAM), what we have survives."""
    try:
        import psutil
        m["ram_used_gb"] = round(psutil.virtual_memory().used / 1e9, 1)
    except Exception:
        pass
    m["images"] = sorted(p.name for p in OUT.glob("*.jpg"))
    m["videos"] = sorted(p.name for p in OUT.glob("*.mp4"))
    m["minutes"] = round((time.time() - T0) / 60, 1)
    (OUT / "manifest.json").write_text(json.dumps(m, indent=1))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    job = json.loads(base64.b64decode(JOB_B64))
    m = {"job_id": job["job_id"], "errors": [], "bench": {}, "gpus": []}
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers>=0.33", "transformers",
                        "accelerate", "imageio-ffmpeg", "sentencepiece", "protobuf", "safetensors"],
                       capture_output=True)
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"], capture_output=True)
        import torch
        from PIL import Image
        m["gpus"] = [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())]
        log(f"GPUs {m['gpus']}")

        # 1) source stills
        from diffusers import AutoencoderKL, StableDiffusionXLPipeline
        vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
        sd = StableDiffusionXLPipeline.from_pretrained("SG161222/RealVisXL_V5.0", vae=vae,
                                                       torch_dtype=torch.float16).to("cuda")
        srcs = {}
        for name, prompt in SOURCES:
            img = sd(prompt=prompt, negative_prompt="text, watermark, cartoon, blurry, deformed",
                     width=1344, height=768, num_inference_steps=30, guidance_scale=5.5,
                     generator=torch.Generator("cpu").manual_seed(7)).images[0]
            img.save(OUT / f"src_{name}.jpg", quality=92)
            srcs[name] = img
        del sd
        torch.cuda.empty_cache()
        log("source stills ready")
        m["stage"] = "stills ready"
        save(m)

        def cover(img, w, h):
            k = max(w / img.width, h / img.height)
            img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
            x, y = (img.width - w) // 2, (img.height - h) // 2
            return img.crop((x, y, x + w, y + h))

        variants = [
            ("base2b_25steps", "base"),
            ("distilled2b_098", "distilled"),
        ]
        for vname, kind in variants:
            m["stage"] = f"loading {vname}"
            save(m)
            try:
                import gc
                gc.collect()
                t_load = time.time()
                if kind == "base":
                    from diffusers import LTXImageToVideoPipeline
                    pipe = LTXImageToVideoPipeline.from_pretrained("Lightricks/LTX-Video", torch_dtype=torch.float16)
                else:
                    from diffusers import LTXConditionPipeline
                    from transformers import T5EncoderModel, T5TokenizerFast
                    te = T5EncoderModel.from_pretrained("Lightricks/LTX-Video", subfolder="text_encoder",
                                                        torch_dtype=torch.float16)
                    tok = T5TokenizerFast.from_pretrained("Lightricks/LTX-Video", subfolder="tokenizer")
                    pipe = LTXConditionPipeline.from_single_file(
                        "https://huggingface.co/Lightricks/LTX-Video/blob/main/ltxv-2b-0.9.8-distilled.safetensors",
                        text_encoder=te, tokenizer=tok, torch_dtype=torch.float16)
                pipe.enable_model_cpu_offload()
                pipe.vae.enable_tiling()
                pipe.set_progress_bar_config(disable=True)
                log(f"{vname}: loaded in {time.time() - t_load:.0f} s")
                times = []
                for name, img in srcs.items():
                    t = time.time()
                    im = cover(img, 960, 544)
                    prompt = f"{dict(SOURCES)[name]}. {MOTION[name]}"
                    if kind == "base":
                        frames = pipe(image=im, prompt=prompt, negative_prompt=NEG, width=960, height=544,
                                      num_frames=97, num_inference_steps=25, guidance_scale=3.0,
                                      generator=torch.Generator("cpu").manual_seed(3)).frames[0]
                    else:
                        frames = pipe(image=im, frame_index=0, strength=1.0, prompt=prompt, negative_prompt=NEG,
                                      width=960, height=544, num_frames=97,
                                      timesteps=[1000, 993, 987, 981, 975, 909, 725, 0.03],
                                      guidance_scale=1.0, guidance_rescale=0.7, image_cond_noise_scale=0.0,
                                      decode_timestep=0.05, decode_noise_scale=0.025,
                                      generator=torch.Generator("cpu").manual_seed(3)).frames[0]
                    write_mp4(frames, OUT / f"{vname}_{name}.mp4")
                    times.append(round(time.time() - t, 1))
                    m["bench"][vname] = {"seconds_per_clip": times, "frames": 97, "partial": True}
                    m["stage"] = f"{vname}: {len(times)} clips"
                    save(m)
                    log(f"{vname} {name}: {times[-1]} s")
                m["bench"][vname] = {"seconds_per_clip": times, "frames": 97}
                pipe.remove_all_hooks() if hasattr(pipe, "remove_all_hooks") else None
                del pipe
                if kind != "base":
                    del te
                gc.collect()
                torch.cuda.empty_cache()
            except Exception:
                err = traceback.format_exc()[-1500:]
                m["errors"].append(f"{vname}: {err}")
                log(f"{vname} failed: {err[-400:]}")
    except Exception:
        m["errors"].append(traceback.format_exc()[-2000:])
    m["images"] = sorted(p.name for p in OUT.glob("*.jpg"))
    m["videos"] = sorted(p.name for p in OUT.glob("*.mp4"))
    m["minutes"] = round((time.time() - T0) / 60, 1)
    (OUT / "manifest.json").write_text(json.dumps(m, indent=1))
    log("done")


if __name__ == "__main__":
    main()
