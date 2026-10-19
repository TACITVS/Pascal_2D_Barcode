"""PASCAL-MDS v2 ("dense") prototype: encoder and photo reader.

Symbol (S x S modules, S = 2 n', n' odd 11..47, so S = 22, 26, ..., 94):

* frame: the v1 frame on the n' x n' grid of 2 x 2-module cells (solid L on
  the left and bottom, alternating cells on top and right), so v1's detector
  finds it; quiet zone 4 modules;
* data: the (S-4) x (S-4) interior, split into four interleaved cosets
  (r % 2, c % 2) decoded in the order of STAGES; coset k carries one IRA-LDPC
  codeword at the level's stage rate, interleaved and scrambled;
* information: the LDPC information bits form a byte stream holding Pascal
  GF(257) Reed-Solomon blocks (header + payload + pad + parity).

Reader: v1 detection on the cell grid, per-photo light/dark normalisation,
blur and noise estimated from the frame and quiet zone, then the model-based
soft detector of research/v2_detector.py stage by stage with belief
propagation, then the outer code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))

from ldpc import Decoder, IRACode, encode as ldpc_encode  # noqa: E402
from pascal_mds import gf257  # noqa: E402
from pascal_mds.codec import _choose_pad, _header, _parse_header, best_payload, unpack_text  # noqa: E402
from pascal_mds.layout import frame_value as v1_frame_value, is_frame as v1_is_frame  # noqa: E402

SIZES = tuple(range(22, 95, 4))
QUIET = 4
STAGES = [(0, 0), (1, 1), (0, 1), (1, 0)]
# Stage code rates per level.  Every stage gets the same rate.  The first
# design (A: 0.43, 0.41, 0.82, 0.89) relied on the simulated channel, where
# decoded neighbours make the late stages much cleaner; on real phone photos
# they were no cleaner than stage 0.  Replaying the measured LLRs of 75
# real symbol sightings through codes of each rate, flat 0.6 read 40 and
# the old level A 22, for 3% more width (fieldtest/RESULTS.md, round 3).
LEVELS = {
    "A": {"rates": (0.6, 0.6, 0.6, 0.6)},
    "B": {"rates": (0.5, 0.5, 0.5, 0.5)},
    "C": {"rates": (0.4, 0.4, 0.4, 0.4)},
}
RS_PARITY = 4      # parity bytes per outer block
RS_BLOCK = 250     # max bytes per outer block


# ------------------------------------------------------------ portable PRNG

class XorShift32:
    def __init__(self, seed: int):
        self.s = (seed & 0xFFFFFFFF) or 0x9E3779B9

    def next(self) -> int:
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s

    def below(self, n: int) -> int:
        return self.next() % n

    def shuffle(self, a: list) -> None:
        for i in range(len(a) - 1, 0, -1):
            j = self.below(i + 1)
            a[i], a[j] = a[j], a[i]


def _seed(*parts) -> int:
    """FNV-1a of the parts joined with '/', e.g. 'ira/30/B/0'."""
    h = 2166136261
    for p in "/".join(str(x) for x in parts).encode():
        h = ((h ^ p) * 16777619) & 0xFFFFFFFF
    return h


# ------------------------------------------------------------------- layout

def frame_modules(S: int) -> np.ndarray:
    """-1 for data modules, else the frame value (0/1)."""
    n = S // 2
    out = np.full((S, S), -1, dtype=np.int8)
    for R in range(n):
        for C in range(n):
            if v1_is_frame(R, C, n):
                out[2 * R:2 * R + 2, 2 * C:2 * C + 2] = v1_frame_value(R, C, n)
    return out


@lru_cache(maxsize=None)
def coset_positions(S: int, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Rows and columns of coset k's modules, in codeword order."""
    r0, c0 = STAGES[k]
    rows = np.arange(2 + r0, S - 2, 2)
    cols = np.arange(2 + c0, S - 2, 2)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    order = list(range(len(rr)))
    XorShift32(_seed("perm", S, k)).shuffle(order)
    order = np.array(order)
    return rr[order], cc[order]


def make_ira(k: int, m: int, seed: int) -> IRACode:
    """IRA code built with the portable PRNG (same rule as research/ldpc.py)."""
    dv = max(3, round(2 * m / max(k, 1)))
    cols = [i for i in range(k) for _ in range(dv)]
    rng = XorShift32(seed)
    for _ in range(50):
        rows = [j % m for j in range(k * dv)]
        rng.shuffle(rows)
        if len({r * k + c for r, c in zip(rows, cols)}) == len(rows):
            break
    pairs = sorted({(r, c) for r, c in zip(rows, cols)}, key=lambda t: (t[1], t[0]))
    return IRACode(k, m, np.array([p[0] for p in pairs]), np.array([p[1] for p in pairs]))


