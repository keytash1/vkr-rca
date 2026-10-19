"""Bounded, non-executing inventory of the official AnoMod archive."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
import csv
import io
from pathlib import Path, PurePosixPath
import time
import urllib.request
import zipfile
import argparse

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "external-data/r3-fresh-red-v1"
OUT = ROOT / "docs/product-research/r3-fresh-red-v1"
URL = "https://zenodo.org/api/records/18342898/files/AnoMod.zip/content"
SIZE = 201917396
MD5 = "30c5835190c3550c5efc34d6be4f9238"


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    archive = CACHE / "AnoMod.zip"
    if not archive.exists():
        partial = CACHE / "AnoMod.zip.part"
        started = time.monotonic()
        with urllib.request.urlopen(URL, timeout=30) as source, partial.open("xb") as dest:
            count = 0
            while block := source.read(1024 * 1024):
                count += len(block)
                if count > SIZE or time.monotonic() - started > 300:
                    raise ValueError("registered download budget exceeded")
                dest.write(block)
        if count != SIZE:
            raise ValueError("archive size mismatch")
        partial.rename(archive)
    digest = hashlib.md5(usedforsecurity=False)
    sha = hashlib.sha256()
    with archive.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
            sha.update(block)
    if archive.stat().st_size != SIZE or digest.hexdigest() != MD5:
        raise ValueError("archive checksum mismatch")
    with zipfile.ZipFile(archive) as source:
        inventory = []
        categories = Counter()
        total_bytes = 0
        member_count = 0
        for item in source.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in item.filename:
                raise ValueError("unsafe archive member")
            member_count += 1
            total_bytes += item.file_size
            categories["/".join(path.parts[:2])] += 1
            if len(path.parts) > 1 and path.parts[1] in {"metric_data", "trace_data"}:
                inventory.append({"path": item.filename, "bytes": item.file_size,
                                  "compressed_bytes": item.compress_size, "crc32": item.CRC})
    dump(OUT / "inventory.json", {"role": "SOURCE_INVENTORY_ONLY", "url": URL,
        "license": "CC-BY-4.0", "bytes": SIZE, "md5": MD5, "sha256": sha.hexdigest(),
        "protocol_sha256": hashlib.sha256((ROOT / "docs/R3_FRESH_RED_PROTOCOL.md").read_bytes()).hexdigest(),
        "all_member_count": member_count, "all_uncompressed_bytes": total_bytes,
        "directory_counts": dict(sorted(categories.items())), "members": inventory})
    print(json.dumps({"members": member_count, "archive_bytes": SIZE,
                      "uncompressed_bytes": total_bytes,
                      "sha256": sha.hexdigest()}, indent=2), flush=True)


def discovery() -> None:
    inventory = json.loads((OUT / "inventory.json").read_text())
    selected = {}
    for system in ("SN_data", "TT_data"):
        cases = sorted({PurePosixPath(m["path"]).parts[2] for m in inventory["members"]
                        if m["bytes"] and m["path"].startswith(system + "/metric_data/")})
        normal = [c for c in cases if c.lower().startswith("normal")]
        abnormal = [c for c in cases if c not in normal]
        selected[system] = [normal[0], abnormal[0]]
    registration = OUT / "discovery-registration.json"
    chosen = {"role": "DISCOVERY_ONLY_NOT_TEST", "metric_cases": selected,
              "reason": "one normal and first lexicographic abnormal per system",
              "full_read_max_file_bytes": 20_000_000, "sample_rows": 200}
    if registration.exists():
        if json.loads(registration.read_text()) != chosen:
            raise ValueError("discovery selection changed")
    else:
        dump(registration, chosen)
    rows = []
    with zipfile.ZipFile(CACHE / "AnoMod.zip") as source:
        for item in inventory["members"]:
            path = PurePosixPath(item["path"])
            if not item["bytes"] or path.suffix != ".csv" or path.parts[1] != "metric_data":
                continue
            if path.parts[2] not in selected[path.parts[0]]:
                continue
            result = {"path": item["path"], "bytes": item["bytes"]}
            with source.open(item["path"]) as stream:
                text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                result["columns"] = reader.fieldnames
                sample = []
                for row in reader:
                    sample.append(row)
                    if len(sample) == 200:
                        break
                result["prefix_rows"] = len(sample)
                result["prefix_metric_names"] = sorted({r.get("metric_name", "") for r in sample} - {""})
                result["service_labels"] = sorted({r.get("service", r.get("container_label_com_docker_compose_service", "")) for r in sample} - {""})
                result["prefix_timestamps"] = [sample[0].get("timestamp"), sample[-1].get("timestamp")] if sample else []
                result["scope"] = "PREFIX_ONLY_NOT_FULL_FILE"
                if item["bytes"] <= 20_000_000:
                    # Full small-member checksum, not a parse of other modalities.
                    data = source.read(item["path"])
                    result["sha256"] = hashlib.sha256(data).hexdigest()
            rows.append(result)
    dump(OUT / "discovery-schema.json", {"role": "DISCOVERY_ONLY", "tables": rows})
    print(json.dumps({"selected": selected, "tables": len(rows)}, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", default="inventory", choices=("inventory", "discovery"))
    main() if parser.parse_args().stage == "inventory" else discovery()
