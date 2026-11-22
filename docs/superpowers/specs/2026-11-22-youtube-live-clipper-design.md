# YouTube Live Clipper — Design

Date: 2026-11-22
Status: approved by user (chat, 2026-11-22)

## Intent

Tool lokal untuk memantau live YouTube orang lain (mis. ishowspeed), mendeteksi
lonjakan live chat, lalu otomatis memotong klip 9:16 dengan facecam di atas dan
gameplay di bawah.

Alasan: momen terbaik sebuah live ditandai oleh chat yang meledak. Menonton
berjam-jam untuk menemukannya manual tidak masuk akal.

## Goals

- Tempel URL live di dashboard lokal, tekan Start.
- Rekam live secara kontinu ke ring buffer 2 detik per segmen.
- Hitung laju pesan chat per detik, bandingkan dengan baseline 5 menit.
- Saat lonjakan: potong dari 20 detik sebelum sampai 10 detik sesudah.
- Render 1080x1920: facecam (crop rect per channel) di atas, gameplay di bawah.
- Dashboard: status, grafik chat rate, daftar klip, preview kalibrasi rect.

## Non-goals

- Auto-upload ke Shorts/TikTok.
- Lebih dari satu stream aktif sekaligus.
- Auto-deteksi posisi facecam.
- Mode VOD (clip setelah live selesai).
- Login YouTube / cookies. Stream publik saja.

## Constraints

- Windows, Python 3.12, ffmpeg di PATH, NVENC di RTX 4060.
- Satu proses Python. Dashboard HTML/JS vanilla + SSE, tanpa build step.
- Dependency: `yt-dlp`, `fastapi`, `uvicorn`. Tidak ada lib chat pihak ketiga.
- Ring buffer harus dibuang otomatis; disk tidak boleh tumbuh tanpa batas.

## Approaches considered

1. **Rekam kontinu + ring buffer, potong saat spike.** Satu-satunya cara
   mendapat 20 detik sebelum spike. Live tidak bisa di-rewind.
2. **Download VOD setelah live selesai, potong offline.** Sederhana, tapi tidak
   real-time dan tidak memenuhi "otomatis saat live".
3. **Tarik stream lalu seek mundur ke DVR.** Tidak reliabel; window DVR tidak
   dijamin ada dan ffmpeg tidak bisa seek di HLS live.

Dipilih: 1.

## Architecture

```
paste URL
  -> yt-dlp resolve (id, title, channel, live?)
  -> ffmpeg -c copy -> buffer/seg_%06d.ts (2s, list.csv)
  -> yt-dlp --write-subs --sub-langs live_chat -> buffer/chat.live_chat.json
       -> tail file -> hitung addChatItemAction -> SpikeDetector
  -> spike: t0 = now-20, t1 = now+10
       -> tunggu t1+2 -> concat segmen -> filter_complex 9:16 -> clips/*.mp4
  -> dashboard baca state via SSE tiap 1 detik
```

### Spike detection

- Rate = jumlah pesan 10 detik terakhir / 10.
- Baseline = median rate per bucket 10 detik selama 5 menit, bucket 10 detik
  terakhir dikecualikan.
- Trigger bila `rate >= max(3 x baseline, 8 msg/s)` dan 60 detik sejak klip
  terakhir. Cooldown mencegah satu hype panjang jadi lima klip.

### Layout 1080x1920

```
y=0     facecam: crop rect channel -> scale fill 1080x1000
y=1000  gameplay: crop tengah 16:9 ke 1.543:1 -> 1080x700
y=1700  220px aman untuk UI Shorts
```

Rect facecam disimpan relatif (0..1) per nama channel di `channels.json`.
Default: `x=0.68, y=0.03, w=0.29, h=0.40` (kanan atas).

### File layout

| File | Tanggung jawab |
|------|----------------|
| `app.py` | FastAPI routes, SSE, wiring |
| `core/detector.py` | SpikeDetector murni, tanpa I/O |
| `core/chat.py` | yt-dlp chat downloader + tail file |
| `core/recorder.py` | resolve URL, ffmpeg segmenter, prune, pilih segmen |
| `core/clipper.py` | filter graph + render NVENC |
| `core/manager.py` | state machine, thread, event |
| `static/*` | dashboard |
| `config.json`, `channels.json` | setelan |

## Decisions taken by the builder

- Chat lewat fitur `live_chat` subtitle yt-dlp, bukan reverse-engineer InnerTube.
  yt-dlp sudah memelihara endpoint itu; menulis poller sendiri menambah ~150
  baris rapuh tanpa manfaat.
- Waktu pesan memakai jam dinding saat baris chat terbaca, bukan
  `videoOffsetTimeMsec`. Offset video tidak punya anchor ke awal rekaman.
- Rect facecam manual per channel. Auto-deteksi tidak reliabel; salah crop
  merusak klip.
- NVENC dengan fallback libx264 bila tidak tersedia.
- Segmen lama dihapus berdasarkan mtime, bukan edit `list.csv` yang sedang
  ditulis ffmpeg.

## Risks

- Endpoint chat yt-dlp bisa berubah saat YouTube mengubah protokol. Gejala:
  chat rate tetap 0, dashboard memberi peringatan.
- Rect facecam salah = klip jelek. Mitigasi: preview di dashboard.
- Stream yang di-restart YouTube di tengah rekaman akan memutus ffmpeg.
  Mitigasi fase 2: auto-resolve ulang. Untuk sekarang: status error jelas.
