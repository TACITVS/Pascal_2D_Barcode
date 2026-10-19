"""PM257-PHOTO-READER-2026-10-19-v1: assisted screen-fixture analysis.

External markers identify a target and register its plane. Both formats use
the same registered crop. Optical nuisance fitting uses the known frame and
quiet zone only; payload truth is consulted after decoding for verification.
Rectification introduces interpolation and does not preserve white noise.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

try:
    from .benchmark_density import reader2, turbo
except ImportError:
    from benchmark_density import reader2, turbo


@dataclass(frozen=True)
class Registration:
    case: dict[str, object]
    homography: np.ndarray
    markers: int
    residual_px: float
    corners: np.ndarray


def load_photo(path: Path) -> np.ndarray:
    if path.suffix.lower() in (".heic", ".heif"):
        try:
            import pillow_heif
        except ImportError as exc:
            raise RuntimeError("HEIC input requires: python -m pip install pillow-heif") from exc
        pillow_heif.register_heif_opener()
    with Image.open(path) as image:
        return np.asarray(ImageOps.exif_transpose(image).convert("L"), dtype=np.float32)


def project(h: np.ndarray, points: np.ndarray) -> np.ndarray:
    return cv2.perspectiveTransform(np.asarray(points, dtype=np.float64).reshape(1, -1, 2), h)[0]


def register(gray: np.ndarray, manifest: dict[str, object]) -> list[Registration]:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    parameters = cv2.aruco.DetectorParameters()
    parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    corners, identifiers, _ = cv2.aruco.ArucoDetector(dictionary, parameters).detectMarkers(
        np.clip(gray, 0, 255).astype(np.uint8))
    if identifiers is None:
        return []
    observed = {int(i): c.reshape(4, 2).astype(np.float64) + 0.5
                for i, c in zip(identifiers.ravel(), corners)}
    found = []
    for case in manifest["cases"]:
        sources, targets = [], []
        for identifier, points in zip(case["marker_ids"], case["marker_corners_units"]):
            if identifier in observed:
                sources.extend(points)
                targets.extend(observed[identifier])
        if len(sources) < 12:
            continue
        source, target = np.asarray(sources, float), np.asarray(targets, float)
        h, mask = cv2.findHomography(source, target, cv2.RANSAC, 2.0)
        if h is None or mask is None or int(mask.sum()) < 10:
            continue
        residual = float(np.sqrt(np.mean(np.sum((project(h, source) - target) ** 2, axis=1))))
        origin = int(case["code_origin_units"]) + int(case["quiet"])
        side = int(case["S"])
        code = np.array([[origin, origin], [origin + side, origin],
                         [origin + side, origin + side], [origin, origin + side]], float)
        found.append(Registration(case, h, len(sources) // 4, residual, project(h, code)))
    return found


def rectify(gray: np.ndarray, registration: Registration) -> tuple[np.ndarray, float]:
    case = registration.case
    edges = np.roll(registration.corners, -1, axis=0) - registration.corners
    pitch = float(np.linalg.norm(edges, axis=1).mean() / int(case["S"]))
    cells = int(case["S"]) + 2 * int(case["quiet"])
    width = max(8, round(cells * pitch))
    pitch = width / cells
    # Preserve approximately the native captured resolution, rather than
    # resampling to a generous fixed number of pixels per module.
    coordinates = (np.arange(width) + 0.5) / pitch + int(case["code_origin_units"])
    xx, yy = np.meshgrid(coordinates, coordinates)
    native = project(registration.homography, np.column_stack((xx.ravel(), yy.ravel())))
    map_x = (native[:, 0].reshape(width, width) - 0.5).astype(np.float32)
    map_y = (native[:, 1].reshape(width, width) - 0.5).astype(np.float32)
    return cv2.remap(gray, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                     borderValue=255), pitch


def decode_crop(image: np.ndarray, pitch: float, case: dict[str, object]) -> tuple[bytes | None, dict[str, object]]:
    size, quiet = int(case["S"]), int(case["quiet"])
    lo, hi = quiet * pitch, (quiet + size) * pitch
    corners = np.array([[lo, lo], [hi, lo], [hi, hi], [lo, hi]])
    family, setting = str(case["profile"]).split("/")
    match family:
        case "dense":
            for gammas in ((1.0,), reader2.GAMMAS):
                decoded = reader2.decode_symbol(image, corners, size, False, setting, gammas=gammas)
                if decoded is not None:
                    raw = decoded.data
                    result = raw[:-8] if len(raw) >= 8 and turbo.tag(raw[:-8]) == raw[-8:] else None
                    return result, {"gamma": None, "blur_px": decoded.blur_px,
                                    "tone_fit": "existing_dense_reader"}
            return None, {}
        case "turbo":
            centers = (quiet + np.arange(size) + 0.5) * pitch
            history = []
            for gammas in ((1.0,), reader2.GAMMAS):
                photo = reader2.Photo(image, corners, size, False)
                blur, noise = reader2.estimate(photo, gammas)
                # Lighting, gamma and contrast come from the frame, never
                # the manifest's true data cells or expected payload bytes.
                xy = ((np.arange(image.shape[0]) + 0.5) / pitch - quiet) / size - 0.5
                light = reader2._quad_eval(photo.fit_light, xy[None, :], xy[:, None])
                darkness = (1 - np.clip(image / np.maximum(light, 1), 0, 1.5) ** photo.gamma) / photo.kappa
                normalised = (225 - 200 * darkness).astype(np.float32)
                result, rounds = turbo.decode(turbo.version(size, float(setting)), normalised,
                                               centers, centers, pitch, blur,
                                               noise=float(np.clip(np.median(noise), 3, 40)),
                                               rounds=16)
                history.append({"gamma": photo.gamma, "kappa": photo.kappa,
                                "blur_px": blur, "rounds": rounds})
                if result is not None:
                    return result, {"attempts": history}
            return None, {"attempts": history}
        case _:
            raise ValueError("unsupported fixture profile")


def analyze(gray: np.ndarray, manifest: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for registration in register(gray, manifest):
        start = time.perf_counter()
        crop, pitch = rectify(gray, registration)
        decoded, details = decode_crop(crop, pitch, registration.case)
        expected = base64.b64decode(registration.case["payload_base64"])
        rows.append({"target": registration.case["id"], "profile": registration.case["profile"],
                     "payload_bytes": len(expected), "decoded_exactly": decoded == expected,
                     "accepted_wrong": decoded is not None and decoded != expected,
                     "decoded_sha256": hashlib.sha256(decoded).hexdigest() if decoded is not None else None,
                     "pixels_per_module_rectified": pitch,
                     "symbol_width_px": pitch * int(registration.case["S"]),
                     "width_with_quiet_px": crop.shape[0],
                     "full_board_width_px_equivalent": pitch * int(registration.case["board_side_units"]),
                     "markers_detected": registration.markers,
                     "registration_rms_px": registration.residual_px,
                     "registered_corners": registration.corners.tolist(), "details": details,
                     "seconds": time.perf_counter() - start,
                     "registration": "assisted_external_markers",
                     "truth_used_only_after_decoding": True})
    return rows


def decoder_fingerprint() -> str:
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    sources = sorted(root.glob("*.py")) + sorted((repo / "pascal_mds").glob("*.py"))
    sources += [repo / "research" / "ldpc.py"]
    sources += [Path(turbo.dense.__file__), Path(reader2.__file__), Path(reader2.det.__file__)]
    versions = {name: importlib.metadata.version(name) for name in
                ("numpy", "scipy", "Pillow", "opencv-python-headless")}
    try:
        versions["pillow-heif"] = importlib.metadata.version("pillow-heif")
    except importlib.metadata.PackageNotFoundError:
        pass
    return hashlib.sha256(b"".join(path.read_bytes() for path in sources)
                          + json.dumps(versions, sort_keys=True).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photos", type=Path, nargs="+")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("/tmp/pascal-screen-reads.jsonl"))
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    source = decoder_fingerprint()
    manifest_hash = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    previous = [json.loads(line) for line in args.out.read_text().splitlines()] if args.out.exists() else []
    done = {(row["input_sha256"], row["decoder_sha256"], row.get("manifest_sha256")) for row in previous}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with args.out.open("a") as log:
        for index, path in enumerate(args.photos):
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            if (checksum, source, manifest_hash) in done:
                continue
            print(f"[{index + 1}/{len(args.photos)}] reading {path.name}", flush=True)
            try:
                image = load_photo(path)
                result = {"photo": path.name, "shape": list(image.shape), "reads": analyze(image, manifest)}
            except (OSError, ValueError, RuntimeError) as exc:
                result = {"photo": path.name, "error": str(exc), "reads": []}
            result.update({"input_sha256": checksum, "decoder_sha256": source,
                           "kit_id": manifest["kit_id"], "manifest_sha256": manifest_hash})
            log.write(json.dumps(result) + "\n")
            log.flush()
            elapsed = time.perf_counter() - start
            eta = elapsed * (len(args.photos) - index - 1) / (index + 1)
            print(f"  {[(r['target'], r['decoded_exactly']) for r in result['reads']]} "
                  f"elapsed={elapsed:.1f}s ETA={eta:.1f}s", flush=True)


if __name__ == "__main__":
    main()
