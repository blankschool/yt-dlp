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

# Proxies opcionais
TIKTOK_PROXY = os.getenv("TIKTOK_PROXY")
INSTAGRAM_PROXY = os.getenv("INSTAGRAM_PROXY")


# Detectores
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

    # --------------- TikTok ---------------
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

    # --------------- Instagram ---------------
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

    # --------------- YouTube (versão corrigida e estável) ---------------
    if is_youtube(url):
        opts = {
            "quiet": True,
            "noprogress": True,
            "outtmpl": outtmpl,

            # FORMAT CORRIGIDO – MELHOR VÍDEO + MELHOR ÁUDIO
            "format": "bv*+ba/b",

            # SEMPRE remuxa para MP4
            "merge_output_format": "mp4",

            "cookiefile": COOKIE_YOUTUBE,

            # Bypass de player restrictions
            "extractor_args": {
                "youtube": {
                    "player_skip": ["webpage", "configs"],
                    "player_c_
