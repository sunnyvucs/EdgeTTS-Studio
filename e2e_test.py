# -*- coding: utf-8 -*-
"""E2E test suite for Edge TTS Web App"""
import io
import json
import sys
import time
import urllib.request
import urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

BASE = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0

def req(method, path, body=None, expect_status=200):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body else None
    headers = {'Content-Type': 'application/json'} if data else {}
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            status = resp.status
            content = resp.read()
            return status, content
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        print(f"  PASS  {name}")
        PASS += 1
    else:
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1

# ── 1. Static routes ──────────────────────────────────────────────────────────
print("\n── Static Routes ──")
s, b = req("GET", "/")
check("GET / returns 200", s == 200)
check("GET / returns HTML", b"<!DOCTYPE html>" in b or b"<!doctype html>" in b.lower())

s, b = req("GET", "/static/css/style.css")
check("GET /static/css/style.css returns 200", s == 200)

s, b = req("GET", "/static/js/app.js")
check("GET /static/js/app.js returns 200", s == 200)

# ── 2. Voices API ─────────────────────────────────────────────────────────────
print("\n── Voices API ──")
s, b = req("GET", "/api/voices")
check("GET /api/voices returns 200", s == 200)
data = json.loads(b)
check("voices response has 'voices' key", "voices" in data)
check("voices response has 'allStyles' key", "allStyles" in data)
check("Hindi (India) group present", "Hindi (India)" in data.get("voices", {}))
check("English (US) group present", "English (US)" in data.get("voices", {}))
check("allStyles has 9 entries", len(data.get("allStyles", [])) == 9)

# ── 3. Voice styles API ───────────────────────────────────────────────────────
print("\n── Voice Styles API ──")
s, b = req("GET", "/api/voice-styles/en-US-AriaNeural")
check("GET /api/voice-styles/en-US-AriaNeural returns 200", s == 200)
data = json.loads(b)
check("styles list returned", "styles" in data and len(data["styles"]) > 0)

s, b = req("GET", "/api/voice-styles/hi-IN-SwaraNeural")
check("GET /api/voice-styles/hi-IN-SwaraNeural returns 200", s == 200)

# ── 4. Preview — basic English ────────────────────────────────────────────────
print("\n── Preview API ──")
s, b = req("POST", "/api/preview", {
    "text": "Hello, this is a test.", "voice_id": "en-US-AriaNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300
})
check("Preview English returns 200", s == 200)
data = json.loads(b)
check("Preview returns token", "token" in data, f"got {data}")
token = data.get("token", "")
check("Token is 32-char hex", len(token) == 32 and all(c in '0123456789abcdef' for c in token))

# Fetch the audio file using the token
s2, b2 = req("GET", f"/api/preview-file/{token}")
check("Preview file returns 200", s2 == 200)
check("Preview file returns audio bytes > 1000", len(b2) > 1000, f"got {len(b2)}")
check("Preview file is MP3", b2[:2] in (b'\xff\xfb', b'\xff\xe3', b'\xff\xe2', b'\xff\xf3'), f"first bytes: {b2[:2].hex()}")

# ── 5. Preview — Hindi ────────────────────────────────────────────────────────
s, b = req("POST", "/api/preview", {
    "text": "नमस्ते, यह एक परीक्षण है।", "voice_id": "hi-IN-SwaraNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300
})
check("Preview Hindi returns 200", s == 200)
token_hi = json.loads(b).get("token", "")
s2, b2 = req("GET", f"/api/preview-file/{token_hi}")
check("Preview Hindi file returns audio bytes > 1000", len(b2) > 1000)

def preview_audio_size(payload):
    """POST /api/preview then GET the file; return audio byte count."""
    s, b = req("POST", "/api/preview", payload)
    if s != 200:
        return 0
    tok = json.loads(b).get("token", "")
    if not tok:
        return 0
    s2, b2 = req("GET", f"/api/preview-file/{tok}")
    return len(b2) if s2 == 200 else 0

# ── 6. Preview — styles ───────────────────────────────────────────────────────
print("\n── Emotion Styles ──")
for style in ["cheerful", "calm", "friendly", "sad", "angry",
              "narration-professional", "newscast", "customerservice"]:
    s, b = req("POST", "/api/preview", {
        "text": "Testing emotion style.", "voice_id": "en-US-AriaNeural",
        "rate": "+0%", "pitch": "+1Hz", "style": style,
        "emphasis": "none", "pause_ms": 0
    })
    check(f"Style '{style}' preview returns 200", s == 200)

# ── 7. Preview — emphasis ─────────────────────────────────────────────────────
print("\n── Emphasis ──")
for emph in ["none", "moderate", "strong"]:
    s, b = req("POST", "/api/preview", {
        "text": "Testing emphasis level.", "voice_id": "en-US-AriaNeural",
        "rate": "+0%", "pitch": "+1Hz", "style": "default",
        "emphasis": emph, "pause_ms": 0
    })
    check(f"Emphasis '{emph}' preview returns 200", s == 200)

# ── 8. Preview — multi-sentence with pause ────────────────────────────────────
print("\n── Multi-sentence + Pause ──")
multi_text = "First sentence here. Second sentence follows. Third and final sentence."
size = preview_audio_size({
    "text": multi_text, "voice_id": "en-US-AriaNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300
})
check("Multi-sentence preview returns 200", size > 0)
check("Multi-sentence audio > 5000 bytes", size > 5000, f"got {size}")

