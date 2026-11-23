"""Orkestrasi: rekam, pantau chat, deteksi, potong."""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from pathlib import Path

from .chat import ChatWatcher, download_chat, read_offsets
from .clipper import pick_segments, render
from .detector import SpikeDetector, find_spikes
from .recorder import Recorder, download_section, resolve

DEFAULT_WEBCAM = {"x": 0.68, "y": 0.03, "w": 0.29, "h": 0.40}
DEFAULT_GAMEPLAY = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
DEFAULT_CONFIG = {"pre": 20, "post": 30, "cooldown": 60, "window": 10,
                  "baseline_window": 300, "k": 3, "min_rate": 8,
                  "max_clip": 50, "subtitles": True,
                  "subtitle_model": "small", "subtitle_language": None,
                  "subtitle_x": 0.5, "subtitle_size": 76}


def _fmt_time(seconds: float) -> str:
    return time.strftime("%H:%M:%S", time.gmtime(max(seconds, 0)))


class Manager:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.clips_dir = self.root / "clips"
        self.buffer_dir = self.root / "buffer"
        self.channels_path = self.root / "channels.json"
        self.config = dict(self._load_json(self.root / "config.json", DEFAULT_CONFIG))
        self.status = "idle"
        self.error: str | None = None
        self.url = ""
        self.title = ""
        self.channel = ""
        self.started_wall: float | None = None
        self.vod_messages = 0
        self.detector = SpikeDetector(**{k: self.config[k] for k in
                                         ("window", "baseline_window", "k", "min_rate", "cooldown")})
        self.recorder = Recorder()
        self.chat: ChatWatcher | None = None
        self.clips: list[dict] = []
        self.logs: deque[str] = deque(maxlen=200)
        self.clips_scheduled = 0
        self._stop = threading.Event()
        self._job = 0
        self.chat_warning: str | None = None
        self._chat_restarts = 0
        self._chat_last_problem: str | None = None
        self._chat_since: float | None = None

    # ---- state ----

    def state(self) -> dict:
        now = time.time()
        snap = self.detector.snapshot(now)
        return {
            "status": self.status,
            "error": self.error,
            "url": self.url,
            "title": self.title,
            "channel": self.channel,
            "uptime": round(now - self.started_wall) if self.started_wall else 0,
            "messages": self.chat.messages_seen if self.chat else self.vod_messages,
            "chat_started": bool(self.chat and self.chat.started),
            "chat_warning": self.chat_warning,
            "clips_scheduled": self.clips_scheduled,
            "clips": self.clips[-50:],
            "logs": list(self.logs)[-60:],
            "rects": self.rects_for(self.channel),
            "subtitle": {"enabled": bool(self.config.get("subtitles", True)),
                         "x": self.config.get("subtitle_x", 0.5),
                         "size": self.config.get("subtitle_size", 76)},
            **snap,
        }

    def log(self, msg: str) -> None:
        self.logs.append(f"{time.strftime('%H:%M:%S')} {msg}")

    # ---- channel rect ----

    @staticmethod
    def _clean(rect: dict, default: dict) -> dict:
        clean = {k: min(max(float(rect.get(k, default[k])), 0.0), 1.0) for k in default}
        clean["w"] = min(clean["w"], 1.0 - clean["x"])
        clean["h"] = min(clean["h"], 1.0 - clean["y"])
        return clean

    def rects_for(self, channel: str) -> dict:
        data = self._load_json(self.channels_path, {})
        entry = data.get(channel) or data.get(channel.lower()) or {}
        if "webcam" in entry or "gameplay" in entry:
            return {"webcam": self._clean(entry.get("webcam", {}), DEFAULT_WEBCAM),
                    "gameplay": self._clean(entry.get("gameplay", {}), DEFAULT_GAMEPLAY)}
        # format lama: rect datar = webcam
        return {"webcam": self._clean(entry, DEFAULT_WEBCAM),
                "gameplay": dict(DEFAULT_GAMEPLAY)}

    def save_rects(self, channel: str, webcam: dict, gameplay: dict) -> None:
        data = self._load_json(self.channels_path, {})
        clean = {"webcam": self._clean(webcam or {}, DEFAULT_WEBCAM),
                 "gameplay": self._clean(gameplay or {}, DEFAULT_GAMEPLAY)}
        data[channel or "default"] = clean
        self.channels_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.log(f"rect {channel}: webcam {clean['webcam']} gameplay {clean['gameplay']}")

    def save_config(self, patch: dict) -> None:
        if "subtitles" in patch:
            self.config["subtitles"] = bool(patch["subtitles"])
        if "subtitle_x" in patch:
            self.config["subtitle_x"] = min(max(float(patch["subtitle_x"]), 0.0), 1.0)
        if "subtitle_size" in patch:
            self.config["subtitle_size"] = min(max(int(patch["subtitle_size"]), 20), 200)
        (self.root / "config.json").write_text(
            json.dumps(self.config, indent=2), encoding="utf-8")
        self.log(f"subtitle: {'on' if self.config.get('subtitles', True) else 'off'} "
                 f"x {self.config.get('subtitle_x')} size {self.config.get('subtitle_size')}")

    @staticmethod
    def _load_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    # ---- lifecycle ----

    def start(self, url: str) -> dict:
        if self.status in ("starting", "live", "vod"):
            return {"ok": False, "error": "stream lain sedang aktif"}
        if not url.strip():
            return {"ok": False, "error": "URL kosong"}
        self.url = url.strip()
        self.status = "starting"
        self.error = None
        self.vod_messages = 0
        self.clips_scheduled = 0
        self.chat_warning = None
        self._chat_restarts = 0
        self._chat_last_problem = None
        self._chat_since = None
        self._stop.clear()
        self._job += 1
        threading.Thread(target=self._start_worker, args=(self._job,), daemon=True).start()
        return {"ok": True}

    def _start_worker(self, job: int) -> None:
        try:
            self.log("resolve URL...")
            info = resolve(self.url)
            if self._job != job:
                return
            if info.get("live_status") == "was_live":
                self._run_vod(info, job)
                return
            if not info["is_live"]:
                raise RuntimeError("URL bukan live atau replay live")
            self.title = info["title"]
            self.channel = info["channel"]
            self.log(f"live: {self.title} ({self.channel})")

            self.buffer_dir.mkdir(parents=True, exist_ok=True)
            self.clips_dir.mkdir(parents=True, exist_ok=True)
            for old in self.buffer_dir.glob("seg_*.ts"):
                old.unlink(missing_ok=True)
            for old in self.buffer_dir.glob("chat.live_chat.json*"):
                old.unlink(missing_ok=True)

            self.recorder = Recorder()
            self.recorder.start(self.url, self.buffer_dir)
            self.started_wall = time.time()
            self.detector = SpikeDetector(
                window=self.config["window"], baseline_window=self.config["baseline_window"],
                k=self.config["k"], min_rate=self.config["min_rate"],
                cooldown=self.config["cooldown"])
            self.chat = ChatWatcher(self.url, self.buffer_dir, self._on_chat, self._stop)
            self._chat_since = time.time()
            self.chat.start()
            self.status = "live"
            self.log("rekaman jalan")
            threading.Thread(target=self._monitor_loop, daemon=True).start()
        except Exception as exc:
            if self._job == job:
                self.status = "error"
                self.error = str(exc)
                self.log(f"error: {exc}")

    def _run_vod(self, info: dict, job: int) -> None:
        """Replay live yang sudah selesai: chat dulu, deteksi, unduh hanya bagian spike."""
        self.status = "vod"
        self.title = info["title"]
        self.channel = info["channel"]
        self.chat = None
        self.started_wall = time.time()
        self.log(f"replay: {self.title} ({self.channel})")
        self.buffer_dir.mkdir(parents=True, exist_ok=True)
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        for old in self.buffer_dir.glob("sec_*.mp4"):
            old.unlink(missing_ok=True)
        for old in self.buffer_dir.glob("chat.live_chat.json*"):
            old.unlink(missing_ok=True)
        url = self.url
        video_id = re.sub(r"[^A-Za-z0-9_-]+", "_", info.get("id", ""))[:40]

        self.log("download chat replay...")
        chat_path = download_chat(url, self.buffer_dir)
        offsets = read_offsets(chat_path)
        chat_path.unlink(missing_ok=True)
        self.vod_messages = len(offsets)
        if self._job != job or self._stop.is_set():
            return
        if not offsets:
            raise RuntimeError("chat replay tidak tersedia")
        self.log(f"chat: {len(offsets)} pesan")

        spikes = find_spikes(
            offsets, window=self.config["window"],
            baseline_window=self.config["baseline_window"], k=self.config["k"],
            min_rate=self.config["min_rate"], cooldown=self.config["cooldown"])
        self.clips_scheduled = len(spikes)
        self.log(f"deteksi: {len(spikes)} spike")

        pre = self.config["pre"]
        post = min(self.config["post"], max(self.config["max_clip"] - pre, 1))
        for i, (t, rate, base) in enumerate(spikes, 1):
            if self._job != job or self._stop.is_set():
                return
            self.log(f"klip {i}/{len(spikes)}: video {_fmt_time(t)}")
            self._render_vod_clip(job, url, video_id, t, max(t - pre, 0.0), t + post,
                                  rate, base)
        if self._job == job and not self._stop.is_set():
            self.status = "done"
            self.log("replay selesai")

    def _render_vod_clip(self, job: int, url: str, video_id: str, t: float,
                         t0: float, t1: float, rate: float, base: float) -> None:
        section = None
        try:
            section = download_section(
                url, t0, t1, self.buffer_dir / f"sec_{int(t)}.mp4")
            if self._job != job or self._stop.is_set():
                return
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", self.channel)[:40] or "channel"
            stem = f"{safe}_{video_id}" if video_id else safe
            out = self.clips_dir / f"{stem}_{int(t)}.mp4"
            render([section.name], out, self.rects_for(self.channel), self.buffer_dir,
                   self.log, self._subtitle_opts(), max_duration=t1 - t0)
            score = rate / base if base > 0 else rate / self.config["min_rate"]
            self.clips.append({
                "file": out.name,
                "score": round(score, 2),
                "rate": round(rate, 1),
                "at": f"video {_fmt_time(t)}",
                "title": self.title,
            })
            self.log(f"klip jadi: {out.name}")
        except Exception as exc:
            self.log(f"klip gagal: {exc}")
        finally:
            if section:
                section.unlink(missing_ok=True)

    def _subtitle_opts(self) -> dict:
        return {
            "enabled": bool(self.config.get("subtitles", True)),
            "model": self.config.get("subtitle_model", "small"),
            "language": self.config.get("subtitle_language"),
            "x": self.config.get("subtitle_x", 0.5),
            "size": self.config.get("subtitle_size", 76),
        }

    def stop(self) -> dict:
        self._stop.set()
        if self.chat:
            self.chat.join(timeout=5)
        self.recorder.stop()
        self.status = "idle"
        self.started_wall = None
        self.log("berhenti")
        return {"ok": True}

    def _chat_problem(self, now: float) -> str | None:
        chat = self.chat
        if not chat or self.status != "live":
            return None
        if not chat.is_alive():
            return "chat mati"
        if chat.started and chat.last_message_at and now - chat.last_message_at > 30:
            return "chat macet >30 detik"
        if not chat.started and self._chat_since and now - self._chat_since > 30:
            return "chat belum terbaca setelah 30 detik"
        return None

    def _restart_chat(self) -> None:
        if self._stop.is_set() or not self.url or self._chat_restarts >= 5:
            return
        self._chat_restarts += 1
        seen = self.chat.messages_seen if self.chat else 0
        self.log(f"restart chat ({self._chat_restarts}/5)")
        self.chat = ChatWatcher(self.url, self.buffer_dir, self._on_chat, self._stop)
        self.chat.messages_seen = seen
        self._chat_since = time.time()
        self.chat.start()
        self._chat_last_problem = None

    def _monitor_loop(self) -> None:
        while not self._stop.wait(1.0):
            if not self.recorder.alive():
                self.status = "error"
                self.error = "rekaman berhenti (stream selesai atau jaringan putus)"
                self.log(self.error)
                self._stop.set()
                return
            self.recorder.prune(self.config["pre"] + self.config["post"] + 60)
            problem = self._chat_problem(time.time())
            self.chat_warning = problem
            if problem and problem != self._chat_last_problem:
                self._chat_last_problem = problem
                self.log(f"peringatan: {problem}")
                if problem == "chat mati":
                    self._restart_chat()
            elif not problem:
                self._chat_last_problem = None

    # ---- detection ----

    def _on_chat(self, t: float) -> None:
        self.detector.add(t)
        hit = self.detector.check(t)
        if not hit:
            return
        rate, base = hit
        self.clips_scheduled += 1
        self.log(f"spike {rate:.1f} msg/s (baseline {base:.1f})")
        threading.Thread(target=self._clip_worker, args=(t, rate, base), daemon=True).start()

    def _clip_worker(self, spike_wall: float, rate: float, base: float) -> None:
        if self.recorder.outdir is None:
            return
        try:
            pre = self.config["pre"]
            post = min(self.config["post"], max(self.config["max_clip"] - pre, 1))
            t0 = max(self.recorder.stream_time(spike_wall) - pre, 0.0)
            t1 = self.recorder.stream_time(spike_wall) + post
            while time.time() < spike_wall + post + 2:
                time.sleep(0.5)
            names = pick_segments(self.recorder.segments(), t0, t1)
            if not names:
                self.log("klip batal: buffer kosong")
                return
            safe = re.sub(r"[^A-Za-z0-9_-]+", "_", self.channel)[:40] or "channel"
            out = self.clips_dir / f"{safe}_{int(spike_wall)}.mp4"
            render(names, out, self.rects_for(self.channel), self.buffer_dir, self.log,
                   self._subtitle_opts(), max_duration=self.config["max_clip"])
            score = rate / base if base > 0 else rate / self.config["min_rate"]
            self.clips.append({
                "file": out.name,
                "score": round(score, 2),
                "rate": round(rate, 1),
                "at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(spike_wall)),
                "title": self.title,
            })
            self.log(f"klip jadi: {out.name} ({len(names)} segmen)")
        except Exception as exc:
            self.log(f"klip gagal: {exc}")
