/* Edge TTS Web App — Frontend Logic */

'use strict';

// ── State ──────────────────────────────────────────────────────────────────────

const state = {
  voices: {},
  allStyles: [],
  currentVoiceStyles: [],       // styles supported by the selected voice
  isMobile: /Mobi|Android|iPhone|iPad|iPod/i.test(navigator.userAgent),
};

// ── DOM refs ───────────────────────────────────────────────────────────────────

const $ = id => document.getElementById(id);
const voiceSelect    = $('voice-select');
const textArea       = $('text-input');
const charCounter    = $('char-counter');
const speedSlider    = $('speed-slider');
const speedVal       = $('speed-val');
const pitchSlider    = $('pitch-slider');
const pitchVal       = $('pitch-val');
const styleSelect    = $('style-select');
const styleInfo      = $('style-info');
const emphasisSelect = $('emphasis-select');
const pauseInput     = $('pause-input');
const advToggle      = $('advanced-toggle');
const advBody        = $('advanced-body');
const filenameInput  = $('filename-input');
const playBtn        = $('play-btn');
const genBtn         = $('gen-btn');
const stopBtn        = $('stop-btn');
const resultBlock    = $('result-block');
const resultName     = $('result-filename');
const dlBtn          = $('dl-btn');
const statusDot      = $('status-dot');
const statusMsg      = $('status-msg');
const statusPath     = $('status-path');
const themeBtn       = $('theme-btn');
const audioPlayer    = $('audio-player');

// ── Theme ──────────────────────────────────────────────────────────────────────

function initTheme() {
  applyTheme(localStorage.getItem('theme') || 'dark');
}

function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  themeBtn.textContent = theme === 'dark' ? '☀ Light' : '🌙 Dark';
  localStorage.setItem('theme', theme);
}

themeBtn.addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  applyTheme(cur === 'dark' ? 'light' : 'dark');
});

// ── Advanced Controls toggle ───────────────────────────────────────────────────

advToggle.addEventListener('click', () => {
  const open = advBody.classList.toggle('open');
  advToggle.classList.toggle('open', open);
});

// ── Voices ────────────────────────────────────────────────────────────────────

async function loadVoices() {
  setStatus('Loading voices…', 'loading');
  try {
    const res = await fetch('/api/voices');
    const { voices, allStyles } = await res.json();
    state.voices  = voices;
    state.allStyles = allStyles || [];

    voiceSelect.innerHTML = '';
    for (const [group, list] of Object.entries(voices)) {
      const og = document.createElement('optgroup');
      og.label = group;
      for (const v of list) {
        const opt = document.createElement('option');
        opt.value = v.id;
        opt.dataset.styles = JSON.stringify(v.styles || []);
        const genderIcon   = v.gender === 'Female' ? '♀' : '♂';
        const friendlyName = v.name
          .replace('Microsoft ', '')
          .replace(' Online (Natural) - ', ' — ');
        opt.textContent = `${genderIcon} ${friendlyName}`;
        og.appendChild(opt);
      }
      voiceSelect.appendChild(og);
    }
    updateVoiceCapabilities();
    setStatus('Ready — select a voice and enter your text.', 'ok');
  } catch (e) {
    setStatus('Failed to load voices. Is Edge TTS installed?', 'error');
    showToast('Could not load voices: ' + e.message, 'error');
  }
}

function updateVoiceCapabilities() {
  const opt = voiceSelect.options[voiceSelect.selectedIndex];
  if (!opt) return;

  $('voice-info').textContent = opt.value ? `Voice ID: ${opt.value}` : '';

  // Parse style capabilities from data attribute
  let styles = [];
  try { styles = JSON.parse(opt.dataset.styles || '[]'); } catch (_) {}
  state.currentVoiceStyles = styles;

  // All voices support emotion presets (applied as rate/pitch adjustments)
  styleSelect.disabled  = false;
  styleInfo.textContent = 'Emotion applied as voice style preset';
  styleInfo.className   = 'style-info supported';
}

voiceSelect.addEventListener('change', updateVoiceCapabilities);

// ── Char counter ──────────────────────────────────────────────────────────────

textArea.addEventListener('input', () => {
  const n = textArea.value.length;
  charCounter.textContent = `${n} / 5000`;
  charCounter.className   = 'char-counter' +
    (n > 5000 ? ' over' : n > 4000 ? ' warn' : '');
});

// ── Sliders ───────────────────────────────────────────────────────────────────

speedSlider.addEventListener('input', () => {
  speedVal.textContent = parseFloat(speedSlider.value).toFixed(1) + 'x';
});

pitchSlider.addEventListener('input', () => {
  const v = parseInt(pitchSlider.value);
  pitchVal.textContent = (v >= 0 ? '+' : '') + v + 'Hz';
});

