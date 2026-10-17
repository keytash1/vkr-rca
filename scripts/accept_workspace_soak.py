"""Bounded real-source runtime soak on our named disposable product container.

No LLM calls, faults, Docker socket mount or accepted-18220 changes. Measures
one workload/installation, not an SLA or a proof that memory can never leak.
"""

import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPCookieProcessor


def save(path, value):
    with path.open("x") as target:
        json.dump(value, target, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        target.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if (not args.container.startswith("rca-intelligent-container-")
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.container)
            or not 18224 <= args.port <= 18229 or args.output.exists()):
        parser.error("only a new receipt and named isolated development product container")
    args.output.mkdir(parents=True)
    base = f"http://127.0.0.1:{args.port}"
    client = build_opener(HTTPCookieProcessor(CookieJar()))

    def api(path, body=None):
        try:
            with client.open(Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                headers={"Origin":base,"Content-Type":"application/json"}),timeout=125) as response:
                return response.status,json.load(response)
        except HTTPError as error:
            return error.code,json.load(error)

    started = time.monotonic()
    save(args.output / "design.json", {"samples":60,"sample_period_seconds":15,
        "global_wall_budget_seconds":1200,"profile":"petclinic","force_refresh_then_identical":True,
        "llm_calls":0,"purpose":"BOUNDED_REAL_SOURCE_ENGINEERING_SOAK_NOT_SLA"})
    records = []
    for index in range(60):
        if time.monotonic()-started > 1200:
            break
        end = int(time.time())-30
        body = {"profile_id":"petclinic","start_unix":end-30,"end_unix":end,"force_refresh":True}
        before = time.monotonic()
        status,value = api("/api/analyze",body)
        record = {"number":index+1,"recorded_at_unix":time.time(),"http_status":status,
            "elapsed_seconds":time.monotonic()-before}
        if status == 200:
            repeated_status,repeated = api("/api/analyze",body|{"force_refresh":False})
            record.update(result_id=value["result_id"],candidate_count=value["candidate_count"],
                workspace_status=value.get("workspace_status"),source_status=value["source_status"],
                repeated_http_status=repeated_status,
                same_cached_result=repeated.get("result_id")==value["result_id"],
                cache_hit=repeated.get("delivery",{}).get("cache_hit",False))
        else:
            record["error_code"] = value.get("code")
        raw = subprocess.check_output(["docker","stats","--no-stream","--format","{{json .}}",args.container],text=True,timeout=15)
        stats = json.loads(raw)
        record["container_stats"] = {k:stats[k] for k in ("MemUsage","MemPerc","CPUPerc","PIDs")}
        records.append(record)
        save(args.output / f"sample-{index+1:03d}.json", record)
        print(json.dumps({"sample":index+1,"http":status,"cache":record.get("cache_hit"),"memory":stats["MemUsage"]}),flush=True)
        remaining = started + (index+1)*15 - time.monotonic()
        if remaining > 0 and index < 59:
            time.sleep(remaining)
    summary = {"assigned_samples":60,"recorded_samples":len(records),
        "wall_seconds":time.monotonic()-started,"llm_calls":0,
        "all_requests_successful":len(records)==60 and all(r["http_status"]==200 for r in records),
        "all_snapshots_saved":all(r.get("workspace_status")=="saved" for r in records),
        "all_repeats_cached":all(r.get("cache_hit") and r.get("same_cached_result") for r in records),
        "first_memory":records[0]["container_stats"]["MemUsage"] if records else None,
        "last_memory":records[-1]["container_stats"]["MemUsage"] if records else None,
        "not_a_long_term_leak_or_sla_proof":True}
    save(args.output / "summary.json",summary)
    print(json.dumps(summary),flush=True)
    if not all(summary[k] for k in ("all_requests_successful","all_snapshots_saved","all_repeats_cached")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
