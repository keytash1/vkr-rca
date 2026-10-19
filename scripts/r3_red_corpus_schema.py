"""Registered schema-only Eadro check. No values, labels, extraction or pickle."""
import csv
import hashlib
import json
from pathlib import Path
import time
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/r3-red-corpus-schema-v1'
URL = 'https://zenodo.org/records/7615394/files/TT%20Dataset.zip?download=1'
EXPECTED_SIZE = 48923113
EXPECTED_MD5 = '2d77861e4a025781e598d51866fd6f4e'


def run():
    OUT.mkdir(exist_ok=True)
    archive = OUT / 'TT-Dataset.zip'
    count = archive.stat().st_size if archive.exists() else 0
    started = time.monotonic()
    if not archive.exists():
        with urlopen(URL, timeout=30) as response, archive.open('xb') as output:
            while True:
                if time.monotonic()-started > 180:
                    raise TimeoutError('archive download exceeded registered budget')
                block = response.read(64*1024)
                if not block:
                    break
                count += len(block)
                if count > 64*1024*1024:
                    raise ValueError('archive exceeds registered byte budget')
                output.write(block)
    if count != EXPECTED_SIZE:
        raise ValueError('archive differs from published size')
    with archive.open('rb') as stream:
        checksum = hashlib.file_digest(stream, 'md5').hexdigest()
    if checksum != EXPECTED_MD5:
        raise ValueError('archive differs from published checksum')
    with archive.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    schemas = {}
    with ZipFile(archive) as zipped:
        files = zipped.infolist()
        if len(files) > 20000:
            raise ValueError('ZIP entry budget exceeded')
        selected = sorted((row for row in files if '/metrics/' in row.filename and row.filename.endswith('.csv')
                           and not row.filename.startswith('__MACOSX/') and not Path(row.filename).name.startswith('._')),
                          key=lambda row:row.filename)
        if not 0 < len(selected) <= 400:
            raise ValueError('CSV count outside registered budget')
        total = 0
        for row in selected:
            with zipped.open(row) as stream:
                header = stream.readline(4097)
            total += len(header)
            if len(header) > 4096 or total > 2*1024*1024:
                raise ValueError('CSV header budget exceeded')
            fields = tuple(next(csv.reader([header.decode('utf-8-sig').strip()])))
            schemas[fields] = schemas.get(fields, 0)+1
    receipt = {'role':'RAW_SCHEMA_AUDIT_NO_VALUES_OR_LABELS', 'source':URL, 'archive_bytes':count,
        'published_md5_verified':checksum, 'archive_sha256':sha, 'csv_files':len(selected),
        'header_bytes':total, 'schemas':[{'columns':list(fields), 'files':n} for fields,n in schemas.items()],
        'ranking_fits':0, 'ranking_predictions':0, 'labels_opened':False,
        'protocol_sha256':hashlib.sha256((ROOT / 'docs/R3_RED_CORPUS_SCHEMA_PROTOCOL.md').read_bytes()).hexdigest()}
    with (OUT / 'receipt.json').open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    run()
