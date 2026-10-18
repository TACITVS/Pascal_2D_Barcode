"""Irregular repeat-accumulate (IRA) LDPC codes with soft belief-propagation
decoding.  Research code (numpy), for the soft-decision inner layer.

H = [H1 | T], where T is the dual-diagonal accumulator, so encoding is linear
time: p_j = p_{j-1} XOR (H1 u)_j.  Every information bit has degree dv in H1;
H1's rows are as even as possible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class IRACode:
    k: int                 # information bits
    m: int                 # parity bits (= checks)
    h1_rows: np.ndarray    # check index of each H1 edge
    h1_cols: np.ndarray    # info-bit index of each H1 edge

    @property
    def n(self) -> int:
        return self.k + self.m

    @property
    def rate(self) -> float:
        return self.k / self.n


def make_ira(k: int, m: int, dv: int = 3, seed: int = 0) -> IRACode:
    """Random IRA code avoiding repeated edges (some 4-cycles may remain)."""
    rng = np.random.default_rng(seed)
    cols = np.repeat(np.arange(k), dv)
    # spread sockets evenly over checks, then shuffle
    rows = np.arange(k * dv) % m
    for _ in range(50):
        rng.shuffle(rows)
        pairs = rows * k + cols
        if len(np.unique(pairs)) == len(pairs):
            break
    else:
        pairs = rows * k + cols
        keep = np.unique(pairs, return_index=True)[1]
        rows, cols = rows[keep], cols[keep]
    return IRACode(k, m, rows.astype(np.int64), cols.astype(np.int64))


def encode(code: IRACode, u: np.ndarray) -> np.ndarray:
    s = np.zeros(code.m, np.uint8)
    np.add.at(s, code.h1_rows, u[code.h1_cols])
    s &= 1
    p = np.bitwise_xor.accumulate(s)
    return np.concatenate([u.astype(np.uint8), p])


class Decoder:
    """Sum-product decoding in the log domain over all edges of H."""

    def __init__(self, code: IRACode):
        k, m = code.k, code.m
        # edges of H: H1 edges, then accumulator edges (check j: parity j and j-1)
        acc_r = np.concatenate([np.arange(m), np.arange(1, m)])
        acc_c = np.concatenate([np.arange(m), np.arange(m - 1)]) + k
        r = np.concatenate([code.h1_rows, acc_r])
        c = np.concatenate([code.h1_cols, acc_c])
        order = np.argsort(r, kind="stable")
        self.r, self.c = r[order], c[order]
        self.check_starts = np.flatnonzero(np.r_[True, self.r[1:] != self.r[:-1]])
        self.n = code.n
        self.code = code

    def decode(self, llr: np.ndarray, iters: int = 60) -> tuple[np.ndarray, bool]:
        """llr > 0 means bit 0.  Returns (hard bits, all checks satisfied)."""
        r, c, starts = self.r, self.c, self.check_starts
        v2c = llr[c].astype(np.float64)
        total = llr.astype(np.float64)
        bits = (total < 0).astype(np.uint8)
        for _ in range(iters):
            t = np.tanh(np.clip(v2c, -30, 30) / 2)
            t = np.where(np.abs(t) < 1e-12, 1e-12, t)
            # product over each check, excluding the edge itself
            sign = np.sign(t)
            logabs = np.log(np.abs(t))
            sum_log = np.add.reduceat(logabs, starts)
            neg = np.add.reduceat((sign < 0).astype(np.int64), starts)
            seg = np.repeat(np.arange(len(starts)), np.diff(np.r_[starts, len(r)]))
            ext_log = sum_log[seg] - logabs
            ext_sign = np.where((neg[seg] - (sign < 0)) % 2 == 1, -1.0, 1.0)
            ext = np.clip(ext_sign * np.exp(ext_log), -0.999999999, 0.999999999)
            c2v = 2 * np.arctanh(ext)
            total = llr.astype(np.float64).copy()
            np.add.at(total, c, c2v)
            bits = (total < 0).astype(np.uint8)
            syn = np.add.reduceat(bits[c], starts) & 1
            if not syn.any():
                return bits, True
            v2c = total[c] - c2v
        return bits, False
