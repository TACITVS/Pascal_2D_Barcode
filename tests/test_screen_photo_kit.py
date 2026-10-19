"""PM257-PHOTO-TESTS-2026-10-19-v1: fixture geometry and actual payload reads."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "research/density"))

from analyze_screen_photo import analyze, register  # noqa: E402
from screen_targets import TargetCase, board_array, make_cases  # noqa: E402


@pytest.fixture(scope="module")
def cases() -> list[TargetCase]:
    return make_cases(1)


def fixture_manifest(cases: list[TargetCase]) -> dict[str, object]:
    return {"cases": [case.record() for case in cases]}


def test_pairs_have_the_promised_equal_area_and_payload(cases: list[TargetCase]) -> None:
    a1, a2, b1, b2 = cases
    assert a1.payload == a2.payload and len(a1.payload) == 128
    assert a1.grid.shape == a2.grid.shape == (50, 50)
    assert b1.grid.shape == b2.grid.shape == (94, 94)
    assert len(b1.payload) == 582 and len(b2.payload) == 800
    assert b1.payload == b2.payload[:582]
    assert a1.layout == a2.layout and b1.layout == b2.layout
    assert not np.array_equal(a1.grid, a2.grid)


def test_marker_identifiers_disjoint_across_confirmation_sets() -> None:
    targets = make_cases(3)
    identifiers = [i for case in targets for i in case.marker_ids]
    assert len(set(identifiers)) == len(identifiers) == 48
    assert len({hashlib.sha256(case.payload).digest() for case in targets if case.identifier.startswith("A1")}) == 3


@pytest.mark.parametrize("index", [0, 1, 2, 3])
def test_registered_perspective_image_to_exact_payload(cases: list[TargetCase], index: int) -> None:
    case = cases[index]
    clean = board_array(case)
    side = clean.shape[0]
    source = np.array([[0, 0], [side, 0], [side, side], [0, side]], np.float32)
    target = source + np.array([[32, 24], [21, 33], [28, 21], [39, 38]], np.float32)
    warped = cv2.warpPerspective(clean, cv2.getPerspectiveTransform(source, target),
                                 (side + 70, side + 70), borderValue=255)
    photograph = 20 + 0.84 * cv2.GaussianBlur(warped.astype(np.float32), (0, 0), 0.35)
    rows = analyze(photograph, fixture_manifest(cases))
    assert len(rows) == 1 and rows[0]["target"] == case.identifier
    assert rows[0]["decoded_exactly"] and not rows[0]["accepted_wrong"]
    assert rows[0]["markers_detected"] == 4


def test_rotation_and_truth_is_never_a_decoder_prior(cases: list[TargetCase]) -> None:
    case = cases[1]
    manifest = copy.deepcopy(fixture_manifest(cases))
    target = manifest["cases"][1]
    # Replace every data bit and the expected payload in the manifest. The
    # optical decoder must still return the original image's payload hash.
    target["rows"] = ["0" * 50] * 50
    target["payload_base64"] = "d3Jvbmc="
    rows = analyze(np.rot90(board_array(case)).copy().astype(np.float32), manifest)
    assert len(rows) == 1 and not rows[0]["decoded_exactly"]
    assert rows[0]["accepted_wrong"]
    assert rows[0]["decoded_sha256"] == hashlib.sha256(case.payload).hexdigest()


def test_photo_cli_checkpoint_and_resume(cases: list[TargetCase], tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"kit_id": "PM257-PHOTO-CLI-TEST-v1", **fixture_manifest(cases)}))
    photograph = tmp_path / "A2.png"
    assert cv2.imwrite(str(photograph), board_array(cases[1]))
    output = tmp_path / "results.jsonl"
    script = Path(__file__).resolve().parents[1] / "research/density/analyze_screen_photo.py"
    command = [sys.executable, str(script), "--manifest", str(manifest), "--out", str(output), str(photograph)]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    second = subprocess.run(command, check=True, capture_output=True, text=True)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["reads"][0]["decoded_exactly"]
    assert "reading A2.png" in first.stdout and "reading A2.png" not in second.stdout


@pytest.mark.parametrize("index", [1, 3])
def test_edge_touching_markers_recover_using_frame(cases: list[TargetCase], index: int) -> None:
    case = cases[index]
    board = board_array(case)
    trim = case.layout.gap * 4
    cropped = board[trim:-trim, trim:-trim].astype(np.float32)
    manifest = fixture_manifest(cases)
    assert not register(cropped, manifest)
    rows = analyze(cropped, manifest, recover_cropped=True)
    assert len(rows) == 1 and rows[0]["decoded_exactly"]
    assert rows[0]["registration"] == "barcode_frame_with_marker_id"
    assert rows[0]["registration_rms_px"] is None
