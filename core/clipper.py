"""Render klip vertikal 9:16: facecam di atas, gameplay di bawah."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from .subtitles import group_words, transcribe, write_ass

OUT_W, OUT_H = 1080, 1920
FACE_H = 920
GAME_H = OUT_H - FACE_H

# Kandidat encoder H.264, tercepat/terbaik duluan. Opsi mengikuti encoder:
# -cq hanya untuk NVENC, -crf hanya untuk x264, -b:v untuk openh264.
_ENCODERS: list[tuple[str, list[str]]] = [
    ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr",
                    "-cq", "21", "-b:v", "0"]),
    ("libx264", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]),
    ("libopenh264", ["-c:v", "libopenh264", "-b:v", "8M"]),
    ("mpeg4", ["-c:v", "mpeg4", "-q:v", "4"]),
]

_probe_cache: dict[str, bool] = {}
_probe_lock = threading.Lock()


def encoder_works(name: str) -> bool:
    """True kalau encoder benar-benar bisa dipakai, bukan cuma terdaftar.

    `ffmpeg -encoders` tetap mencantumkan h264_nvenc walau tidak ada GPU/driver
    NVIDIA, jadi encoder harus dicoba encode satu frame. Hasil di-cache.
    """
    with _probe_lock:
        if name in _probe_cache:
            return _probe_cache[name]
    try:
        res = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
             "-c:v", name, "-f", "null", "-"],
            capture_output=True, timeout=30)
        ok = res.returncode == 0
    except Exception:
        ok = False
    with _probe_lock:
        _probe_cache[name] = ok
    return ok


def video_encoders() -> list[list[str]]:
    """Argumen encoder yang bisa dipakai, urut preferensi. Kosong kalau tidak ada."""
    return [args for name, args in _ENCODERS if encoder_works(name)]


def has_nvenc() -> bool:
    return encoder_works("h264_nvenc")


def _clamp_rect(src_w: int, src_h: int, rect: dict,
                default: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
                ) -> tuple[int, int, int, int]:
    dx, dy, dw, dh = default
    x = min(max(float(rect.get("x", dx)), 0.0), 1.0)
    y = min(max(float(rect.get("y", dy)), 0.0), 1.0)
    w = min(max(float(rect.get("w", dw)), 0.0), 1.0 - x)
    h = min(max(float(rect.get("h", dh)), 0.0), 1.0 - y)
    px, py = round(x * src_w), round(y * src_h)
    pw, ph = round(w * src_w), round(h * src_h)
    pw = max(min(pw, src_w - px), 16)
    ph = max(min(ph, src_h - py), 16)
    return px, py, pw, ph


def build_filter(src_w: int, src_h: int, webcam: dict, gameplay: dict,
                 extra: str = "") -> str:
    fx, fy, fw, fh = _clamp_rect(src_w, src_h, webcam, (0.68, 0.03, 0.29, 0.40))
    gx, gy, gw, gh = _clamp_rect(src_w, src_h, gameplay)
    return (
        f"[0:v]setpts=PTS-STARTPTS,split=2[g][f];"
        f"[f]crop={fw}:{fh}:{fx}:{fy},"
        f"scale={OUT_W}:{FACE_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{FACE_H},setsar=1[face];"
        f"[g]crop={gw}:{gh}:{gx}:{gy},"
        f"scale={OUT_W}:{GAME_H}:force_original_aspect_ratio=increase,"
        f"crop={OUT_W}:{GAME_H},setsar=1[game];"
        f"[face][game]vstack=inputs=2,pad={OUT_W}:{OUT_H}:0:0:black{extra}[v]"
    )


def pick_segments(entries: list[tuple[str, float, float]], t0: float, t1: float) -> list[str]:
    return [name for name, start, end in entries if end > t0 and start < t1]


def _first_pts(path: Path, stream: str) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream,
         "-show_entries", "packet=pts_time", "-of", "csv=p=0",
         "-read_intervals", "%+#1", str(path)],
        capture_output=True, text=True).stdout.strip()
    try:
        return float(out.split(",")[0])
    except (ValueError, IndexError):
        return None


def _has_audio(path: Path) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True).stdout.strip()
    return bool(out)


def _audio_chain(first_segment: Path) -> str:
    """Koreksi audio yang datang terlambat/terlalu awal dari dua input HLS terpisah.

    shortcut: hanya offset awal segmen pertama; kalau audio masih meleset di
    tengah klip, perlu koreksi per segmen.
    """
    vstart = _first_pts(first_segment, "v:0")
    astart = _first_pts(first_segment, "a:0")
    delta = (astart - vstart) if vstart is not None and astart is not None else 0.0
    # Video dipetakan ke start-nya sendiri (setpts). Audio harus ikut video:
    # audio yang mulai lebih lambat ditunda, yang mulai lebih awal dipotong.
    if delta > 0.05:
        ms = int(round(delta * 1000))
        return f"adelay={ms}|{ms},aresample=async=1:first_pts=0"
    if delta < -0.05:
        return f"atrim=start={-delta:.3f},asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0"
    return "aresample=async=1:first_pts=0"


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


def _burn_subtitles(list_file: Path, workdir: Path, out_stem: str,
                    opts: dict, audio_filter: str, log) -> str:
    wav = workdir / f"sub_{out_stem}.wav"
    ass_name = f"sub_{out_stem}.ass"
    try:
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
               "-f", "concat", "-safe", "0", "-i", str(list_file),
               "-vn", "-ac", "1", "-ar", "16000"]
        if audio_filter:
            cmd += ["-af", audio_filter]
        cmd.append(str(wav))
        subprocess.run(cmd, check=True, capture_output=True)
        words = transcribe(wav, opts.get("model", "small"), opts.get("language"))
        chunks = group_words(words)
        if not chunks:
            return ""
        write_ass(chunks, workdir / ass_name,
                  font_size=int(opts.get("size", 76)),
                  pos_y=float(opts.get("y", 0.51)))
        log(f"subtitle: {len(chunks)} baris")
        return f",ass={ass_name}"
    except Exception as exc:
        log(f"subtitle dilewati: {exc}")
        return ""
    finally:
        wav.unlink(missing_ok=True)


def render(segments: list[str], out_path: Path, rects: dict, workdir: Path,
           log=print, subtitle_opts: dict | None = None,
           max_duration: float | None = None) -> Path:
    stem = out_path.stem
    list_file = workdir / f"concat_{stem}.txt"
    list_file.write_text(
        "".join(f"file '{(workdir / s).as_posix()}'\n" for s in segments), encoding="utf-8")

    src_w, src_h = _probe_size(segments, workdir)
    first = workdir / segments[0]
    has_audio = _has_audio(first)
    audio_filter = _audio_chain(first) if has_audio else ""

    extra = ""
    if has_audio and subtitle_opts and subtitle_opts.get("enabled"):
        extra = _burn_subtitles(list_file, workdir, stem, subtitle_opts, audio_filter, log)

    video_filter = build_filter(src_w, src_h, rects.get("webcam", {}),
                                rects.get("gameplay", {}), extra)
    filters = [video_filter]
    if has_audio:
        filters.append(f"[0:a]{audio_filter}[a]")

    base = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-filter_complex", ";".join(filters), "-map", "[v]"]
    if has_audio:
        base += ["-map", "[a]", "-c:a", "aac", "-b:a", "128k"]
    if max_duration:
        base += ["-t", f"{max_duration:g}"]

    encoders = video_encoders()
    if not encoders:
        list_file.unlink(missing_ok=True)
        (workdir / f"sub_{stem}.ass").unlink(missing_ok=True)
        raise RuntimeError("tidak ada encoder video yang bisa dipakai; cek instalasi ffmpeg")

    last_error = ""
    for enc in encoders:
        cmd = [*base, *enc, "-movflags", "+faststart", str(out_path)]
        log("render: " + " ".join(cmd))
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
        if res.returncode == 0:
            break
        last_error = (res.stderr or "").strip()[-800:]
        log(f"encoder {enc[1]} gagal, coba berikutnya: {last_error[-300:]}")
        out_path.unlink(missing_ok=True)
    else:
        list_file.unlink(missing_ok=True)
        (workdir / f"sub_{stem}.ass").unlink(missing_ok=True)
        raise RuntimeError(last_error or "ffmpeg gagal")

    list_file.unlink(missing_ok=True)
    (workdir / f"sub_{stem}.ass").unlink(missing_ok=True)
    return out_path
