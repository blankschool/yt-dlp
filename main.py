import os
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from yt_dlp import YoutubeDL
import uuid

app = FastAPI(
    title="yt-dlp Downloader",
    description="Baixa vídeos TikTok/YouTube e retorna binário",
    version="3.0.0",
)

COOKIE_FILE = "cookies/tiktok.txt"

TIKTOK_UA = os.getenv("TIKTOK_UA",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url or "vt.tiktok.com" in url

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

class VideoRequest(BaseModel):
    url: str


@app.post("/download")
def download(req: VideoRequest):
    url = req.url
    temp_filename = f"/tmp/{uuid.uuid4()}.mp4"

    # TikTok
    if is_tiktok(url):
        ydl_opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": temp_filename,
            "cookiefile": COOKIE_FILE,
            "format": "best",
            "http_headers": {
                "User-Agent": TIKTOK_UA,
                "Referer": "https://www.tiktok.com/",
            }
        }

    # YouTube (melhor qualidade)
    elif is_youtube(url):
        ydl_opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": temp_filename,
            "format": "best[ext=mp4]/best"
        }

    # Outros sites
    else:
        ydl_opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": temp_filename,
            "format": "best"
        }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erro ao baixar vídeo: {str(e)}"
        )

    # Ler o binário
    try:
        with open(temp_filename, "rb") as f:
            data = f.read()
    except:
        raise HTTPException(status_code=500, detail="Erro ao ler arquivo baixado")

    # Apaga o arquivo temporário
    try:
        os.remove(temp_filename)
    except:
        pass

    return Response(
        content=data,
        media_type="video/mp4",
        headers={
            "Content-Disposition": 'attachment; filename="video.mp4"'
        }
    )
