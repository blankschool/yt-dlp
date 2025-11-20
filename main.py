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
COOKIE_YOUTUBE = "cookies/youtube.txt"

# User-Agent TikTok
TIKTOK_UA = os.getenv(
    "TIKTOK_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Proxies opcionais
TIKTOK_PROXY = os.getenv("TIKTOK_PROXY")
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY")


# ============================
# DETECTORES DE PLATAFORMA
# ============================

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url


def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url


# ============================
# MONTAGEM DE OPÇÕES DO YT-DLP
# ============================

def build_opts_for_download(url: str, outtmpl: str) -> tuple[dict, str]:
    """
    Monta ydl_opts para DOWNLOAD em melhor qualidade possível.
    Retorna (ydl_opts, platform)
    """

    # -------- TikTok --------
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



    # -------- YouTube (CORRIGIDO) --------
    if is_youtube(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,

            # Pega melhor video + melhor audio
            "format": "bv*+ba/b",

            # Sempre volta MP4
            "merge_output_format": "mp4",

            "cookiefile": COOKIE_YOUTUBE,

            # Força cliente multivariado para desbloquear formatos
            "extractor_args": {
                "youtube": {
                    "player_skip": ["webpage", "configs"],
                    "player_client": ["web", "android", "ios", "tv"],
                }
            },

            "postprocessors": [{
                "key": "FFmpegVideoRemuxer",
                "preferedformat": "mp4"
            }],
        }

        return opts, "youtube"

    # -------- Genérico --------
    opts = {
        "quiet": True,
        "noprogress": True,
        "outtmpl": outtmpl,
        "format": "best",
    }
    return opts, "generic"


# ============================
# MODELO DE REQUEST
# ============================

class VideoRequest(BaseModel):
    url: str


# ============================
# HEALTH CHECK
# ============================

@app.get("/health")
def health():
    return {"status": "ok"}


# ============================
# DOWNLOAD DE VÍDEO
# ============================

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

    # ---------- DOWNLOAD ----------
    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao baixar vídeo ({platform}): {str(e)}"
        )

    # ---------- LEITURA ----------
    try:
        with open(temp_filename, "rb") as f:
            data = f.read()
    except Exception:
        raise HTTPException(status_code=500, detail="Erro ao ler arquivo baixado")

    # ---------- LIMPEZA ----------
    try:
        os.remove(temp_filename)
    except Exception:
        pass

    # ---------- RESPOSTA ----------
    return Response(
        content=data,
        media_type="video/mp4",
        headers={"Content-Disposition": 'attachment; filename="video.mp4"'}
    )
