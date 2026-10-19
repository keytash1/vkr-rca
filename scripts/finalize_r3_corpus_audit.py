"""Seal this audit's own summaries; never rewrites an older research manifest."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/product-research/r3-new-corpus-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    acquisition = read(OUT / "acquisition.json")
    semantics = read(OUT / "semantics.json")
    overlap = read(OUT / "overlap-and-protected.json")
    assert len(acquisition["selection"]) == 3 and len(acquisition["files"]) == 30
    assert acquisition["downloaded_bytes"] == sum(f["bytes"] for f in acquisition["files"]) <= 100 * 1024**2
    assert acquisition["oracle_files_downloaded"] == []
    assert acquisition["fits"] == acquisition["inferences"] == acquisition["llm_calls"] == 0
    assert len(semantics["profiles"]) == 3
    assert all(p["normal_precedes_abnormal"] for p in semantics["profiles"])
    assert all(p["verdict"] == "ADAPTER_REQUIRED_NOT_READY_FOR_TRAINING" for p in semantics["profiles"])
    assert all(p["overlap_trace_ids"] == 0 for p in overlap["historical"].values())
    for relative, expected in overlap["protected_assets_sha256"].items():
        assert sha(ROOT / relative) == expected, relative
    for item in acquisition["files"]:
        path = ROOT / "external-data/r3-openrca2-schema-v1" / item["path"]
        assert path.stat().st_size == item["bytes"] and sha(path) == item["sha256"], item["path"]
    paths = [
        "docs/R3_NEW_CORPUS_PROTOCOL.md", "docs/product-research/R3_NEW_CORPUS_RESULTS.md",
        "docs/PLAN_PRODUCT_ITERATION_2.md", "docs/HANDOFF_PRODUCT_NEXT_ITERATION.md",
        "docs/PROGRESS_PRODUCT_R3.md", "ml/requirements-r3-audit.txt",
        "scripts/r3_new_corpus_audit.py", "scripts/test_r3_new_corpus_audit.py",
        "scripts/finalize_r3_corpus_audit.py",
        *[f"docs/product-research/r3-new-corpus-v1/{name}.json"
          for name in ("acquisition", "schema", "semantics", "overlap-and-protected")],
    ]
    assert not any(p.startswith(("external-data/", "reports/", ".rca-private/")) for p in paths)
    manifest = {"scope": "Research-only new-corpus audit; no telemetry rows, weights, or DOCX",
                "verdict": "ADAPTER_REQUIRED_NOT_READY_FOR_TRAINING", "ranking_fits": 0,
                "ranking_inferences": 0, "llm_calls": 0,
                "older_manifest_scope": "R3_ML_MANIFEST.json is the snapshot at research commit 12b89d4; current plans can advance",
                "sha256": {p: sha(ROOT / p) for p in paths}}
    path = ROOT / "docs/product-research/R3_NEW_CORPUS_MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"verified_files": len(paths), "bytes": sum((ROOT / p).stat().st_size for p in paths),
                      "protected_assets_unchanged": True, "product_runtime_changes": 0}))


if __name__ == "__main__":
    main()
