import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from fastapi import FastAPI, HTTPException, Response, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, UnsupportedError

# Configurações de logging
DEBUG_YTDLP = os.getenv("DEBUG_YTDLP", "0") == "1"
logging.basicConfig(level=logging.DEBUG if DEBUG_YTDLP else logging.INFO)
logger = logging.getLogger("downloader")

app = FastAPI(
    title="Universal Downloader Completo",
    description="API completa para download de mídia usando yt-dlp, suportando todas as plataformas e opções principais.",
    version="6.0.0",
)

# Caminhos base
BASE_DIR = Path(__file__).resolve().parent
COOKIES_DIR = BASE_DIR / "cookies"

# Cookies padrões (expandidos para múltiplas plataformas)
COOKIE_FILES = {
    "youtube": str(COOKIES_DIR / "youtube_cookies.txt"),
    "tiktok": str(COOKIES_DIR / "tiktok.txt"),
    "instagram": str(COOKIES_DIR / "instagram.txt"),
    "twitter": str(COOKIES_DIR / "twitter.txt"),
    "generic": str(COOKIES_DIR / "cookies.txt"),  # Para outros sites
}

# User-Agents personalizáveis
USER_AGENTS = {
    "tiktok": os.getenv(
        "TIKTOK_UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "instagram": os.getenv(
        "INSTAGRAM_UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "default": os.getenv(
        "DEFAULT_UA",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Proxies opcionais por plataforma
PROXIES = {
    "tiktok": os.getenv("TIKTOK_PROXY"),
    "instagram": os.getenv("INSTAGRAM_PROXY"),
    "youtube": os.getenv("YOUTUBE_PROXY"),
    "default": os.getenv("DEFAULT_PROXY"),
}

# Controle de verbosidade
QUIET_FLAG = not DEBUG_YTDLP

def detect_platform(url: str) -> str:
    """Detecta a plataforma baseada na URL."""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "tiktok.com" in url_lower:
        return "tiktok"
    elif "instagram.com" in url_lower or "instagr.am" in url_lower:
        return "instagram"
    elif "twitter.com" in url_lower or "x.com" in url_lower:
        return "twitter"
    else:
        return "generic"

def ensure_cookie(cookie_path: str, platform: str):
    """Verifica se o cookie existe, não está vazio e é legível."""
    if not os.path.exists(cookie_path):
        logger.warning(f"Cookie para {platform} não encontrado: {cookie_path}")
        raise HTTPException(status_code=401, detail=f"Cookie de {platform.capitalize()} ausente. Crie {cookie_path}.")
    if os.path.getsize(cookie_path) == 0:
        logger.warning(f"Cookie para {platform} vazio: {cookie_path}")
        raise HTTPException(status_code=401, detail=f"Cookie de {platform.capitalize()} vazio.")
    if not os.access(cookie_path, os.R_OK):
        logger.warning(f"Cookie para {platform} sem permissão de leitura: {cookie_path}")
        raise HTTPException(status_code=401, detail=f"Cookie de {platform.capitalize()} ilegível.")

def build_base_opts(platform: str, outtmpl: str, custom_opts: Dict[str, Any] = None) -> Dict[str, Any]:
    """Constrói opções base do yt-dlp."""
    opts = {
        "quiet": QUIET_FLAG,
        "no_warnings": QUIET_FLAG,
        "outtmpl": outtmpl,
        "restrictfilenames": True,  # Para compatibilidade
        "format": "best",  # Padrão, pode ser sobrescrito
        "http_headers": {
            "User-Agent": USER_AGENTS.get(platform, USER_AGENTS["default"]),
        },
    }

    # Adiciona cookie se aplicável
    cookie_file = COOKIE_FILES.get(platform)
    if cookie_file and os.path.exists(cookie_file):
        ensure_cookie(cookie_file, platform)
        opts["cookiefile"] = cookie_file

    # Adiciona proxy se configurado
    proxy = PROXIES.get(platform) or PROXIES["default"]
    if proxy:
        opts["proxy"] = proxy

    # Opções comuns avançadas
    opts.update({
        "noplaylist": False,  # Baixar playlists por padrão
        "ignoreerrors": False,
        "retries": 10,
        "fragment_retries": 10,
        "extractaudio": False,
        "audioformat": "mp3",  # Se extrair áudio
        "embed_subs": False,
        "write_subs": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "subtitleslangs": ["en", "pt"],  # Idiomas preferidos
        "merge_output_format": "mp4",
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
        ],
        "prefer_ffmpeg": True,
        "ffmpeg_location": os.getenv("FFMPEG_PATH", "ffmpeg"),
    })

    # Opções específicas por plataforma
    if platform == "youtube":
        opts.update({
            "format": (
                "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
            ),
            "extractor_args": {
                "youtube": {
                    "player_client": ["web", "android"],
                    "skip": ["hls", "dash"],  # Evita formatos problemáticos
                }
            },
        })
    elif platform == "tiktok":
        opts["http_headers"].update({
            "Referer": "https://www.tiktok.com/",
            "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8",
        })
    elif platform == "instagram":
        opts["http_headers"].update({
            "Referer": "https://www.instagram.com/",
        })
    elif platform == "twitter":
        opts["extractor_args"] = {"twitter": {"include_rts": True}}

    # Mescla opções customizadas (sobrescreve)
    if custom_opts:
        opts.update(custom_opts)

    return opts

def download_and_stream(url: str, opts: Dict[str, Any]) -> Tuple[bytes, str]:
    """Baixa o conteúdo e retorna dados binários com tipo MIME."""
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
        temp_path = tmp_file.name
        opts["outtmpl"] = temp_path

    try:
        with YoutubeDL(opts) as ydl:
            # Tenta download com fallbacks para formatos em YouTube
            if detect_platform(url) == "youtube":
                format_candidates = [
                    "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
                    "bv*+ba/bestvideo+bestaudio/best",
                    "bestvideo+bestaudio/best",
                    "best",
                ]
                last_error = None
                for fmt in format_candidates:
                    temp_opts = opts.copy()
                    temp_opts["format"] = fmt
                    try:
                        logger.info(f"Tentando formato: {fmt}")
                        ydl.download([url])
                        last_error = None
                        break
                    except (DownloadError, UnsupportedError) as e:
                        last_error = e
                        logger.warning(f"Falha com {fmt}: {e}")
                if last_error:
                    raise last_error
            else:
                ydl.download([url])

        # Lê o arquivo baixado
        if os.path.exists(temp_path):
            with open(temp_path, "rb") as f:
                data = f.read()
            mime_type = "video/mp4"  # Padrão; pode ser detectado melhor
            return data, mime_type
        else:
            raise HTTPException(status_code=500, detail="Arquivo não gerado após download")
    except Exception as e:
        logger.exception(f"Erro no download: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao baixar: {str(e)}")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)

