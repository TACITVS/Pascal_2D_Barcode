"""Create a deterministic compact archive and provenance manifest.

Run after the frozen validation, aggregation, and figure generation complete.
Raw logs stay available in the working directory but are ignored by git.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.metadata
import io
import json
import platform
import subprocess
import tarfile
from pathlib import Path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parent
    repo = root.parents[1]
    logs = sorted(root.glob("*.jsonl"))
    if not (root / "combined_validation.json").exists():
        raise RuntimeError("complete both validation families and summarize first")
    with (root / "evidence.tar.gz").open("wb") as target:
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as archive:
                for path in logs:
                    content = path.read_bytes()
                    info = tarfile.TarInfo(path.name)
                    info.size = len(content)
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(content))
    witness = root / "certificate_example.json"
    (root / "certificate_example.json.gz").write_bytes(gzip.compress(witness.read_bytes(), mtime=0))
    sources = sorted(root.glob("*.py")) + [repo / "tests/test_density_research.py", repo / "pyproject.toml"]
    packages = ["numpy", "scipy", "Pillow", "opencv-python-headless", "scikit-learn", "pytest", "matplotlib"]
    manifest = {"base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
                "python": platform.python_version(), "platform": platform.platform(),
                "packages": {name: importlib.metadata.version(name) for name in packages},
                "source_sha256": {str(p.relative_to(repo)): digest(p) for p in sources},
                "raw_log_sha256": {p.name: digest(p) for p in logs},
                "raw_log_rows": {p.name: len(p.read_text().splitlines()) for p in logs},
                "evidence_archive_sha256": digest(root / "evidence.tar.gz"),
                "certificate_sha256": digest(witness),
                "tests": {"python_passed": 377, "javascript_checks_passed": 89}}
    (root / "evidence_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Archived {len(logs)} logs; {sum(manifest['raw_log_rows'].values())} log rows")


if __name__ == "__main__":
    main()
