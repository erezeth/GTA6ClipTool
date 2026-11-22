# YouTube Live Clipper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dashboard lokal yang merekam live YouTube, mendeteksi lonjakan chat, dan otomatis menghasilkan klip vertikal 9:16 (facecam atas, gameplay bawah).

**Architecture:** Satu proses FastAPI. Tiga thread/loop: ffmpeg segmenter (ring buffer 2s), yt-dlp chat downloader yang file JSONL-nya di-tail, dan monitor 1s yang menjalankan SpikeDetector lalu memicu render ffmpeg filter_complex ke NVENC.

**Tech Stack:** Python 3.12, FastAPI + uvicorn, yt-dlp (CLI), ffmpeg (NVENC), pytest. Frontend HTML/JS vanilla + SSE.

**Spec:** `docs/superpowers/specs/2026-11-22-youtube-live-clipper-design.md`

## Global Constraints

- Windows, ffmpeg di PATH, `.venv` di root proyek.
- Dependency hanya: `yt-dlp`, `fastapi`, `uvicorn`, `pytest`.
- Output 1080x1920; facecam 1080x1000 di y=0; gameplay 1080x700 di y=1000; 220px bawah hitam.
- Pre-roll 20s, post-roll 10s, cooldown 60s, window 10s, baseline 300s, min rate 8 msg/s, k=3.
- UI Bahasa Indonesia, dark, tanpa framework.

## Review Focus

- Stream berakhir atau URL bukan live: dashboard harus menampilkan error jelas, bukan diam.
- Chat mati / rate 0 selama >30s saat status live: tampilkan peringatan, rekaman tetap jalan.
- Rect facecam di luar frame (x+w>1, negatif): clamp, jangan render gagal.
- Spike saat buffer belum 20s penuh: potong yang ada saja, jangan error.
- Dua spike berdekatan: cooldown menahan, hanya satu klip.

---

### Task 1: SpikeDetector

**Files:**
- Create: `core/__init__.py`, `core/detector.py`
- Test: `tests/test_detector.py`

**Interfaces:**
- Produces: `SpikeDetector(window=10.0, baseline_window=300.0, k=3.0, min_rate=8.0, cooldown=60.0)`;
  `.add(now: float, count: int = 1) -> None`;
  `.check(now: float) -> tuple[float, float] | None` (rate, baseline);
  `.snapshot(now: float) -> dict` dengan key `rate`, `baseline`, `threshold`, `last_spike`.

- [ ] **Step 1: Tulis test gagal**

```python
def test_spike_triggers_above_threshold_and_respects_cooldown():
    d = SpikeDetector(min_rate=5.0, cooldown=60.0)
    for i in range(100):          # baseline 5 msg/s selama 100 detik
        for _ in range(5):
            d.add(100.0 + i)
    for i in range(10):           # burst 30 msg/s
        for _ in range(30):
            d.add(200.0 + i)
    assert d.check(210.0) is not None
    assert d.check(211.0) is None  # cooldown

def test_no_spike_on_flat_chat():
    d = SpikeDetector(min_rate=8.0)
    for i in range(100):
        for _ in range(3):
            d.add(100.0 + i)
    assert d.check(200.0) is None

def test_short_history_does_not_fake_baseline():
    d = SpikeDetector(min_rate=8.0)
    for _ in range(10):
        d.add(100.0)
    assert d.snapshot(100.0)["baseline"] == 0.0
```

- [ ] **Step 2: Jalankan, pastikan FAIL** — `pytest tests/test_detector.py -q`
- [ ] **Step 3: Implementasi** — deque `(t, count)`, prune > `baseline_window`; `rate` = sum dalam window / window; `baseline` = median rate bucket 10s antara `now-baseline_window` dan `now-window`, minimal 6 bucket terisi, selain itu 0.0.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Commit** — `git add core tests && git commit -m "feat: spike detector"`

---

### Task 2: Clipper (filter graph + render)

**Files:**
- Create: `core/clipper.py`
- Test: `tests/test_clipper.py`

**Interfaces:**
- Produces: `build_filter(src_w: int, src_h: int, rect: dict, out_w=1080, out_h=1920, face_h=1000) -> str`;
  `render(segments: list[str], out_path: Path, rect: dict, workdir: Path, log=print) -> Path`;
  `pick_segments(entries: list[tuple[str, float, float]], t0: float, t1: float) -> list[str]`.

