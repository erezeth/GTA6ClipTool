import time

from core.manager import DEFAULT_RECT, Manager


def test_state_idle_before_start(tmp_path):
    m = Manager(tmp_path)
    assert m.state()["status"] == "idle"
    assert m.state()["clips"] == []


def test_rect_defaults_and_persists(tmp_path):
    m = Manager(tmp_path)
    assert m.rect_for("ishowspeed")["w"] == DEFAULT_RECT["w"]
    m.save_rect("ishowspeed", {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2})
    assert Manager(tmp_path).rect_for("ishowspeed")["x"] == 0.1


def test_rect_is_clamped(tmp_path):
    m = Manager(tmp_path)
    m.save_rect("x", {"x": 0.9, "y": 0.9, "w": 0.5, "h": 0.5})
    r = m.rect_for("x")
    assert r["x"] + r["w"] <= 1.0 and r["y"] + r["h"] <= 1.0


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
