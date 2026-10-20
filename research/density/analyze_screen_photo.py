"""PM257-PHOTO-READER-2026-10-19-v1.2: assisted screen-fixture analysis.

External markers identify a target; optional cropped-image recovery locates
its known timing frame. Both formats use the same registered crop.
Optical nuisance fitting uses the known frame and
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
    from .photo_centers import decode_native_centers
except ImportError:
    from benchmark_density import reader2, turbo
    from photo_centers import decode_native_centers


@dataclass(frozen=True)
class Registration:
    case: dict[str, object]
    homography: np.ndarray
    markers: int
    residual_px: float | None
    corners: np.ndarray
    method: str = "assisted_external_markers"
    marker_ids: tuple[int, ...] = ()
    frame_score: float | None = None


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


def register_cropped_frame(gray: np.ndarray, manifest: dict[str, object]) -> list[Registration]:
    """Recover one tightly cropped fixture without using its payload bits.

    Padding helps identify edge-touching markers. Enlarged images are used
    for marker identification only; frame geometry and payload decoding use
    the original pixels. Two consistent marker IDs identify the configured
    target; its known timing frame supplies the homography.
    """
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_100)
    padding = 24
    background = float(np.median(gray[:5]))
    padded = np.clip(np.pad(gray, padding, constant_values=background), 0, 255).astype(np.uint8)
    observed: set[int] = set()
    for scale in (1, 2, 3, 4):
        image = (cv2.resize(padded, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                 if scale != 1 else padded)
        detector = cv2.aruco.ArucoDetector(dictionary, cv2.aruco.DetectorParameters())
        _, identifiers, _ = detector.detectMarkers(image)
        if identifiers is not None:
            observed.update(map(int, identifiers.ravel()))
    ranked = sorted(((len(observed.intersection(case["marker_ids"])), case)
                     for case in manifest["cases"]), key=lambda pair: pair[0], reverse=True)
    ambiguous = len(ranked) > 1 and ranked[0][0] == ranked[1][0]
    if not ranked or ranked[0][0] < 2 or ambiguous:
        return []
    count, case = ranked[0]
    best = None
    for binarize in (reader2.binarize_adaptive, reader2.binarize_otsu):
        for quad in reader2.candidate_quads(gray, binarize(gray)):
            located = reader2.locate(gray, quad)
            if located is None:
                continue
            corners, coarse_side, score = located
            if 2 * coarse_side != int(case["S"]) or score < 0.8:
                continue
            if best is None or score > best[2]:
                best = (corners, coarse_side, score)
    if best is None:
        return []
    corners, _, score = best
    origin, size = int(case["code_origin_units"]) + int(case["quiet"]), int(case["S"])
    source = np.array([[origin, origin], [origin + size, origin],
                       [origin + size, origin + size], [origin, origin + size]], np.float32)
    h = cv2.getPerspectiveTransform(source, corners.astype(np.float32))
    return [Registration(case, h, count, None, corners, "barcode_frame_with_marker_id",
                         tuple(sorted(observed.intersection(case["marker_ids"]))), float(score))]


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


def analyze(gray: np.ndarray, manifest: dict[str, object],
            recover_cropped: bool = False,
            receiver_fallback: bool = False) -> list[dict[str, object]]:
    rows = []
    registrations = register(gray, manifest)
    if not registrations and recover_cropped:
        registrations = register_cropped_frame(gray, manifest)
    for registration in registrations:
        start = time.perf_counter()
        crop, pitch = rectify(gray, registration)
        decoded, details = decode_crop(crop, pitch, registration.case)
        family, setting = str(registration.case["profile"]).split("/")
        if decoded is None and receiver_fallback and family == "turbo":
            decoded, fallback_details = decode_native_centers(
                gray, registration.corners, int(registration.case["S"]), float(setting))
            details["native_center_fallback"] = fallback_details
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
                     "registration": registration.method,
                     "marker_ids": list(registration.marker_ids),
                     "frame_score": registration.frame_score,
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
    parser.add_argument("--recover-cropped", action="store_true",
                        help="identify clipped markers and locate the known barcode frame when marker registration fails")
    parser.add_argument("--receiver-fallback", action="store_true",
                        help="after a turbo failure, try native module centres and an unlabelled Otsu threshold")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    source = hashlib.sha256((decoder_fingerprint() + str(args.recover_cropped)
                             + str(args.receiver_fallback)).encode()).hexdigest()
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
                result = {"photo": path.name, "shape": list(image.shape),
                          "reads": analyze(image, manifest, recover_cropped=args.recover_cropped,
                                           receiver_fallback=args.receiver_fallback),
                          "recover_cropped": args.recover_cropped,
                          "receiver_fallback": args.receiver_fallback}
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
