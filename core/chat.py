"""Pantau live chat lewat fitur subtitle live_chat milik yt-dlp."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path


def parse_messages(lines: list[bytes]) -> list[float]:
    """Offset video (detik) untuk tiap pesan chat. Abaikan ticker dan baris rusak."""
    offsets = []
    for line in lines:
        if b'"addChatItemAction"' not in line:
            continue
        try:
            obj = json.loads(line)
            offsets.append(int(obj["videoOffsetTimeMsec"]) / 1000)
        except (ValueError, KeyError, TypeError):
            continue
    return offsets


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
                    if path != current:
                        if current is not None and primed:
                            offset, buf = path.stat().st_size, b""
                        else:
                            offset, buf = 0, b""
                        current = path
                    with open(path, "rb") as fh:
                        fh.seek(offset)
                        chunk = fh.read()
                        offset = fh.tell()
                    if chunk:
                        buf += chunk
                        *lines, buf = buf.split(b"\n")
                        # frag pertama = backlog chat sebelum kita mulai; bukan laju live
                        if not primed and lines:
                            primed, lines = True, []
                        self._emit(parse_messages(lines))
                self.stop_event.wait(0.5)
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
