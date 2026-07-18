// ── Voice Agent · browser client ────────────────────────────────────────────
// mic → 16 kHz PCM16 → WebSocket → server. server → 24 kHz PCM16 → speaker.
// Handles the "clear" (barge-in) control message by flushing playback instantly.

const $ = (id) => document.getElementById(id);
const talkBtn = $("talkBtn");
const stateText = $("stateText");
const hint = $("hint");
const transcriptEl = $("transcript");

let ws = null;
let captureCtx = null;
let playbackCtx = null;
let recorderNode = null;
let playerNode = null;
let micStream = null;
let running = false;
let energy = 0;           // 0..1, drives the visualizer
let speaking = false;

// ── audio encode/decode helpers ─────────────────────────────────────────────
function floatToPCM16(float32) {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}
function pcm16ToFloat(buffer) {
  const int16 = new Int16Array(buffer);
  const out = new Float32Array(int16.length);
  for (let i = 0; i < int16.length; i++) out[i] = int16[i] / 0x8000;
  return out;
}

// ── connection lifecycle ────────────────────────────────────────────────────
async function start() {
  running = true;
  talkBtn.textContent = "Stop";
  talkBtn.classList.add("live");
  hint.textContent = "Listening… just talk. Cut me off whenever you like.";

  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true,
             channelCount: 1 },
  });

  captureCtx = new AudioContext({ sampleRate: 16000 });
  await captureCtx.audioWorklet.addModule("/worklets/recorder.js");
  const src = captureCtx.createMediaStreamSource(micStream);
  recorderNode = new AudioWorkletNode(captureCtx, "recorder-processor");
  recorderNode.port.onmessage = ({ data }) => {
    if (!running || !ws || ws.readyState !== WebSocket.OPEN) return;
    energy = Math.min(1, data.rms * 6);
    ws.send(floatToPCM16(data.samples).buffer);
  };
  src.connect(recorderNode);
  // Keep the worklet's process() pumping without routing mic to the speakers.
  const sink = captureCtx.createGain();
  sink.gain.value = 0;
  recorderNode.connect(sink).connect(captureCtx.destination);

  playbackCtx = new AudioContext({ sampleRate: 24000 });
  await playbackCtx.audioWorklet.addModule("/worklets/player.js");
  playerNode = new AudioWorkletNode(playbackCtx, "player-processor");
  playerNode.port.onmessage = ({ data }) => { speaking = data.playing; };
  playerNode.connect(playbackCtx.destination);

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  ws.onmessage = onMessage;
  ws.onclose = () => running && stop();
}

function stop() {
  running = false;
  talkBtn.textContent = "Start talking";
  talkBtn.classList.remove("live");
  hint.textContent = "Grant mic access, then just speak. Interrupt any time.";
  setState("idle");
  ws?.close(); ws = null;
  micStream?.getTracks().forEach((t) => t.stop());
  recorderNode?.disconnect(); playerNode?.disconnect();
  captureCtx?.close(); playbackCtx?.close();
}

// ── server → client messages ────────────────────────────────────────────────
function onMessage(evt) {
  if (evt.data instanceof ArrayBuffer) {
    playerNode?.port.postMessage({ samples: pcm16ToFloat(evt.data) });
    return;
  }
  const msg = JSON.parse(evt.data);
  switch (msg.type) {
    case "state":     setState(msg.value); break;
    case "clear":     playerNode?.port.postMessage({ cmd: "clear" }); break; // barge-in
    case "transcript":liveTranscript(msg.text, msg.final); break;
    case "user":      commitBubble("user", msg.text); break;
    case "agent":     commitBubble("agent", msg.text); break;
    case "latency":   $("mLast").textContent = Math.round(msg.mouth_to_response_ms); break;
    case "metrics":   updateMetrics(msg); break;
  }
}

function setState(value) {
  document.body.dataset.state = value === "idle" ? "" : value;
  stateText.textContent = value;
}

// ── transcript rendering ─────────────────────────────────────────────────────
let interimEl = null;
function liveTranscript(text, final) {
  if (!interimEl) {
    interimEl = document.createElement("div");
    interimEl.className = "bubble user interim";
    transcriptEl.appendChild(interimEl);
  }
  interimEl.textContent = text;
  scroll();
  if (final) { /* server will emit a committed "user" bubble */ }
}
function commitBubble(role, text) {
  if (role === "user" && interimEl) { interimEl.remove(); interimEl = null; }
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  el.textContent = text;
  transcriptEl.appendChild(el);
  scroll();
}
function scroll() { transcriptEl.scrollTop = transcriptEl.scrollHeight; }

function updateMetrics(m) {
  $("mP50").textContent = Math.round(m.p50_ms);
  $("mP95").textContent = Math.round(m.p95_ms);
  $("mCount").textContent = m.count;
}

// ── visualizer ───────────────────────────────────────────────────────────────
const canvas = $("viz"), ctx = canvas.getContext("2d");
const N = 72;
function draw() {
  const w = canvas.width, h = canvas.height, cx = w / 2, cy = h / 2;
  ctx.clearRect(0, 0, w, h);
  const state = document.body.dataset.state;
  const base = state === "speaking" ? 0.55 : state === "listening" ? 0.35 : 0.2;
  const amp = state === "speaking" ? 0.5 + Math.random() * 0.4 : energy;
  const color = state === "speaking" ? "#7aa2ff" : state === "thinking" ? "#f5c451" : "#31d0aa";
  energy *= 0.9; // decay
  for (let i = 0; i < N; i++) {
    const a = (i / N) * Math.PI * 2;
    const t = performance.now() / 600;
    const r = 96 + (base + amp * 0.6) * 34 * (0.6 + 0.4 * Math.sin(a * 3 + t));
    const x1 = cx + Math.cos(a) * 96, y1 = cy + Math.sin(a) * 96;
    const x2 = cx + Math.cos(a) * r, y2 = cy + Math.sin(a) * r;
    ctx.strokeStyle = color;
    ctx.globalAlpha = 0.25 + 0.5 * (r - 96) / 60;
    ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
  }
  ctx.globalAlpha = 1;
  requestAnimationFrame(draw);
}
draw();

// ── wire up button ───────────────────────────────────────────────────────────
talkBtn.addEventListener("click", async () => {
  if (running) return stop();
  try { await start(); }
  catch (err) { hint.textContent = "Mic error: " + err.message; stop(); }
});
