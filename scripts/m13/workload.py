#!/usr/bin/env python3
"""Deterministic Social Network registration and mixed compose-post workload."""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.parse
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "deploy/m13/workload.json").read_text())
if base_url := os.getenv("M13_FRONTEND_URL"):
    for name in tuple(key for key in CONFIG if key.endswith("_endpoint")):
        CONFIG[name] = base_url.rstrip("/") + urllib.parse.urlparse(CONFIG[name]).path


def request(url: str, values: dict[str, str], *, method: str = "POST", timeout: float = 3.0) -> int:
    encoded = urllib.parse.urlencode(values)
    body = encoded.encode() if method == "POST" else None
    target = url if method == "POST" else f"{url}?{encoded}"
    call = urllib.request.Request(target, data=body, method=method, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as error:
        error.read()
        return int(error.code)
    except Exception:
        return 0


def post(url: str, values: dict[str, str], timeout: float = 3.0) -> int:
    return request(url, values, method="POST", timeout=timeout)


def initialize() -> dict:
    registrations = Counter()
    for user_id in range(CONFIG["users"]):
        status = post(CONFIG["registration_endpoint"], {
            "first_name": f"first_{user_id}", "last_name": f"last_{user_id}",
            "username": f"username_{user_id}", "password": "m13-password", "user_id": str(user_id),
        })
        registrations[status] += 1
    follows = Counter()
    # A deterministic bidirectional ring prevents the upstream HomeTimeline
    # service from receiving an empty Redis ZADD key during compose-post.
    for user_id in range(CONFIG["users"]):
        for distance in (1, 2):
            followee = (user_id + distance) % CONFIG["users"]
            status = post(CONFIG["follow_endpoint"], {
                "user_name": f"username_{user_id}", "followee_name": f"username_{followee}",
            })
            follows[status] += 1
    result = {
        "users_attempted": CONFIG["users"], "statuses": dict(sorted(registrations.items())),
        "follows_attempted": CONFIG["users"] * 2, "follow_statuses": dict(sorted(follows.items())),
    }
    print(json.dumps(result, sort_keys=True))
    return result


def run(duration: float, regime: str, seed: int) -> dict:
    rps = int(CONFIG["regimes"][regime]["requests_per_second"])
    randomizer = random.Random(seed)
    deadline = time.monotonic() + duration
    interval = 1.0 / rps
    next_request = time.monotonic()
    statuses = Counter()
    futures: list[Future[int]] = []
    count = 0
    started = time.monotonic()
    # Dispatch at the preregistered fixed rate even when an injected fault makes
    # individual requests slow. A sequential loop would silently turn latency
    # faults into a lower-workload regime and confound the experiment.
    with ThreadPoolExecutor(max_workers=max(32, rps * 2)) as executor:
        while next_request < deadline:
            wait = next_request - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            user_id = randomizer.randrange(CONFIG["users"])
            other = (user_id + 1 + randomizer.randrange(CONFIG["users"]-1)) % CONFIG["users"]
            media_id = str(randomizer.randrange(10**16, 10**17))
            coin = randomizer.random()
            if coin < CONFIG["mix"]["home_timeline"]:
                futures.append(executor.submit(request, CONFIG["home_timeline_endpoint"], {
                    "user_id": str(user_id), "start": "0", "stop": "10",
                }, method="GET"))
            elif coin < CONFIG["mix"]["home_timeline"] + CONFIG["mix"]["user_timeline"]:
                futures.append(executor.submit(request, CONFIG["user_timeline_endpoint"], {
                    "user_id": str(user_id), "start": "0", "stop": "10",
                }, method="GET"))
            else:
                futures.append(executor.submit(post, CONFIG["endpoint"], {
                    "username": f"username_{user_id}", "user_id": str(user_id),
                    "text": f"m13 diagnostic post {count} @username_{other} http://example-{count}.test/path",
                    "media_ids": json.dumps([media_id]), "media_types": json.dumps(["png"]), "post_type": "0",
                }))
            count += 1
            next_request += interval
        for future in as_completed(futures):
            statuses[future.result()] += 1
    elapsed = time.monotonic() - started
    result = {
        "duration_seconds": duration, "regime": regime, "requests_per_second": rps,
        "attempts": count, "statuses": dict(sorted(statuses.items())), "seed": seed,
        "dispatch_rate": count / max(duration, 1e-9), "elapsed_seconds": elapsed,
    }
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--regime", choices=tuple(CONFIG["regimes"]), default="mixed_low")
    parser.add_argument("--seed", type=int, default=20260906)
    args = parser.parse_args()
    initialize() if args.init else run(args.duration, args.regime, args.seed)
