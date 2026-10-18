"""Image reading (numpy + Pillow): synthetic photos of rendered symbols."""

import random

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

from pascal_mds import encode  # noqa: E402
from pascal_mds.reader import read  # noqa: E402
from pascal_mds.render import to_image  # noqa: E402


def photo(sym, module_px=8, angle=0.0, mirror=False, canvas=420, blur=0.0, noise=0.0, seed=0):
    img = to_image(sym, module_px)
    if mirror:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    bg = Image.new("L", (canvas, canvas), 235)
    bg.paste(img, ((canvas - img.width) // 2, (canvas - img.height) // 2))
    if blur:
        from PIL import ImageFilter

        bg = bg.filter(ImageFilter.GaussianBlur(blur))
    arr = np.asarray(bg, dtype=np.float32)
    if noise:
        arr = arr + np.random.default_rng(seed).normal(0, noise, arr.shape)
    return np.clip(arr, 0, 255)


@pytest.mark.parametrize("angle", [0, 17, 90, 145, 180, 271])
def test_rotations(angle):
    sym = encode("https://www.example.com/path?id=12345", "M")
    found = read(photo(sym, angle=angle, blur=1.0, noise=6, seed=angle))
    assert [d.decoded.text for d in found] == ["https://www.example.com/path?id=12345"]


def test_mirrored_photo():
    sym = encode("seen through the glass", "Q")
    found = read(photo(sym, angle=33, mirror=True))
    assert found and found[0].decoded.text == "seen through the glass" and found[0].decoded.mirrored


@pytest.mark.parametrize("payload,level,px", [(b"x", "L", 12), (bytes(range(150)), "L", 5), ("Hello PASCAL", "H", 9)])
def test_sizes(payload, level, px):
    sym = encode(payload, level)
    data = payload.encode() if isinstance(payload, str) else payload
    canvas = sym.size * px + 120
    found = read(photo(sym, module_px=px, angle=8, canvas=canvas, blur=0.8))
    assert found and found[0].decoded.data == data


def test_two_symbols_in_one_image():
    a = to_image(encode("first", "M"), 8)
    b = to_image(encode("second one", "H"), 8)
    canvas = Image.new("L", (a.width + b.width + 60, max(a.height, b.height) + 40), 255)
    canvas.paste(a, (20, 20))
    canvas.paste(b, (a.width + 40, 20))
    texts = sorted(d.decoded.text for d in read(canvas))
    assert texts == ["first", "second one"]


def test_damage_is_corrected_with_erasures():
    sym = encode("scratch resistant", "H")
    arr = photo(sym, module_px=10, angle=12)
    h, w = arr.shape
    rng = random.Random(4)
    # paint two grey smudges over the data area
    for _ in range(2):
        y, x = rng.randrange(h // 2 - 40, h // 2 + 20), rng.randrange(w // 2 - 40, w // 2 + 20)
        arr[y:y + 22, x:x + 22] = 128
    found = read(arr)
    assert found and found[0].decoded.text == "scratch resistant"


def test_blank_and_noise_images_give_nothing():
    rng = np.random.default_rng(1)
    assert read(np.full((300, 300), 200.0)) == []
    assert read(rng.uniform(0, 255, (300, 300))) == []
