import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
sys.path.append(str(root))

from core.clipper import render


def main():
    buffer_dir = root / "buffer"
    clips_dir = root / "clips"
    clips_dir.mkdir(exist_ok=True)

    segments = []
    list_file = buffer_dir / "list.csv"
    if list_file.exists():
        for line in list_file.read_text().splitlines():
            parts = line.split(",")
            if len(parts) == 3:
                segments.append(parts[0])

    if len(segments) < 5:
        print("Buffer belum cukup! Tunggu beberapa detik lagi di dashboard (pastikan status LIVE).")
        return

    test_segments = segments[-12:-2]
    print(f"Ketemu {len(test_segments)} segmen siap dirender.")

    channels_file = root / "channels.json"
    channels = json.loads(channels_file.read_text()) if channels_file.exists() else {}
    # channel terakhir yang disimpan = channel yang sedang dipakai
    channel_name = next(reversed(channels), "default")
    print(f"Menggunakan setting crop untuk channel: {channel_name}")
    rects = channels.get(channel_name, {})

    try:
        config = json.loads((root / "config.json").read_text())
    except Exception:
        config = {}

    subtitle_opts = {
        "enabled": bool(config.get("subtitles", True)),
        "model": config.get("subtitle_model", "small"),
        "language": config.get("subtitle_language", "id"),
        "y": config.get("subtitle_y", 0.51),
        "size": config.get("subtitle_size", 76),
    }

    out = clips_dir / "test_manual.mp4"
    print(f"Mulai merender ke {out}...")
    render(test_segments, out, rects, buffer_dir, log=print,
           subtitle_opts=subtitle_opts)
    print("Selesai! Cek folder clips/ dan buka test_manual.mp4")


if __name__ == "__main__":
    main()
