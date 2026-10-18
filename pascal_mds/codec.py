"""Payload <-> module matrix.  Pure Python, no third-party dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from . import gf257
from .layout import (
    LEVELS,
    SIZES,
    Version,
    acceptable,
    frame_value,
    is_frame,
    placement,
    scrambler,
    version,
)

MODE_BYTES = 0
MODE_TEXT = 1

# Compact text mode: 6 bits per character for the characters URLs, Wi-Fi
# strings and short messages mostly use.  Code 63 escapes one raw byte.
TEXT_TOKENS: tuple[bytes, ...] = tuple(
    [bytes([c]) for c in b"abcdefghijklmnopqrstuvwxyz0123456789"]
    + [bytes([c]) for c in b" ./:-_?=&%#@+~!*,;$'()\n"]
    + [b"https://", b"http://", b"www.", b".com"]
)
TEXT_ESCAPE = 63
assert len(TEXT_TOKENS) == 63
_LONG_TOKENS = sorted((t for t in TEXT_TOKENS if len(t) > 1), key=len, reverse=True)
_SINGLE = {t[0]: i for i, t in enumerate(TEXT_TOKENS) if len(t) == 1}
_TOKEN_INDEX = {t: i for i, t in enumerate(TEXT_TOKENS)}


class DecodeError(ValueError):
    pass


@dataclass(frozen=True)
class Symbol:
    version: Version
    modules: tuple[tuple[int, ...], ...]  # 1 = dark
    pad: int

    @property
    def size(self) -> int:
        return self.version.n


@dataclass(frozen=True)
class Decoded:
    data: bytes
    version: Version
    errors: int
    erasures: int
    mirrored: bool

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


# --------------------------------------------------------------------- modes

def pack_text(data: bytes) -> bytes:
    bits: list[int] = []

    def put(value: int, width: int) -> None:
        bits.extend((value >> (width - 1 - i)) & 1 for i in range(width))

    i = 0
    while i < len(data):
        for token in _LONG_TOKENS:
            if data.startswith(token, i):
                put(_TOKEN_INDEX[token], 6)
                i += len(token)
                break
        else:
            byte = data[i]
            if byte in _SINGLE:
                put(_SINGLE[byte], 6)
            else:
                put(TEXT_ESCAPE, 6)
                put(byte, 8)
            i += 1
    while len(bits) % 8:
        bits.append(1)  # a trailing partial escape terminates parsing
    return bytes(
        int("".join(map(str, bits[j:j + 8])), 2) for j in range(0, len(bits), 8)
    )


def unpack_text(packed: bytes) -> bytes:
    bits = [(b >> (7 - i)) & 1 for b in packed for i in range(8)]
    out = bytearray()
    pos = 0

    def take(width: int) -> int:
        nonlocal pos
        value = 0
        for _ in range(width):
            value = (value << 1) | bits[pos]
            pos += 1
        return value

    while len(bits) - pos >= 6:
        code = take(6)
        if code == TEXT_ESCAPE:
            if len(bits) - pos < 8:
                break
            out.append(take(8))
        else:
            out += TEXT_TOKENS[code]
    return bytes(out)


def _header(mode: int, length: int) -> bytes:
    if length <= 31:
        return bytes([(mode << 6) | length])
    if length >= 1 << 13:
        raise ValueError("payload too long")
    return bytes([(mode << 6) | 0x20 | (length >> 8), length & 0xFF])


def _parse_header(message: list[int]) -> tuple[int, int, int]:
    mode = message[0] >> 6
    if message[0] & 0x20:
        return mode, ((message[0] & 0x1F) << 8) | message[1], 2
    return mode, message[0] & 0x1F, 1


# ------------------------------------------------------------------- encoder

def _choose_pad(parity0: list[int], unit: list[int]) -> tuple[int, list[int]]:
    """Smallest pad value s in 0..255 making every parity symbol a byte.

    Parity is affine in the pad: c_x(s) = c_x(0) + s * C(x, K-1), and
    C(x, K-1) != 0 mod 257 for K <= x < 257, so each parity position rules out
    at most one value of s.  With r <= 255 parity symbols some s <= r works
    (Theorem 1 in SPEC.md).  Only additions are used.
    """
    current = list(parity0)
    for s in range(256):
        if all(v != 256 for v in current):
            return s, current
        current = [v + u - 257 if v + u >= 257 else v + u for v, u in zip(current, unit)]
    raise AssertionError("unreachable: Theorem 1 guarantees a pad")


def _codeword(v: Version, message: list[int]) -> tuple[list[int], int]:
    parity0 = gf257.pascal_extend(message, v.r)
    unit = gf257.pascal_extend([0] * (v.K - 1) + [1], v.r)  # C(x, K-1)
    s, parity = _choose_pad(parity0, unit)
    return message[:-1] + [s] + parity, s


def best_payload(data: bytes, mode: str = "auto") -> tuple[int, bytes]:
    if mode == "bytes":
        return MODE_BYTES, data
    packed = pack_text(data)
    if mode == "text":
        return MODE_TEXT, packed
    if mode != "auto":
        raise ValueError("mode must be auto, bytes or text")
    return (MODE_TEXT, packed) if len(packed) < len(data) else (MODE_BYTES, data)


def encode(
    data: bytes | str,
    level: str = "M",
    size: int | None = None,
    mode: str = "auto",
) -> Symbol:
    if isinstance(data, str):
        data = data.encode("utf-8")
    mode_id, payload = best_payload(data, mode)
    sizes = [size] if size is not None else SIZES
    for n in sizes:
        v = version(n, level)
        if len(payload) <= v.payload_capacity:
            break
    else:
        largest = version(sizes[-1], level).payload_capacity
        raise ValueError(
            f"payload needs {len(payload)} bytes; level {level} holds at most "
            f"{largest} in a {sizes[-1]}x{sizes[-1]} symbol"
        )
    message = list(_header(mode_id, len(payload)) + payload)
    message += [0] * (v.K - len(message))  # filler, last one is the pad
    codeword, pad = _codeword(v, message)
    return Symbol(version=v, modules=_render(v, codeword), pad=pad)


def _render(v: Version, codeword: list[int]) -> tuple[tuple[int, ...], ...]:
    n = v.n
    grid = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            if is_frame(r, c, n):
                grid[r][c] = frame_value(r, c, n)
    mask = scrambler(v.level, v.N)
    cells = placement(n)
    for i, symbol in enumerate(codeword):
        byte = symbol ^ mask[i]
        for b in range(8):
            r, c = cells[8 * i + b]
            grid[r][c] = (byte >> (7 - b)) & 1
    # the single remainder module stays light
    return tuple(tuple(row) for row in grid)


# ------------------------------------------------------------------- decoder

def read_bytes(modules: list[list[int]] | tuple, mirrored: bool = False) -> list[int]:
    """Raw (still scrambled) codeword bytes from a module matrix."""
    n = len(modules)
    out = []
    cells = placement(n)
    for i in range((len(cells) - 1) // 8):
        byte = 0
        for b in range(8):
            r, c = cells[8 * i + b]
            if mirrored:  # reflection about the BL-TR diagonal fixes the frame
                r, c = n - 1 - c, n - 1 - r
            byte = (byte << 1) | (1 if modules[r][c] else 0)
        out.append(byte)
    return out


def decode_codeword(
    v: Version, received: list[int | None]
) -> tuple[list[int], int, int] | None:
    """Errors-and-erasures decoding; received[i] is None for an erasure.
    Returns (codeword, errors, erasures) or None."""
    xs = [i for i, y in enumerate(received) if y is not None]
    ys = [received[i] for i in xs]
    erasures = v.N - len(xs)
    if not acceptable(v, 0, erasures):
        return None
    f = gf257.gao_decode(xs, ys, v.K)
    if f is None:
        return None
    word = [gf257.poly_eval(f, x) for x in range(v.N)]
    errors = sum(1 for x in xs if word[x] != received[x])
    if not acceptable(v, errors, erasures) or any(c > 255 for c in word):
        return None
    return word, errors, erasures


def parse_message(v: Version, message: list[int]) -> bytes | None:
    mode, length, hlen = _parse_header(message)
    end = hlen + length
    if mode not in (MODE_BYTES, MODE_TEXT) or end > v.K - 1:
        return None
    if any(message[end:v.K - 1]):  # filler must be zero
        return None
    payload = bytes(message[hlen:end])
    return unpack_text(payload) if mode == MODE_TEXT else payload


def decode_bytes(
    n: int,
    reads: list[tuple[list[int], list[float] | None, bool]],
    erasure_rounds: int = 6,
) -> Decoded | None:
    """Decode raw (scrambled) symbol bytes.

    ``reads`` holds (raw bytes, per-symbol confidence or None, mirrored)
    candidates.  Every level is tried on every read without erasures first;
    only then are the least confident symbols erased in growing batches.
    """
    for round_ in range(erasure_rounds + 1):
        for raw, confidence, mirrored in reads:
            if round_ and confidence is None:
                continue
            for level in LEVELS:
                v = version(n, level)
                if v.payload_capacity <= 0:
                    continue
                budget = v.r - v.guard
                count = round(budget * round_ / erasure_rounds)
                if round_ and (count == 0 or not acceptable(v, 0, count)):
                    continue
                mask = scrambler(level, v.N)
                received: list[int | None] = [b ^ m for b, m in zip(raw, mask)]
                if count:
                    for i in sorted(range(v.N), key=lambda i: confidence[i])[:count]:
                        received[i] = None
                result = decode_codeword(v, received)
                if result is None:
                    continue
                codeword, errors, erasures = result
                data = parse_message(v, codeword[: v.K])
                if data is not None:
                    return Decoded(data, v, errors, erasures, mirrored)
    return None


def decode_modules(
    modules: list[list[int]] | tuple, confidence: list[list[float]] | None = None
) -> Decoded:
    n = len(modules)
    if n not in SIZES or any(len(row) != n for row in modules):
        raise DecodeError(f"not a PASCAL-MDS module matrix (size {n})")
    reads = [
        (read_bytes(modules, mirrored),
         None if confidence is None else symbol_confidence(confidence, mirrored),
         mirrored)
        for mirrored in (False, True)
    ]
    result = decode_bytes(n, reads)
    if result is None:
        raise DecodeError("uncorrectable: too many damaged symbols")
    return result


def symbol_confidence(confidence: list[list[float]], mirrored: bool) -> list[float]:
    n = len(confidence)
    cells = placement(n)
    out = []
    for i in range((len(cells) - 1) // 8):
        worst = 1e9
        for b in range(8):
            r, c = cells[8 * i + b]
            if mirrored:
                r, c = n - 1 - c, n - 1 - r
            worst = min(worst, confidence[r][c])
        out.append(worst)
    return out
