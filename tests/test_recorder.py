import os
import time

import core.recorder as recorder
from core.recorder import Recorder


def test_parse_segment_list(tmp_path):
    (tmp_path / "list.csv").write_text(
        "seg_000000.ts,0.000000,2.004000\nseg_000001.ts,2.004000,4.008000\n")
    r = Recorder()
    r.outdir = tmp_path
    assert r.segments() == [("seg_000000.ts", 0.0, 2.004), ("seg_000001.ts", 2.004, 4.008)]


def test_parse_segment_list_ignores_bad_lines(tmp_path):
    (tmp_path / "list.csv").write_text("seg_000000.ts,0.000000,2.000000\n\nbroken\n")
    r = Recorder()
    r.outdir = tmp_path
    assert r.segments() == [("seg_000000.ts", 0.0, 2.0)]


def test_prune_deletes_only_old_files(tmp_path):
    for i, age in enumerate([300, 100, 5]):
        p = tmp_path / f"seg_{i:06d}.ts"
        p.write_bytes(b"x")
        os.utime(p, (time.time() - age, time.time() - age))
    r = Recorder()
    r.outdir = tmp_path
    r.prune(keep_seconds=60)
    assert sorted(p.name for p in tmp_path.glob("*.ts")) == ["seg_000002.ts"]


def test_stream_time_relative_to_start():
    r = Recorder()
    r.started_wall = 1000.0
    assert r.stream_time(1042.5) == 42.5


def test_start_keeps_input_timestamps(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "_stream_urls", lambda url: ["video-url", "audio-url"])
    calls = []

    class FakeProc:
        pass

    def fake_popen(cmd, **kwargs):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(recorder.subprocess, "Popen", fake_popen)
    r = Recorder()
    try:
        r.start("https://example.com/live", tmp_path)
    finally:
        r.log.close()
    cmd = calls[0]
    inputs = [i for i, arg in enumerate(cmd) if arg == "-i"]
    assert len(inputs) == 2
    assert all(cmd[i - 1] == "-copyts" for i in inputs)
