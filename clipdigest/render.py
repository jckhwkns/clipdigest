"""Render the self-contained viewer (`index.html`).

The manifest is embedded inline (so `file://` works with no server) and also
written alongside as `manifest.json` for sharing/linking.
"""

from __future__ import annotations

import json
import os

from . import config

VIEWER_CONFIG = {
    "pollMs": int(1000 / config.POLL_HZ),
    "primerSeconds": config.PRIMER_SECONDS,
    "cardLeadSeconds": config.CARD_LEAD_SECONDS,
    "cardMinSeconds": config.CARD_MIN_SECONDS,
    "readingSpeedWps": config.READING_SPEED_WPS,
    "pauseHoldSeconds": config.PAUSE_HOLD_SECONDS,
}


def render(manifest: dict, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    html = _TEMPLATE.replace("__MANIFEST__", json.dumps(manifest)).replace(
        "__CONFIG__", json.dumps(VIEWER_CONFIG)
    )
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>clipdigest viewer</title>
<style>
  :root { color-scheme: dark; --bg:#0d0f13; --panel:#161a21; --line:#262c36;
          --fg:#e8eaed; --muted:#9aa4b2; --accent:#6ea8fe; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
  .wrap { max-width: 900px; margin: 0 auto; padding: 20px; }
  h1 { font-size: 18px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .stage { position: relative; aspect-ratio: 16/9; background:#000;
           border-radius: 12px; overflow: hidden; }
  #player { width:100%; height:100%; }
  /* Overlays */
  .overlay { position:absolute; left:0; right:0; bottom:0; padding:18px;
             display:none; pointer-events:none;
             background:linear-gradient(transparent, rgba(0,0,0,.82)); }
  .overlay.show { display:block; animation: fade .25s ease; }
  .card { pointer-events:none; max-width: 640px;
          background: rgba(20,24,32,.92); border:1px solid var(--line);
          border-left:3px solid var(--accent); border-radius:10px;
          padding:12px 14px; box-shadow:0 8px 30px rgba(0,0,0,.5); }
  .card .kind { font-size:11px; letter-spacing:.06em; text-transform:uppercase;
                color:var(--accent); margin-bottom:3px; }
  .card .text { font-size:15px; }
  .primer .kind { color:#ffd479; }
  .primer { border-left-color:#ffd479; }
  @keyframes fade { from{opacity:0; transform:translateY(6px);} to{opacity:1;} }
  /* Start gate (autoplay-safe) */
  .gate { position:absolute; inset:0; display:flex; align-items:center;
          justify-content:center; background:rgba(0,0,0,.55); cursor:pointer; }
  .gate button { font-size:16px; padding:12px 22px; border-radius:999px;
                 border:none; background:var(--accent); color:#08131f;
                 font-weight:600; cursor:pointer; }
  .done { position:absolute; inset:0; display:none; align-items:center;
          justify-content:center; flex-direction:column; gap:12px;
          background:rgba(0,0,0,.7); }
  .done button { font-size:14px; padding:9px 16px; border-radius:8px; border:none;
                 background:var(--panel); color:var(--fg); cursor:pointer;
                 border:1px solid var(--line); }
  /* Stats + lists */
  .stats { display:flex; gap:18px; flex-wrap:wrap; margin:16px 0;
           color:var(--muted); font-size:13px; }
  .stats b { color:var(--fg); }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.05em;
       color:var(--muted); margin:22px 0 8px; }
  .seg { display:flex; gap:10px; align-items:baseline; padding:9px 10px;
         border:1px solid var(--line); border-radius:8px; margin-bottom:6px;
         background:var(--panel); }
  .seg.active { border-color:var(--accent); }
  .seg .ts { font-variant-numeric:tabular-nums; color:var(--accent);
             cursor:pointer; white-space:nowrap; font-size:13px; }
  .seg .reason { flex:1; }
  .seg a { color:var(--muted); font-size:12px; text-decoration:none;
           white-space:nowrap; }
  .seg a:hover { color:var(--fg); text-decoration:underline; }
  .miss { padding:8px 10px; border-left:2px solid var(--line);
          margin-bottom:6px; font-size:13px; }
  .miss .ts { color:var(--accent); font-variant-numeric:tabular-nums;
              cursor:pointer; margin-right:8px; }
  .empty { color:var(--muted); font-size:13px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>clipdigest</h1>
  <div class="sub" id="subtitle"></div>

  <div class="stage">
    <div id="player"></div>
    <div class="overlay" id="overlay"><div class="card" id="card">
      <div class="kind" id="cardKind"></div><div class="text" id="cardText"></div>
    </div></div>
    <div class="gate" id="gate"><button>▶  Play condensed cut</button></div>
    <div class="done" id="done">
      <div>End of condensed cut.</div>
      <button id="replay">Replay</button>
    </div>
  </div>

  <div class="stats" id="stats"></div>

  <h2>Segments</h2>
  <div id="segList"></div>

  <h2>You may have missed</h2>
  <div id="missList"></div>
</div>

<script>
const MANIFEST = __MANIFEST__;
const CFG = __CONFIG__;

// ---- helpers ---------------------------------------------------------------
const fmt = s => { s = Math.max(0, Math.round(s));
  const m = Math.floor(s/60), r = String(s%60).padStart(2,'0');
  return `${m}:${r}`; };
const embedUrl = (a,b) =>
  `https://www.youtube.com/embed/${MANIFEST.video_id}?start=${Math.floor(a)}&end=${Math.ceil(b)}`;

// Precompute condensed-time offset for each segment (for jump-to + tracking).
let acc = 0;
MANIFEST.segments.forEach(s => { s._condStart = acc; acc += s.end_sec - s.start_sec; });
const CONDENSED_TOTAL = acc;

// Precompute bridge card timings in condensed time.
MANIFEST.bridges.forEach(b => {
  const words = b.text.trim().split(/\s+/).length;
  b._hold = Math.max(CFG.cardMinSeconds, words / CFG.readingSpeedWps);
  b._showAt = Math.max(0, b.anchor_sec - CFG.cardLeadSeconds);
  b._fired = false;
});

// ---- player ----------------------------------------------------------------
let player, timer = null, segIndex = 0, cardHideAt = 0, started = false;

window.onYouTubeIframeAPIReady = () => {
  player = new YT.Player('player', {
    videoId: MANIFEST.video_id,
    playerVars: { controls: 1, rel: 0, modestbranding: 1, playsinline: 1,
                  start: Math.floor(MANIFEST.segments[0]?.start_sec || 0) },
    events: { onReady: () => {}, onStateChange: onState },
  });
};

function startPlayback() {
  if (started || !player) return;
  started = true;
  document.getElementById('gate').style.display = 'none';
  document.getElementById('done').style.display = 'none';
  segIndex = 0;
  MANIFEST.bridges.forEach(b => b._fired = false);
  seekToSegment(0);
  player.playVideo();
  showPrimer();
  if (timer) clearInterval(timer);
  timer = setInterval(tick, CFG.pollMs);
}

function seekToSegment(i) {
  segIndex = i;
  player.seekTo(MANIFEST.segments[i].start_sec, true);
  markActive(i);
}

// Chain segments purely on polled currentTime (endSeconds is voided by seekTo).
function tick() {
  if (!player || !player.getCurrentTime) return;
  const t = player.getCurrentTime();
  const seg = MANIFEST.segments[segIndex];
  if (!seg) return;

  if (t >= seg.end_sec - 0.15) {
    if (segIndex + 1 < MANIFEST.segments.length) {
      seekToSegment(segIndex + 1);
    } else {
      finish();
      return;
    }
  }
  // Guard against a user scrubbing far outside the current kept span.
  if (t < seg.start_sec - 1.0 || t > seg.end_sec + 1.5) {
    const found = MANIFEST.segments.findIndex(s => t >= s.start_sec - 1 && t <= s.end_sec + 1);
    if (found !== -1) { segIndex = found; markActive(found); }
  }

  const cur = MANIFEST.segments[segIndex];
  const condNow = cur._condStart + Math.min(cur.end_sec, Math.max(cur.start_sec, t)) - cur.start_sec;
  updateBridges(condNow);
  maybeHideCard(condNow);
}

function finish() {
  clearInterval(timer); timer = null; started = false;
  player.pauseVideo();
  document.getElementById('done').style.display = 'flex';
}

function onState(e) {
  // If the video ends on its own (rare, since we gate on time), wrap up.
  if (e.data === YT.PlayerState.ENDED && started) finish();
}

// ---- overlay cards ---------------------------------------------------------
const overlay = document.getElementById('overlay');
const cardKind = document.getElementById('cardKind');
const cardText = document.getElementById('cardText');
const card = document.getElementById('card');

function showCard(kind, text, holdSeconds, isPrimer) {
  cardKind.textContent = isPrimer ? 'Primer' : kind;
  cardText.textContent = text;
  card.classList.toggle('primer', !!isPrimer);
  overlay.classList.add('show');
  cardHideAt = performance.now() + holdSeconds * 1000;
}
function hideCard() { overlay.classList.remove('show'); cardHideAt = 0; }
function maybeHideCard() { if (cardHideAt && performance.now() >= cardHideAt) hideCard(); }

function showPrimer() {
  if (!MANIFEST.primer) return;
  showCard('', MANIFEST.primer, CFG.primerSeconds, true);
}

function updateBridges(condNow) {
  for (const b of MANIFEST.bridges) {
    if (b._fired || condNow < b._showAt) continue;
    b._fired = true;
    showCard(b.kind, b.text, b._hold, false);
    if (b.pause) {
      player.pauseVideo();
      cardHideAt = 0; // hold the card while paused
      setTimeout(() => {
        hideCard();
        if (started) player.playVideo();
      }, CFG.pauseHoldSeconds * 1000);
    }
  }
}

// ---- UI: stats, segment list, missed list ----------------------------------
function markActive(i) {
  document.querySelectorAll('.seg').forEach((el, idx) =>
    el.classList.toggle('active', idx === i));
}

function build() {
  document.getElementById('subtitle').innerHTML =
    `Condensed from <a href="${MANIFEST.source_url}" style="color:var(--accent)">`
    + `the original</a> &middot; target ~${MANIFEST.target_minutes} min`;

  const st = MANIFEST.stats;
  document.getElementById('stats').innerHTML =
    `<div>Original <b>${fmt(st.original_sec)}</b></div>`
    + `<div>Condensed <b>${fmt(st.condensed_sec)}</b></div>`
    + `<div>Kept <b>${st.percent_kept}%</b></div>`
    + `<div>Segments <b>${MANIFEST.segments.length}</b></div>`;

  const segList = document.getElementById('segList');
  MANIFEST.segments.forEach((s, i) => {
    const row = document.createElement('div');
    row.className = 'seg';
    row.innerHTML =
      `<span class="ts">[${fmt(s.start_sec)}–${fmt(s.end_sec)}]</span>`
      + `<span class="reason">${escapeHtml(s.reason)}</span>`
      + `<a href="${embedUrl(s.start_sec, s.end_sec)}" target="_blank" rel="noopener">open on YouTube ↗</a>`;
    row.querySelector('.ts').onclick = () => {
      if (!started) startPlayback();
      seekToSegment(i);
      player.playVideo();
    };
    segList.appendChild(row);
  });

  const missList = document.getElementById('missList');
  if (!MANIFEST.bridges.length) {
    missList.innerHTML = '<div class="empty">No comprehension gaps flagged.</div>';
  } else {
    MANIFEST.bridges.forEach(b => {
      const row = document.createElement('div');
      row.className = 'miss';
      row.innerHTML = `<span class="ts">${fmt(b.anchor_sec)}</span>`
        + `<span>${escapeHtml(b.text)}</span>`;
      row.querySelector('.ts').onclick = () => jumpToCondensed(b.anchor_sec);
      missList.appendChild(row);
    });
  }
}

// Map a condensed timestamp back to original time and seek there.
function jumpToCondensed(cond) {
  let i = 0;
  for (let k = 0; k < MANIFEST.segments.length; k++) {
    const s = MANIFEST.segments[k];
    const len = s.end_sec - s.start_sec;
    if (cond <= s._condStart + len) {
      if (!started) startPlayback();
      segIndex = k;
      player.seekTo(s.start_sec + (cond - s._condStart), true);
      markActive(k);
      player.playVideo();
      return;
    }
    i = k;
  }
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
}

// ---- boot ------------------------------------------------------------------
document.getElementById('gate').onclick = startPlayback;
document.getElementById('replay').onclick = startPlayback;
build();
(function loadAPI(){
  const tag = document.createElement('script');
  tag.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(tag);
})();
</script>
</body>
</html>
"""
