"""Maratón: junta episodios ya publicados en un solo video largo (cero GPU) y lo sube en privado.

Uso (lo lanza .github/workflows/maraton.yml):
    CHANNEL=estrato-nocturno python -m pipeline.marathon --videos ID1,ID2,ID3 [--title "..."] [--no-upload]

De dónde saca cada episodio, en este orden:
  1. release "episodios-<canal>" (desde el 25-oct-2026 cada episodio nuevo se guarda ahí completo),
  2. release "maraton-entrada" con un archivo <ID>.mp4 (subido a mano desde YouTube Studio),
  3. yt-dlp desde YouTube (puede fallar desde las máquinas de GitHub).
Cada parte se iguala a -16 LUFS con fundidos suaves en las uniones, para que nadie se despierte.
"""
import argparse
import datetime
import io
import json
import os
import pathlib
import subprocess

from .common import CHANNEL, DATA, ROOT, load_config, read_json, write_json

WORK = ROOT / "outputs" / "maraton"
REPO = os.environ.get("GITHUB_REPOSITORY", "universalventurescorp/quiet-cosmos")


def sh(cmd, check=True):
    print("   $", " ".join(map(str, cmd))[:300])
    try:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    except FileNotFoundError as exc:  # herramienta no instalada (gh, yt-dlp)
        if check:
            raise
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


def probe(path):
    out = sh(["ffprobe", "-v", "error", "-show_entries",
              "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt:format=duration",
              "-of", "json", str(path)]).stdout
    d = json.loads(out)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {"dur": float(d["format"]["duration"]),
            "sig": (v["codec_name"], v["width"], v["height"], v["r_frame_rate"], v["pix_fmt"])}


def fetch(vid):
    dest = WORK / "src" / f"{vid}.mp4"
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest, "cache"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for tag, pattern in ((f"episodios-{CHANNEL}", f"*{vid}*.mp4"), ("maraton-entrada", f"{vid}*.mp4")):
        r = sh(["gh", "release", "download", tag, "-R", REPO, "-p", pattern, "-D", str(dest.parent),
                "--clobber"], check=False)
        got = sorted(dest.parent.glob(pattern), key=lambda p: p.stat().st_mtime)
        if r.returncode == 0 and got:
            if got[-1] != dest:
                got[-1].rename(dest)
            return dest, tag
    r = sh(["yt-dlp", "-q", "--no-warnings", "-f",
            "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b", "--merge-output-format", "mp4",
            "-o", str(dest), f"https://www.youtube.com/watch?v={vid}"], check=False)
    if r.returncode == 0 and dest.exists():
        return dest, "yt-dlp"
    print(r.stderr[-1500:])
    return None, "missing"


GOODBYE = ("buenas noches", "descansa", "dulces sueños", "que duermas", "hasta la próxima",
           "good night", "goodnight", "sleep well", "rest well")
_whisper = None


def goodbye_cut(src, tail=180.0, gap=0.8):
    """Busca la despedida ("buenas noches…") en los últimos minutos y devuelve (fin, inicio_fundido) para cortar
    justo antes del párrafo de despedida. None si no la encuentra (entonces la parte se deja entera)."""
    global _whisper
    dur = probe(src)["dur"]
    off = max(0.0, dur - tail)
    wav = WORK / "tail.wav"
    sh(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{off:.2f}", "-i", str(src), "-vn", "-ac", "1",
        "-ar", "16000", str(wav)])
    try:
        from faster_whisper import WhisperModel
        _whisper = _whisper or WhisperModel("small", device="cpu", compute_type="int8")
        segs = list(_whisper.transcribe(str(wav), language=None, vad_filter=True)[0])
    except Exception as exc:  # noqa: BLE001
        print("   whisper failed:", exc)
        return None
    hits = [k for k, sg in enumerate(segs) if any(w in sg.text.lower() for w in GOODBYE)]
    if not hits:
        return None
    k = j = hits[-1]
    # retrocede hasta el inicio del párrafo de despedida (una pausa larga), sin pasar de 45 s
    while j > 0 and segs[j].start - segs[j - 1].end < gap and segs[k].start - segs[j - 1].start < 45:
        j -= 1
    if j == 0:
        return None
    end = off + segs[j].start - 0.1
    fade_from = off + segs[j - 1].end + 0.05
    print(f"   despedida: «{' '.join(sg.text.strip() for sg in segs[j:k + 1])[:160]}» → corte en {end:.1f}s")
    return end, min(fade_from, end - 0.3)


