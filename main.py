import os
import uuid
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from yt_dlp import YoutubeDL

app = FastAPI(
    title="Universal Downloader",
    description="TikTok + Instagram + YouTube usando yt-dlp",
    version="4.0.0",
)

# Caminhos de cookies dentro do container
COOKIE_TIKTOK = "cookies/tiktok.txt"
COOKIE_INSTAGRAM = "cookies/instagram.txt"

# User-Agent TikTok
TIKTOK_UA = os.getenv(
    "TIKTOK_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Proxies opcionais (se você quiser usar depois)
TIKTOK_PROXY = os.getenv("TIKTOK_PROXY")
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY")


# ---------------------------
# Helpers
# ---------------------------

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url


def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url


def build_opts_for_extract(url: str, audio_only: bool = False) -> tuple[dict, str]:
    """
    Monta ydl_opts para modo EXTRACT (sem download).
    Retorna (ydl_opts, platform)
    """
    if is_tiktok(url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiefile": COOKIE_TIKTOK,
            "format": "bestaudio/best" if audio_only else "best",
            "http_headers": {
                "User-Agent": TIKTOK_UA,
                "Referer": "https://www.tiktok.com/",
                "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
            },
        }
        if TIKTOK_PROXY:
            opts["proxy"] = TIKTOK_PROXY
        return opts, "tiktok"

    if is_instagram(url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiefile": COOKIE_INSTAGRAM,  # funciona p/ público e privado
            "format": "bestaudio/best" if audio_only else "best",
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

    if is_youtube(url):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "format": "bestaudio/best" if audio_only else "best[ext=mp4]/best",
            "extractor_args": {
                "youtube": {"player_client": ["web", "android"]}
            },
        }
        return opts, "youtube"

    # genérico
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": "bestaudio/best" if audio_only else "best",
    }
    return opts, "generic"


def build_opts_for_download(url: str, outtmpl: str) -> tuple[dict, str]:
    """
    Monta ydl_opts para modo DOWNLOAD (baixa arquivo).
    Retorna (ydl_opts, platform)
    """
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

    if is_youtube(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,
            "format": "best[ext=mp4]/best",
            "extractor_args": {
                "youtube": {"player_client": ["web", "android"]}
            },
        }
        return opts, "youtube"

    # genérico
    opts = {
        "quiet": True,
        "noprogress": True,
        "outtmpl": outtmpl,
        "format": "best",
    }
    return opts, "generic"


def pick_best_url(info: dict) -> str | None:
    """
    Tenta descobrir a melhor URL de download a partir do dict do yt-dlp.
    """
    # Alguns extractors já colocam a melhor URL em info["url"]
    if info.get("url"):
        return info["url"]

    formats = info.get("formats") or []
    if not formats:
        return None

    # Heurística simples: pega o último formato com url (normalmente maior qualidade)
    for f in reversed(formats):
        if f.get("url"):
            return f["url"]

    return None


# ---------------------------
# Models
# ---------------------------

class ExtractRequest(BaseModel):
    url: str
    audio_only: bool | None = False


class VideoRequest(BaseModel):
    url: str


# ---------------------------
# Rotas
# ---------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
def extract(req: ExtractRequest):
    """
    NÃO baixa o arquivo.
    Retorna metadados + melhor download_url.
    """
    url = req.url.strip()
    if url.startswith("="):
        url = url[1:].strip()

    ydl_opts, platform = build_opts_for_extract(url, audio_only=req.audio_only)

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao extrair informações: {str(e)}"
        )

    # Playlist → pega primeiro item
    if "entries" in info:
        info = info["entries"][0]

    best_url = pick_best_url(info)
    if not best_url:
        raise HTTPException(
            status_code=500,
            detail="Não foi possível determinar a URL de download."
        )

    return {
        "platform": platform,
        "id": info.get("id"),
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url"),
        "download_url": best_url,   # <- URL NA MELHOR QUALIDADE
        "audio_only": req.audio_only,
    }


@app.post("/download")
def download(req: VideoRequest):
    """
    Baixa o vídeo na melhor qualidade e devolve o binário (video/mp4)
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