class DownloadRequest(BaseModel):
    url: str = Field(..., description="URL do vídeo ou playlist")
    format_selector: Optional[str] = Field(None, description="Seletor de formato (ex: 'best', 'worst', 'bestaudio')")
    extract_audio: bool = Field(False, description="Extrair áudio apenas")
    audio_format: Optional[str] = Field("mp3", description="Formato de áudio (mp3, m4a, etc.)")
    list_formats: bool = Field(False, description="Listar formatos disponíveis (não baixa)")
    playlist_items: Optional[str] = Field(None, description="Itens da playlist (ex: '1-5', '2')")
    write_subs: bool = Field(False, description="Baixar legendas")
    sub_langs: Optional[List[str]] = Field(default_factory=list, description="Idiomas de legenda")
    embed_subs: bool = Field(False, description="Embedar legendas no vídeo")
    output_template: Optional[str] = Field("%(title)s.%(ext)s", description="Template de saída")
    rate_limit: Optional[str] = Field(None, description="Limite de taxa (ex: '500K')")
    retries: Optional[int] = Field(10, description="Número de retries")
    no_overwrites: bool = Field(True, description="Não sobrescrever arquivos")
    verbose: bool = Field(False, description="Modo verbose")

class FormatInfo(BaseModel):
    formats: List[Dict[str, Any]]
    requested_formats: List[Dict[str, Any]]

