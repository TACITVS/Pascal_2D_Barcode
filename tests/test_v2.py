"""PASCAL-MDS v2 (Dense): encoder, photo reader, and the JavaScript port."""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "research" / "v2"), str(ROOT / "research")]
pytest.importorskip("cv2")  # research/capacity.py, imported by the detector
pytest.importorskip("sklearn")
import dense  # noqa: E402
import reader2  # noqa: E402

WEB = ROOT / "web"
LINK = "https://www.example.com/products/item?id=12345&ref=t1"


def photo(text, level, scale=6, angle=0.0, blur=0.8, gamma=1.0, gain=1.0, noise=3.0, seed=0) -> np.ndarray:
    """A synthetic photo: modules at `scale` px, rotated, blurred in linear
    light, then exposed with `gain` (clipping above white) and encoded with
    1 / gamma, as a phone stores it."""
    _, grid = dense.encode(text, level)
    q = dense.QUIET + 4
    mods = np.pad(grid, q)
    lin = np.where(mods == 1, 0.08, 0.92).repeat(scale, 0).repeat(scale, 1)
    img = Image.fromarray((lin * 255).astype(np.uint8)).rotate(angle, expand=True, fillcolor=235, resample=Image.BILINEAR)
    img = img.filter(ImageFilter.GaussianBlur(blur * scale / 3))
    lin = np.asarray(img, dtype=np.float32) / 255
    out = np.clip(lin * gain, 0, 1) ** (1 / gamma) * 255
    out += np.random.default_rng(seed).normal(0, noise, out.shape)
    return np.clip(out, 0, 255).astype(np.uint8)


@pytest.mark.parametrize("level", ["A", "B", "C"])
def test_round_trip_each_level(level):
    res = reader2.read(photo(LINK, level, angle=7))
    assert [r.data.decode() for r in res] == [LINK]
    assert res[0].level == level


def test_flat_stage_rates():
    for level, spec in dense.LEVELS.items():
        assert len(set(spec["rates"])) == 1, level
        v = dense.version(38, level)
        assert max(v.k_stage) - min(v.k_stage) == 0


def test_capacity_grows_with_size_and_falls_with_level():
    for level in "ABC":
        caps = [dense.version(S, level).capacity for S in dense.SIZES]
        assert caps == sorted(caps) and caps[0] < caps[-1]
    for S in (38, 58, 94):
        a, b, c = (dense.version(S, lv).capacity for lv in "ABC")
        assert a > b > c


def test_overexposed_tone_mapped_photo(monkeypatch):
    """Round 2's failure mode: a gamma-encoded phone photo of an overexposed
    screen.  The linear model fails; the fitted tone curve reads it."""
    img = photo(LINK, "A", scale=3, blur=1.0, gamma=2.2, gain=2.0, seed=3)
    assert [r.data.decode() for r in reader2.read(img)] == [LINK]
    monkeypatch.setattr(reader2, "GAMMAS", (1.0,))
    assert reader2.read(img) == []


def test_blank_and_noise_give_nothing():
    rng = np.random.default_rng(1)
    assert reader2.read(np.full((300, 300), 200, np.uint8)) == []
    assert reader2.read(rng.integers(0, 256, (300, 300), dtype=np.uint8)) == []


node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@node
def test_js_encoder_and_ldpc_match_python():
    out = subprocess.run(["node", str(WEB / "test_node_v2.js")], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok ")


@node
def test_js_reader_matches_python_reader(tmp_path):
    import json
    import os

    cases = [(LINK, "A", 5, 0.8, 1.0, 1.0), ("BEGIN:VCARD\nN:Doe;Jane\nEND:VCARD", "B", 4, 1.0, 2.2, 1.5)]
    files = []
    for i, (text, level, scale, blur, gamma, gain) in enumerate(cases):
        img = photo(text, level, scale=scale, angle=11, blur=blur, gamma=gamma, gain=gain, seed=i)
        assert [r.data.decode() for r in reader2.read(img)] == [text]
        path = tmp_path / f"{i}.pgm"
        Image.fromarray(img).save(path)
        files.append(str(path))
    out = subprocess.run(["node", str(WEB / "read_pgm.js"), *files], capture_output=True, text=True, timeout=600,
                         env={**os.environ, "V2": "1"})
    assert out.returncode == 0, out.stderr
    got = [json.loads(line)["texts"] for line in out.stdout.splitlines()]
    assert got == [[text] for text, *_ in cases]