function getRate() {
  const speed = parseFloat(speedSlider.value);
  const pct   = Math.round((speed - 1.0) * 100);
  return (pct >= 0 ? '+' : '') + pct + '%';
}

function getPitch() {
  const hz = parseInt(pitchSlider.value);
  return (hz >= 0 ? '+' : '') + hz + 'Hz';
}

// ── Build request payload ─────────────────────────────────────────────────────

function buildPayload(extra = {}) {
  return {
    text:      textArea.value.trim(),
    voice_id:  voiceSelect.value,
    rate:      getRate(),
    pitch:     getPitch(),
    style:     styleSelect.value || 'default',
    emphasis:  emphasisSelect.value || 'none',
    pause_ms:  parseInt(pauseInput.value) || 300,
    ...extra,
  };
}

// ── Play / Preview ────────────────────────────────────────────────────────────

playBtn.addEventListener('click', async () => {
  const payload = buildPayload();
  if (!payload.text)     { showToast('Please enter some text first.', 'error'); return; }
  if (!payload.voice_id) { showToast('Please select a voice.', 'error'); return; }

  setLoading(playBtn, true, '⏳ Generating…');
  setStatus('Generating preview…', 'loading');
  stopBtn.disabled = false;

  try {
    // Step 1 — generate audio server-side and get a token
    const res = await fetch('/api/preview', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Preview failed');
    }
    const { token } = await res.json();

    // Step 2 — point the audio element at the file URL directly.
    // The browser fetches it natively with Content-Length + Accept-Ranges,
    // so mobile devices can buffer and play correctly.
    audioPlayer.src = `/api/preview-file/${token}`;
    await audioPlayer.play();
    setStatus('▶ Playing preview…', 'ok');
  } catch (e) {
    showToast('Preview error: ' + e.message, 'error');
    setStatus('Preview failed.', 'error');
    stopBtn.disabled = true;
  } finally {
    setLoading(playBtn, false, '▶ Play');
  }
});

// ── Stop ──────────────────────────────────────────────────────────────────────

stopBtn.addEventListener('click', () => {
  audioPlayer.pause();
  audioPlayer.currentTime = 0;
  setStatus('Stopped.', 'ok');
  stopBtn.disabled = true;
});

audioPlayer.addEventListener('ended', () => {
  setStatus('Ready.', 'ok');
  stopBtn.disabled = true;
});

// ── Generate ──────────────────────────────────────────────────────────────────

genBtn.addEventListener('click', async () => {
  let filename = filenameInput ? filenameInput.value.trim() : '';
  if (!filename) {
    const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 15);
    filename  = `tts_${ts}.mp3`;
  }
  const payload = buildPayload({ filename });
  if (!payload.text)     { showToast('Please enter some text first.', 'error'); return; }
  if (!payload.voice_id) { showToast('Please select a voice.', 'error'); return; }

  setLoading(genBtn, true, '⏳ Generating…');
  setStatus('Generating audio file…', 'loading');
  resultBlock.classList.remove('show');

  try {
    const res = await fetch('/api/generate', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || 'Generation failed');
    }
    const data = await res.json();

    resultName.textContent = data.filename;
    dlBtn.href             = `/api/download/${encodeURIComponent(data.filename)}`;
    dlBtn.download         = data.filename;
    resultBlock.classList.add('show');
    statusPath.textContent = data.path;

    setStatus(`✓ Saved: ${data.filename}`, 'ok');
    showToast(`Generated: ${data.filename}`, 'success');
    if (filenameInput) filenameInput.value = '';
  } catch (e) {
    showToast('Generation error: ' + e.message, 'error');
    setStatus('Generation failed.', 'error');
  } finally {
    setLoading(genBtn, false, '⚡ Generate');
  }
});

// ── Status helpers ────────────────────────────────────────────────────────────

function setStatus(msg, type = 'ok') {
  statusMsg.textContent = msg;
  statusDot.className   = 'status-dot' +
    (type === 'loading' ? ' loading' : type === 'error' ? ' error' : '');
}

function setLoading(btn, loading, label) {
  btn.disabled  = loading;
  btn.innerHTML = loading ? `<span class="spin"></span> ${label}` : label;
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function showToast(msg, type = 'info') {
  const icon = { success: '✓', error: '✗', info: 'ℹ' }[type] || 'ℹ';
  const t    = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
  $('toast-container').appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── Mobile adaptation ─────────────────────────────────────────────────────────

function applyDeviceLayout() {
  if (state.isMobile) {
    document.querySelectorAll('.desktop-only').forEach(el => {
      el.style.display = 'none';
    });
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────

initTheme();
applyDeviceLayout();
loadVoices();

// Set initial display values
speedVal.textContent = parseFloat(speedSlider.value).toFixed(1) + 'x';
const initPitch = parseInt(pitchSlider.value);
pitchVal.textContent = (initPitch >= 0 ? '+' : '') + initPitch + 'Hz';
