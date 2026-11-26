import time

from core.manager import DEFAULT_GAMEPLAY, DEFAULT_WEBCAM, Manager


def test_state_idle_before_start(tmp_path):
    m = Manager(tmp_path)
    assert m.state()["status"] == "idle"
    assert m.state()["clips"] == []
    assert m.state()["rects"]["gameplay"] == DEFAULT_GAMEPLAY


def test_rects_default_and_persist(tmp_path):
    m = Manager(tmp_path)
    assert m.rects_for("ishowspeed")["webcam"]["w"] == DEFAULT_WEBCAM["w"]
    m.save_rects("ishowspeed", {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2},
                 {"x": 0.2, "y": 0.2, "w": 0.5, "h": 0.5})
    saved = Manager(tmp_path).rects_for("ishowspeed")
    assert saved["webcam"]["x"] == 0.1
    assert saved["gameplay"]["x"] == 0.2


def test_last_saved_channel_is_reordered_to_end(tmp_path):
    m = Manager(tmp_path)
    m.save_rects("a", {}, {})
    m.save_rects("b", {}, {})
    m.save_rects("a", {}, {})
    data = m._load_json(m.channels_path, {})
    assert list(data) == ["b", "a"]


def test_old_flat_rect_is_read_as_webcam(tmp_path):
    (tmp_path / "channels.json").write_text('{"x": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}}')
    rects = Manager(tmp_path).rects_for("x")
    assert rects["webcam"]["x"] == 0.1
    assert rects["gameplay"] == DEFAULT_GAMEPLAY


def test_rects_are_clamped(tmp_path):
    m = Manager(tmp_path)
    m.save_rects("x", {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5},
                 {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5})
    rects = m.rects_for("x")
    for key in ("webcam", "gameplay"):
        assert rects[key]["x"] + rects[key]["w"] <= 1.0
        assert rects[key]["y"] + rects[key]["h"] <= 1.0


def test_clip_length_capped_at_max(tmp_path):
    m = Manager(tmp_path)
    m.config["pre"] = 20
    m.config["post"] = 99
    m.config["max_clip"] = 50
    assert min(m.config["post"], m.config["max_clip"] - m.config["pre"]) == 30


def test_spike_schedules_clip_without_recorder(tmp_path):
    m = Manager(tmp_path)
    m.status = "live"
    m.started_wall = time.time() - 100
    for i in range(100):
        for _ in range(5):
            m._on_chat(100.0 + i)
    for i in range(10):
        for _ in range(30):
            m._on_chat(200.0 + i)
    assert m.clips_scheduled == 1


def test_chat_problem_flags_dead_stalled_and_unstarted(tmp_path):
    class FakeChat:
        def __init__(self, alive=True, started=True, last=None):
            self._alive = alive
            self.started = started
            self.last_message_at = last

        def is_alive(self):
            return self._alive

    now = time.time()
    m = Manager(tmp_path)
    m.status = "live"
    m.started_wall = now - 100
    m._chat_since = now - 100
    m.chat = FakeChat(alive=False)
    assert m._chat_problem(now) == "chat mati"
    m.chat = FakeChat(started=True, last=now - 31)
    assert m._chat_problem(now) == "chat macet >30 detik"
    m.chat = FakeChat(started=True, last=now)
    assert m._chat_problem(now) is None
    m.chat = FakeChat(started=False)
    assert m._chat_problem(now) == "chat belum terbaca setelah 30 detik"


def test_save_config_clamps_and_persists(tmp_path):
    m = Manager(tmp_path)
    m.save_config({"subtitle_y": 2, "subtitle_size": 5000})
    assert m.config["subtitle_y"] == 1.0
    assert m.config["subtitle_size"] == 200
    assert m.state()["subtitle"] == {"enabled": True, "y": 1.0, "size": 200}
    assert Manager(tmp_path).config["subtitle_y"] == 1.0
    assert "subtitle_x" not in m.config


def test_subtitles_toggle_persists(tmp_path):
    m = Manager(tmp_path)
    m.save_config({"subtitles": False})
    assert m.state()["subtitle"]["enabled"] is False
    assert Manager(tmp_path).config["subtitles"] is False
    m.save_config({"subtitles": True})
    assert m.state()["subtitle"]["enabled"] is True


def test_vod_pipeline_renders_each_spike(tmp_path, monkeypatch):
    m = Manager(tmp_path)
    m.url = "https://example.com/replay"
    chat = tmp_path / "chat.live_chat.json"
    chat.write_bytes(b"")
    monkeypatch.setattr("core.manager.download_chat", lambda url, outdir: chat)
    monkeypatch.setattr("core.manager.read_offsets", lambda path: [120.0])
    monkeypatch.setattr("core.manager.find_spikes",
                        lambda offsets, **cfg: [(120.0, 10.0, 2.0)])

    def fake_section(url, start, end, out):
        out.write_bytes(b"x")
        return out

    monkeypatch.setattr("core.manager.download_section", fake_section)
    monkeypatch.setattr("core.manager.render", lambda *args, **kwargs: None)

    m._run_vod({"title": "Replay", "channel": "ch"}, m._job)

    assert m.status == "done"
    assert m.clips_scheduled == 1
    assert m.clips[0]["file"] == "ch_120.mp4"
    assert m.clips[0]["at"] == "video 00:02:00"
    assert not list(m.buffer_dir.glob("sec_*.mp4"))
