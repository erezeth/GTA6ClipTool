"""Transkripsi klip dan pembuatan subtitle ASS (burn-in)."""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

_models: dict[tuple[str, str], object] = {}
_cpu_only = False


def _model(size: str):
    if _cpu_only:
        return _model_cpu(size)
    key = (size, "cuda")
    if key not in _models:
        from faster_whisper import WhisperModel
        try:
            _models[key] = WhisperModel(size, device="cuda", compute_type="float16")
        except Exception:
            return _model_cpu(size)
    return _models[key]


def _model_cpu(size: str):
    key = (size, "cpu")
    if key not in _models:
        from faster_whisper import WhisperModel
        _models[key] = WhisperModel(size, device="cpu", compute_type="int8")
    return _models[key]


def _load_wav(path: Path) -> np.ndarray:
    """Baca WAV 16 kHz mono 16-bit (hasil ffmpeg) jadi array float32.

    Dengan ini faster-whisper tidak decode lewat PyAV, jadi versi `av` tidak
    lagi memengaruhi timing transkripsi (penyebab subtitle/audio meleset).
    """
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"WAV harus 16-bit, dapat {w.getsampwidth() * 8}-bit")
        channels = w.getnchannels()
        raw = w.readframes(w.getnframes())
    data = np.frombuffer(raw, dtype=np.int16)
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return data.astype(np.float32) / 32768.0


def _run(model, samples: np.ndarray, language: str | None) -> list[dict]:
    # segments adalah generator: transkripsi baru jalan saat di-iterasi,
    # jadi error CUDA muncul di sini, bukan saat model dibuat.
    segments, _ = model.transcribe(
        samples, word_timestamps=True, vad_filter=True, language=language)
    words = []
    for seg in segments:
        for word in seg.words or []:
            text = word.word.strip()
            if text:
                words.append({"start": word.start, "end": word.end, "text": text})
    return words


def transcribe(audio: Path, model_size: str = "small", language: str | None = None) -> list[dict]:
    global _cpu_only
    samples = _load_wav(audio)
    try:
        return _run(_model(model_size), samples, language)
    except Exception as exc:
        msg = str(exc).lower()
        if _cpu_only or not any(k in msg for k in ("cublas", "cudnn", "cuda", ".dll")):
            raise
        print(f"CUDA tidak bisa dipakai ({exc}); pindah ke CPU.")
        _cpu_only = True
        return _run(_model_cpu(model_size), samples, language)


def group_words(words: list[dict], max_words: int = 3, max_chars: int = 20,
                max_dur: float = 2.2, max_gap: float = 0.7) -> list[dict]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for word in words:
        if current:
            gap = word["start"] - current[-1]["end"]
            joined = len(" ".join(w["text"] for w in [*current, word]))
            if (len(current) >= max_words or gap > max_gap or joined > max_chars
                    or word["end"] - current[0]["start"] > max_dur):
                chunks.append(current)
                current = []
        current.append(word)
    if current:
        chunks.append(current)
    return [{"start": c[0]["start"], "end": c[-1]["end"],
             "text": " ".join(w["text"] for w in c)} for c in chunks]


def _ass_time(seconds: float) -> str:
    cs = int(round(max(seconds, 0) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def write_ass(chunks: list[dict], path: Path, width: int = 1080, height: int = 1920,
              font_size: int = 76, pos_x: float = 0.5, pos_y: int = 980) -> Path:
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,7,2,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for chunk in chunks:
        text = _escape(chunk["text"])
        lines.append(
            f"Dialogue: 0,{_ass_time(chunk['start'])},{_ass_time(chunk['end'])},Default,,0,0,0,,"
            f"{{\\pos({round(pos_x * width)},{pos_y})}}{text}\n")
    path.write_text("".join(lines), encoding="utf-8")
    return path
