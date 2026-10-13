"""Upload to YouTube with the official Data API v3 (default quota: ~6 uploads/day)."""
import os

SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
          "https://www.googleapis.com/auth/youtube.force-ssl"]


def has_credentials():
    return all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def _client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials(None, refresh_token=os.environ["YT_REFRESH_TOKEN"],
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
                   "containsSyntheticMedia": up["synthetic_media"]},
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
