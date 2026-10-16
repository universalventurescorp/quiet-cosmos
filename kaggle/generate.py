"""Quiet Cosmos v3 — GPU worker that runs on Kaggle's free GPUs (T4 x2).

pipeline/gpu.py writes a copy of this file with the episode's job inlined (JOB_B64), pushes it as a
private Kaggle script and downloads /kaggle/working/ai when it finishes.

  GPU 0  still images: SDXL (RealVisXL by default) or FLUX.1-schnell, then Real-ESRGAN x2
  GPU 1  short video clips: LTX-Video image-to-video from the matching still, Real-ESRGAN x2 per frame
         (with a single GPU, videos run after the images)

Everything is best-effort under a time budget: whatever is finished is returned, and the episode
falls back to real NASA imagery for anything missing. The script always exits 0 and explains
problems in ai/manifest.json, so the orchestrator can read them.
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
T0 = time.time()
ESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_VAE = "madebyollin/sdxl-vae-fp16-fix"
PIP = ["diffusers>=0.32", "transformers>=4.46", "accelerate>=1.0", "spandrel", "imageio-ffmpeg",
       "sentencepiece", "protobuf", "safetensors"]
VIDEO_NEGATIVE = ("worst quality, inconsistent motion, blurry, jittery, distorted, fast motion, "
                  "camera shake, text, watermark")
_lock = threading.Lock()
# from_pretrained patches torch globally (meta-device init): two threads loading at once corrupt each
# other's weights, so model loading is serialized; generation itself runs in parallel
_load_lock = threading.Lock()


def load_job():
    return json.loads(base64.b64decode(JOB_B64).decode("utf-8"))


def log(role, msg):
    line = f"[{(time.time() - T0) / 60:6.1f} min] {role}: {msg}"
    print(line, flush=True)
    with _lock, open(OUT / "log.txt", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save_status(role, st):
    (OUT / f"status_{role}.json").write_text(json.dumps(st, indent=1))


def deadline(job):
    return T0 + job["budget_minutes"] * 60


def valid(img):
    """Reject NaN/black/flat outputs (fp16 overflow shows up as black or uniform frames)."""
    import numpy as np
    a = np.asarray(img.convert("L"), np.float32)
    return bool(np.isfinite(a).all() and a.std() > 4 and a.mean() > 2)


def cover(img, w, h):
    from PIL import Image
    k = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * k), round(img.height * k)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


# ---------------------------------------------------------------- upscaler
class Upscaler:
    def __init__(self, device, role):
        import torch
        from spandrel import ModelLoader
        path = pathlib.Path("/tmp/RealESRGAN_x2plus.pth")
        with _lock:
            if not path.exists():
                import urllib.request
                urllib.request.urlretrieve(ESRGAN_URL, path)
        self.m = ModelLoader().load_from_file(str(path)).eval().to(device)
        self.dtype = torch.float16 if self.m.supports_half else torch.float32
        if self.dtype == torch.float16:
            self.m.half()
        self.device, self.role = device, role

    def __call__(self, img):
        import numpy as np
        import torch
        from PIL import Image
        try:
            t = torch.from_numpy(np.asarray(img.convert("RGB"))).permute(2, 0, 1)[None]
            t = t.to(self.device, self.dtype) / 255.0
            with torch.inference_mode():
                y = self.m(t).clamp(0, 1)
            arr = (y[0].permute(1, 2, 0).float().cpu().numpy() * 255 + 0.5).astype("uint8")
            out = Image.fromarray(arr)
            return out if valid(out) else img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            return img.resize((img.width * 2, img.height * 2), Image.LANCZOS)


def try_upscaler(device, role):
    try:
        return Upscaler(device, role)
    except Exception as exc:                                    # noqa: BLE001
        log(role, f"upscaler unavailable, using Lanczos: {exc}")
        return None


# ---------------------------------------------------------------- images
def load_image_pipe(job, device, gpu, role):
    import torch
    model = job["image_model"]
    major = torch.cuda.get_device_capability(gpu)[0]
    if "flux" in model.lower():
        try:
            from diffusers import FluxPipeline
            repo = model if "/" in model else "black-forest-labs/FLUX.1-schnell"
            dtype = torch.bfloat16 if major >= 8 else torch.float16
            pipe = FluxPipeline.from_pretrained(repo, torch_dtype=dtype)
            pipe.enable_model_cpu_offload(gpu_id=gpu)
            pipe.set_progress_bar_config(disable=True)
            test = pipe("a spiral galaxy, deep space photograph", width=512, height=512,
                        num_inference_steps=4, guidance_scale=0.0,
                        generator=torch.Generator("cpu").manual_seed(1)).images[0]
            if not valid(test):
                raise RuntimeError("FLUX produced an invalid test image on this GPU")
            log(role, f"image model: {repo} ({dtype})")
            return pipe, "flux"
        except Exception as exc:                                # noqa: BLE001
            log(role, f"FLUX unavailable ({exc}); falling back to SDXL")
            model = SDXL_BASE
            torch.cuda.empty_cache()
    from diffusers import AutoencoderKL, DPMSolverMultistepScheduler, StableDiffusionXLPipeline
    vae = AutoencoderKL.from_pretrained(SDXL_VAE, torch_dtype=torch.float16)
    pipe = None
    for repo in dict.fromkeys([model, SDXL_BASE]):
        for kw in ({"use_safetensors": True}, {}):
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(repo, vae=vae, torch_dtype=torch.float16, **kw)
                model = repo
                break
            except Exception as exc:                            # noqa: BLE001
                log(role, f"could not load {repo} {kw}: {str(exc)[:200]}")
        if pipe is not None:
            break
    if pipe is None:
        raise RuntimeError("no image model could be loaded")
    pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True,
                                                             algorithm_type="dpmsolver++")
    pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    log(role, f"image model: {model} (fp16)")
    return pipe, "sdxl"


def make_image(pipe, kind, job, item, seed):
    import torch
    g = torch.Generator("cpu").manual_seed(seed)
    if kind == "flux":
        return pipe(f"{item['prompt']}. {job['style']}", width=job["width"], height=job["height"],
                    num_inference_steps=4, guidance_scale=0.0, max_sequence_length=256,
                    generator=g).images[0]
    return pipe(prompt=f"{item['prompt']}, {job['style']}", negative_prompt=job["negative"],
                width=job["width"], height=job["height"], num_inference_steps=job["steps"],
                guidance_scale=5.5, generator=g).images[0]


def run_images(job, gpu):
    role = "images"
    st = {"done": 0, "failed": 0, "skipped": 0, "seconds": [], "error": None}
    try:
        import torch
        device = f"cuda:{gpu}"
        with _load_lock:
            pipe, kind = load_image_pipe(job, device, gpu, role)
        st["model"] = kind
        with _load_lock:
            up = try_upscaler(device, role) if job.get("upscale") else None
        todo = job["images"]
        for n, item in enumerate(todo):
            avg = sum(st["seconds"][-5:]) / max(1, len(st["seconds"][-5:])) if st["seconds"] else 40
            if time.time() + avg + 30 > deadline(job):
                st["skipped"] = len(todo) - n
                log(role, f"time budget reached, {st['skipped']} images skipped")
                break
            dst = OUT / f"{item['id']}.jpg"
            if dst.exists():
                continue
            t = time.time()
            try:
                img = make_image(pipe, kind, job, item, item["seed"])
                if not valid(img):
                    img = make_image(pipe, kind, job, item, item["seed"] + 1)
                if not valid(img):
                    st["failed"] += 1
                    continue
                if up:
                    img = up(img)
                tmp = OUT / f".{item['id']}.part.jpg"
                img.convert("RGB").save(tmp, "JPEG", quality=93)
                tmp.rename(dst)                         # atomic: the video thread never sees half a file
                st["done"] += 1
                st["seconds"].append(round(time.time() - t, 1))
                if st["done"] % 10 == 1:
                    log(role, f"{st['done']}/{len(todo)} images ({st['seconds'][-1]} s each)")
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                st["failed"] += 1
            except Exception as exc:                    # noqa: BLE001
                st["failed"] += 1
                log(role, f"{item['id']} failed: {str(exc)[:300]}")
            save_status(role, st)
    except Exception:                                   # noqa: BLE001
        st["error"] = traceback.format_exc()[-2500:]
        log(role, st["error"])
    save_status(role, st)


# ---------------------------------------------------------------- videos
def write_mp4(frames, path, fps=24):
    import imageio_ffmpeg
    w, h = frames[0].size
    tmp = path.with_name(f".{path.stem}.part.mp4")
    p = subprocess.Popen([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                          str(tmp)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.convert("RGB").tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    tmp.rename(path)


def run_videos(job, gpu, images_thread):
    role = "videos"
    st = {"done": 0, "failed": 0, "skipped": 0, "seconds": [], "error": None}
    try:
        import torch
        from diffusers import LTXImageToVideoPipeline
        from PIL import Image
        device = f"cuda:{gpu}"
        major = torch.cuda.get_device_capability(gpu)[0]
        dtype = torch.bfloat16 if major >= 8 else torch.float16
        with _load_lock:
            pipe = LTXImageToVideoPipeline.from_pretrained(job["video_model"], torch_dtype=dtype)
            pipe.enable_model_cpu_offload(gpu_id=gpu)
        try:
            pipe.vae.enable_tiling()
        except Exception:                                # noqa: BLE001
            pass
        pipe.set_progress_bar_config(disable=True)
        log(role, f"video model: {job['video_model']} ({dtype})")
        with _load_lock:
            up = try_upscaler(device, role) if job.get("upscale") else None
        W, H = job["video_width"], job["video_height"]
        for n, v in enumerate(job["videos"]):
            est = max(st["seconds"]) if st["seconds"] else 600
            src = OUT / f"{v['image']}.jpg"
            while not src.exists() and time.time() < deadline(job) and images_thread.is_alive():
                time.sleep(10)
            if not src.exists():
                st["skipped"] += 1
                continue
            if time.time() + est + 60 > deadline(job):
                st["skipped"] = len(job["videos"]) - n
                log(role, f"time budget reached, {st['skipped']} clips skipped")
                break
            dst = OUT / f"{v['id']}.mp4"
            if dst.exists():
                continue
            t = time.time()
            try:
                img = cover(Image.open(src).convert("RGB"), W, H)
                frames = pipe(image=img, prompt=f"{v['prompt']}. Slow, calm, cinematic.",
                              negative_prompt=VIDEO_NEGATIVE, width=W, height=H,
                              num_frames=job["video_frames"], num_inference_steps=job["video_steps"],
                              guidance_scale=3.0, generator=torch.Generator("cpu").manual_seed(v["seed"])).frames[0]
                if not (valid(frames[len(frames) // 2]) and valid(frames[-1])):
                    st["failed"] += 1
                    log(role, f"{v['id']}: invalid frames")
                    if st["done"] == 0 and st["failed"] >= 2:
                        st["error"] = "video model gives invalid frames on this GPU; clips disabled"
                        log(role, st["error"])
                        break
                    continue
                if up:
                    frames = [up(f) for f in frames]
                write_mp4(frames, dst)
                st["done"] += 1
                st["seconds"].append(round(time.time() - t, 1))
                log(role, f"clip {st['done']}/{len(job['videos'])} in {st['seconds'][-1]} s")
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                st["failed"] += 1
                log(role, f"{v['id']}: out of GPU memory")
            except Exception as exc:                    # noqa: BLE001
                st["failed"] += 1
                log(role, f"{v['id']} failed: {str(exc)[:300]}")
            save_status(role, st)
    except Exception:                                   # noqa: BLE001
        st["error"] = traceback.format_exc()[-2500:]
        log(role, st["error"])
    save_status(role, st)


# ---------------------------------------------------------------- main
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    job = load_job()
    manifest = {"job_id": job["job_id"], "errors": [], "gpus": []}
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", *PIP],
                           capture_output=True, text=True)
        if r.returncode:
            manifest["errors"].append("pip: " + r.stderr[-800:])
        # Kaggle's preinstalled torchao is older than new diffusers expects and breaks its import;
        # nothing here needs it (diffusers only uses it when it is installed)
        subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao"],
                       capture_output=True, text=True)
        log("main", "packages ready")
        import torch
        n = torch.cuda.device_count()
        manifest["gpus"] = [torch.cuda.get_device_name(i) for i in range(n)]
        log("main", f"GPUs: {manifest['gpus']}")
        if n == 0:
            raise RuntimeError("no GPU in this Kaggle session (the account must be phone-verified "
                               "and the kernel pushed with a GPU accelerator)")
        do_video = bool(job["videos"] and job.get("video_model"))
        ti = threading.Thread(target=run_images, args=(job, 0))
        ti.start()
        if do_video and n >= 2:
            tv = threading.Thread(target=run_videos, args=(job, 1, ti))
            tv.start()
            tv.join()
        ti.join()
        if do_video and n < 2:
            run_videos(job, 0, ti)
    except Exception:                                   # noqa: BLE001
        manifest["errors"].append(traceback.format_exc()[-2500:])
    for role in ("images", "videos"):
        p = OUT / f"status_{role}.json"
        if p.exists():
            st = json.loads(p.read_text())
            manifest[role + "_status"] = {k: st[k] for k in ("done", "failed", "skipped", "model") if k in st}
            if st.get("error"):
                manifest["errors"].append(f"{role}: {st['error']}")
    manifest["images"] = sorted(p.name for p in OUT.glob("*.jpg") if not p.name.startswith("."))
    manifest["videos"] = sorted(p.name for p in OUT.glob("*.mp4") if not p.name.startswith("."))
    manifest["minutes"] = round((time.time() - T0) / 60, 1)
    for p in OUT.glob(".*.part.*"):
        p.unlink(missing_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    log("main", f"finished: {len(manifest['images'])} images, {len(manifest['videos'])} clips")


if __name__ == "__main__":
    main()
