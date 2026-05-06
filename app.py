"""
Edge TTS Local Web App
FastAPI backend — Hindi & English TTS, accessible on LAN
Features: FFmpeg concat pipeline, sentence-level temp files, emotion presets, logging
"""

import asyncio
import json
import logging
import re
import shutil
import subprocess
import time
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

import edge_tts
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.requests import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# ── Directories ────────────────────────────────────────────────────────────────

OUTPUT_DIR  = Path("OUTPUT_AUDIO")
OUTPUT_DIR.mkdir(exist_ok=True)

PREVIEW_DIR = OUTPUT_DIR / ".previews"
PREVIEW_DIR.mkdir(exist_ok=True)

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# ── Logging setup ──────────────────────────────────────────────────────────────

def _make_logger(name: str, filename: str, max_bytes: int = 5_000_000) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(
        LOG_DIR / filename,
        maxBytes=max_bytes,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger

access_log = _make_logger("access",  "access.log")
tts_log    = _make_logger("tts",     "tts_requests.log", max_bytes=10_000_000)

# ── Device detection ───────────────────────────────────────────────────────────

def _detect_device(ua: str) -> str:
    ua = ua.lower()
    if "ipad" in ua or "tablet" in ua or ("android" in ua and "mobile" not in ua):
        return "Tablet"
    if any(k in ua for k in ("iphone", "android", "mobile", "blackberry", "windows phone")):
        return "Mobile"
    return "Desktop"

# ── Access log middleware ──────────────────────────────────────────────────────

class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start

        ip     = request.client.host if request.client else "unknown"
        ua     = request.headers.get("user-agent", "")
        device = _detect_device(ua)
        ts     = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path   = request.url.path

        access_log.info(
            f'[{ts}] IP={ip} Device={device} Method={request.method} '
            f'Path={path} Status={response.status_code} Time={elapsed:.2f}s '
            f'UA="{ua[:120]}"'
        )
        return response

# ── TTS request logger ─────────────────────────────────────────────────────────

def _log_tts(ip: str, req, action: str, text: str) -> None:
    ts           = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text_preview = text.replace("\n", " ").strip()[:150]
    tts_log.info(
        f"[{ts}] Action={action} IP={ip} Voice={req.voice_id} "
        f"Rate={req.rate} Pitch={req.pitch} Style={req.style} "
        f"Emphasis={req.emphasis} PauseMs={req.pause_ms} "
        f"TextLen={len(text)} Text=\"{text_preview}\""
    )

# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(title="Edge TTS Web App")
app.add_middleware(AccessLogMiddleware)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ── Voice locale groups ────────────────────────────────────────────────────────

TARGET_LOCALES = {
    "hi-IN": "Hindi (India)",
    "en-IN": "English (India)",
    "en-US": "English (US)",
    "en-GB": "English (UK)",
    "en-AU": "English (Australia)",
}

# ── Emotion presets ────────────────────────────────────────────────────────────

EMOTION_PRESETS: dict[str, dict] = {
    "default":                {"rate_delta":  0,   "pitch_delta":  0},
    "cheerful":               {"rate_delta": +15,  "pitch_delta": +4},
    "calm":                   {"rate_delta": -15,  "pitch_delta": -3},
    "friendly":               {"rate_delta":  +5,  "pitch_delta": +2},
    "sad":                    {"rate_delta": -20,  "pitch_delta": -5},
    "angry":                  {"rate_delta": +20,  "pitch_delta": +8},
    "narration-professional": {"rate_delta":  -5,  "pitch_delta":  0},
    "newscast":               {"rate_delta":  +5,  "pitch_delta":  0},
    "customerservice":        {"rate_delta":  -5,  "pitch_delta": +2},
}

ALL_STYLES = list(EMOTION_PRESETS.keys())


# ── Request model ──────────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    text: str
    voice_id: str
    rate: str    = "+0%"
    pitch: str   = "+1Hz"
    style: str   = "default"
    emphasis: str = "none"
    pause_ms: int = 300
    filename: Optional[str] = None

# ── Sentence splitting ─────────────────────────────────────────────────────────

_SENTENCE_RE = re.compile(r'(?<=[.?!।])\s+')

def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]

# ── Prosody helpers ────────────────────────────────────────────────────────────

def _parse_rate(s: str) -> int:
    m = re.match(r'^([+-]?\d+)%$', s.strip())
    return int(m.group(1)) if m else 0

def _parse_pitch(s: str) -> int:
    m = re.match(r'^([+-]?\d+)Hz$', s.strip())
    return int(m.group(1)) if m else 0

def _apply_emotion(rate_str: str, pitch_str: str, style: str) -> tuple[str, str]:
    p  = EMOTION_PRESETS.get(style, EMOTION_PRESETS["default"])
    r  = max(-50, min(200, _parse_rate(rate_str)  + p["rate_delta"]))
    hz = max(-20, min( 20, _parse_pitch(pitch_str) + p["pitch_delta"]))
    return (f"+{r}%" if r >= 0 else f"{r}%"), (f"+{hz}Hz" if hz >= 0 else f"{hz}Hz")

