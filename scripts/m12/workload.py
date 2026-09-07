#!/usr/bin/env python3
"""Seeded Hotel Reservation workload using only Python's standard library."""

from __future__ import annotations

import argparse
import http.client
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PATHS = {
    "hotels": ("/hotels", {"inDate": "2015-04-09", "outDate": "2015-04-10", "lat": "38.0235", "lon": "-122.095", "locale": "en", "currency": "USD"}),
    "recommendations": ("/recommendations", {"require": "dis", "lat": "38.0235", "lon": "-122.095"}),
    "login": ("/user", {"username": "Cornell_1", "password": "1111111111"}),
    "reservation": ("/reservation", {"inDate": "2015-04-09", "outDate": "2015-04-10", "lat": "38.0235", "lon": "-122.095", "hotelId": "1", "customerName": "Cornell_1", "username": "Cornell_1", "password": "1111111111", "number": "1"}),
}


def run(config: dict, duration: float) -> dict:
    rng = random.Random(int(config["seed"]))
    names, weights = zip(*config["mix"].items())
    interval = 1 / float(config["requests_per_second"])
    deadline, next_at = time.monotonic() + duration, time.monotonic()
    result = {"requests": 0, "success": 0, "errors": 0, "by_path": {name: 0 for name in names}}
    while time.monotonic() < deadline:
        name = rng.choices(names, weights=weights, k=1)[0]
        path, query = PATHS[name]
        method = "POST" if name in {"login", "reservation"} else "GET"
        request = urllib.request.Request(config["frontend_url"] + path + "?" + urllib.parse.urlencode(query), headers={"X-M12-Workload": "locked-v1"}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                result["success"] += int(200 <= response.status < 500)
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
            result["errors"] += 1
        result["requests"] += 1
        result["by_path"][name] += 1
        next_at += interval
        time.sleep(max(0, next_at - time.monotonic()))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("deploy/m12/workload.json"))
    parser.add_argument("--duration", type=float, required=True)
    args = parser.parse_args()
    print(json.dumps(run(json.loads(args.config.read_text()), args.duration), sort_keys=True))