@app.get("/health")
def health():
    return {"status": "ok", "version": "6.0.0"}

@app.get("/info")
def get_info(url: str, platform: Optional[str] = None):
    """Obtém informações sobre o vídeo/playlist sem baixar."""
    if not url:
        raise HTTPException(status_code=400, detail="URL é obrigatória")
    
    detected_platform = platform or detect_platform(url)
    cookie_file = COOKIE_FILES.get(detected_platform)
    if cookie_file:
        ensure_cookie(cookie_file, detected_platform)
    
    opts = build_base_opts(detected_platform, "%(id)s.%(ext)s", {"skip_download": True, "dump_single_json": True})
    
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "view_count": info.get("view_count"),
                "platform": detected_platform,
                "formats": info.get("formats", []),
                "is_live": info.get("is_live"),
                "playlist": info.get("playlist") is not None,
                "playlist_count": info.get("playlist_count"),
            }
    except Exception as e:
        logger.exception(f"Erro ao extrair info: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao obter info: {str(e)}")

@app.get("/list-formats")
def list_formats(url: str, platform: Optional[str] = None):
    """Lista formatos disponíveis para a URL."""
    detected_platform = platform or detect_platform(url)
    opts = build_base_opts(detected_platform, "%(id)s.%(ext)s", {"listformats": True})
    
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])  # Isso só lista, não baixa
        return {"message": "Formatos listados no log. Use /info para JSON."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao listar formatos: {str(e)}")

@app.post("/download")
def download_video(req: DownloadRequest):
    """Endpoint principal para download, com opções completas."""
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL é obrigatória")
    
    if url.startswith("="):
        url = url[1:].strip()
    
    platform = detect_platform(url)
    cookie_file = COOKIE_FILES.get(platform)
    if cookie_file:
        ensure_cookie(cookie_file, platform)
    
    # Constrói opts com customizações
    custom_opts = {}
    if req.format_selector:
        custom_opts["format"] = req.format_selector
    if req.extract_audio:
        custom_opts["extractaudio"] = True
        custom_opts["audioformat"] = req.audio_format
    if req.playlist_items:
        custom_opts["playlist_items"] = req.playlist_items
    if req.write_subs:
        custom_opts["writesubtitles"] = True
        custom_opts["writeautomaticsub"] = True
        custom_opts["subtitleslangs"] = req.sub_langs or ["en", "pt"]
    if req.embed_subs:
        custom_opts["embed_subs"] = True
    if req.output_template:
        custom_opts["outtmpl"] = req.output_template
    if req.rate_limit:
        custom_opts["limit_rate"] = req.rate_limit
    custom_opts["retries"] = req.retries
    custom_opts["overwrites"] = not req.no_overwrites
    custom_opts["verbose"] = req.verbose
    
    if req.list_formats:
        # Modo lista apenas
        opts = build_base_opts(platform, "%(id)s.%(ext)s", {**custom_opts, "listformats": True})
        try:
            with YoutubeDL(opts) as ydl:
                ydl.download([url])
            return {"message": "Formatos listados com sucesso."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao listar: {str(e)}")
    
    # Download real
    opts = build_base_opts(platform, "%(id)s.%(ext)s", custom_opts)
    
    data, mime_type = download_and_stream(url, opts)
    
    filename = f"download_{uuid.uuid4().hex[:8]}.mp4"
    return Response(
        content=data,
        media_type=mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Access-Control-Expose-Headers": "Content-Disposition",
        }
    )

@app.get("/search")
def search_youtube(query: str, type: str = "video", max_results: int = Query(10, le=50)):
    """Busca no YouTube (exemplo de uso de busca)."""
    search_url = f"ytsearch{type}:{query}:{max_results}"
    opts = build_base_opts("youtube", "%(id)s.%(ext)s", {"extract_flat": True})
    
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
            if "entries" in info:
                return [
                    {
                        "title": entry.get("title"),
                        "id": entry.get("id"),
                        "url": f"https://youtube.com/watch?v={entry.get('id')}",
                        "duration": entry.get("duration"),
                    }
                    for entry in info["entries"][:max_results]
                ]
            return []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro na busca: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