def _emphasis_rate_boost(emphasis: str) -> int:
    return {"none": 0, "moderate": 5, "strong": 10}.get(emphasis, 0)

# ── Audio generation ───────────────────────────────────────────────────────────

# Max parallel Edge TTS connections per request (avoids rate-limiting)
_BATCH_SIZE = 5

async def _tts_to_file(text: str, voice_id: str, rate: str, pitch: str, dest: Path) -> None:
    """Generate TTS for one sentence and write directly to dest file."""
    communicate = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch)
    with dest.open("wb") as f:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])


def _make_silence_file(duration_ms: int, dest: Path) -> None:
    """Generate a silent MP3 of the given duration using FFmpeg."""
    duration_s = duration_ms / 1000.0
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r=24000:cl=mono",
            "-t", str(duration_s),
            "-q:a", "9",
            "-acodec", "libmp3lame",
            str(dest),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _ffmpeg_concat(parts: list[Path], output: Path) -> None:
    """Concatenate MP3 files using FFmpeg concat demuxer — produces a clean, seekable MP3."""
    concat_list = output.parent / f"{output.stem}_concat.txt"
    with concat_list.open("w", encoding="utf-8") as f:
        for p in parts:
            # Must use absolute paths — FFmpeg resolves relative paths from the list file's dir
            f.write(f"file '{p.resolve().as_posix()}'\n")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    concat_list.unlink(missing_ok=True)


async def _generate_audio_to_file(req: TTSRequest, output: Path) -> None:
    """
    Full pipeline:
      1. Split text into sentences
      2. Generate each sentence to its own temp file (in parallel batches)
      3. Build silence files for pauses
      4. FFmpeg concat → final output file
    All intermediates are written to disk; nothing large lives in memory.
    """
    rate, pitch = _apply_emotion(req.rate, req.pitch, req.style)
    boost = _emphasis_rate_boost(req.emphasis)
    if boost:
        r_val = max(-50, min(200, _parse_rate(rate) + boost))
        rate  = f"+{r_val}%" if r_val >= 0 else f"{r_val}%"

    pause_ms  = max(0, req.pause_ms)
    sentences = split_sentences(req.text)

    # Use a private temp dir inside PREVIEW_DIR so files stay on the same drive
    tmp_dir = output.parent / f"_tmp_{output.stem}"
    tmp_dir.mkdir(exist_ok=True)
    try:
        if len(sentences) > 1 and pause_ms > 0:
            # ── 1. Generate sentence files in parallel batches ──────────────
            sent_files: list[Path] = []
            for i in range(0, len(sentences), _BATCH_SIZE):
                batch     = sentences[i : i + _BATCH_SIZE]
                batch_paths = [tmp_dir / f"s{i + j:04d}.mp3" for j in range(len(batch))]
                await asyncio.gather(
                    *[_tts_to_file(s, req.voice_id, rate, pitch, p)
                      for s, p in zip(batch, batch_paths)]
                )
                sent_files.extend(batch_paths)

            # ── 2. Generate one shared silence file ─────────────────────────
            silence_file = tmp_dir / "silence.mp3"
            await asyncio.get_event_loop().run_in_executor(
                None, _make_silence_file, pause_ms, silence_file
            )

            # ── 3. Build concat order: s0, pause, s1, pause, …, sN ─────────
            parts: list[Path] = []
            for idx, sf in enumerate(sent_files):
                parts.append(sf)
                if idx < len(sent_files) - 1:
                    parts.append(silence_file)

            # ── 4. FFmpeg concat → final file ───────────────────────────────
            await asyncio.get_event_loop().run_in_executor(
                None, _ffmpeg_concat, parts, output
            )

        else:
            # Single sentence or no pause — write directly to output
            await _tts_to_file(req.text, req.voice_id, rate, pitch, output)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

# ── File helpers ───────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    name = Path(name).name
    name = re.sub(r'[^\w\-_\. ]', '_', name)
    if not name.lower().endswith(".mp3"):
        name += ".mp3"
    return name

def _new_filename() -> str:
    return f"tts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp3"

# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/video", response_class=HTMLResponse)
async def video_studio(request: Request):
    return templates.TemplateResponse(request, "video.html")


@app.get("/api/voices")
async def get_voices():
    all_voices = await edge_tts.list_voices()
    grouped: dict[str, list] = {}
    for v in all_voices:
        locale = v.get("Locale", "")
        if locale not in TARGET_LOCALES:
            continue
        group = TARGET_LOCALES[locale]
        grouped.setdefault(group, []).append({
            "id":     v["ShortName"],
            "name":   v["FriendlyName"],
            "gender": v["Gender"],
            "locale": locale,
            "styles": ALL_STYLES,
        })
    ordered = {k: grouped[k] for k in TARGET_LOCALES.values() if k in grouped}
    return JSONResponse({"voices": ordered, "allStyles": ALL_STYLES})


