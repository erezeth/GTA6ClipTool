# Live Clipper

Pantau live YouTube, deteksi lonjakan live chat, potong klip vertikal 9:16
(facecam di atas, gameplay di bawah) otomatis.

## Pakai

1. Double-click `run.bat`. Browser terbuka di `http://127.0.0.1:8765`.
2. Tempel URL live YouTube (harus sedang live, bukan VOD).
3. Start. Tool merekam ke `buffer/`, memantau chat, dan menyimpan klip di `clips/`.
4. Saat klip pertama, cek hasilnya. Kalau facecam kepotong, atur rect facecam
   di dashboard: klik **Ambil frame**, lalu isi x/y/w/h (persen) sampai kotak
   pas di webcam streamer, lalu **Simpan**. Rect disimpan per channel.

## Setelan

`config.json`:

| key | arti |
|-----|------|
| `pre` | detik sebelum spike (default 20) |
| `post` | detik setelah spike (default 10) |
| `window` | jendela hitung rate, detik |
| `baseline_window` | panjang baseline, detik |
| `k` | spike = k x baseline |
| `min_rate` | ambang minimum msg/detik |
| `cooldown` | jeda minimum antar klip, detik |

`channels.json` menyimpan rect facecam per channel (0..1, relatif ke frame).

## Batasan

- Satu stream aktif dalam satu waktu.
- Butuh ffmpeg di PATH. NVENC dipakai kalau ada, kalau tidak fallback libx264.
- Stream publik saja. URL privat/umur terbatas tidak didukung.
- Buffer hanya ~50 detik; klip dibuat saat spike, bukan setelah live selesai.
- Endpoint chat memakai fitur `live_chat` yt-dlp. Kalau YouTube mengubah
  protokol, chat rate akan 0 dan dashboard memberi peringatan.

## Dev

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn app:app --port 8765
```