# ── 9. Preview — long Hindi story (the mobile bug scenario) ──────────────────
print("\n── Long Hindi Story (mobile bug scenario) ──")
hindi_story = (
    "एक बार एक नदी में जोरो की बाढ़ आई। तीन दिनों के बाद बाढ़ का जोर कुछ कम हुआ। "
    "बाढ़ के पानी में ढेरों चीजें बह रही थीं। उनमें एक ताँबे का घड़ा एवं एक मिट्टी का घड़ा भी था। "
    "जब वे आपस में टकराने लगे तो मिट्टी के घड़े ने ताँबे के घड़े से कहा- भाई, हमें इस प्रकार साथ-साथ नहीं बहना चाहिए। "
    "क्योंकि यदि हम टकराएँगे तो तुम तो बच जाओगे, पर मैं टूट जाऊँगा। "
    "इसलिए तुम मुझसे दूर रहो। इस पर ताँबे के घड़े ने कहा- भाई, मैं तुम्हें नुकसान नहीं पहुँचाना चाहता। "
    "मैं तुम्हारी रक्षा करूँगा और तुम्हें बचाने की कोशिश करूँगा। "
    "लेकिन मिट्टी का घड़ा नहीं माना। वह दूर हट गया। "
    "लहरों के थपेड़ों से वह इधर-उधर भटकने लगा। "
    "अंत में वह एक पत्थर से टकराया और टूट गया। "
    "ताँबे का घड़ा बच गया। "
    "इस कहानी से हमें यह शिक्षा मिलती है कि हमें अपने से बड़ों की बात माननी चाहिए। "
    "और एकता में ही शक्ति होती है।"
)
t0 = time.monotonic()
s, b = req("POST", "/api/preview", {
    "text": hindi_story, "voice_id": "hi-IN-SwaraNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300
})
elapsed_gen = time.monotonic() - t0
check("Long Hindi story token returned", s == 200)
tok_story = json.loads(b).get("token", "") if s == 200 else ""
s2, b2 = req("GET", f"/api/preview-file/{tok_story}")
elapsed = time.monotonic() - t0
check("Long Hindi story file returns 200", s2 == 200)
check("Long Hindi story audio > 100,000 bytes", len(b2) > 100_000, f"got {len(b2)}")
check(f"Long Hindi story generated in <30s (took {elapsed_gen:.1f}s)", elapsed_gen < 30)

# ── 10. Generate ──────────────────────────────────────────────────────────────
print("\n── Generate API ──")
s, b = req("POST", "/api/generate", {
    "text": "This is E2E test audio generation.", "voice_id": "en-US-AriaNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300, "filename": "e2e_test_final.mp3"
})
check("Generate returns 200", s == 200)
data = json.loads(b)
check("Generate returns status ok", data.get("status") == "ok")
check("Generate returns filename", "filename" in data)
check("Generate returns path", "path" in data)
fname = data.get("filename", "")

# ── 11. Download ──────────────────────────────────────────────────────────────
print("\n── Download API ──")
if fname:
    s, b = req("GET", f"/api/download/{fname}")
    check("Download generated file returns 200", s == 200)
    check("Download returns audio bytes > 1000", len(b) > 1000)

s, b = req("GET", "/api/download/no_such_file_xyz.mp3")
check("Download non-existent file returns 404", s == 404)

# invalid preview token
s, b = req("GET", "/api/preview-file/notavalidtoken")
check("Preview-file invalid token returns 400", s == 400)
s, b = req("GET", "/api/preview-file/a" * 32)  # valid hex but doesn't exist
check("Preview-file missing token returns 404", s == 404)

# ── 12. Error handling ────────────────────────────────────────────────────────
print("\n── Error Handling ──")
s, b = req("POST", "/api/preview", {
    "text": "", "voice_id": "en-US-AriaNeural",
    "rate": "+0%", "pitch": "+1Hz", "style": "default",
    "emphasis": "none", "pause_ms": 300
})
check("Empty text preview returns 400", s == 400)

# ── 13. Log files ─────────────────────────────────────────────────────────────
print("\n── Log Files ──")
import os
from pathlib import Path
log_dir = Path("logs")
check("logs/ directory exists", log_dir.exists())
access_log = log_dir / "access.log"
tts_log = log_dir / "tts_requests.log"
check("access.log exists", access_log.exists())
check("tts_requests.log exists", tts_log.exists())
if access_log.exists():
    content = access_log.read_text(encoding='utf-8', errors='replace')
    check("access.log has entries", len(content.strip()) > 0)
    check("access.log has IP field", "IP=" in content)
    check("access.log has Device field", "Device=" in content)
if tts_log.exists():
    content = tts_log.read_text(encoding='utf-8', errors='replace')
    check("tts_requests.log has entries", len(content.strip()) > 0)
    check("tts_requests.log has Action field", "Action=" in content)
    check("tts_requests.log has TextLen field", "TextLen=" in content)

# ── Summary ───────────────────────────────────────────────────────────────────
total = PASS + FAIL
print(f"\n{'='*50}")
print(f"  Results: {PASS}/{total} passed" + (f"  ({FAIL} failed)" if FAIL else "  ALL PASS"))
print(f"{'='*50}\n")
sys.exit(0 if FAIL == 0 else 1)
