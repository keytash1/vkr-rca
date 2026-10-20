"""Explicit experiment-free source composition for a separate product repo.

Creates a NEW directory; never modifies an existing checkout, publishes or
copies Git history. Every copied byte is hashed. Credentials, datasets, labels,
acceptance transcripts, controllers and Word documents are excluded by design.
"""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PRODUCT_FILES = (
    "Dockerfile", "Dockerfile.dockerignore", "requirements.txt", "requirements-assistant.txt",
    "runtime-pyproject.toml", "build_bundle.py", "verify_bundle.py", "export_source.py",
    "README.md", "WORKSPACE.md", "compose.yml", "compose.workspace.yml", "compose.assistant.yml",
    "LICENSE", "NOTICE", "THIRD_PARTY.md", "THIRD_PARTY_NOTICES", "SOURCE_README.md", "ASSISTANT_CONNECTION.md", "COMPATIBILITY.md", "ARCHITECTURE.md", "RELEASE.md", "source-ci.yml",
)
TESTS = (
    "analysis_requests", "assistant_auth", "assistant_budget", "assistant_contract",
    "assistant_privacy", "assistant_provider", "assistant_runner", "assistant_supervisor",
    "assistant_tools", "assistant_workflow", "evidence_catalog", "investigations",
    "profile_contract", "profile_onboarding", "profile_setup", "runbook_corpus",
    "trace_adapters", "trace_evidence", "workspace_http", "workspace_store", "product_http", "baseline_applicability", "incident_context", "http_observations",
)


def export(root, output):
    root, output = root.resolve(), output.absolute()
    if output.exists() or output.is_symlink():
        raise FileExistsError("source destination must be new")
    spec = importlib.util.spec_from_file_location("product_builder",root/"deploy/product/build_bundle.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    files = {name:root/name for name in builder.MODEL_FILES}
    for name in builder.RUNTIME_MODULES:
        path = f"ml/rca_ml/{name}.py"
        files[path] = root/path
    for name in builder.APPLICATION_MODULES + builder.WORKSPACE_MODULES + builder.PROVIDER_MODULES:
        path = f"cmd/thesis_demo/{name}.py"
        files[path] = root/path
    for name in TESTS:
        path = f"cmd/thesis_demo/test_{name}.py"
        files[path] = root/path
    files["cmd/thesis_demo/profile_test_fixtures.py"] = root/"cmd/thesis_demo/profile_test_fixtures.py"
    files["cmd/thesis_demo/telemetry_test_fixtures.py"] = root/"cmd/thesis_demo/telemetry_test_fixtures.py"
    files["cmd/thesis_demo/test_workspace_ui_restore.mjs"] = root/"cmd/thesis_demo/test_workspace_ui_restore.mjs"
    files["cmd/thesis_demo/test_baseline_ui.mjs"] = root/"cmd/thesis_demo/test_baseline_ui.mjs"
    files["cmd/thesis_demo/test_context_ui.mjs"] = root/"cmd/thesis_demo/test_context_ui.mjs"
    files["cmd/thesis_demo/test_http_ui.mjs"] = root/"cmd/thesis_demo/test_http_ui.mjs"
    for path in sorted((root/"cmd/thesis_demo/static").iterdir()):
        if path.is_file():
            files[str(path.relative_to(root))] = path
    for name in PRODUCT_FILES:
        files["deploy/product/"+name] = root/"deploy/product"/name
    for name in ("LICENSE", "NOTICE", "THIRD_PARTY.md", "THIRD_PARTY_NOTICES"):
        files[name] = root/"deploy/product"/name
    files["README.md"] = root/"deploy/product/SOURCE_README.md"
    files[".github/workflows/product.yml"] = root/"deploy/product/source-ci.yml"
    files["ml/pyproject.toml"] = root/"deploy/product/runtime-pyproject.toml"
    files["requirements-dev.txt"] = root/"requirements-dev.txt"
    # Operator-only research tools are source material, never runtime modules.
    for name in ("loki_context_probe.py", "test_loki_context_probe.py", "docker_context_collector.py", "test_docker_context_collector.py"):
        files["tools/"+name] = root/"tools"/name
    for name in ("ITERATION_2.md", "BASELINE_APPLICABILITY.md", "CONTEXT_PROBE.md", "LOKI_ACCEPTANCE.md", "HTTP_OBSERVATIONS.md", "DOCKER_CONTEXT.md", "RUNTIME_HISTORY_ACCEPTANCE.md"):
        files["docs/"+name] = root/"docs"/name
    files["deploy/runbooks/basic-investigation.json"] = root/"deploy/runbooks/basic-investigation.json"
    files["deploy/profiles/examples/new-system.template.json"] = root/"deploy/profiles/examples/new-system.template.json"
    onboarding = root/"docs/product-architecture/ONBOARDING.md"
    files["docs/ONBOARDING.md"] = onboarding if onboarding.is_file() else root/"docs/ONBOARDING.md"
    files["docs/WORKSPACE.md"] = root/"deploy/product/WORKSPACE.md"
    files["docs/ASSISTANT_CONNECTION.md"] = root/"deploy/product/ASSISTANT_CONNECTION.md"
    files["docs/ARCHITECTURE.md"] = root/"deploy/product/ARCHITECTURE.md"
    files["RELEASE.md"] = root/"deploy/product/RELEASE.md"
    files["requirements-assistant.txt"] = root/"deploy/product/requirements-assistant.txt"
    # Source paths are fixed above, but still refuse symlinks and escapes. No
    # output exists until every source is checked and read successfully.
    payload = {}
    for name, source in files.items():
        if source.is_symlink() or not source.resolve().is_relative_to(root) or not source.is_file():
            raise ValueError("unexpected source: "+name)
        payload[name] = source.read_bytes()
    payload[".gitignore"] = b".rca-private/\n.venv*/\n__pycache__/\n*.egg-info/\n.ruff_cache/\ndeploy/profiles/*.json\ndeploy/profiles/artifacts/\n"
    output.mkdir(parents=True)
    for name, data in payload.items():
        destination = output/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open("xb") as target:
            target.write(data)
    commit = subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    manifest = {"kind":"EXPLICIT_PRODUCT_SOURCE_SNAPSHOT","origin_commit":commit,
        "worktree_bytes_are_authoritative":True,"credentials_included":False,"research_corpus_included":False,
        "files_sha256":{name:hashlib.sha256(data).hexdigest() for name,data in sorted(payload.items())}}
    with (output/"source-manifest.json").open("x") as target:
        json.dump(manifest,target,sort_keys=True,indent=2)
        target.write("\n")
    return {"output":str(output),"files":len(payload),"source_manifest_sha256":hashlib.sha256((output/"source-manifest.json").read_bytes()).hexdigest()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(ROOT,args.output),indent=2))
