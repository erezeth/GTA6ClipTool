from core.detector import SpikeDetector, find_spikes


def test_spike_triggers_above_threshold_and_respects_cooldown():
    d = SpikeDetector(min_rate=5.0, cooldown=60.0)
    for i in range(100):
        for _ in range(5):
            d.add(100.0 + i)
    for i in range(10):
        for _ in range(30):
            d.add(200.0 + i)
    assert d.check(210.0) is not None
    assert d.check(211.0) is None


def test_no_spike_on_flat_chat():
    d = SpikeDetector(min_rate=8.0)
    for i in range(100):
        for _ in range(3):
            d.add(100.0 + i)
    assert d.check(200.0) is None


def test_short_history_does_not_fake_baseline():
    d = SpikeDetector(min_rate=8.0)
    for _ in range(10):
        d.add(100.0)
    assert d.snapshot(100.0)["baseline"] == 0.0


def test_baseline_adapts_to_naturally_fast_chat():
    d = SpikeDetector(min_rate=8.0, k=3.0)
    for i in range(200):
        for _ in range(20):
            d.add(100.0 + i)
    assert d.check(300.0) is None
    assert d.snapshot(300.0)["threshold"] == 60.0


def test_find_spikes_from_video_offsets():
    offsets = []
    for i in range(100):
        offsets += [float(100 + i)] * 3
    for i in range(10):
        offsets += [float(200 + i)] * 30
    hits = find_spikes(offsets, min_rate=5.0, cooldown=60.0)
    assert len(hits) == 1
    assert 200.0 <= hits[0][0] <= 210.0
    assert hits[0][1] > 5.0
