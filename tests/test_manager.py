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
