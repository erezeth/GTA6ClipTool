const $ = (id) => document.getElementById(id);
const history = [];
const MAX_POINTS = 180;
let previewImg = null;
let rectDirty = false;
let clipsKey = "";
let currentChannel = "";
let previewRequested = false;

function fmtUptime(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return [h, m, s].map((v) => String(v).padStart(2, "0")).join(":");
}

function drawSpark(state) {
  const c = $("spark");
  const ctx = c.getContext("2d");
  const w = c.width, h = c.height;
  ctx.clearRect(0, 0, w, h);

  const max = Math.max(10, state.threshold * 1.4, ...history, 1);
  const x = (i) => (history.length <= 1 ? 0 : (i / (MAX_POINTS - 1)) * w);
  const y = (v) => h - (v / max) * (h - 8) - 4;

  ctx.strokeStyle = "#242a32";
  ctx.beginPath();
  ctx.moveTo(0, y(state.baseline));
  ctx.lineTo(w, y(state.baseline));
  ctx.stroke();

  ctx.strokeStyle = "#ffc857";
  ctx.setLineDash([6, 6]);
  ctx.beginPath();
  ctx.moveTo(0, y(state.threshold));
  ctx.lineTo(w, y(state.threshold));
  ctx.stroke();
  ctx.setLineDash([]);

  if (history.length > 1) {
    ctx.strokeStyle = "#6ee7a8";
    ctx.lineWidth = 2;
    ctx.beginPath();
    history.forEach((v, i) => (i ? ctx.lineTo(x(i), y(v)) : ctx.moveTo(x(i), y(v))));
    ctx.stroke();
  }
}

function drawPreview() {
  const c = $("preview");
  const ctx = c.getContext("2d");
  ctx.clearRect(0, 0, c.width, c.height);
  if (previewImg) {
    ctx.drawImage(previewImg, 0, 0, c.width, c.height);
  } else {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, c.width, c.height);
  }
  $("nopreview").style.display = previewImg ? "none" : "grid";

  const rect = readRect();
  ctx.strokeStyle = "#6ee7a8";
  ctx.lineWidth = 2;
  ctx.strokeRect(rect.x * c.width, rect.y * c.height, rect.w * c.width, rect.h * c.height);
}

function readRect() {
  return {
    x: (+$("rx").value || 0) / 100,
    y: (+$("ry").value || 0) / 100,
    w: (+$("rw").value || 1) / 100,
    h: (+$("rh").value || 1) / 100,
  };
}

function writeRect(rect) {
  $("rx").value = Math.round(rect.x * 100);
  $("ry").value = Math.round(rect.y * 100);
  $("rw").value = Math.round(rect.w * 100);
  $("rh").value = Math.round(rect.h * 100);
}

function renderClips(clips) {
  const key = clips.map((c) => c.file).join("|");
  if (key === clipsKey) return;
  clipsKey = key;
  const box = $("clips");
  box.innerHTML = "";
  $("clipcount").textContent = clips.length ? `(${clips.length})` : "";
  if (!clips.length) {
    box.innerHTML = '<div class="empty">Belum ada klip.</div>';
    return;
  }
  clips.slice().reverse().forEach((clip) => {
    const el = document.createElement("div");
    el.className = "clip";
    el.innerHTML = `<video src="/clips/${encodeURIComponent(clip.file)}" controls preload="metadata"></video>
      <div class="cap"><b>score ${clip.score}</b> &middot; ${clip.rate} msg/s<br>${clip.at}</div>`;
    box.appendChild(el);
  });
}

function render(state) {
  $("status").textContent = state.status;
  $("status").className = `pill ${state.status}`;
  $("meta").textContent = state.title || "tempel URL live YouTube lalu Start";
  $("uptime").textContent = state.uptime ? fmtUptime(state.uptime) : "";
  $("error").textContent = state.error || "";
  $("rate").textContent = state.rate.toFixed(1);
  $("baseline").textContent = state.baseline.toFixed(1);
  $("threshold").textContent = state.threshold.toFixed(1);
  $("messages").textContent = state.messages;
  $("scheduled").textContent = state.clips_scheduled;
  $("log").textContent = state.logs.join("\n");
  $("log").scrollTop = $("log").scrollHeight;
  $("start").disabled = state.status === "starting" || state.status === "live";
  $("stop").disabled = state.status === "idle" || state.status === "error";

  history.push(state.rate);
  if (history.length > MAX_POINTS) history.shift();
  drawSpark(state);

  renderClips(state.clips);

  if (state.channel !== currentChannel) {
    currentChannel = state.channel;
    rectDirty = false;
    previewRequested = false;
    previewImg = null;
    $("ch").textContent = state.channel || "-";
    writeRect(state.rect);
    drawPreview();
  }
  if (!rectDirty && document.activeElement?.tagName !== "INPUT") writeRect(state.rect);

  if (state.status === "live" && !previewRequested) {
    previewRequested = true;
    loadPreview();
  }
}

async function loadPreview() {
  try {
    const res = await fetch("/api/preview", { cache: "no-store" });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      previewImg = img;
      URL.revokeObjectURL(url);
      drawPreview();
    };
    img.src = url;
  } catch { /* frame belum siap */ }
}

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json();
}

$("start").onclick = () => post("/api/start", { url: $("url").value });
$("stop").onclick = () => post("/api/stop");
$("refresh").onclick = loadPreview;
$("save").onclick = async () => {
  await post("/api/rect", { channel: currentChannel || "default", rect: readRect() });
  rectDirty = false;
};
["rx", "ry", "rw", "rh"].forEach((id) => {
  $(id).addEventListener("input", () => {
    rectDirty = true;
    drawPreview();
  });
});

const es = new EventSource("/api/events");
es.onmessage = (ev) => render(JSON.parse(ev.data));
