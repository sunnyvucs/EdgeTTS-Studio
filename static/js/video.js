/**
 * video.js — Video Studio frontend logic
 * Handles: JSON parse → scene table → audio generation → render trigger
 *
 * This file is completely independent of app.js (no shared globals).
 */

'use strict';

// ── DOM refs ──────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const scriptEditor  = $('script-editor');
const jsonBadge     = $('json-valid-badge');
const loadBtn       = $('load-btn');
const sampleBtn     = $('sample-btn');
const clearBtn      = $('clear-btn');
const sceneTableWrap= $('scene-table-wrap');
const sceneCount    = $('scene-count');
const genAudioBtn   = $('gen-audio-btn');
const runRenderBtn  = $('run-render-btn');
const dlVideoBtn    = $('dl-video-btn');
const renderNotice  = $('render-notice');
const logOutput     = $('log-output');
const statusDot     = $('status-dot');
const statusMsg     = $('status-msg');
const statusPath    = $('status-path');
const themeBtn      = $('theme-btn');

// ── State ─────────────────────────────────────────────────────────────────────
let scenes = [];          // parsed scene array
let audioStatus = {};     // { [scene.id]: 'ok' | 'missing' | 'error' }

// ── Sample script ─────────────────────────────────────────────────────────────
const SAMPLE = [
  {
    id: 1,
    english_line: "Welcome to our channel!",
    hindi_line: "Hamare channel mein aapka swagat hai!",
    duration: 4,
    background: "#1a1a2e",
    tts: { voice_id: "hi-IN-SwaraNeural", style: "cheerful",
           rate: "+5%", pitch: "+2Hz", emphasis: "moderate", pause_ms: 300 }
  },
  {
    id: 2,
    english_line: "Today we will learn something amazing.",
    hindi_line: "Aaj hum kuch kamaal sikhenge.",
    duration: 4,
    background: "#16213e",
    tts: { voice_id: "hi-IN-MadhurNeural", style: "narration-professional",
           rate: "+0%", pitch: "+0Hz", emphasis: "none", pause_ms: 300 }
  },
  {
    id: 3,
    english_line: "Stay tuned till the end!",
    hindi_line: "Aakhir tak bane rahein!",
    duration: 3,
    background: "#0f3460",
    tts: { voice_id: "hi-IN-SwaraNeural", style: "friendly",
           rate: "+10%", pitch: "+3Hz", emphasis: "strong", pause_ms: 200 }
  }
];

// ── Theme ─────────────────────────────────────────────────────────────────────
(function initTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  themeBtn.textContent = saved === 'dark' ? '☀ Light' : '🌙 Dark';
})();

themeBtn.addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  themeBtn.textContent = next === 'dark' ? '☀ Light' : '🌙 Dark';
  localStorage.setItem('theme', next);
});

// ── Log helpers ───────────────────────────────────────────────────────────────
function log(msg, type = 'info') {
  const cls = { ok: 'log-ok', error: 'log-err', info: 'log-info', warn: 'log-warn' }[type] || '';
  const ts = new Date().toLocaleTimeString();
  logOutput.innerHTML += `<span class="${cls}">[${ts}] ${escHtml(msg)}</span>\n`;
  logOutput.scrollTop = logOutput.scrollHeight;
}