@dataclass(frozen=True)
class Version:
    S: int
    level: str
    n_coset: int
    k_stage: tuple[int, ...]
    blocks: tuple[int, ...]   # total bytes (message + parity) per outer block

    @property
    def info_bits(self) -> int:
        return sum(self.k_stage)

    @property
    def capacity(self) -> int:
        room = sum(b - RS_PARITY - 1 for b in self.blocks)  # minus pad per block
        return max(0, room - (1 if room - 1 <= 31 else 2))


@lru_cache(maxsize=None)
def version(S: int, level: str) -> Version:
    n_coset = ((S - 4) // 2) ** 2
    k_stage = tuple(int(LEVELS[level]["rates"][k] * n_coset) for k in range(4))
    total = sum(k_stage) // 8
    nb = max(1, -(-total // RS_BLOCK))
    blocks = tuple(total // nb + (1 if i < total % nb else 0) for i in range(nb))
    return Version(S, level, n_coset, k_stage, blocks)


@lru_cache(maxsize=None)
def codes(S: int, level: str) -> tuple[IRACode, ...]:
    v = version(S, level)
    return tuple(make_ira(v.k_stage[k], v.n_coset - v.k_stage[k], _seed("ira", S, level, k)) for k in range(4))


@lru_cache(maxsize=None)
def scramble(S: int, level: str, k: int, n: int) -> np.ndarray:
    rng = XorShift32(_seed("scr", S, level, k))
    return np.array([rng.next() >> 31 for _ in range(n)], dtype=np.uint8)


# ------------------------------------------------------------------ encoder

def _rs_block(message: list[int], parity: int) -> list[int]:
    p0 = gf257.pascal_extend(message, parity)
    unit = gf257.pascal_extend([0] * (len(message) - 1) + [1], parity)
    s, par = _choose_pad(p0, unit)
    return message[:-1] + [s] + par


def encode(data: bytes | str, level: str = "B", size: int | None = None, mode: str = "auto"):
    if isinstance(data, str):
        data = data.encode()
    mode_id, payload = best_payload(data, mode)
    for S in ([size] if size else SIZES):
        v = version(S, level)
        if len(payload) <= v.capacity:
            break
    else:
        raise ValueError(f"payload of {len(payload)} bytes does not fit level {level}")
    stream = list(_header(mode_id, len(payload)) + payload)
    msgs = []
    for b in v.blocks:
        k = b - RS_PARITY
        chunk, stream = stream[:k - 1], stream[k - 1:]
        msgs.append(_rs_block(chunk + [0] * (k - len(chunk)), RS_PARITY))
    # interleave block bytes, then bits (MSB first)
    nb = len(msgs)
    order = [msgs[j][i] for i in range(max(v.blocks)) for j in range(nb) if i < v.blocks[j]]
    bits = np.unpackbits(np.array(order, dtype=np.uint8))
    bits = np.concatenate([bits, np.zeros(v.info_bits - len(bits), dtype=np.uint8)])
    grid = frame_modules(S).astype(np.int16)
    pos = 0
    for k, code in enumerate(codes(S, level)):
        cw = ldpc_encode(code, bits[pos:pos + code.k])
        pos += code.k
        rr, cc = coset_positions(S, k)
        grid[rr, cc] = cw ^ scramble(S, level, k, len(cw))
    assert (grid >= 0).all()
    return v, grid.astype(np.uint8)


def decode_info_bits(v: Version, bits: np.ndarray) -> bytes | None:
    """Outer code: bytes -> RS blocks -> header + payload."""
    nbytes = sum(v.blocks)
    stream = np.packbits(bits[:nbytes * 8]).tolist()
    nb = len(v.blocks)
    blocks = [[] for _ in range(nb)]
    i = 0
    for pos in range(max(v.blocks)):
        for j in range(nb):
            if pos < v.blocks[j]:
                blocks[j].append(stream[i])
                i += 1
    message = []
    for blk in blocks:
        n, k = len(blk), len(blk) - RS_PARITY
        f = gf257.gao_decode(list(range(n)), blk, k)
        if f is None:
            return None
        word = [gf257.poly_eval(f, x) for x in range(n)]
        if sum(a != b for a, b in zip(word, blk)) > 1 or any(c > 255 for c in word):
            return None
        message += word[:k - 1]
    mode, length, hlen = _parse_header(message)
    end = hlen + length
    if mode > 1 or end > len(message) or any(message[end:]):
        return None
    payload = bytes(message[hlen:end])
    return unpack_text(payload) if mode == 1 else payload
