# Live Clipper

Pantau live YouTube, deteksi lonjakan live chat, potong klip vertikal 9:16
(facecam di atas, gameplay di bawah) otomatis.

## Pakai

1. Double-click `run.bat`. Browser terbuka di `http://127.0.0.1:8765`.
2. Tempel URL live YouTube: bisa live yang sedang jalan, atau replay live yang
   sudah selesai.
3. Start. Untuk live: tool merekam ke `buffer/`, memantau chat, dan menyimpan
   klip di `clips/`. Untuk replay: tool mengunduh chat replay dulu, mendeteksi
   lonjakan, lalu hanya mengunduh bagian video di sekitar lonjakan.
4. Saat klip pertama, cek hasilnya. Kalau facecam/gameplay kepotong, atur
   rect-nya di dashboard: klik **Ambil frame**, lalu isi x/y/w/h (persen)
   sampai kotak hijau pas di webcam dan kotak biru pas di gameplay, lalu
   **Simpan crop**. Rect disimpan per channel.
5. Posisi Y dan ukuran subtitle diatur di fieldset **Subtitle** (y % dari tinggi
   output, ukuran font dalam px), lalu **Simpan subtitle**. Garis putus-putus
   kuning di preview menandai posisi subtitle. Tombol **Subtitle: ON/OFF**
   mematikan atau menyalakan subtitle untuk klip berikutnya. **Simpan crop**
   juga menyimpan subtitle yang belum di-save.

## Setelan

`config.json`:

| key | arti |
|-----|------|
| `pre` | detik sebelum spike (default 20) |
| `post` | detik setelah spike (default 30) |
| `max_clip` | panjang klip maksimum, detik (default 50) |
| `window` | jendela hitung rate, detik |
| `baseline_window` | panjang baseline, detik |
| `k` | spike = k x baseline |
| `min_rate` | ambang minimum msg/detik |
| `cooldown` | jeda minimum antar klip, detik |
| `subtitles` | auto subtitle via faster-whisper (default `true`) |
| `subtitle_model` | ukuran model whisper (default `small`) |
| `subtitle_language` | kode bahasa, `null` = deteksi otomatis |
| `subtitle_y` | posisi vertikal subtitle, 0..1 dari atas (default `0.51` = tengah) |
| `subtitle_size` | ukuran font subtitle dalam px (default `76`) |

`channels.json` menyimpan rect webcam dan gameplay per channel (0..1, relatif
ke frame).

## Batasan

- Satu stream aktif dalam satu waktu.
- Butuh ffmpeg di PATH. NVENC dipakai kalau ada, kalau tidak fallback libx264.
- Stream publik saja. URL privat/umur terbatas tidak didukung.
- Live: buffer hanya menyimpan `pre + post + 60` detik; klip dibuat saat spike,
  bukan setelah live selesai. Panjang klip dibatasi `max_clip` (50 detik).
- Replay: chat replay harus tersedia (bisa dimatikan streamer). Video diunduh
  hanya pada rentang spike, jadi tidak perlu mengunduh seluruh replay.
- Klip pertama yang memakai subtitle mengunduh model faster-whisper dulu, jadi
  render bisa lama. Klip berikutnya memakai model yang sudah di-cache.
- Endpoint chat memakai fitur `live_chat` yt-dlp. Kalau YouTube mengubah
  protokol, chat rate akan 0 dan dashboard memberi peringatan.

## Dev

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn app:app --port 8765
.venv\Scripts\python tests\test_render.py
```

`tests/test_render.py` merender ~20 detik segmen terakhir dari `buffer/` ke
`clips/test_manual.mp4`, memakai rect channel yang terakhir disimpan dan setting
subtitle dari `config.json` (ON/OFF, `subtitle_y`, `subtitle_size`). Jalankan
saat dashboard sedang LIVE supaya buffer terisi.
