"""The JavaScript port must match the Python reference (needs Node)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_node_vectors_and_matrices():
    out = subprocess.run(["node", str(WEB / "test_node.js")], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("ok ")


def test_js_reader_matches_python_reader(tmp_path):
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from PIL import ImageFilter

    from pascal_mds import encode
    from pascal_mds.reader import read
    from pascal_mds.render import to_image

    cases = [("https://www.example.com/a?b=1", "M", 23), ("WIFI:S:Net;T:WPA;P:Secret1;;", "Q", 140),
             ("x", "H", 300), (bytes(range(100)).hex(), "L", 77)]
    files, texts = [], []
    for i, (text, level, angle) in enumerate(cases):
        img = to_image(encode(text, level), 7).rotate(angle, expand=True, fillcolor=240)
        img = img.filter(ImageFilter.GaussianBlur(0.8))
        arr = np.asarray(img, dtype=np.float32) + np.random.default_rng(i).normal(0, 5, (img.height, img.width))
        arr = np.clip(arr, 0, 255).astype(np.uint8)
        path = tmp_path / f"{i}.pgm"
        Image.fromarray(arr).save(path)
        assert [d.decoded.text for d in read(arr)] == [text]
        files.append(str(path))
        texts.append(text)
    out = subprocess.run(["node", str(WEB / "read_pgm.js"), *files], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr
    got = [json.loads(line)["texts"] for line in out.stdout.splitlines()]
    assert got == [[t] for t in texts]
