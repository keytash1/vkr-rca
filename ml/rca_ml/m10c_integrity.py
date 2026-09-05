"""Read-only integrity guard for the frozen M10A research and M10B demo."""

from __future__ import annotations

import hashlib
from pathlib import Path


FROZEN_SHA256 = {
    "docs/m10a-protocol.md": "b5e4a15ec9dd68806da9a11b670fed2665b9458dda85c5f3ed4da4c6e8e8af7d",
    "docs/m10a-results.md": "7661f11ac41e1c93b63a17f69fc7121714336afa000baa7c91aa7a20643cf2be",
    "docs/thesis-claims.md": "5f648c02c69a553dc40c2b748627a819a494b4210a742f0f6960744ab71e2dd8",
    "ml/models/m10a-freeze/evaluation.json": "eb14e3fd02ebb9fe55d97c3852075114d103493586dd02e8ca40988caeac6db4",
    "ml/models/m10a-freeze/integrity-manifest.json": "7e152bdb19301bdd9cd0e38377cdd22a990b507e4c9b86f95610d768d62928c7",
    "docs/m10b-demo-cases.md": "d492ea4d9be69f3ad496a19349829e4ddee933e4ea19f2a13114ba295559ba49",
    "docs/demo-guide.md": "33dc8d623ddd642860d405ee92ba6b23c02208af4e69052a22f8c6b5200bf631",
    "docs/defense-demo-script.md": "eea52dad938aecbe944f680baf357ee62093e361d36056558f2fb56c96e8d3b7",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_frozen(root: Path) -> dict:
    actual = {name: sha256_file(root / name) for name in FROZEN_SHA256}
    mismatches = {
        name: {"expected": FROZEN_SHA256[name], "actual": actual[name]}
        for name in FROZEN_SHA256
        if actual[name] != FROZEN_SHA256[name]
    }
    return {
        "m10a_commit": "c83c4e5df98aef2dffadcd7d8943f5624caae002",
        "m10b_commit": "5e8bd3523c1e192296a58e69fdcc10f328b5f233",
        "checked_files": len(actual),
        "ok": not mismatches,
        "mismatches": mismatches,
        "sha256": actual,
    }

