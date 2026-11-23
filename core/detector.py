"""Deteksi lonjakan laju live chat. Tanpa I/O supaya gampang dites."""
from __future__ import annotations

import statistics
from collections import Counter, deque


class SpikeDetector:
    def __init__(self, window: float = 10.0, baseline_window: float = 300.0,
                 k: float = 3.0, min_rate: float = 8.0, cooldown: float = 60.0):
        self.window = window
        self.baseline_window = baseline_window
        self.k = k
        self.min_rate = min_rate
        self.cooldown = cooldown
        self._ticks: deque[tuple[float, int]] = deque()
        self.last_spike: float | None = None

    def add(self, now: float, count: int = 1) -> None:
        self._ticks.append((now, count))
        cutoff = now - self.baseline_window
        while self._ticks and self._ticks[0][0] < cutoff:
            self._ticks.popleft()

    def rate(self, now: float) -> float:
        lo = now - self.window
        total = sum(c for t, c in self._ticks if t >= lo)
        return total / self.window

    def baseline(self, now: float) -> float:
        lo = now - self.baseline_window
        hi = now - self.window
        buckets = max(int((hi - lo) // self.window), 0)
        if buckets < 6:
            return 0.0
        counts = [0] * buckets
        for t, c in self._ticks:
            if lo <= t < hi:
                counts[min(int((t - lo) // self.window), buckets - 1)] += c
        return statistics.median(c / self.window for c in counts)

    def threshold(self, baseline: float) -> float:
        return max(self.k * baseline, self.min_rate)

    def check(self, now: float) -> tuple[float, float] | None:
        rate = self.rate(now)
        base = self.baseline(now)
        if rate < self.threshold(base):
            return None
        if self.last_spike is not None and now - self.last_spike < self.cooldown:
            return None
        self.last_spike = now
        return rate, base

    def snapshot(self, now: float) -> dict:
        base = self.baseline(now)
        return {
            "rate": round(self.rate(now), 2),
            "baseline": round(base, 2),
            "threshold": round(self.threshold(base), 2),
            "last_spike": self.last_spike,
        }


def find_spikes(offsets: list[float], **cfg) -> list[tuple[float, float, float]]:
    """Deteksi spike dari offset video chat replay: [(detik, rate, baseline)]."""
    detector = SpikeDetector(**cfg)
    counts = Counter(int(offset) for offset in offsets)
    hits = []
    for second in sorted(counts):
        detector.add(second, counts[second])
        hit = detector.check(second)
        if hit:
            hits.append((float(second), *hit))
    return hits
