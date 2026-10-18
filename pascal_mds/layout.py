"""Physical layout of a PASCAL-MDS symbol (see SPEC.md).

An n x n symbol (n odd, 11..47) has a one-module frame:

* left column and bottom row solid dark (the "L" finder),
* top row and right column alternate dark/light (timing tracks); with n odd
  all four corner modules are dark,

and an (n-2) x (n-2) data region filled by a two-column snake, eight modules
per codeword symbol.  Since (n-2) is odd, (n-2)^2 = 8N + 1: N symbols plus one
remainder module.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import comb, ceil

SIZES = tuple(range(11, 48, 2))
LEVELS = "LMQH"
# Fraction of the N codeword symbols that must be correctable as unknown
# errors (the same nominal recovery targets as QR's L/M/Q/H).
LEVEL_FRACTION = {"L": 0.07, "M": 0.15, "Q": 0.25, "H": 0.30}
# A decoding attempt that keeps M = N - e symbols (e erasures) and corrects t
# errors accepts a uniformly random word with probability at most
# V(M, t) / 257^(r - e), V(M, t) = sum_{i<=t} C(M, i) 256^i.  Levels add
# guard parity until the error-only attempt meets this target, and the
# decoder rejects any attempt (with erasures) that does not.  The comparison
# is done in exact integer arithmetic.
MISCORRECTION_TARGET_EXP = 10  # target = 10^-10


def is_frame(r: int, c: int, n: int) -> bool:
    return r == 0 or c == 0 or r == n - 1 or c == n - 1


def frame_value(r: int, c: int, n: int) -> int:
    if c == 0 or r == n - 1:
        return 1
    if r == 0:
        return 1 if c % 2 == 0 else 0
    if c == n - 1:
        return 1 if r % 2 == 0 else 0
    raise ValueError("not a frame module")


@lru_cache(maxsize=None)
def placement(n: int) -> tuple[tuple[int, int], ...]:
    """Symbol-coordinate (row, col) of data bit k, for k = 0 .. (n-2)^2 - 1."""
    m = n - 2
    order: list[tuple[int, int]] = []
    right = m - 1
    upward = True
    while right >= 0:
        cols = (right, right - 1) if right >= 1 else (right,)
        rows = range(m - 1, -1, -1) if upward else range(m)
        for i in rows:
            for j in cols:
                order.append((i + 1, j + 1))
        right -= 2
        upward = not upward
    return tuple(order)


@dataclass(frozen=True)
class Version:
    n: int          # symbol side in modules
    level: str      # L, M, Q or H
    N: int          # codeword symbols (bytes on the page)
    K: int          # systematic symbols (header + payload + pad)
    r: int          # parity symbols, N - K
    t: int          # guaranteed correctable unknown symbol errors
    guard: int      # parity reserved against miscorrection; 2e + s <= r - guard

    @property
    def payload_capacity(self) -> int:
        """Largest payload (in bytes after mode packing) that fits."""
        room = self.K - 1  # last systematic symbol is the pad
        return max(0, room - (1 if room - 1 <= 31 else 2))


def miscorrection_bound(kept: int, errors: int, redundancy: int) -> float:
    """Probability that a random word lies within ``errors`` of a codeword
    of a length-``kept`` MDS code with ``redundancy`` parity symbols."""
    if redundancy <= 0:
        return 1.0
    return _volume(kept, errors) / 257 ** redundancy


def _volume(kept: int, errors: int) -> int:
    return sum(comb(kept, i) * 256 ** i for i in range(errors + 1))


def _safe(kept: int, errors: int, redundancy: int) -> bool:
    """Exactly: V(kept, errors) / 257^redundancy <= 10^-10."""
    return redundancy > 0 and (
        _volume(kept, errors) * 10 ** MISCORRECTION_TARGET_EXP <= 257 ** redundancy)


def acceptable(v: "Version", errors: int, erasures: int) -> bool:
    return (2 * errors + erasures <= v.r - v.guard
            and _safe(v.N - erasures, errors, v.r - erasures))


def max_erasures(v: "Version") -> int:
    """Largest number of erasures (with no errors) the decoder will accept."""
    e = v.r - v.guard
    while e > 0 and not acceptable(v, 0, e):
        e -= 1
    return e


@lru_cache(maxsize=None)
def version(n: int, level: str) -> Version:
    if n not in SIZES:
        raise ValueError(f"symbol size must be one of {SIZES}")
    if level not in LEVELS:
        raise ValueError("level must be one of L, M, Q, H")
    m = n - 2
    N = (m * m - 1) // 8
    t = max(1, ceil(LEVEL_FRACTION[level] * N))
    guard = 0
    while not _safe(N, t, 2 * t + guard):
        guard += 1
    r = 2 * t + guard
    return Version(n=n, level=level, N=N, K=N - r, r=r, t=t, guard=guard)


def scrambler(level: str, count: int) -> list[int]:
    """Level-specific whitening bytes (xorshift32).  Reading a symbol with the
    wrong level's scrambler yields a word far from the code, which is how the
    level is recognised without format modules."""
    state = (0x2545F491 * (LEVELS.index(level) + 1)) & 0xFFFFFFFF
    out = []
    for _ in range(count):
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        out.append(state >> 24)
    return out
