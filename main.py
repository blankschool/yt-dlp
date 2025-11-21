import logging
import os
from pathlib import Path
import uuid
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from yt_dlp import YoutubeDL

DEBUG_YTDLP = os.getenv("DEBUG_YTDLP", "0") == "1"

logging.basicConfig(level=logging.DEBUG if DEBUG_YTDLP else logging.INFO)
logger = logging.getLogger("downloader")

app = FastAPI(
    title="Universal Downloader",
    description="YouTube + Instagram + TikTok via yt-dlp, retornando binário",
    version="5.0.0",
)

# Caminhos de cookies dentro do container (resolvidos para absoluto)
BASE_DIR = Path(__file__).resolve().parent
COOKIE_TIKTOK = str(BASE_DIR / "cookies" / "tiktok.txt")
COOKIE_INSTAGRAM = str(BASE_DIR / "cookies" / "instagram.txt")
# YouTube usa cookies.txt (conforme instrução do usuário)
COOKIE_YOUTUBE = str(BASE_DIR / "cookies" / "cookies.txt")

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

# Controle de verbosidade do yt-dlp
QUIET_FLAG = not DEBUG_YTDLP


def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url


def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url


def describe_cookie(path: str) -> str:
    """Retorna info curta sobre o arquivo de cookies para debugging."""
    if not os.path.exists(path):
        return f"{path} (NAO existe)"
    try:
        size = os.path.getsize(path)
    except Exception:
        size = -1
    readable = os.access(path, os.R_OK)
    return f"{path} (size={size}, readable={readable})"


def ensure_cookie(path: str, platform: str):
    """Garante que o arquivo de cookie existe e é legível; senão lança HTTP 401."""
    if not os.path.exists(path):
        logger.warning("%s cookie nao encontrado: %s", platform, path)
        raise HTTPException(status_code=401, detail=f"Cookie de {platform} ausente")
    if not os.access(path, os.R_OK):
        logger.warning("%s cookie sem permissao de leitura: %s", platform, path)
        raise HTTPException(status_code=401, detail=f"Cookie de {platform} ilegivel")
    try:
        if os.path.getsize(path) == 0:
            logger.warning("%s cookie vazio: %s", platform, path)
            raise HTTPException(status_code=401, detail=f"Cookie de {platform} vazio")
    except OSError:
        logger.warning("%s cookie sem size disponivel: %s", platform, path)


def build_opts_for_download(url: str, outtmpl: str) -> tuple[dict, str]:
    """
    Monta ydl_opts para DOWNLOAD em melhor qualidade possível.
    Retorna (ydl_opts, platform)
    """
    # TikTok
    if is_tiktok(url):
        opts = {
            "quiet": QUIET_FLAG,
            "noprogress": QUIET_FLAG,
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
            "quiet": QUIET_FLAG,
            "noprogress": QUIET_FLAG,
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
            "quiet": QUIET_FLAG,
            "noprogress": QUIET_FLAG,
            "outtmpl": outtmpl,
            # pega melhor vídeo+áudio disponível e remuxa para mp4 quando possível
            "format": "bv*+ba/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "postprocessors": [
                {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
            ],
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
        if platform == "youtube":
            ensure_cookie(COOKIE_YOUTUBE, "youtube")
            # Tenta alguns formatos em ordem, para contornar "Requested format is not available"
            format_candidates = [
                "bv*+ba/bestvideo+bestaudio/best",
                "bestvideo+bestaudio/best",
                "best",
            ]
            last_error = None

            logger.info(
                "YouTube: usando cookies %s",
                describe_cookie(COOKIE_YOUTUBE),
            )

            for fmt in format_candidates:
                ydl_opts["format"] = fmt
                logger.info("YouTube: tentando formato '%s' para %s", fmt, url)
                try:
                    with YoutubeDL(ydl_opts) as ydl:
                        ydl.download([url])
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    logger.warning(
                        "YouTube: falhou com formato '%s' em %s: %s", fmt, url, e
                    )
            if last_error:
                raise last_error
        elif platform == "tiktok":
            ensure_cookie(COOKIE_TIKTOK, "tiktok")
            logger.info(
                "TikTok: usando cookies %s, UA=%s, proxy=%s",
                describe_cookie(COOKIE_TIKTOK),
                TIKTOK_UA,
                TIKTOK_PROXY or "none",
            )
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        elif platform == "instagram":
            ensure_cookie(COOKIE_INSTAGRAM, "instagram")
            logger.info(
                "Instagram: usando cookies %s, proxy=%s",
                describe_cookie(COOKIE_INSTAGRAM),
                INSTAGRAM_PROXY or "none",
            )
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
        else:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
    except Exception as e:
        logger.exception("Falha ao baixar (%s) %s", platform, url)
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
