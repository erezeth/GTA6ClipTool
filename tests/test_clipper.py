from pathlib import Path

import pytest

import core.clipper as clipper
from core.clipper import GAME_H, build_filter, pick_segments

WEBCAM = {"x": 0.68, "y": 0.03, "w": 0.29, "h": 0.40}
GAMEPLAY = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}


def test_build_filter_geometry_and_order():
    f = build_filter(1920, 1080, WEBCAM, GAMEPLAY)
    assert "crop=557:432:1306:32" in f
    assert "crop=1920:1080:0:0" in f
    assert f"scale=1080:{GAME_H}:force_original_aspect_ratio=increase" in f
    assert "vstack=inputs=2" in f
    assert "pad=1080:1920:0:0:black" in f
    assert f.index("[face]") < f.index("[game]")


def test_gameplay_rect_is_used():
    f = build_filter(1920, 1080, WEBCAM, {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.6})
    assert "crop=960:648:192:216" in f


def test_rect_clamped_inside_frame():
    f = build_filter(1920, 1080, {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5},
                     {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5})
    assert "crop=192:108:1728:972" in f


def test_rect_never_smaller_than_16px():
    f = build_filter(1920, 1080, {"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0}, GAMEPLAY)
    assert "crop=16:16:960:540" in f


def test_build_filter_burns_subtitles_before_output():
    f = build_filter(1920, 1080, WEBCAM, GAMEPLAY, ",ass=sub.ass")
    assert "pad=1080:1920:0:0:black,ass=sub.ass[v]" in f


def test_render_caps_duration(tmp_path, monkeypatch):
    (tmp_path / "seg_000000.ts").write_bytes(b"")
    calls = []

    class Result:
        returncode = 0
        stdout = "1920,1080"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    monkeypatch.setattr(clipper, "video_encoders", lambda: [["-c:v", "libx264"]])
    clipper.render(["seg_000000.ts"], tmp_path / "out.mp4", {}, tmp_path,
                   max_duration=50)
    cmd = calls[-1]
    assert cmd[cmd.index("-t") + 1] == "50"


def test_video_encoders_skips_unusable_hardware(monkeypatch):
    monkeypatch.setattr(clipper, "encoder_works",
                        lambda name: name == "libopenh264")
    assert clipper.video_encoders() == [["-c:v", "libopenh264", "-b:v", "8M"]]


def test_video_encoders_keeps_preference_order(monkeypatch):
    monkeypatch.setattr(clipper, "encoder_works",
                        lambda name: name in ("h264_nvenc", "libx264"))
    names = [args[1] for args in clipper.video_encoders()]
    assert names == ["h264_nvenc", "libx264"]


def test_render_falls_back_to_next_encoder(tmp_path, monkeypatch):
    (tmp_path / "seg_000000.ts").write_bytes(b"")
    renders = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            stream = cmd[cmd.index("-select_streams") + 1]
            return Result(stdout="" if stream == "a" else "1920,1080")
        renders.append(cmd)
        if "h264_nvenc" in cmd:
            return Result(1, stderr="[h264_nvenc] Cannot load libcuda.so.1")
        return Result()

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    monkeypatch.setattr(clipper, "video_encoders", lambda: [
        ["-c:v", "h264_nvenc"],
        ["-c:v", "libopenh264", "-b:v", "8M"],
    ])
    clipper.render(["seg_000000.ts"], tmp_path / "out.mp4", {}, tmp_path,
                   log=lambda msg: None)
    assert len(renders) == 2
    assert "h264_nvenc" in renders[0]
    assert "libopenh264" in renders[1]


def test_render_raises_when_all_encoders_fail(tmp_path, monkeypatch):
    (tmp_path / "seg_000000.ts").write_bytes(b"")

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        if cmd[0] == "ffprobe":
            stream = cmd[cmd.index("-select_streams") + 1]
            return Result(stdout="" if stream == "a" else "1920,1080")
        return Result(1, stderr="[h264_nvenc] Cannot load libcuda.so.1")

    monkeypatch.setattr(clipper.subprocess, "run", fake_run)
    monkeypatch.setattr(clipper, "video_encoders", lambda: [["-c:v", "h264_nvenc"]])
    with pytest.raises(RuntimeError, match="libcuda"):
        clipper.render(["seg_000000.ts"], tmp_path / "out.mp4", {}, tmp_path,
                       log=lambda msg: None)


def test_pick_segments_covers_window():
    entries = [(f"seg_{i:06d}.ts", i * 2.0, i * 2.0 + 2.0) for i in range(100)]
    assert pick_segments(entries, 20.0, 40.0) == [f"seg_{i:06d}.ts" for i in range(10, 20)]


def test_pick_segments_short_buffer():
    entries = [("seg_000000.ts", 0.0, 2.0)]
    assert pick_segments(entries, 0.0, 5.0) == ["seg_000000.ts"]


def test_audio_chain_delays_late_audio(monkeypatch):
    monkeypatch.setattr(clipper, "_first_pts",
                        lambda path, stream: 10.0 if stream == "v:0" else 10.5)
    chain = clipper._audio_chain(Path("seg.ts"))
    assert chain.startswith("adelay=500|500")


def test_audio_chain_trims_early_audio(monkeypatch):
    monkeypatch.setattr(clipper, "_first_pts",
                        lambda path, stream: 10.5 if stream == "v:0" else 10.0)
    chain = clipper._audio_chain(Path("seg.ts"))
    assert chain.startswith("atrim=start=0.500")