- [ ] **Step 1: Tulis test gagal**

```python
def test_build_filter_geometry_and_order():
    f = build_filter(1920, 1080, {"x": 0.68, "y": 0.03, "w": 0.29, "h": 0.40})
    assert "crop=557:432:1305:32" in f      # 0.29*1920, 0.40*1080
    assert "crop=1666:1080:127:0" in f      # gameplay 1080/700 aspect, center
    assert "vstack=inputs=2" in f
    assert "pad=1080:1920:0:0:black" in f
    assert f.index("[face]") < f.index("[game]")  # facecam di atas

def test_rect_clamped_inside_frame():
    f = build_filter(1920, 1080, {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5})
    assert "crop=192:108:1728:972" in f

def test_pick_segments_covers_window():
    entries = [(f"seg_{i:06d}.ts", i * 2.0, i * 2.0 + 2.0) for i in range(100)]
    assert pick_segments(entries, 20.0, 40.0) == [f"seg_{i:06d}.ts" for i in range(10, 20)]
```

- [ ] **Step 2: Jalankan, pastikan FAIL**
- [ ] **Step 3: Implementasi** — clamp rect ke `[0,1]` dan minimal 16x16 px; crop gameplay `gw = round(src_h * out_w / game_h)`, `game_h = out_h - face_h - 220`; concat demuxer list file; encode `h264_nvenc -preset p5 -cq 21 -b:v 0`, fallback `libx264 -crf 20` bila `nvenc` tidak ada di `ffmpeg -encoders`.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Commit**

---

### Task 3: Recorder

**Files:**
- Create: `core/recorder.py`
- Test: `tests/test_recorder.py`

**Interfaces:**
- Produces: `resolve(url: str) -> dict` (key `id`, `title`, `channel`, `is_live`);
  `class Recorder` dengan `.start(url, outdir) -> None`, `.stop() -> None`, `.alive() -> bool`,
  `.segments() -> list[tuple[str, float, float]]`, `.stream_time(now_wall: float) -> float`,
  `.prune(keep_seconds: float) -> None`, `.latest_segment() -> Path | None`.

- [ ] **Step 1: Tulis test gagal**

```python
def test_parse_segment_list(tmp_path):
    (tmp_path / "list.csv").write_text(
        "seg_000000.ts,0.000000,2.004000\nseg_000001.ts,2.004000,4.008000\n")
    r = Recorder()
    r.outdir = tmp_path
    assert r.segments() == [("seg_000000.ts", 0.0, 2.004), ("seg_000001.ts", 2.004, 4.008)]

def test_prune_deletes_only_old_files(tmp_path):
    for i, age in enumerate([300, 100, 5]):
        p = tmp_path / f"seg_{i:06d}.ts"; p.write_bytes(b"x")
        os.utime(p, (time.time() - age, time.time() - age))
    r = Recorder(); r.outdir = tmp_path
    r.prune(keep_seconds=60)
    assert sorted(p.name for p in tmp_path.glob("*.ts")) == ["seg_000001.ts", "seg_000002.ts"]
```

- [ ] **Step 2: Jalankan, pastikan FAIL**
- [ ] **Step 3: Implementasi** — `resolve` pakai `yt-dlp -J --no-warnings`; stream URL pakai `yt-dlp -g -f "best[protocol*=m3u8]/best"` (2 baris = video+audio, map terpisah); ffmpeg `-c copy -f segment -segment_time 2 -reset_timestamps 1 -segment_list list.csv -segment_list_type csv`; `stream_time` = `now - self.started_wall`.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Commit**

---

### Task 4: ChatWatcher

**Files:**
- Create: `core/chat.py`
- Test: `tests/test_chat.py`

**Interfaces:**
- Produces: `count_messages(lines: list[bytes]) -> int` (hanya baris dengan `"addChatItemAction"`);
  `class ChatWatcher(threading.Thread)` dengan `__init__(url, outdir, on_message, stop_event)`, `messages_seen` (int), `.last_message_at`.

- [ ] **Step 1: Tulis test gagal**

