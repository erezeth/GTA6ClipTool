"""Dashboard lokal untuk YouTube Live Clipper."""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse

from core.manager import Manager

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
manager = Manager(ROOT)

app = FastAPI(title="Live Clipper")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/state")
def state():
    return manager.state()


@app.get("/api/events")
async def events():
    async def gen():
        while True:
            yield f"data: {json.dumps(manager.state())}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/start")
def start(body: dict):
    return manager.start(str(body.get("url", "")))


@app.post("/api/stop")
def stop():
    return manager.stop()


@app.post("/api/rect")
def save_rect(body: dict):
    manager.save_rect(str(body.get("channel", "")), body.get("rect", {}))
    return {"ok": True}


@app.get("/api/preview")
def preview():
    segment = manager.recorder.latest_segment()
    if not segment:
        raise HTTPException(404, "belum ada frame")
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(segment),
         "-frames:v", "1", "-vf", "scale=640:-2", "-f", "image2pipe",
         "-vcodec", "mjpeg", "-"],
        capture_output=True, timeout=30)
    if not res.stdout:
        raise HTTPException(500, "gagal ambil frame")
    return Response(res.stdout, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.get("/clips/{name}")
def clip(name: str):
    path = (manager.clips_dir / name).resolve()
    if path.parent != manager.clips_dir.resolve() or not path.exists():
        raise HTTPException(404, "klip tidak ada")
    return FileResponse(path, media_type="video/mp4")