function clearLog() {
  logOutput.innerHTML = '';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Status bar ────────────────────────────────────────────────────────────────
function setStatus(msg, type = 'ok', path = '') {
  statusMsg.textContent  = msg;
  statusPath.textContent = path;
  statusDot.className    = 'status-dot' +
    (type === 'loading' ? ' loading' : type === 'error' ? ' error' : '');
}

// ── Step indicator ────────────────────────────────────────────────────────────
function setStep(id, state) {
  const el = $(id);
  if (!el) return;
  el.className = 'step' + (state ? ` ${state}` : '');
}

// ── Toast ─────────────────────────────────────────────────────────────────────
function showToast(msg, type = 'info') {
  const icon = { success: '✓', error: '✗', info: 'ℹ' }[type] || 'ℹ';
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.innerHTML = `<span>${icon}</span><span>${escHtml(msg)}</span>`;
  $('toast-container').appendChild(t);
  setTimeout(() => t.remove(), 4000);
}

// ── JSON parse & scene table ──────────────────────────────────────────────────
function parseAndRender() {
  const raw = scriptEditor.value.trim();
  if (!raw) {
    jsonBadge.textContent = '—';
    jsonBadge.style.color = 'var(--fg3)';
    sceneTableWrap.innerHTML = '<p style="color:var(--fg3);font-size:.85rem;">No JSON entered.</p>';
    sceneCount.textContent = '—';
    scenes = [];
    genAudioBtn.disabled = true;
    runRenderBtn.disabled = true;
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    jsonBadge.textContent = '✗ Invalid JSON';
    jsonBadge.style.color = 'var(--red)';
    sceneTableWrap.innerHTML = `<p style="color:var(--red);font-size:.83rem;">JSON parse error: ${escHtml(e.message)}</p>`;
    sceneCount.textContent = '—';
    scenes = [];
    genAudioBtn.disabled = true;
    runRenderBtn.disabled = true;
    log('JSON parse failed: ' + e.message, 'error');
    return;
  }

  if (!Array.isArray(parsed) || parsed.length === 0) {
    jsonBadge.textContent = '✗ Expected non-empty array';
    jsonBadge.style.color = 'var(--yellow)';
    sceneTableWrap.innerHTML = '<p style="color:var(--yellow);font-size:.83rem;">Script must be a JSON array with at least one scene.</p>';
    scenes = [];
    genAudioBtn.disabled = true;
    runRenderBtn.disabled = true;
    return;
  }

  scenes = parsed;
  audioStatus = {};

  jsonBadge.textContent = `✓ Valid — ${scenes.length} scene${scenes.length !== 1 ? 's' : ''}`;
  jsonBadge.style.color = 'var(--green)';
  sceneCount.textContent = `${scenes.length} scene${scenes.length !== 1 ? 's' : ''}`;

  renderSceneTable();
  setStep('step-script', 'done');
  genAudioBtn.disabled = false;
  runRenderBtn.disabled = false;

  log(`Parsed ${scenes.length} scene(s) successfully.`, 'ok');
  setStatus(`${scenes.length} scenes loaded — ready to generate audio.`);
}

function renderSceneTable() {
  if (!scenes.length) return;

  const totalSecs = scenes.reduce((s, sc) => s + (sc.duration || 0), 0);
  sceneCount.textContent = `${scenes.length} scenes · ${totalSecs}s total`;

  let html = `<div style="overflow-x:auto;">
    <table class="scene-table">
      <thead>
        <tr>
          <th>#</th>
          <th>English</th>
          <th>Hindi</th>
          <th>Voice / Style</th>
          <th>Dur</th>
          <th>Audio</th>
        </tr>
      </thead>
      <tbody>`;

  for (const sc of scenes) {
    const tts   = sc.tts || {};
    const voice = (tts.voice_id || 'hi-IN-SwaraNeural').replace('Neural', '');
    const style = tts.style || 'default';
    const dur   = sc.duration ? `${sc.duration}s` : '—';
    const bg    = sc.background || '#1a1a2e';
    const aStatus = audioStatus[sc.id];
    const aBadge  = aStatus === 'ok'
      ? '<span class="audio-ok">✓ ready</span>'
      : aStatus === 'error'
      ? '<span class="audio-err">✗ error</span>'
      : '<span class="audio-miss">— pending</span>';

    html += `<tr>
      <td><strong>${sc.id}</strong><br>
        <span class="scene-swatch" style="background:${escHtml(bg)}"></span>
      </td>
      <td style="max-width:200px;">${escHtml(sc.english_line || '')}</td>
      <td style="max-width:200px;">${escHtml(sc.hindi_line  || '')}</td>
      <td>
        <span class="tag voice">${escHtml(voice)}</span><br>
        <span class="tag style" style="margin-top:4px;display:inline-block;">${escHtml(style)}</span>
      </td>
      <td>${dur}</td>
      <td class="audio-status">${aBadge}</td>
    </tr>`;
  }

  html += '</tbody></table></div>';
  sceneTableWrap.innerHTML = html;
}

// ── Audio generation ──────────────────────────────────────────────────────────
genAudioBtn.addEventListener('click', async () => {
  if (!scenes.length) { showToast('Parse your script first.', 'error'); return; }

  setLoading(genAudioBtn, true, '⏳ Generating…');
  setStep('step-audio', 'active');
  setStatus('Generating audio…', 'loading');
  clearLog();
  log(`Starting audio generation for ${scenes.length} scene(s)…`, 'info');

  let allOk = true;

  for (const scene of scenes) {
    const tts = scene.tts || {};
    const payload = {
      text:      scene.hindi_line,
      voice_id:  tts.voice_id  || 'hi-IN-SwaraNeural',
      rate:      tts.rate      || '+0%',
      pitch:     tts.pitch     || '+1Hz',
      style:     tts.style     || 'default',
      emphasis:  tts.emphasis  || 'none',
      pause_ms:  tts.pause_ms  ?? 300,
      filename:  `scene_${scene.id}.mp3`,
    };

    log(`Scene ${scene.id} — voice: ${payload.voice_id}, style: ${payload.style}`, 'info');
    log(`  text: "${scene.hindi_line}"`, 'info');

    try {
      const res = await fetch('/api/generate', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }

      const data = await res.json();
      audioStatus[scene.id] = 'ok';
      log(`  ✓ saved → ${data.filename}`, 'ok');
    } catch (e) {
      audioStatus[scene.id] = 'error';
      allOk = false;
      log(`  ✗ scene ${scene.id} failed: ${e.message}`, 'error');
      showToast(`Scene ${scene.id} audio failed: ${e.message}`, 'error');
    }
  }

  renderSceneTable(); // refresh audio status column

  if (allOk) {
    setStep('step-audio', 'done');
    log('All audio files generated successfully.', 'ok');
    setStatus('Audio ready — you can now render the video.');
    showToast('All audio generated!', 'success');
  } else {
    setStep('step-audio', 'error');
    log('Some audio files failed — check errors above.', 'warn');
    setStatus('Audio generation had errors.', 'error');
  }

  setLoading(genAudioBtn, false, '🎙 Generate Audio');
});

// ── Render trigger ────────────────────────────────────────────────────────────
runRenderBtn.addEventListener('click', async () => {
  if (!scenes.length) { showToast('Parse your script first.', 'error'); return; }

  // First, save script.json to the Motion Graphics project
  setLoading(runRenderBtn, true, '⏳ Saving script…');
  setStep('step-render', 'active');
  setStatus('Saving script and triggering render…', 'loading');

  try {
    const res = await fetch('/api/video/render', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ scenes }),
    });

    const data = await res.json().catch(() => ({}));

    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }

    log(data.message || 'Render triggered.', 'ok');
    setStep('step-render', 'done');
    setStatus('Render complete!', 'ok', data.output || '');
    showToast('Video rendered!', 'success');

    if (data.output) {
      dlVideoBtn.style.display = 'inline-flex';
      dlVideoBtn.href = `/api/video/download`;
    }

  } catch (e) {
    log('Render failed: ' + e.message, 'error');
    setStep('step-render', 'error');
    setStatus('Render failed.', 'error');
    showToast('Render failed: ' + e.message, 'error');

    // Show helpful CLI fallback
    renderNotice.style.display = 'block';
    renderNotice.innerHTML = `
      <strong>Render note:</strong> The full Remotion render requires the pipeline server to be running.<br>
      You can also run it manually from the <code>Motion Graphics</code> project:<br>
      <code>npm run pipeline</code>
    `;
  }

  setLoading(runRenderBtn, false, '🎬 Render Video');
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function setLoading(btn, loading, label) {
  btn.disabled  = loading;
  btn.innerHTML = loading ? `<span class="spin"></span> ${label}` : label;
}

// ── Toolbar buttons ───────────────────────────────────────────────────────────
loadBtn.addEventListener('click', parseAndRender);

sampleBtn.addEventListener('click', () => {
  scriptEditor.value = JSON.stringify(SAMPLE, null, 2);
  parseAndRender();
  showToast('Sample script loaded.', 'info');
});

clearBtn.addEventListener('click', () => {
  scriptEditor.value = '';
  jsonBadge.textContent = '—';
  jsonBadge.style.color = 'var(--fg3)';
  sceneTableWrap.innerHTML = '<p style="color:var(--fg3);font-size:.85rem;">Parse your JSON to see scenes here.</p>';
  sceneCount.textContent = '—';
  scenes = [];
  audioStatus = {};
  genAudioBtn.disabled = true;
  runRenderBtn.disabled = true;
  dlVideoBtn.style.display = 'none';
  renderNotice.style.display = 'none';
  clearLog();
  logOutput.textContent = 'Ready. Parse your script to begin.';
  ['step-script', 'step-audio', 'step-render'].forEach(id => setStep(id, ''));
  setStatus('Ready.');
});

// Auto-parse on Ctrl+Enter
scriptEditor.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.ctrlKey) { e.preventDefault(); parseAndRender(); }
});