def part(src, i, n, same_video, cut=None):
    """Audio a -16 LUFS + fundidos en las uniones; el video se copia si todas las partes son iguales.
    cut = (fin, inicio_fundido): quita la despedida de los episodios que no son el último."""
    dur = probe(src)["dur"]
    out = WORK / f"part_{i:02d}.mp4"
    af = "loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000"
    if i > 0:
        af += ",afade=t=in:d=3"
    trim = []
    if i < n - 1 and cut:
        dur, fade_from = cut
        af += f",afade=t=out:st={fade_from:.2f}:d={max(0.3, dur - fade_from):.2f}"
        trim = ["-t", f"{dur:.2f}"]
    elif i < n - 1:
        af += f",afade=t=out:st={max(0, dur - 4):.2f}:d=4"
    vc = ["-c:v", "copy"] if same_video else \
        ["-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:-1:-1,fps=30,format=yuv420p",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
    sh(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0", *vc,
        "-af", af, *trim, "-c:a", "aac", "-b:a", "192k", "-ac", "2", str(out)])
    return out


def stamp(sec):
    sec = int(sec)
    if sec < 3600:  # YouTube exige que el primer capítulo sea 0:00
        return f"{sec // 60}:{sec % 60:02d}"
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def short_name(title):
    return title.split(":")[0].split("|")[0].strip()


def names_list(names):
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " y " + names[-1]


