"""One clean export/bundle check for R3-J; never runs an experiment."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT.parent / 'rca-workbench'
OUT = ROOT / 'artifacts/r3-http-observations-delivery-v1'
sys.path.insert(0, str(PRODUCT / 'deploy/product'))
from export_source import export
from build_bundle import build


def run():
    OUT.mkdir(exist_ok=False)
    source = OUT / 'source'
    exported = export(PRODUCT, source)
    previous = ROOT / 'artifacts/r3-http-observations-v2/source'
    profile_relative = Path('deploy/profiles/system.json')
    profile = json.loads((previous / profile_relative).read_text())
    shutil.copytree(previous / profile['artifact_dir'], source / profile['artifact_dir'])
    shutil.copy2(previous / profile_relative, source / profile_relative)
    bundle = OUT / 'product.zip'
    built = build(source, source / profile_relative, bundle, with_workspace=True)
    with ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert 'cmd/thesis_demo/http_observations.py' in names
        assert 'docs/HTTP_OBSERVATIONS.md' in names
        assert not any(name.startswith(('external-data/', 'ml/models/m14', '.rca-private/')) for name in names)
        archive.extractall(OUT / 'bundle')
    result = subprocess.run([sys.executable, str(OUT / 'bundle/verify_bundle.py'), '--root', str(OUT / 'bundle')],
        check=True, capture_output=True, text=True)
    env = dict(__import__('os').environ, PYTHONPATH=str(source / 'ml')+':'+str(source / 'cmd/thesis_demo'), PYTHONDONTWRITEBYTECODE='1')
    imports = subprocess.run([sys.executable, '-c',
        'import server,http_observations,assistant_context,profile_onboarding; from runtime_assets import EXPECTED_SHA256; '
        'from pathlib import Path; import hashlib; assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in EXPECTED_SHA256.items()); print("clean import and frozen hashes OK")'],
        cwd=source, env=env, check=True, capture_output=True, text=True)
    receipt = {'source_files':exported['files'], 'source_manifest_sha256':exported['source_manifest_sha256'],
        'bundle_files':built['files'], 'bundle_sha256':hashlib.sha256(bundle.read_bytes()).hexdigest(),
        'bundle_verification':result.stdout.strip(), 'clean_import':imports.stdout.strip(),
        'frozen_assets_unchanged':True, 'provider_calls':0, 'ranking_fits':0}
    with (OUT / 'receipt.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
    print(json.dumps(receipt))


if __name__ == '__main__':
    run()
