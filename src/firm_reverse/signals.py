from bisect import bisect_right
from dataclasses import dataclass
from functools import cached_property

Edge = tuple[float, int]


@dataclass(frozen=True)
class Channel:
    name: str
    edges: list[Edge]

    @property
    def idle_level(self) -> int:
        return self.edges[0][1] if self.edges else 1

    def pulses(self) -> list[tuple[int, float, float]]:
        """(level, start_s, duration_s) for every completed level segment."""
        return [
            (level, t, self.edges[i + 1][0] - t)
            for i, (t, level) in enumerate(self.edges[:-1])
        ]

    @cached_property
    def _times(self) -> list[float]:
        return [t for t, _ in self.edges]

    def level_at(self, t: float) -> int:
        index = bisect_right(self._times, t) - 1
        return self.edges[index][1] if index >= 0 else self.idle_level


@dataclass(frozen=True)
class Frame:
    t: float
    protocol: str
    data: dict


def from_samples(name: str, samples: list[int], sample_rate: float) -> Channel:
    if not samples:
        raise ValueError(f"channel {name} has no samples")
    edges: list[Edge] = [(0.0, samples[0])]
    for i in range(1, len(samples)):
        if samples[i] != samples[i - 1]:
            edges.append((i / sample_rate, samples[i]))
    edges.append((len(samples) / sample_rate, samples[-1]))
    return Channel(name, edges)
