"""Pantau live chat lewat fitur subtitle live_chat milik yt-dlp."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def _offset_seconds(obj: dict) -> float | None:
    """Live: offset di level atas. Replay: di dalam replayChatItemAction."""
    ms = obj.get("videoOffsetTimeMsec")
    if ms is None:
        replay = obj.get("replayChatItemAction")
        if isinstance(replay, dict):
            ms = replay.get("videoOffsetTimeMsec")
    try:
        return int(ms) / 1000
    except (TypeError, ValueError):
        return None


def parse_messages(lines: list[bytes]) -> list[float]:
    """Offset video (detik) untuk tiap pesan chat. Abaikan ticker dan baris rusak."""
    offsets = []
    for line in lines:
        if b'"addChatItemAction"' not in line:
            continue
        try:
            seconds = _offset_seconds(json.loads(line))
        except (ValueError, AttributeError):
            continue
        if seconds is not None:
            offsets.append(seconds)
    return offsets


def download_chat(url: str, outdir: Path) -> Path:
    """Unduh seluruh chat replay (stream yang sudah selesai) jadi satu file JSONL."""
    outdir.mkdir(parents=True, exist_ok=True)
    res = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs",
         "--sub-langs", "live_chat", "--no-warnings", "--no-playlist",
         "-o", str(outdir / "chat.%(ext)s"), url],
        capture_output=True, text=True, timeout=1800)
    path = outdir / "chat.live_chat.json"
    if res.returncode != 0 or not path.exists():
        raise RuntimeError((res.stderr or "").strip()[-500:] or "chat replay tidak tersedia")
    return path


def read_offsets(path: Path) -> list[float]:
    offsets = []
    with path.open("rb") as fh:
        for line in fh:
            offsets.extend(parse_messages([line]))
    return offsets


def _read_from(path: Path, offset: int) -> tuple[bytes, int]:
    """Baca byte baru dari path. Reset ke awal kalau file mengecil (truncate/rotate)."""
    try:
        size = path.stat().st_size
    except OSError:
        return b"", offset
    if size < offset:
        offset = 0
    with path.open("rb") as fh:
        fh.seek(offset)
        return fh.read(), fh.tell()


class ChatWatcher(threading.Thread):
    def __init__(self, url: str, outdir: Path, on_message, stop_event: threading.Event):
        super().__init__(daemon=True)
        self.url = url
        self.outdir = outdir
        self.on_message = on_message
        self.stop_event = stop_event
        self.messages_seen = 0
        self.last_message_at: float | None = None
        self.proc: subprocess.Popen | None = None
        self.started = False

    def alive(self) -> bool:
        return self.is_alive() and self.proc is not None and self.proc.poll() is None

    def _consume(self, chunk: bytes, buf: bytes, primed: bool) -> tuple[bool, bytes]:
        if not chunk:
            return primed, buf
        buf += chunk
        *lines, buf = buf.split(b"\n")
        # frag pertama = backlog chat sebelum kita mulai; bukan laju live
        if not primed and lines:
            primed, lines = True, []
        self._emit(parse_messages(lines))
        return primed, buf

    def run(self) -> None:
        self.outdir.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-m", "yt_dlp", "--skip-download", "--write-subs",
               "--sub-langs", "live_chat", "--no-warnings", "--no-playlist",
               "-o", str(self.outdir / "chat.%(ext)s"), self.url]
        log = open(self.outdir / "chat.log", "w", encoding="utf-8")
        try:
            self.proc = subprocess.Popen(cmd, stdout=log, stderr=log)
            offset, buf, current = 0, b"", None
            primed = False
            while not self.stop_event.is_set() and self.proc.poll() is None:
                path = next((p for p in (self.outdir / "chat.live_chat.json.part",
                                         self.outdir / "chat.live_chat.json")
                             if p.exists()), None)
                if path:
                    self.started = True
                    current = path
                    chunk, offset = _read_from(path, offset)
                    primed, buf = self._consume(chunk, buf, primed)
                self.stop_event.wait(0.5)
            if not self.stop_event.is_set():
                path = next((p for p in (self.outdir / "chat.live_chat.json.part",
                                         self.outdir / "chat.live_chat.json")
                             if p.exists()), current)
                if path:
                    chunk, offset = _read_from(path, offset)
                    self._consume(chunk, buf, primed)
        finally:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
            log.close()

    def _emit(self, offsets: list[float]) -> None:
        """Petakan offset video ke jam dinding: pesan terakhir = waktu terima batch.

        Batch datang tiap ~10 detik, jadi waktu terima bukan waktu pesan. Offset
        pesan memberi urutan dan jarak yang benar.
        """
        if not offsets:
            return
        now = time.time()
        newest = max(offsets)
        for off in offsets:
            self.messages_seen += 1
            self.on_message(now - (newest - off))
        self.last_message_at = now