def thumbnail(urls, hours, out):
    """Mosaico oscuro con las miniaturas de los episodios y el número de horas grande."""
    import requests
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    from .fonts import font

    W, H = 1280, 720
    tiles = []
    for u in urls[:4]:
        try:
            tiles.append(Image.open(io.BytesIO(requests.get(u, timeout=30).content)).convert("RGB"))
        except Exception as exc:  # noqa: BLE001
            print("   thumbnail tile failed:", exc)
    canvas = Image.new("RGB", (W, H), (8, 10, 24))
    if tiles:
        cols = 2 if len(tiles) > 1 else 1
        rows = (len(tiles) + cols - 1) // cols
        tw, th = W // cols, H // rows
        for k, t in enumerate(tiles):
            canvas.paste(t.resize((tw, th)), ((k % cols) * tw, (k // cols) * th))
    canvas = ImageEnhance.Brightness(canvas.filter(ImageFilter.GaussianBlur(2))).enhance(0.45)
    d = ImageDraw.Draw(canvas)
    big, small = font("black", 230), font("semibold", 64)
    line1 = f"{hours} HORAS"
    w1 = d.textlength(line1, font=big)
    d.text(((W - w1) / 2 + 4, 170 + 4), line1, font=big, fill=(0, 0, 0))
    d.text(((W - w1) / 2, 170), line1, font=big, fill=(242, 238, 228))
    line2 = "PARA DORMIR"
    w2 = d.textlength(line2, font=small)
    d.text(((W - w2) / 2, 440), line2, font=small, fill=(142, 147, 217))
    canvas.save(out, quality=92)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--videos", required=True, help="IDs de YouTube separados por coma, en orden")
    ap.add_argument("--title", default="")
    ap.add_argument("--no-upload", action="store_true")
    a = ap.parse_args()
    ids = [v.strip() for v in a.videos.split(",") if v.strip()]
    cfg = load_config()
    WORK.mkdir(parents=True, exist_ok=True)
    report = {"date": datetime.date.today().isoformat(), "ids": ids, "sources": {}, "ok": False}
    diag = DATA / "diagnostics" / "last_marathon.json"

    from . import upload as up
    yt = up._client() if up.has_credentials() else None
    info = {}
    if yt:
        for item in yt.videos().list(part="snippet", id=",".join(ids)).execute().get("items", []):
            th = item["snippet"]["thumbnails"]
            info[item["id"]] = {"title": item["snippet"]["title"],
                                "thumb": (th.get("maxres") or th.get("high") or th.get("default"))["url"]}
    done = {e["video_id"]: e for e in read_json(DATA / "done.json", []) if e.get("video_id")}
    for vid in ids:
        info.setdefault(vid, {"title": done.get(vid, {}).get("title", vid), "thumb": None})

    srcs = []
    for vid in ids:
        path, how = fetch(vid)
        report["sources"][vid] = how
        if not path:
            report["error"] = f"no se pudo conseguir el episodio {vid}"
            write_json(diag, report)
            raise SystemExit(report["error"] + " (sube <ID>.mp4 a la release 'maraton-entrada')")
        srcs.append(path)

    sigs = [probe(s)["sig"] for s in srcs]
    same = len(set(sigs)) == 1
    report["video_copy"] = same
    cuts = [goodbye_cut(s) if i < len(srcs) - 1 else None for i, s in enumerate(srcs)]
    report["goodbye_cuts"] = {v: (round(c[0], 1) if c else None) for v, c in zip(ids, cuts)}
    parts = [part(s, i, len(srcs), same, c) for i, (s, c) in enumerate(zip(srcs, cuts))]
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts))
    final = WORK / "maraton.mp4"
    sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
        "-c", "copy", "-movflags", "+faststart", str(final)])

    total, t, chapters = 0.0, 0.0, []
    for vid, p in zip(ids, parts):
        chapters.append(f"{stamp(t)} {short_name(info[vid]['title'])}")
        t += probe(p)["dur"]
    total = t
    hours = max(1, round(total / 3600))
    names = [short_name(info[v]["title"]) for v in ids]
    title = a.title or f"{hours} horas de documentales del espacio para dormir: {names_list(names)}"
    if len(title) > 100:
        title = f"{hours} horas de documentales del espacio para dormir | Viaje completo"
    links = "\n".join(f"{short_name(info[v]['title'])}: https://youtu.be/{v}" for v in ids)
    desc = (f"{hours} horas de calma para quedarte dormido viajando por el espacio: {names_list(names)}, "
            f"uno tras otro, sin cortes bruscos ni cambios de volumen. Pon el video, apaga la luz y deja que el "
            f"universo te cuente su historia.\n\nCapítulos\n" + "\n".join(chapters) +
            f"\n\nEpisodios por separado:\n{links}\n\n"
            "Imágenes y video: NASA Image and Video Library (dominio público; la NASA no respalda este canal) "
            "y escenas generadas con IA (impresión artística).\nNarración: voz IA. Guion investigado, escrito "
            "y revisado para este canal. Música: banda sonora ambiental original.\n\n"
            "#documental #dormir #espacio #sistemasolar #relajacion")
    meta = {"title": title, "description": desc, "synthetic": True,
            "tags": ["documental para dormir", "documental del espacio", "sistema solar", "dormir",
                     "relajante", "universo", "astronomía", f"{hours} horas"] + [n.lower() for n in names]}
    thumb = thumbnail([info[v]["thumb"] for v in ids if info[v]["thumb"]], hours, WORK / "thumbnail.jpg")
    report.update(title=title, minutes=round(total / 60, 1), chapters=chapters)

    if a.no_upload or not yt:
        report["ok"] = True
        report["uploaded"] = False
    else:
        vid = up.upload(final, meta, cfg, thumbnail=thumb, yt=yt)
        report.update(ok=True, uploaded=True, video_id=vid, url=f"https://youtu.be/{vid}")
        log = read_json(DATA / "marathons.json", [])
        log.append({"date": report["date"], "video_id": vid, "title": title, "parts": ids,
                    "minutes": report["minutes"]})
        write_json(DATA / "marathons.json", log)
    write_json(diag, report)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
