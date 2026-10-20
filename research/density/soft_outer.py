"""PB-SOFT-OUTER-2026-10-20-v1: confidence-guided concatenated decoding.

The frozen Turbo format is unchanged. Try its four-parity RS blocks with
zero, two and four least-reliable byte erasures, even if inner LDPC checks
have not converged. Only the existing end-to-end tag accepts a payload.
This is a bounded generalized-minimum-distance (GMD) research receiver.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Iterator, Protocol

import numpy as np

try:
    from . import turbo
except ImportError:
    import turbo

from pascal_mds.syndrome import decode_word


class OuterVersion(Protocol):
    """The common information-stream layout used by Turbo and Gray."""

    info_bits: int
    blocks: tuple[int, ...]


@dataclass(frozen=True)
class Candidate:
    score: float
    word: tuple[int, ...]


def block_positions(lengths: tuple[int, ...]) -> tuple[np.ndarray, ...]:
    """Indices into the column-interleaved byte stream, for each RS block."""
    positions: list[list[int]] = [[] for _ in lengths]
    offset = 0
    for column in range(max(lengths)):
        for block, length in enumerate(lengths):
            if column < length:
                positions[block].append(offset)
                offset += 1
    return tuple(np.asarray(row, dtype=np.int64) for row in positions)


def _combinations(
    candidates: list[list[Candidate]], limit: int,
) -> Iterator[tuple[Candidate, ...]]:
    """Enumerate candidate products in increasing additive soft distance."""
    origin = (0,) * len(candidates)
    heap = [(sum(row[0].score for row in candidates), origin)]
    seen = {origin}
    for _ in range(limit):
        if not heap:
            return
        _, indices = heapq.heappop(heap)
        yield tuple(row[index] for row, index in zip(candidates, indices))
        for j, row in enumerate(candidates):
            neighbor = list(indices)
            neighbor[j] += 1
            key = tuple(neighbor)
            if neighbor[j] < len(row) and key not in seen:
                seen.add(key)
                score = sum(candidates[i][index].score
                            for i, index in enumerate(key))
                heapq.heappush(heap, (score, key))


def decode(
    v: OuterVersion, bits: np.ndarray, posterior_llr: np.ndarray,
    max_combinations: int = 256,
) -> bytes | None:
    """Decode using signed posterior LLRs; no expected payload is supplied.

    Byte reliability is the minimum magnitude of its eight bit LLRs.
    Erasure lists are nested and tie-broken by byte index. Full RS words,
    byte representability, padding, header and the existing 64-bit tag
    must all pass. The tag is an integrity check, not authentication.
    """
    if max_combinations < 1:
        raise ValueError("positive candidate budget required")
    count = 8 * sum(v.blocks)
    if len(bits) < count or len(posterior_llr) < count:
        raise ValueError("truncated outer word or reliability vector")
    if not np.isfinite(posterior_llr[:count]).all():
        raise ValueError("nonfinite reliability")
    received = np.packbits(bits[:count]).astype(np.uint8)
    bit_weights = np.abs(posterior_llr[:count]).reshape(-1, 8)
    reliability = bit_weights.min(axis=1)
    positions = block_positions(v.blocks)
    choices: list[list[Candidate]] = []
    parity = turbo.dense.RS_PARITY
    for indices in positions:
        raw = received[indices]
        order = np.argsort(reliability[indices], kind="stable")
        candidates: dict[tuple[int, ...], Candidate] = {}
        for erased in range(0, parity + 1, 2):
            hypothesis: list[int | None] = raw.tolist()
            for index in order[:erased]:
                hypothesis[int(index)] = None
            word = decode_word(len(raw), len(raw) - parity, hypothesis)
            if word is None or any(value > 255 for value in word):
                continue
            key = tuple(word)
            changed = np.bitwise_xor(raw, np.asarray(word, dtype=np.uint8))
            differences = np.unpackbits(changed).reshape(-1, 8)
            score = float(np.sum(differences * bit_weights[indices]))
            candidates[key] = Candidate(score, key)
        if not candidates:
            return None
        choices.append(sorted(candidates.values(), key=lambda row: row.score))
    for combination in _combinations(choices, max_combinations):
        corrected = received.copy()
        for indices, candidate in zip(positions, combination):
            corrected[indices] = candidate.word
        info = np.pad(np.unpackbits(corrected), (0, v.info_bits - count))
        # These are now exact RS codewords, so the frozen outer parser's
        # one-error acceptance limit no longer discards a two-error repair.
        result = turbo.decode_outer(v, info)
        if result is not None:
            return result
    return None


def decode_pair(
    v: turbo.Version, image: np.ndarray, cx: np.ndarray, cy: np.ndarray,
    pitch: float, blur: float, noise: float = 8.0, rounds: int = 16,
) -> tuple[bytes | None, bytes | None, list[dict[str, object]]]:
    """Frozen and GMD acceptance on exactly the same optical/BP trajectory.

    The two receivers share every soft message. New outer candidates never
    alter feedback. Thus a legacy valid result is retained by the new
    receiver, while failures may be rescued before inner convergence.
    """
    code, permutation, mask = turbo.code_and_mapping(v.S, v.rate)
    frame = turbo.dense.frame_modules(v.S).astype(float)
    frame[frame < 0] = 0
    operator = turbo.NativeOperator(
        image, frame, cx, cy, pitch, blur, noise)
    decoder = turbo.SoftIRA(code)
    prior = np.zeros((v.S - 4, v.S - 4))
    baseline: bytes | None = None
    improved: bytes | None = None
    history: list[dict[str, object]] = []
    for step in range(rounds):
        physical = operator.extrinsic(prior).ravel()[permutation]
        channel = np.clip(
            0.8 * np.where(mask, -physical, physical), -30, 30)
        word, external, ok = decoder.decode(channel)
        legacy = turbo.decode_outer(v, word[:v.info_bits]) if ok else None
        candidate = None
        if improved is None:
            candidate = decode(v, word[:v.info_bits],
                               (channel + external)[:v.info_bits])
        if baseline is None and legacy is not None:
            baseline = legacy
        if improved is None:
            improved = legacy if legacy is not None else candidate
        history.append({
            "round": step + 1, "checks_satisfied": bool(ok),
            "legacy_valid": legacy is not None,
            "gmd_valid": candidate is not None,
        })
        if baseline is not None and improved is not None:
            break
        feedback = np.zeros(code.n)
        feedback[permutation] = np.where(mask, -external, external)
        prior = 0.5 * prior + 0.5 * np.clip(
            feedback.reshape(prior.shape), -15, 15)
    return baseline, improved, history
