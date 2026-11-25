import json
import sys
from pathlib import Path

# 1. Daftarkan folder utama (D:\clip) ke sistem agar bisa import 'core'
root = Path(__file__).resolve().parent.parent
sys.path.append(str(root))

from core.clipper import render

# 2. Setup path buffer dan clips
buffer_dir = root / "buffer"
clips_dir = root / "clips"
clips_dir.mkdir(exist_ok=True)

# 3. Ambil segmen terakhir dari list.csv
segments = []
list_file = buffer_dir / "list.csv"
if list_file.exists():
    for line in list_file.read_text().splitlines():
        parts = line.split(",")
        if len(parts) == 3:
            segments.append(parts[0])

if len(segments) < 5:
    print("Buffer belum cukup! Tunggu beberapa detik lagi di dashboard (pastikan status LIVE).")
    exit()

# Ambil 10 segmen terakhir (sekitar 20 detik)
test_segments = segments[-12:-2]
print(f"Ketemu {len(test_segments)} segmen siap dirender.")

# 4. Ambil setting crop dari channels.json
channels = json.loads((root / "channels.json").read_text())
channel_name = list(channels.keys())[0] if channels else "default"
print(f"Menggunakan setting crop untuk channel: {channel_name}")
rects = channels.get(channel_name, {})

# 5. Ambil setting subtitle dari config.json
try:
    config = json.loads((root / "config.json").read_text())
except Exception:
    config = {}

subtitle_opts = {
    "enabled": True,  # <--- SUDAH DIAKTIFKAN UNTUK TEST
    "model": config.get("subtitle_model", "small"),
    "language": config.get("subtitle_language", "id")
}

# 6. Render!
out = clips_dir / "test_manual.mp4"
print(f"Mulai merender ke {out}...")

render(
    test_segments, 
    out, 
    rects, 
    buffer_dir, 
    log=print, 
    subtitle_opts=subtitle_opts
)
print("Selesai! Cek folder clips/ dan buka test_manual.mp4")