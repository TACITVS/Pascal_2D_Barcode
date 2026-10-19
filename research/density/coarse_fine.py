"""PM257-SHELL-2026-10-19: optimal coarse-intensity gap with fine payload.

PB-15: two coarse classes, 2**fine_bits distinct binary n-module patterns
per class. With an ideal block-average observation, the largest separation
of the ordered classes is (n-2t)/n, where t is the smallest binomial-tail
quantile containing 2**fine_bits patterns. This is a scoped optimum, not
maximum capacity of an arbitrary optical channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb


@dataclass(frozen=True)
class ShellCode:
    modules: int
    fine_bits: int

    def __post_init__(self) -> None:
        if self.modules < 1 or not 0 <= self.fine_bits < self.modules:
            raise ValueError("invalid shell dimensions")
        if 2 * self.threshold >= self.modules:
            raise ValueError("these dimensions leave no positive coarse gap")

    @property
    def threshold(self) -> int:
        count = 0
        for t in range(self.modules + 1):
            count += comb(self.modules, t)
            if count >= 1 << self.fine_bits:
                return t
        raise AssertionError("unreachable")

    @property
    def payload_bits(self) -> int:
        return self.fine_bits + 1

    @property
    def count_gap(self) -> int:
        return self.modules - 2 * self.threshold

    def encode(self, value: int) -> tuple[int, ...]:
        if not 0 <= value < 1 << self.payload_bits:
            raise ValueError("payload outside shell range")
        coarse = value >> self.fine_bits
        rank = value % (1 << self.fine_bits)
        weight = 0
        while rank >= comb(self.modules, weight):
            rank -= comb(self.modules, weight)
            weight += 1
        result = []
        for pos in range(self.modules):
            remaining = self.modules - pos - 1
            zero_count = comb(remaining, weight) if weight <= remaining else 0
            if rank < zero_count:
                result.append(coarse)
            else:
                rank -= zero_count
                weight -= 1
                result.append(1 - coarse)
        return tuple(result)

    def coarse(self, dark_count: float) -> int:
        return int(2 * dark_count > self.modules)

    def decode(self, pattern: tuple[int, ...]) -> int | None:
        if len(pattern) != self.modules or any(x not in (0, 1) for x in pattern):
            return None
        weight = sum(pattern)
        coarse = self.coarse(weight)
        low = tuple(x ^ coarse for x in pattern)
        weight = sum(low)
        if weight > self.threshold:
            return None
        rank = sum(comb(self.modules, j) for j in range(weight))
        remaining_weight = weight
        for pos, bit in enumerate(low):
            if bit:
                remaining = self.modules - pos - 1
                if remaining_weight <= remaining:
                    rank += comb(remaining, remaining_weight)
                remaining_weight -= 1
        if rank >= 1 << self.fine_bits:
            return None
        return (coarse << self.fine_bits) | rank
