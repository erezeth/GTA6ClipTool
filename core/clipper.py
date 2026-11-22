"""Render klip vertikal 9:16: facecam di atas, gameplay di bawah."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

OUT_W, OUT_H = 1080, 1920
FACE_H = 1000
SAFE_H = 220
GAME_H = OUT_H - FACE_H - SAFE_H

_nvenc: bool | None = None
_nvenc_lock = threading.Lock()


def has_nvenc() -> bool:
    global _nvenc
    with _nvenc_lock:
        if _nvenc is None:
            try:
                out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                     capture_output=True, text=True, timeout=30).stdout
                _nvenc = "h264_nvenc" in out
            except Exception:
                _nvenc = False
        return _nvenc


def _clamp_rect(src_w: int, src_h: int, rect: dict) -> tuple[int, int, int, int]:
    x = min(max(float(rect.get("x", 0.68)), 0.0), 1.0)
    y = min(max(float(rect.get("y", 0.03)), 0.0), 1.0)
    w = min(max(float(rect.get("w", 0.29)), 0.0), 1.0 - x)
    h = min(max(float(rect.get("h", 0.40)), 0.0), 1.0 - y)
    px, py = round(x * src_w), round(y * src_h)
    pw, ph = round(w * src_w), round(h * src_h)
    pw = max(min(pw, src_w - px), 16)
    ph = max(min(ph, src_h - py), 16)
    return px, py, pw, ph


def build_filter(src_w: int, src_h: int, rect: dict) -> str:
    fx, fy, fw, fh = _clamp_rect(src_w, src_h, rect)
    gw = min(round(src_h * OUT_W / GAME_H), src_w)
    gh = src_h
    gx = (src_w - gw) // 2
    gy = (src_h - gh) // 2
    return (
        f"[0:v]split=2[g][f];"
        f"[f]crop={fw}:{fh}:{fx}:{fy},"
        f"scale={OUT_W}:{FACE_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{FACE_H},setsar=1[face];"
        f"[g]crop={gw}:{gh}:{gx}:{gy},scale={OUT_W}:{GAME_H},setsar=1[game];"
        f"[face][game]vstack=inputs=2,pad={OUT_W}:{OUT_H}:0:0:black[v]"
    )


def pick_segments(entries: list[tuple[str, float, float]], t0: float, t1: float) -> list[str]:
    return [name for name, start, end in entries if end > t0 and start < t1]


def render(segments: list[str], out_path: Path, rect: dict, workdir: Path,
           log=print) -> Path:
    list_file = workdir / f"concat_{out_path.stem}.txt"
    list_file.write_text(
        "".join(f"file '{(workdir / s).as_posix()}'\n" for s in segments), encoding="utf-8")

    src_w, src_h = _probe_size(segments, workdir)

    if has_nvenc():
        enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    else:
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-filter_complex", build_filter(src_w, src_h, rect),
           "-map", "[v]", "-map", "0:a?", *enc,
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_path)]
    log("render: " + " ".join(cmd))
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or "").strip()[-800:] or "ffmpeg gagal")
    list_file.unlink(missing_ok=True)
    return out_path


def _probe_size(segments: list[str], workdir: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0",
         str(workdir / segments[0])],
        capture_output=True, text=True).stdout.strip()
    try:
        w, h = (int(v) for v in out.split(",")[:2])
        return w, h
    except ValueError:
        return 1920, 1080
