"""Restart ONLY our explicitly receipted dev container; verify durable state.

No model calls or telemetry recollection requests. Never touches accepted18220.
Does not claim packet-level proof of zero source I/O; routes are independently
tested not to collect. Session cookies/CSRF never enter the receipt.
"""

import argparse
from http.cookiejar import CookieJar
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("new output directory required")
    expected = json.loads((args.receipt/"summary.json").read_text())
    name = expected["container_name"]
    base = expected["base_url"]
    if (not name.startswith(("rca-intelligent-container-workspace-", "rca-intelligent-container-actions-")) or
            base not in {f"http://127.0.0.1:{p}" for p in range(18224,18230)}):
        parser.error("only named isolated product acceptance")
    actual = subprocess.check_output(["docker","inspect","--format","{{.Id}}",name],text=True,timeout=10).strip()
    if actual != expected["container_id"]:
        raise RuntimeError("container identity changed")
    investigation_id = json.loads((args.receipt/"investigation.json").read_text())["id"]
    client = build_opener(HTTPCookieProcessor(CookieJar()))

    def get(path,opener=None):
        with (opener or client).open(base+path,timeout=10) as response:
            return json.load(response)

    get("/api/v2/workspace")
    record = get("/api/v2/investigations/"+investigation_id)
    snapshot_path = "/api/v2/analyses/"+record["analysis_id"]+"/snapshot"
    snapshot = get(snapshot_path)
    started = time.monotonic()
    subprocess.check_output(["docker","restart","--time","10",name],text=True,timeout=30)
    deadline = time.monotonic()+60
    while True:
        try:
            if get("/healthz")["status"]=="ready":
                break
        except OSError:
            pass
        if time.monotonic()>deadline:
            raise RuntimeError("restarted core not ready")
        time.sleep(.5)
    stale_status = None
    try:
        get("/api/v2/investigations/"+investigation_id)
    except HTTPError as error:
        stale_status = error.code
        error.close()
    fresh = build_opener(HTTPCookieProcessor(CookieJar()))
    capability = get("/api/v2/workspace",fresh)
    after_record = get("/api/v2/investigations/"+investigation_id,fresh)
    after_snapshot = get(snapshot_path,fresh)
    summary = {"purpose":"REAL_CONTAINER_RESTART_DURABILITY_NOT_DIAGNOSTIC_ACCURACY",
        "container":name,"container_id":actual,"elapsed_seconds":time.monotonic()-started,
        "investigation_id":investigation_id,"analysis_id":record["analysis_id"],
        "snapshot_exact":after_snapshot==snapshot,"record_exact":after_record==record,
        "old_session_rejected":stale_status==401,"new_session_works":True,
        "recovered_jobs":capability["recovered_jobs"],"inference_requests_sent":0,
        "telemetry_analysis_requests_sent":0,"network_capture_performed":False,
        "accepted_18220_untouched":True}
    args.output.mkdir(parents=True)
    for filename,value in (("before-snapshot.json",snapshot),("after-snapshot.json",after_snapshot),
        ("before-investigation.json",record),("after-investigation.json",after_record),("summary.json",summary)):
        with (args.output/filename).open("x") as target:
            json.dump(value,target,ensure_ascii=False,sort_keys=True,indent=2)
            target.write("\n")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    if not all(summary[k] for k in ("snapshot_exact","record_exact","old_session_rejected")):
        raise SystemExit(1)


if __name__=="__main__":
    main()
