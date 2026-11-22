"""Rekam live YouTube jadi segmen 2 detik, plus utilitas resolve dan prune."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

YTDLP = [sys.executable, "-m", "yt_dlp"]


def resolve(url: str) -> dict:
    res = subprocess.run(
        [*YTDLP, "-J", "--no-warnings", "--no-playlist", url],
        capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "").strip()[-500:] or "yt-dlp gagal")
    info = json.loads(res.stdout)
    return {
        "id": info.get("id", ""),
        "title": info.get("title", ""),
        "channel": info.get("channel") or info.get("uploader") or "unknown",
        "is_live": info.get("live_status") in ("is_live", "is_upcoming") or bool(info.get("is_live")),
    }


def _stream_urls(url: str) -> list[str]:
    res = subprocess.run(
        [*YTDLP, "-g", "--no-warnings", "--no-playlist",
         "-f", "bv*+ba/b", url],
        capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "").strip()[-500:] or "gagal ambil stream URL")
    urls = [line.strip() for line in res.stdout.splitlines() if line.strip()]
    if not urls:
        raise RuntimeError("stream URL kosong")
    return urls[:2]


class Recorder:
    def __init__(self):
        self.outdir: Path | None = None
        self.proc: subprocess.Popen | None = None
        self.started_wall: float = 0.0

    def start(self, url: str, outdir: Path) -> None:
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)
        urls = _stream_urls(url)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]
        for u in urls:
            cmd += ["-i", u]
        if len(urls) > 1:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += ["-c", "copy", "-f", "segment", "-segment_time", "2",
                "-reset_timestamps", "1", "-segment_list", "list.csv",
                "-segment_list_type", "csv", "seg_%06d.ts"]
        self.log = open(outdir / "ffmpeg.log", "w", encoding="utf-8")
        self.started_wall = time.time()
        self.proc = subprocess.Popen(cmd, cwd=outdir, stdout=self.log, stderr=self.log)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if getattr(self, "log", None):
            self.log.close()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stream_time(self, now_wall: float) -> float:
        return now_wall - self.started_wall

    def segments(self) -> list[tuple[str, float, float]]:
        if not self.outdir:
            return []
        path = self.outdir / "list.csv"
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.strip().split(",")
            if len(parts) != 3:
                continue
            try:
                entries.append((Path(parts[0]).name, float(parts[1]), float(parts[2])))
            except ValueError:
                continue
        return entries

    def prune(self, keep_seconds: float) -> None:
        if not self.outdir or not self.outdir.exists():
            return
        cutoff = time.time() - keep_seconds
        for path in self.outdir.glob("seg_*.ts"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
            except OSError:
                pass

    def latest_segment(self) -> Path | None:
        if not self.outdir or not self.outdir.exists():
            return None
        files = list(self.outdir.glob("seg_*.ts"))
        return max(files, key=lambda p: p.stat().st_mtime) if files else None
