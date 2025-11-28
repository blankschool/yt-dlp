import os
import uuid
import shutil
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from yt_dlp import YoutubeDL

# ------------------------------------------------------
# CONFIGURAÇÃO DE LOG
# ------------------------------------------------------
DEBUG = os.getenv("DEBUG_YTDLP", "0") == "1"
logging.basicConfig(level=logging.DEBUG if DEBUG else logging.INFO)
logger = logging.getLogger("downloader")

# ------------------------------------------------------
# CONFIGURAÇÃO DE COOKIES
# ------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
COOKIES_DIR = BASE_DIR / "cookies"

COOKIE_FILES = {
    "instagram": str(COOKIES_DIR / "instagram.txt"),
    "tiktok": str(COOKIES_DIR / "tiktok.txt"),
    "youtube": str(COOKIES_DIR / "youtube.txt"),
}


# ------------------------------------------------------
# CONFIGURAÇÃO DE USER-AGENT
# ------------------------------------------------------
USER_AGENTS = {
    "instagram": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "tiktok": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "youtube": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "default": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


# ------------------------------------------------------
# DETECTA PLATAFORMA AUTOMATICAMENTE
# ------------------------------------------------------
def detect_platform(url: str) -> str:
    url = url.lower()
    if "instagram.com" in url:
        return "instagram"
    if "tiktok.com" in url:
        return "tiktok"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    return "default"


# ------------------------------------------------------
# VERIFICA COOKIES
# ------------------------------------------------------
def ensure_cookie(platform: str):
    cookie = COOKIE_FILES.get(platform)
    if not cookie:
        return None

    if not os.path.exists(cookie):
        raise HTTPException(status_code=401, detail=f"Cookie de {platform} não encontrado")

    if os.path.getsize(cookie) == 0:
        raise HTTPException(status_code=401, detail=f"Cookie de {platform} está vazio")

    return cookie


# ------------------------------------------------------
# MODELO DE ENTRADA
# ------------------------------------------------------
class DownloadRequest(BaseModel):
    url: str
    extract_audio: bool = False
    audio_format: str = "mp3"


# ------------------------------------------------------
# CRIA OPÇÕES DO YT-DLP
# ------------------------------------------------------
def build_opts(url: str, extract_audio: bool, audio_format: str) -> Tuple[dict, str]:
    platform = detect_platform(url)
    cookiefile = ensure_cookie(platform)

    temp_dir = tempfile.mkdtemp()
    output_template = os.path.join(temp_dir, "%(id)s.%(ext)s")

    # Opções base
    opts = {
        "outtmpl": output_template,
        "quiet": not DEBUG,
        "no_warnings": not DEBUG,
        "noplaylist": True,
        "http_headers": {
            "User-Agent": USER_AGENTS.get(platform, USER_AGENTS["default"])
        },
        "cookiefile": cookiefile,
        "format": "bv*+ba/bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "prefer_ffmpeg": True,
    }

    # Extrair áudio
    if extract_audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_format,
                "preferredquality": "0"
            }
        ]

    return opts, temp_dir


# ------------------------------------------------------
# EXECUTA DOWNLOAD
# ------------------------------------------------------
def perform_download(url: str, opts: dict, temp_dir: str) -> Tuple[bytes, str]:
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])

        # procura qualquer arquivo gerado
        files = list(Path(temp_dir).glob("*"))
        if not files:
            raise HTTPException(status_code=500, detail="Nenhum arquivo foi gerado pelo yt-dlp.")

        file_path = files[0]
        mime = "audio/mpeg" if file_path.suffix == ".mp3" else "video/mp4"

        with open(file_path, "rb") as f:
            data = f.read()

        return data, mime

    except Exception as e:
        logger.exception("Erro ao baixar: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# ------------------------------------------------------
# FASTAPI APP
# ------------------------------------------------------
app = FastAPI(
    title="Universal Downloader",
    version="1.0.0",
    description="Downloader profissional para Instagram, TikTok e YouTube com suporte a áudio/mp3."
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/download")
def download(req: DownloadRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL não informada")

    opts, temp_dir = build_opts(url, req.extract_audio, req.audio_format)
    data, mime = perform_download(url, opts, temp_dir)

    filename = f"file_{uuid.uuid4().hex}{'.mp3' if req.extract_audio else '.mp4'}"

    return Response(
        content=data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition"
        }
    )
