"""Read one raw discovery datapack from a bounded author-archive stream."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "external-data/r3-raw-source-v1"
OUT = ROOT / "docs/product-research/r3-raw-source-v1"
URL = "https://zenodo.org/api/records/17105974/files/rcabench-absolute_anomaly.tar.gz/content"
FILES = {f"{period}_{kind}.parquet" for period in ("normal", "abnormal")
         for kind in ("metrics", "metrics_sum", "traces")}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


class BoundedReader:
    def __init__(self, stream, limit):
        self.stream, self.limit, self.received = stream, limit, 0

    def read(self, count):
        if count < 0:
            raise ValueError("unbounded read forbidden")
        if self.received + count > self.limit:
            raise ValueError("registered compressed byte budget reached")
        data = self.stream.read(count)
        self.received += len(data)
        return data


def fetch():
    receipt = OUT / "acquisition.json"
    if receipt.exists():
        prior = json.loads(receipt.read_text())
        if prior.get("status") == "complete":
            for row in prior["files"]:
                assert sha((CACHE / row["local_file"]).read_bytes()) == row["sha256"]
            print("reused verified discovery datapack")
            return
        raise ValueError("partial probe exists; inspect rather than overwrite")
    request = urllib.request.Request(URL, headers={"Range": "bytes=0-134217727"})
    record = {"source_url": URL, "role": "DISCOVERY_ONLY", "files": [],
              "oracle_files_read": [], "fits": 0, "inferences": 0, "status": "started"}
    chosen = None
    scanned = 0
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            reader = BoundedReader(response, 128 * 1024**2)
            with tarfile.open(fileobj=reader, mode="r|gz") as archive:
                for member in archive:
                    scanned += member.size
                    if scanned > 256 * 1024**2:
                        raise ValueError("registered uncompressed scan budget reached")
                    path = PurePosixPath(member.name)
                    if not member.isfile() or path.name not in FILES:
                        continue
                    if chosen is None:
                        chosen = str(path.parent)
                        record["source_datapack"] = chosen
                    if str(path.parent) != chosen:
                        continue
                    if member.size > 20 * 1024**2:
                        raise ValueError("discovery member too large")
                    stream = archive.extractfile(member)
                    data = stream.read(20 * 1024**2 + 1)
                    if len(data) != member.size:
                        raise ValueError("member size differs")
                    local = CACHE / "sample-001" / path.name
                    local.parent.mkdir(parents=True, exist_ok=True)
                    if local.exists():
                        raise ValueError("duplicate archive member")
                    local.write_bytes(data)
                    record["files"].append({"source_member": member.name,
                        "local_file": str(local.relative_to(CACHE)), "bytes": len(data), "sha256": sha(data)})
                    if len(record["files"]) == len(FILES):
                        record["status"] = "complete"
                        break
            record["compressed_bytes_read"] = reader.received
        if record["status"] != "complete":
            raise ValueError("discovery datapack incomplete")
    except Exception as error:
        record.update(status="stopped", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        record["uncompressed_member_bytes_scanned"] = scanned
        dump(receipt, record)
    print(json.dumps({k:v for k,v in record.items() if k != "files"}))


def schema():
    import pyarrow.parquet as pq
    receipt = json.loads((OUT / "acquisition.json").read_text())
    result = []
    for item in receipt["files"]:
        path = CACHE / item["local_file"]
        assert sha(path.read_bytes()) == item["sha256"]
        file = pq.ParquetFile(path)
        row = {"table": path.name, "rows": file.metadata.num_rows, "schema": str(file.schema_arrow)}
        result.append(row)
        print(row)
    dump(OUT / "schema.json", {"role": "DISCOVERY_ONLY", "tables": result})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fetch", "schema"))
    stage = parser.parse_args().stage
    fetch() if stage == "fetch" else schema()
