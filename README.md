# Live Clipper

**English** | [Bahasa Indonesia](README.id.md)

Monitor YouTube live streams, detect live chat spikes, and automatically cut
vertical 9:16 clips (facecam on top, gameplay below).

## Usage

1. Double-click `run.bat`. The browser opens at `http://127.0.0.1:8765`.
2. Paste a YouTube live URL: either an ongoing live stream or a finished live
   replay.
3. Start. For live streams, the tool records to `buffer/`, monitors chat, and
   saves clips in `clips/`. For replays, the tool downloads the chat replay
   first, detects spikes, then downloads only the video segments around those
   spikes.
4. On the first clip, check the result. If the facecam or gameplay is cropped
   incorrectly, adjust the rect in the dashboard: click **Grab frame**, then set
   x/y/w/h (percent) until the green box fits the webcam and the blue box fits
   the gameplay, then **Save crop**. Rects are stored per channel.
5. Set the subtitle Y position and size in the **Subtitle** fieldset (y % of the
   output height, font size in px), then **Save subtitle**. The yellow dashed
   line in the preview marks the subtitle position. The **Subtitle: ON/OFF**
   button disables or enables subtitles for the next clips. **Save crop** also
   saves any unsaved subtitle changes.

## Settings

`config.json`:

| key | meaning |
|-----|---------|
| `pre` | seconds before a spike (default 20) |
| `post` | seconds after a spike (default 30) |
| `max_clip` | maximum clip length, seconds (default 50) |
| `window` | rate calculation window, seconds |
| `baseline_window` | baseline length, seconds |
| `k` | spike = k x baseline |
| `min_rate` | minimum threshold, messages/second |
| `cooldown` | minimum time between clips, seconds |
| `subtitles` | auto subtitles via faster-whisper (default `true`) |
| `subtitle_model` | whisper model size (default `small`) |
| `subtitle_language` | language code, `null` = auto-detect |
| `subtitle_y` | vertical subtitle position, 0..1 from the top (default `0.51` = center) |
| `subtitle_size` | subtitle font size in px (default `76`) |

`channels.json` stores the webcam and gameplay rects per channel (0..1, relative
to the frame).

## Limitations

- One active stream at a time.
- Requires ffmpeg in PATH. NVENC is used when available, otherwise it falls back
  to libx264.
- Public streams only. Private or expiring URLs are not supported.
- Live: the buffer keeps only `pre + post + 60` seconds; clips are created when a
  spike occurs, not after the live stream ends. Clip length is limited by
  `max_clip` (50 seconds).
- Replay: chat replay must be available (the streamer can disable it). Video is
  downloaded only for spike ranges, so the full replay does not need to be
  downloaded.
- The first clip with subtitles downloads the faster-whisper model, so rendering
  can take a while. Later clips use the cached model.
- The chat endpoint uses yt-dlp's `live_chat` feature. If YouTube changes the
  protocol, the chat rate will be 0 and the dashboard will show a warning.

## Dev

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m uvicorn app:app --port 8765
.venv\Scripts\python tests\test_render.py
```

`tests/test_render.py` renders the last ~20 seconds of segments from `buffer/` to
`clips/test_manual.mp4`, using the last saved channel rects and the subtitle
settings from `config.json` (ON/OFF, `subtitle_y`, `subtitle_size`). Run it while
the dashboard is LIVE so the buffer is filled.
