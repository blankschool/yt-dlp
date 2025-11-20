import os
import uuid
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from yt_dlp import YoutubeDL

app = FastAPI(
    title="Universal Downloader",
    description="YouTube + Instagram + TikTok via yt-dlp, retornando binário",
    version="5.0.0",
)

# Caminhos de cookies dentro do container
COOKIE_TIKTOK = "cookies/tiktok.txt"
COOKIE_INSTAGRAM = "cookies/instagram.txt"
COOKIE_YOUTUBE = "cookies/youtube.txt"

# User-Agent TikTok
TIKTOK_UA = os.getenv(
    "TIKTOK_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Proxies opcionais (se quiser usar)
TIKTOK_PROXY = os.getenv("TIKTOK_PROXY")
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY")


def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url


def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url


def build_opts_for_download(url: str, outtmpl: str) -> tuple[dict, str]:
    """
    Monta ydl_opts para DOWNLOAD em melhor qualidade possível.
    Retorna (ydl_opts, platform)
    """
    # TikTok
    if is_tiktok(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,
            "cookiefile": COOKIE_TIKTOK,
            "format": "best",
            "http_headers": {
                "User-Agent": TIKTOK_UA,
                "Referer": "https://www.tiktok.com/",
                "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            },
        }
        if TIKTOK_PROXY:
            opts["proxy"] = TIKTOK_PROXY
        return opts, "tiktok"

    # Instagram
    if is_instagram(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,
            "cookiefile": COOKIE_INSTAGRAM,
            "format": "best",
            "http_headers": {
                "User-Agent":
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://www.instagram.com/",
            },
        }
        if INSTAGRAM_PROXY:
            opts["proxy"] = INSTAGRAM_PROXY
        return opts, "instagram"

    # YouTube
    if is_youtube(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,
            # tenta MP4 na melhor qualidade, se não der pega best
            "format": "best[ext=mp4]/best",
            "cookiefile": COOKIE_YOUTUBE,
            "extractor_args": {
                "youtube": {"player_client": ["web", "android"]}
            },
        }
        return opts, "youtube"

    # Genérico
    opts = {
        "quiet": True,
        "noprogress": True,
        "outtmpl": outtmpl,
        "format": "best",
    }
    return opts, "generic"


class VideoRequest(BaseModel):
    url: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/download")
def download(req: VideoRequest):
    """
    Recebe {"url": "..."} e retorna o binário do vídeo em melhor qualidade possível.
    """
    url = req.url.strip()
    if url.startswith("="):
        url = url[1:].strip()

    temp_filename = f"/tmp/{uuid.uuid4()}.mp4"

    ydl_opts, platform = build_opts_for_download(url, temp_filename)

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao baixar vídeo ({platform}): {str(e)}"
        )

    try:
        with open(temp_filename, "rb") as f:
            data = f.read()
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao ler arquivo baixado")

    try:
        os.remove(temp_filename)
    except Exception:
        pass

    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Content-Disposition": 'attachment; filename=\"video.mp4\"'}
    )
