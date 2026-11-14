"""Tras recortar un video en YouTube Studio, los subtítulos subidos por el canal quedan con los tiempos viejos.
Baja la pista propia, quita las líneas del tramo cortado, adelanta las siguientes y la vuelve a subir.
Uso: python scripts/corregir_subtitulos.py VIDEO_ID CORTE_INICIO_S CORTE_FIN_S [--aplicar]"""
import io, json, os, re, sys
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

vid, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
apply = "--aplicar" in sys.argv
creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN_NOCTURNO"], token_uri="https://oauth2.googleapis.com/token",
                    client_id=os.environ["YT_CLIENT_ID"], client_secret=os.environ["YT_CLIENT_SECRET"],
                    scopes=["https://www.googleapis.com/auth/youtube.force-ssl"])
yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
os.makedirs("diag", exist_ok=True)
rep = {}
v = yt.videos().list(part="contentDetails,processingDetails,status", id=vid).execute()["items"][0]
rep["duracion"] = v["contentDetails"]["duration"]
tracks = yt.captions().list(part="snippet", videoId=vid).execute()["items"]
rep["pistas"] = [{k: t["snippet"].get(k) for k in ("language", "name", "trackKind", "isDraft", "lastUpdated")} | {"id": t["id"]}
                 for t in tracks]
own = [t for t in tracks if t["snippet"].get("trackKind") != "asr"]
T = lambda s: sum(float(x) * m for x, m in zip(re.split("[:,]", s)[::-1], (0.001, 1, 60, 3600)))
def F(x):
    ms = round(x * 1000); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
if own:
    t = own[0]
    srt = yt.captions().download(id=t["id"], tfmt="srt").execute().decode("utf-8")
    open("diag/original.srt", "w").write(srt)
    blocks = [x for x in re.split(r"\n\s*\n", srt.strip()) if "-->" in x]
    out, n = [], 0
    for blk in blocks:
        lines = blk.strip().split("\n")
        i = next(k for k, l in enumerate(lines) if "-->" in l)
        s0, s1 = [T(x.strip()) for x in lines[i].split("-->")]
        if s1 <= a:
            pass
        elif s0 >= b:
            s0, s1 = s0 - (b - a), s1 - (b - a)
        else:
            continue                                   # dentro (o cruzando) el tramo cortado
        n += 1
        out.append(f"{n}\n{F(s0)} --> {F(s1)}\n" + "\n".join(lines[i + 1:]))
    fixed = "\n\n".join(out) + "\n"
    open("diag/corregido.srt", "w").write(fixed)
    rep["lineas_antes"], rep["lineas_despues"] = len(blocks), n
    rep["muestra_corregida"] = fixed[:1500]
    if apply:
        yt.captions().update(part="snippet", body={"id": t["id"], "snippet": {"isDraft": False}},
                             media_body=MediaIoBaseUpload(io.BytesIO(fixed.encode()), mimetype="application/octet-stream")).execute()
        rep["aplicado"] = True
json.dump(rep, open("diag/subtitulos.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != "muestra_corregida"}, ensure_ascii=False, indent=1))
