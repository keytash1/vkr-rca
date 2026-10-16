"""Build a profile-specific, experiment-free diagnostic application bundle.

The bundle contains the transitive runtime modules, sealed model dependencies,
the web application and one already prepared profile. It never ships training
scripts, incident truth or the independent evaluation corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]
SEEDS = range(20260906, 20260911)
MODEL_FILES = (
    "ml/models/m10c-v2/feature-schema.json",
    "ml/models/m10c-v2/m10c-core-v2.json",
    *(f"ml/models/m11/candidate-recovery-k5-seed-{seed}.json" for seed in SEEDS),
    "ml/models/m12/ood-stats.json",
    "ml/models/m13/freeze-manifest.json",
    *(f"ml/models/m13/diagnostic-ranker-seed-{seed}.json" for seed in SEEDS),
)
RUNTIME_MODULES = (
    "__init__", "m10c_schema", "m10d_reranker", "m11_protocol",
    "m12_adapter", "m13_features", "m13_protocol", "m13_trace", "schema",
)


def build(root: Path, profile_path: Path, output: Path) -> dict:
    root = root.resolve()
    profile_path = profile_path.resolve()
    if output.exists():
        raise FileExistsError("refusing to replace an existing product snapshot")
    if output.resolve() == profile_path or output.resolve().is_relative_to(root / "ml/models"):
        raise ValueError("output path would overwrite an input artifact")
    profile = json.loads(profile_path.read_text())
    profile_id = profile["id"]
    if not isinstance(profile_id, str) or not profile_id or any(
        char not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for char in profile_id
    ):
        raise ValueError("invalid profile id")
    artifact_relative = Path(profile["artifact_dir"])
    if artifact_relative.is_absolute() or ".." in artifact_relative.parts or not (
        artifact_relative.parts[:3] == ("deploy", "profiles", "artifacts")
    ):
        raise ValueError("profile artifacts must be under deploy/profiles/artifacts")
    artifact_dir = (root / artifact_relative).resolve()
    if not artifact_dir.is_relative_to(root / "deploy/profiles/artifacts"):
        raise ValueError("profile artifact path escapes product directory")
    files = {name: (root / name).read_bytes() for name in MODEL_FILES}
    for module in RUNTIME_MODULES:
        source = root / "ml/rca_ml" / f"{module}.py"
        files[str(source.relative_to(root))] = source.read_bytes()
    for source in sorted((root / "cmd/thesis_demo").glob("*.py")):
        if not source.name.startswith("test_"):
            files[str(source.relative_to(root))] = source.read_bytes()
    for source in sorted((root / "cmd/thesis_demo/static").iterdir()):
        if source.is_file():
            files[str(source.relative_to(root))] = source.read_bytes()
    files["ml/pyproject.toml"] = (root / "deploy/product/runtime-pyproject.toml").read_bytes()
    files["README.md"] = (root / "deploy/product/README.md").read_bytes()
    files["verify_bundle.py"] = (root / "deploy/product/verify_bundle.py").read_bytes()
    files[f"deploy/profiles/{profile_id}.json"] = json.dumps(
        profile, ensure_ascii=False, indent=2, sort_keys=True
    ).encode() + b"\n"
    for name in ("healthy-baseline.json", "legacy-metric-baseline.json", "provenance.json"):
        source = artifact_dir / name
        if source.is_file():
            files[str(source.relative_to(root))] = source.read_bytes()
        elif name != "provenance.json":
            raise ValueError(f"missing prepared profile artifact: {name}")
    baseline = json.loads(files[str(artifact_relative / "healthy-baseline.json")])
    services = set(profile["candidate_services"])
    if set(baseline["metric"]) != services or set(baseline["trace"]) != services:
        raise ValueError("profile candidate universe differs from healthy baseline")
    freeze = json.loads(files["ml/models/m13/freeze-manifest.json"])
    for name, expected in freeze["models"].items():
        actual = hashlib.sha256(files[f"ml/models/m13/{name}"]).hexdigest()
        if actual != expected:
            raise ValueError(f"sealed model checksum mismatch: {name}")
    manifest = {
        "kind": "PORTABLE_DIAGNOSTIC_APPLICATION",
        "profile_id": profile_id,
        "model_version": freeze["version"],
        "files_sha256": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "x", compression=ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            archive.writestr(name, data)
        archive.writestr("bundle-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {"output": str(output), "profile_id": profile_id, "files": len(files)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a portable RCA application for one prepared system")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.profile, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