```python
def test_count_messages_ignores_tickers_and_viewers():
    lines = [
        b'{"replayChatItemAction":{"actions":[{"addChatItemAction":{"item":{"liveChatTextMessageRenderer":{}}}}]}}',
        b'{"replayChatItemAction":{"actions":[{"addLiveChatTickerItemAction":{}}]}}',
        b'{"replayChatItemAction":{"actions":[{"addChatItemAction":{"item":{"liveChatPaidMessageRenderer":{}}}}]}}',
        b'',
    ]
    assert count_messages(lines) == 2
```

- [ ] **Step 2: Jalankan, pastikan FAIL**
- [ ] **Step 3: Implementasi** — spawn `yt-dlp --skip-download --write-subs --sub-langs live_chat --no-warnings -o <outdir>/chat.%(ext)s <url>`; tail `chat.live_chat.json` tiap 0.5s, buffer sisa baris setengah, hitung lewat `count_messages`, panggil `on_message(n)`; berhenti saat `stop_event` atau proses yt-dlp mati.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Commit**

---

### Task 5: Manager

**Files:**
- Create: `core/manager.py`, `config.json`, `channels.json`
- Test: `tests/test_manager.py`

**Interfaces:**
- Produces: `Manager` dengan `.start(url) -> dict`, `.stop() -> dict`, `.state() -> dict`,
  `.save_rect(channel: str, rect: dict) -> None`, `.clips -> list[dict]`, `.logs -> deque`.
  `state()` key: `status` (`idle|starting|live|stopping|error`), `url`, `title`, `channel`, `uptime`, `rate`, `baseline`, `threshold`, `messages`, `clips`, `logs`, `error`, `rect`.

- [ ] **Step 1: Tulis test gagal**

```python
def test_state_idle_before_start(tmp_path):
    m = Manager(tmp_path)
    assert m.state()["status"] == "idle"

def test_rect_defaults_and_persists(tmp_path):
    m = Manager(tmp_path)
    assert m.rect_for("ishowspeed")["w"] == 0.29
    m.save_rect("ishowspeed", {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    assert Manager(tmp_path).rect_for("ishowspeed")["x"] == 0.1

def test_spike_schedules_clip_without_recorder(tmp_path):
    m = Manager(tmp_path)
    m.status = "live"; m.started_wall = time.time() - 100
    m._on_chat(200)
    assert m.pending_clips == 1
```

- [ ] **Step 2: Jalankan, pastikan FAIL**
- [ ] **Step 3: Implementasi** — monitor loop 1s: `detector.check`, prune, auto-stop saat recorder mati; clip worker thread menunggu `t1+2`, ambil segmen, render, append `{"file","score","at","title"}`; clamp daftar klip 100 terakhir.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Commit**

---

### Task 6: Dashboard + wiring

**Files:**
- Create: `app.py`, `static/index.html`, `static/app.js`, `static/style.css`, `run.bat`, `requirements.txt`, `README.md`
- Test: `tests/test_app.py` (TestClient: `/` 200, `/api/state` bentuk benar)

**Interfaces:**
- Consumes: `Manager` dari Task 5.
- Produces: routes `GET /`, `GET /api/state`, `GET /api/events`, `POST /api/start`, `POST /api/stop`, `POST /api/rect`, `GET /api/preview`, `GET /clips/{name}`.

- [ ] **Step 1: Tulis test gagal** — `client.get("/api/state").json()["status"] == "idle"`, `client.get("/").status_code == 200`
- [ ] **Step 2: Jalankan, pastikan FAIL**
- [ ] **Step 3: Implementasi** — SSE yield `json.dumps(state)` tiap 1s; preview = frame dari segmen terakhir (`ffmpeg -frames:v 1 -f image2pipe -vcodec mjpeg`); UI: status pill, input URL + Start/Stop, angka rate + sparkline canvas 120s, grid klip `<video>`, editor rect (4 input persen + canvas overlay), log pane.
- [ ] **Step 4: Jalankan, pastikan PASS**
- [ ] **Step 5: Smoke test** — `uvicorn app:app --port 8765`, buka `/`, cek `/api/state` 200, stop.
- [ ] **Step 6: Commit**

## Self-review

Spec coverage: rekam, chat, deteksi, potong, render 9:16, dashboard, config rect — semua punya task. VOD, upload, multi-stream = non-goal. Review Focus sudah dipetakan ke test: cooldown (T1), rect clamp (T2), buffer pendek (T2 `pick_segments` + T5), chat mati (T5 state), stream mati (T5 auto-stop).
