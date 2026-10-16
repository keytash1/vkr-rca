"""Check a transferred diagnostic bundle against its recorded file hashes.

This detects corruption or accidental file changes, not a maliciously
replaced bundle and manifest; trusted distribution still needs an external
digest or signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest_path = root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("kind") != "PORTABLE_DIAGNOSTIC_APPLICATION":
        raise ValueError("not a diagnostic application bundle")
    expected = manifest.get("files_sha256")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("bundle manifest has no file inventory")
    names = set(expected)
    if any(not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts
           for name in names):
        raise ValueError("bundle manifest contains an unsafe path")
    actual = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()
              and path != manifest_path}
    if actual != names:
        raise ValueError(f"bundle file inventory differs: missing={sorted(names - actual)}, extra={sorted(actual - names)}")
    for name, expected_hash in expected.items():
        path = root / name
        if path.is_symlink() or not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise ValueError(f"unsafe bundle file: {name}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(f"bundle checksum differs: {name}")
    return {"status": "ok", "profile_id": manifest["profile_id"], "files": len(names)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an extracted diagnostic application bundle")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