@app.get("/api/voice-styles/{voice_id}")
async def voice_styles(voice_id: str):
    return JSONResponse({"styles": ALL_STYLES})


@app.post("/api/preview")
async def preview(request: Request, req: TTSRequest):
    """
    Generate preview audio directly to a file via the FFmpeg pipeline,
    then return a token. The client fetches /api/preview-file/{token},
    which is a proper file served with Content-Length + Accept-Ranges.
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty.")
    ip = request.client.host if request.client else "unknown"
    _log_tts(ip, req, "PREVIEW", req.text)

    token    = uuid.uuid4().hex
    out_path = PREVIEW_DIR / f"{token}.mp3"
    try:
        await _generate_audio_to_file(req, out_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse({"token": token})


@app.get("/api/preview-file/{token}")
async def preview_file(token: str):
    """Serve a previously generated preview file with full range-request support."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(status_code=400, detail="Invalid token.")
    path = PREVIEW_DIR / f"{token}.mp3"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Preview not found.")
    return FileResponse(
        str(path),
        media_type="audio/mpeg",
        headers={
            "Accept-Ranges":  "bytes",
            "Content-Disposition": "inline",
            "Cache-Control":  "no-store",   # fresh file every time
        },
    )


@app.post("/api/generate")
async def generate(request: Request, req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text is empty.")
    ip = request.client.host if request.client else "unknown"
    _log_tts(ip, req, "GENERATE", req.text)

    filename = _safe_filename(req.filename.strip() if req.filename else _new_filename())
    out_path  = OUTPUT_DIR / filename

    try:
        await _generate_audio_to_file(req, out_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return JSONResponse({
        "status":   "ok",
        "filename": filename,
        "path":     str(out_path.resolve()),
    })


@app.get("/api/download/{filename}")
async def download(filename: str):
    filename  = Path(filename).name
    file_path = OUTPUT_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(
        str(file_path),
        media_type="audio/mpeg",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# ── Video Studio routes ────────────────────────────────────────────────────────

# Absolute path to the Motion Graphics Remotion project
_MG_PROJECT = Path(r"D:\AI\AI Projects\Motion Graphics")


class VideoRenderRequest(BaseModel):
    scenes: list


@app.post("/api/video/render")
async def video_render(req: VideoRenderRequest):
    """
    1. Write scenes list → Motion Graphics/data/script.json
    2. Copy audio files from OUTPUT_AUDIO/ → Motion Graphics/public/audio/
    3. Run `npm run pipeline` in the Motion Graphics project directory
    """
    import json as _json
    import asyncio as _asyncio

    script_path = _MG_PROJECT / "data" / "script.json"
    audio_src   = OUTPUT_DIR       # D:\PythonProjects\YTAudioGeneration\OUTPUT_AUDIO
    audio_dst   = _MG_PROJECT / "public" / "audio"

    try:
        # Step 1 – write script.json
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(
            _json.dumps(req.scenes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Step 2 – copy generated scene audio files
        audio_dst.mkdir(parents=True, exist_ok=True)
        for scene in req.scenes:
            sid = scene.get("id")
            if sid is None:
                continue
            src_file = audio_src / f"scene_{sid}.mp3"
            if src_file.exists():
                shutil.copy2(str(src_file), str(audio_dst / f"scene_{sid}.mp3"))

        # Step 3 – run the Remotion render
        # On Windows, npm is npm.cmd — use shell=True so the PATH resolves correctly
        proc = await _asyncio.create_subprocess_shell(
            "npm run render",
            cwd=str(_MG_PROJECT),
            stdout=_asyncio.subprocess.PIPE,
            stderr=_asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        output_text = stdout.decode("utf-8", errors="replace") if stdout else ""

        if proc.returncode != 0:
            raise RuntimeError(f"npm run render exited {proc.returncode}:\n{output_text[-800:]}")

        output_file = _MG_PROJECT / "out" / "video.mp4"
        return JSONResponse({
            "status":  "ok",
            "message": "Render complete.",
            "output":  str(output_file.resolve()) if output_file.exists() else None,
        })

    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/video/download")
async def video_download():
    """Download the rendered video.mp4 from the Motion Graphics project."""
    video_path = _MG_PROJECT / "out" / "video.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="video.mp4 not found. Run the render first.")
    return FileResponse(
        str(video_path),
        media_type="video/mp4",
        filename="video.mp4",
        headers={"Content-Disposition": 'attachment; filename="video.mp4"'},
    )


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import socket
    host, port = "0.0.0.0", 8000
    try:
        lan_ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        lan_ip = "127.0.0.1"
    print(f"\n  Edge TTS Web App running")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{lan_ip}:{port}")
    print(f"  Logs:    {LOG_DIR.resolve()}\n")
    uvicorn.run(app, host=host, port=port)
