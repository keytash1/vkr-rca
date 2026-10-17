"""Fresh runtime image -> real sources -> persistent B-card, without LLM.

Only the isolated teaching Petclinic network is used. No Docker socket or
credentials inside the product. Leaves this named dev container available for
inspection; refuses to replace an existing one or overwrite acceptance files.
"""

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPCookieProcessor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from accept_onboarding_v3 import semantic_map
from accept_live_profile import verify_healthy_workload


def docker(*args, timeout=150):
    return subprocess.check_output(
        ["docker", *args], text=True, timeout=timeout
    ).strip()


def save(path, value):
    with path.open("x") as target:
        target.write(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--port", type=int, default=18224)
    parser.add_argument("--image", choices=["vkr-rca/diagnostic-intelligent:dev-r2", "vkr-rca/diagnostic-intelligent:dev-r2-current", "vkr-rca/diagnostic-intelligent:source-r9", "vkr-rca/diagnostic-intelligent:source-r11"], default="vkr-rca/diagnostic-intelligent:dev-r2-current")
    parser.add_argument("--named-workspace", action="store_true", help="New Docker-managed private volume; never replace an existing volume")
    args = parser.parse_args()
    if not args.run or any(
        c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.run
    ):
        parser.error("invalid run name")
    if not 18224 <= args.port <= 18229:
        parser.error("only reserved dev acceptance ports 18224..18229")
    output = ROOT / "docs/product-acceptance/intelligent-r2" / args.run
    private = ROOT / ".rca-private/container-acceptance" / args.run
    name = "rca-intelligent-" + args.run
    if output.exists() or private.exists():
        parser.error("run directories must be new")
    if docker("ps", "-a", "--filter", f"name=^/{name}$", "--format", "{{.Names}}"):
        parser.error("refusing to replace an existing container")
    volume = name + "-workspace"
    if args.named_workspace and docker("volume", "ls", "--filter", f"name=^{volume}$", "--format", "{{.Name}}"):
        parser.error("refusing to reuse an existing volume")
    networks = docker(
        "network",
        "ls",
        "--filter",
        "label=com.docker.compose.project=rca-petclinic-acceptance",
        "--format",
        "{{.Name}}",
    ).splitlines()
    if len(networks) != 1 or not networks[0].startswith("rca-petclinic-acceptance"):
        raise RuntimeError("exact isolated teaching network not found")
    output.mkdir(parents=True)
    profiles, workspace = private / "profiles", private / "workspace"
    profiles.mkdir(parents=True, mode=0o700)
    workspace.mkdir(mode=0o700)
    raw = json.loads(
        (
            ROOT / "deploy/acceptance/petclinic/container-profile.template.json"
        ).read_text()
    )
    raw["version"] = args.run
    raw["artifact_dir"] = "deploy/profiles/artifacts/" + args.run
    raw["traces"]["api"] = "jaeger-v3-json"
    raw["metrics"]["semantic_map"] = semantic_map()
    save(profiles / "petclinic.json", raw)
    end = int(time.time()) // 2 * 2 - 60
    start = end - 130
    health = {}
    for counter in ("started", "succeeded", "failed", "dropped"):
        query = f"sum(increase(acceptance_requests_{counter}_total[130s]))"
        with urlopen(
            "http://127.0.0.1:19991/api/v1/query?"
            + urlencode({"query": query, "time": end}),
            timeout=15,
        ) as response:
            health[counter] = json.load(response)
    save(output / "workload-health.json", health)
    verified = verify_healthy_workload(health)
    image = args.image
    common = [
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--network",
        networks[0],
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,size=64m",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--pids-limit",
        "128",
        "--memory",
        "768m",
    ]
    from datetime import datetime, timezone

    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    provenance = json.loads(
        docker(
            "run",
            "--rm",
            *common,
            "--mount",
            f"type=bind,source={profiles},target=/opt/rca/deploy/profiles",
            image,
            "python",
            "cmd/thesis_demo/profile_setup.py",
            "--root",
            "/opt/rca",
            "--profile",
            "deploy/profiles/petclinic.json",
            "--start",
            iso(start),
            "--end",
            iso(end),
        )
    )
    save(output / "baseline-provenance.json", provenance)
    if args.named_workspace:
        # Only this new run's teaching config: no credentials, no private DB.
        for item in profiles.rglob("*"):
            item.chmod(0o755 if item.is_dir() else 0o644)
        profiles.chmod(0o755)
        docker("volume", "create", "--label", "rca.acceptance=" + args.run, volume)
    runtime_common = list(common)
    if args.named_workspace:
        runtime_common[1] = "10001:10001"
    identifier = docker(
        "run",
        "-d",
        "--name",
        name,
        *runtime_common,
        "-p",
        f"127.0.0.1:{args.port}:18100",
        "--mount",
        f"type=bind,source={profiles},target=/opt/rca/deploy/profiles,readonly",
        "--mount",
        (f"type=volume,source={volume},target=/var/lib/rca-workspace" if args.named_workspace else
         f"type=bind,source={workspace},target=/var/lib/rca-workspace"),
        image,
        "python",
        "cmd/thesis_demo/server.py",
        "--root",
        "/opt/rca",
        "--host",
        "0.0.0.0",
        "--unsafe-public",
        "--port",
        "18100",
        "--workspace-dir",
        "/var/lib/rca-workspace",
        "--workspace-origin",
        f"http://127.0.0.1:{args.port}",
    )
    client = build_opener(HTTPCookieProcessor(CookieJar()))
    base = f"http://127.0.0.1:{args.port}"
    csrf = None

    def api(path, payload=None):
        headers = {"Origin": base}
        if payload is not None:
            headers |= {"Content-Type": "application/json", "X-RCA-CSRF": csrf or ""}
        with client.open(
            Request(
                base + path,
                data=json.dumps(payload).encode() if payload is not None else None,
                headers=headers,
            ),
            timeout=125,
        ) as response:
            return json.load(response)

    deadline = time.monotonic() + 60
    while True:
        try:
            capabilities = api("/api/v2/workspace")
            break
        except (OSError, HTTPError, URLError):
            if time.monotonic() >= deadline:
                raise RuntimeError("new container did not become ready")
            time.sleep(0.5)
    csrf = capabilities["csrf_token"]
    if capabilities["assistant_configured"]:
        raise RuntimeError("this acceptance must have no external provider configured")
    result = api(
        "/api/analyze",
        {"profile_id": "petclinic", "start_unix": end - 30, "end_unix": end},
    )
    save(output / "live-result.json", result)
    snapshot = api(f"/api/v2/analyses/{result['result_id']}/snapshot")
    save(output / "snapshot.json", snapshot)
    cached = api(
        "/api/analyze",
        {"profile_id": "petclinic", "start_unix": end - 30, "end_unix": end},
    )
    save(output / "cached-result.json", cached)
    job = api(
        "/api/v2/investigations",
        {
            "analysis_id": result["result_id"],
            "mode": "B",
            "question": "Проверка сохранения учебного расследования без заданного отказа.",
            "idempotency_key": args.run,
        },
    )
    while job["state"] in {"queued", "running"}:
        if time.monotonic() >= deadline:
            raise RuntimeError("B worker did not complete")
        time.sleep(0.1)
        job = api("/api/v2/investigations/" + job["id"])
    save(output / "investigation.json", job)
    refreshed = api(
        "/api/analyze",
        {
            "profile_id": "petclinic",
            "start_unix": end - 30,
            "end_unix": end,
            "force_refresh": True,
        },
    )
    save(output / "refreshed-result.json", refreshed)
    # Public container configuration only; never export environment or mounts
    # wholesale because future invocations may contain credential references.
    inspection = json.loads(docker("inspect", name))[0]
    config = {
        "read_only_root": inspection["HostConfig"]["ReadonlyRootfs"],
        "cap_drop": inspection["HostConfig"]["CapDrop"],
        "security_opt": inspection["HostConfig"]["SecurityOpt"],
        "ports": inspection["NetworkSettings"]["Ports"],
        "image_id": inspection["Image"],
        "no_docker_socket": all(
            m["Destination"] != "/var/run/docker.sock" for m in inspection["Mounts"]
        ),
    }
    save(output / "container-safety.json", config)
    summary = {
        "purpose": "CLEAN_CONTAINER_REAL_SOURCES_NO_LLM_NOT_ACCURACY",
        "container_name": name,
        "container_id": identifier,
        "workspace_mount": "new_docker_named_volume" if args.named_workspace else "host_bind",
        "base_url": base,
        "healthy_workload": verified,
        "candidate_count": result["candidate_count"],
        "baseline_state": result["source_status"]["baseline_binding"]["state"],
        "workspace_saved": result.get("workspace_status") == "saved",
        "B_state": job["state"],
        "same_cached_result_id": cached["result_id"] == result["result_id"],
        "cache_hit": cached["delivery"]["cache_hit"],
        "refresh_new_result_id": refreshed["result_id"] != result["result_id"],
        "old_snapshot_unchanged": api(
            f"/api/v2/analyses/{result['result_id']}/snapshot"
        )
        == snapshot,
        "accepted_18220_untouched": True,
        "core_readiness": api("/healthz"),
    }
    save(output / "summary.json", summary)
    if not all(
        (
            summary["workspace_saved"],
            summary["B_state"] == "completed",
            summary["cache_hit"],
            summary["same_cached_result_id"],
            summary["refresh_new_result_id"],
            summary["old_snapshot_unchanged"],
        )
    ):
        raise RuntimeError("acceptance gate failed; inspect the retained proof")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
