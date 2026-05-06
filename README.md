# Edge TTS Studio

A fully local, LAN-accessible web application for multilingual Text-to-Speech generation — with emotion presets, parallel audio synthesis, and an integrated video pipeline powered by Remotion.

Built with FastAPI + Microsoft Edge TTS + FFmpeg. Accessible from any device on your network (desktop, mobile, tablet).

---

## What it does

- Type text → choose a voice, emotion, speed, and pitch → get a clean MP3 in seconds
- Supports **Hindi and English** (India / US / UK / Australia) voices
- **9 emotion presets** — cheerful, calm, sad, angry, newscast, and more
- Splits long text into sentences automatically, generates them **in parallel**, then stitches with configurable pauses using FFmpeg
- **Video Studio mode** — feed scenes with text + audio into a Remotion pipeline and render an animated MP4
- Runs entirely on your local machine — only Edge TTS itself calls Microsoft's servers for voice synthesis

---

## Features

| Feature | Detail |
|---|---|
| Voices | Hindi (India), English (India / US / UK / Australia) |
| Speed control | 0.5× – 2.0× |
| Pitch control | −20Hz – +20Hz |
| Emotion presets | 9 styles with rate/pitch delta |
| Emphasis | None / Moderate / Strong |
| Sentence pause | Configurable (default 300ms) |
| Sentence splitting | Auto-split on `.` `?` `!` `।` |
| Parallel generation | Batches of 5 sentences at once |
| Output | Clean seekable MP3 via FFmpeg concat |
| Playback | In-browser preview + file download |
| Video render | Remotion integration — render MP4 from script.json |
| Logging | Rotating access log + TTS request log |
| Theme | Dark / Light toggle |
| Responsive | Works on desktop, tablet, and mobile |

---

## Architecture

```
Browser UI (index.html)
      │
      │  POST /api/preview or /api/generate
      ▼
FastAPI (app.py)
      │
      ├── split_sentences()          ← splits on . ? ! ।
      ├── _apply_emotion()           ← adds rate/pitch deltas per style
      ├── asyncio.gather (batch=5)   ← parallel Edge TTS calls
      │       └── edge_tts.Communicate → per-sentence .mp3 files
      ├── _make_silence_file()       ← FFmpeg lavfi anullsrc → silence.mp3
      └── _ffmpeg_concat()           ← FFmpeg concat demuxer → final.mp3
                                              │
                                              ▼
                                    OUTPUT_AUDIO/tts_YYYYMMDD_HHMMSS.mp3

Video Studio (video.html)
      │
      │  POST /api/video/render
      ▼
FastAPI writes script.json → copies audio → runs `npm run render`
      │
      ▼
Motion Graphics (Remotion) → out/video.mp4
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| TTS engine | Microsoft Edge TTS (`edge-tts`) |
| Audio processing | FFmpeg (sentence concat + silence) |
| Frontend | Jinja2 templates, Vanilla JS, CSS |
| Video pipeline | Remotion (Node.js) |
| Logging | Python `RotatingFileHandler` |

---

## Prerequisites

- Python 3.10+
- [FFmpeg](https://ffmpeg.org/download.html) installed and on `PATH`
- Internet connection (Edge TTS calls Microsoft's servers for synthesis)
- Node.js (only if using the Video Studio feature)

---

## Setup & Run

**Windows (one-click):**
```
setup.bat    ← creates venv + installs dependencies (run once)
run.bat      ← starts the server
```

**Manual:**
```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS / Linux

pip install -r requirements.txt
python app.py
```

The server starts on `http://0.0.0.0:8000` and prints the LAN IP on startup:
```
Edge TTS Web App running
  Local:   http://localhost:8000
  Network: http://192.168.x.x:8000
```

Open either URL in any browser on the same network.

---

## Project Structure

```
YTAudioGeneration/
├── app.py                    ← FastAPI backend (TTS + Video Studio)
├── templates/
│   ├── index.html            ← TTS Studio UI
│   └── video.html            ← Video Studio UI
├── static/
│   ├── css/style.css
│   └── js/app.js
├── OUTPUT_AUDIO/             ← Generated MP3s (auto-created)
│   └── .previews/            ← Temp preview files (auto-created)
├── logs/
│   ├── access.log            ← HTTP access log (rotating)
│   └── tts_requests.log      ← TTS generation log (rotating)
├── requirements.txt
├── setup.bat                 ← One-time setup
├── run.bat                   ← Start server
└── README.md
```

---

## Emotion Presets

Emotions apply rate and pitch offsets on top of the slider values:

| Style | Rate Δ | Pitch Δ |
|---|---|---|
| default | 0 | 0 |
| cheerful | +15% | +4Hz |
| calm | −15% | −3Hz |
| friendly | +5% | +2Hz |
| sad | −20% | −5Hz |
| angry | +20% | +8Hz |
| narration-professional | −5% | 0 |
| newscast | +5% | 0 |
| customerservice | −5% | +2Hz |

---

## API Reference

### `GET /api/voices`
Returns voices grouped by language + all emotion styles.

### `POST /api/preview`
Generate audio and return a short-lived token for playback.

```json
{
  "text": "Hello, this is a test.",
  "voice_id": "en-US-AriaNeural",
  "rate": "+0%",
  "pitch": "+1Hz",
  "style": "cheerful",
  "emphasis": "none",
  "pause_ms": 300
}
```
Response: `{ "token": "38dcb278..." }`

### `GET /api/preview-file/{token}`
Stream the preview audio (supports HTTP range requests).

### `POST /api/generate`
Generate and save audio permanently to `OUTPUT_AUDIO/`. Same body as preview, plus optional `"filename"` field.

### `GET /api/download/{filename}`
Download a saved file from `OUTPUT_AUDIO/`.

### `POST /api/video/render`
Feed a scenes array → writes `script.json` + audio files → triggers Remotion render → returns path to `video.mp4`.

### `GET /api/video/download`
Download the last rendered `video.mp4`.

---

## Using the API from Python

```python
import requests

BASE = "http://localhost:8000"

payload = {
    "text": "नमस्ते, यह एक परीक्षण है।",
    "voice_id": "hi-IN-SwaraNeural",
    "rate": "+0%",
    "pitch": "+1Hz",
    "style": "calm",
    "pause_ms": 400,
}

# Preview
token = requests.post(f"{BASE}/api/preview", json=payload).json()["token"]
audio = requests.get(f"{BASE}/api/preview-file/{token}").content
open("output.mp3", "wb").write(audio)

# Save permanently
payload["filename"] = "hindi_test.mp3"
print(requests.post(f"{BASE}/api/generate", json=payload).json())
```

---

> Built as a learning project exploring FastAPI, async audio pipelines, FFmpeg integration, and local TTS systems.
