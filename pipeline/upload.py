"""Upload to YouTube with the official Data API v3 (default quota: ~6 uploads/day)."""
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def _token_env():
    """Each channel names its own refresh-token secret (channels/<name>.yaml → upload.token_env), so a missing
    secret means "no upload", never an upload to another channel's account."""
    from .common import load_config
    return load_config().get("upload", {}).get("token_env", "YT_REFRESH_TOKEN")


def has_credentials():
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", _token_env()))


def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(None, refresh_token=os.environ[_token_env()],
                        token_uri="https://oauth2.googleapis.com/token",
                        client_id=os.environ["YT_CLIENT_ID"],
                        client_secret=os.environ["YT_CLIENT_SECRET"], scopes=SCOPES)
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def _safe(text, limit):
    return text.replace("<", "").replace(">", "")[:limit]


def upload(video, meta, cfg, thumbnail=None, captions=None, yt=None):
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = yt or _client()
    up, lang = cfg["upload"], cfg["channel"]["language"]
    tags, total = [], 0
    for t in meta.get("tags", []):
        if total + len(t) + 3 > 480:
            break
        tags.append(t)
        total += len(t) + 3
    body = {
        "snippet": {"title": _safe(meta["title"], 100), "description": _safe(meta["description"], 4900),
                    "tags": tags, "categoryId": up["category_id"],
                    "defaultLanguage": lang, "defaultAudioLanguage": lang},
        "status": {"privacyStatus": up["privacy"],
                   "selfDeclaredMadeForKids": up["made_for_kids"],
                   "containsSyntheticMedia": bool(up["synthetic_media"] or meta.get("synthetic"))},
    }
    request = yt.videos().insert(part="snippet,status", body=body,
                                 media_body=MediaFileUpload(str(video), mimetype="video/mp4",
                                                            chunksize=64 * 1024 * 1024, resumable=True))
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"    upload {status.progress() * 100:.0f}%")
    video_id = response["id"]

    if thumbnail:
        try:
            yt.thumbnails().set(videoId=video_id,
                                media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
        except HttpError as exc:
            print(f"    thumbnail not set (verify the channel by phone): {exc}")
    if captions:
        try:
            yt.captions().insert(part="snippet",
                                 body={"snippet": {"videoId": video_id, "language": lang,
                                                   "name": "", "isDraft": False}},
                                 media_body=MediaFileUpload(str(captions),
                                                            mimetype="application/octet-stream")).execute()
        except HttpError as exc:
            print(f"    captions not uploaded: {exc}")
    return video_id
