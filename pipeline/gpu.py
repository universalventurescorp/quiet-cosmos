"""Kaggle as a free GPU: push the episode's job as a private script, wait, download the results.

GitHub Actions keeps doing everything else in parallel (narration, NASA footage, music, mix), so the
GPU work usually finishes before the render needs it. If Kaggle is not configured, busy, out of quota
or fails, the episode is still produced with NASA imagery only (the v2 look) and qa.json says why.

Secrets (GitHub → Settings → Secrets → Actions): KAGGLE_USERNAME, KAGGLE_KEY.
"""
import base64
import json
import os
import re
import shutil
import subprocess
import time

from .common import ROOT, read_json, write_json

WORKER = ROOT / "kaggle" / "generate.py"


def configured():
    return bool(os.environ.get("KAGGLE_USERNAME") and os.environ.get("KAGGLE_KEY"))


def _env():
    env = dict(os.environ)
    key = env.get("KAGGLE_KEY", "")
    if key.startswith("KGAT_"):                 # new-style Kaggle API token
        env.setdefault("KAGGLE_API_TOKEN", key)
    return env


def _kaggle(*args, timeout=600):
    r = subprocess.run(["kaggle", *args], capture_output=True, text=True, timeout=timeout, env=_env())
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def kernel_ref(cfg):
    return f"{os.environ['KAGGLE_USERNAME']}/{cfg.get('kaggle', {}).get('kernel', 'quiet-cosmos-gen')}"


def launch(job, out, cfg, worker=None):
    """Push the job. Returns a state dict saved to out/kaggle.json."""
    kg = cfg.get("kaggle", {})
    ref = kernel_ref(cfg)
    slug = ref.split("/", 1)[1]
    kdir = out / "kaggle_kernel"
    shutil.rmtree(kdir, ignore_errors=True)
    kdir.mkdir(parents=True)
    payload = base64.b64encode(json.dumps(job, ensure_ascii=False).encode()).decode()
    (kdir / "generate.py").write_text((worker or WORKER).read_text(encoding="utf-8").replace("__JOB_B64__", payload, 1),
                                      encoding="utf-8")
    meta = {"id": ref, "title": slug, "code_file": "generate.py", "language": "python",
            "kernel_type": "script", "is_private": True, "enable_gpu": True, "enable_tpu": False,
            "enable_internet": True, "dataset_sources": [], "competition_sources": [],
            "kernel_sources": [], "model_sources": []}
    (kdir / "kernel-metadata.json").write_text(json.dumps(meta, indent=1))

    acc = kg.get("accelerator", "NvidiaTeslaT4")
    code, text = _kaggle("kernels", "push", "-p", str(kdir), "--accelerator", acc)
    if "unrecognized arguments" in text or "no such option" in text.lower():
        code, text = _kaggle("kernels", "push", "-p", str(kdir))      # older CLI: default GPU
    ok = code == 0 and re.search(r"success|pushed", text, re.I) and not re.search(r"error", text, re.I)
    state = {"job_id": job["job_id"], "kernel": ref, "pushed_at": time.time(), "ok": bool(ok),
             "push_output": text.strip()[-1500:]}
    write_json(out / "kaggle.json", state)
    print(f"   kaggle push {'ok' if ok else 'FAILED'}: {text.strip()[-300:]}")
    return state


def status(ref):
    code, text = _kaggle("kernels", "status", ref, timeout=120)
    m = re.search(r'status\s+"?([\w.]+)"?', text)
    word = (m.group(1) if m else text).lower()
    for key in ("complete", "error", "cancel", "running", "queued"):
        if key in word:
            return key, text.strip()
    return "unknown", text.strip()


def collect(out, cfg, wait_minutes=None):
    """Wait for the kernel and download its output into out/ai. Returns the worker manifest or None."""
    state = read_json(out / "kaggle.json", None)
    ai_dir = out / "ai"
    done = read_json(ai_dir / "manifest.json", None)
    if done and state and done.get("job_id") == state.get("job_id"):
        return done
    if not state or not state.get("ok"):
        return None
    wait_minutes = wait_minutes or cfg.get("kaggle", {}).get("wait_minutes", 240)
    give_up = state["pushed_at"] + wait_minutes * 60
    time.sleep(max(0, state["pushed_at"] + 90 - time.time()))   # the status endpoint lags behind a push
    last = ""
    while time.time() < give_up:
        st, text = status(state["kernel"])
        if st != last:
            print(f"   kaggle: {st} ({(time.time() - state['pushed_at']) / 60:.0f} min)", flush=True)
            last = st
        if st in ("complete", "error", "cancel"):
            manifest = _download(state, out)
            if manifest and manifest.get("job_id") == state["job_id"]:
                return manifest
            if st == "complete" and time.time() - state["pushed_at"] < 600:
                time.sleep(60)                                  # probably still the previous version
                continue
            print(f"   kaggle finished with status {st} but no results for this job")
            return None
        time.sleep(60)
    print(f"   kaggle: gave up after {wait_minutes} min")
    return None


def _download(state, out):
    tmp = out / "kaggle_output"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    code, text = _kaggle("kernels", "output", state["kernel"], "-p", str(tmp), timeout=1800)
    found = list(tmp.rglob("manifest.json"))
    log = list(tmp.rglob("log.txt"))
    if log:
        print("   --- kaggle log (last lines) ---")
        for line in log[0].read_text(errors="ignore").splitlines()[-15:]:
            print(f"   {line}")
    if not found:
        print(f"   kaggle output had no manifest: {text.strip()[-300:]}")
        return None
    src = found[0].parent
    manifest = json.loads(found[0].read_text())
    if manifest.get("job_id") != state["job_id"]:
        return manifest
    ai_dir = out / "ai"
    shutil.rmtree(ai_dir, ignore_errors=True)
    shutil.move(str(src), str(ai_dir))
    shutil.rmtree(tmp, ignore_errors=True)
    return manifest
