import os
import re
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from yt_dlp import YoutubeDL

app = FastAPI(
    title="yt-dlp Microservice - Universal",
    description="Suporta TikTok (cookies), YouTube e qualquer site do yt-dlp",
    version="2.0.0",
)


# ------------------------
# Detection Helpers
# ------------------------

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url or "vt.tiktok.com" in url


def is_youtube(url: str) -> bool:
    return (
        "youtube.com" in url
        or "youtu.be" in url
    )


COOKIE_FILE = "cookies/tiktok.txt"


# ------------------------
# Request Model
# ------------------------

class YtRequest(BaseModel):
    url: str
    audio_only: bool | None = False


# ------------------------
# Routes
# ------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
def extract(req: YtRequest):
    url = req.url

    # =====================
    # TikTok → USAR COOKIES
    # =====================
    if is_tiktok(url):
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiefile": COOKIE_FILE,
            "format": "bestaudio/best" if req.audio_only else "best",
        }

    # =====================
    # YouTube → NÃO USAR COOKIES
    # =====================
    elif is_youtube(url):
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestaudio/best" if req.audio_only else "best",
            # Melhora compatibilidade c/ YouTube
            "extractor_args": {
                "youtube": {
                    "player_client": ["web", "android"],
                }
            }
        }

    # =====================
    # Outros sites
    # =====================
    else:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestaudio/best" if req.audio_only else "best",
        }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"[yt-dlp error] {str(e)}"
        )

    # Playlist? → pega o primeiro
    if "entries" in info:
        info = info["entries"][0]

    # ---------------------
    # Formats
    # ---------------------
    formats_list = []
    best_url = info.get("url")

    for f in info.get("formats", []):
        formats_list.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "acodec": f.get("acodec"),
            "vcodec": f.get("vcodec"),
            "filesize": f.get("filesize"),
            "resolution": f.get("resolution") or f.get("format_note"),
            "url": f.get("url"),
        })

        if not best_url and f.get("url"):
            best_url = f["url"]

    if not best_url:
        raise HTTPException(
            status_code=500,
            detail="Nenhum URL de download encontrado."
        )

    return {
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url"),
        "download_url": best_url,
        "formats": formats_list,
        "audio_only": req.audio_only,
        "cookies_used": is_tiktok(url),
        "platform": (
            "tiktok" if is_tiktok(url)
            else "youtube" if is_youtube(url)
            else "generic"
        )
    }
