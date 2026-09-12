#!/usr/bin/env python3
"""Deterministic fixed-rate mixed Astronomy Shop workload for locked M14."""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed

PRODUCTS = ("0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ")
CHECKOUT = {
    "email": "m14@example.test",
    "address": {"streetAddress": "1 Research Way", "zipCode": "94043", "city": "Mountain View", "state": "CA", "country": "United States"},
    "userCurrency": "USD",
    "creditCard": {"creditCardNumber": "4432-8015-6152-0454", "creditCardExpirationMonth": 1, "creditCardExpirationYear": 2039, "creditCardCvv": 672},
}


def request(base: str, method: str, path: str, payload: dict | None = None, timeout: float = 5.0) -> int:
    body = json.dumps(payload).encode() if payload is not None else None
    call = urllib.request.Request(base.rstrip("/") + path, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(call, timeout=timeout) as response:
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as error:
        error.read()
        return int(error.code)
    except Exception:
        return 0


def operation(base: str, kind: str, product: str, user: str) -> int:
    if kind == "product":
        return request(base, "GET", f"/api/products/{product}")
    if kind == "recommendation":
        return request(base, "GET", f"/api/recommendations?productIds={product}")
    if kind == "ad":
        return request(base, "GET", "/api/data/?contextKeys=telescopes")
    cart = {"item": {"productId": product, "quantity": 1}, "userId": user}
    if kind == "cart":
        return request(base, "POST", "/api/cart", cart)
    added = request(base, "POST", "/api/cart", cart)
    if not 200 <= added < 400:
        return added
    return request(base, "POST", "/api/checkout", {**CHECKOUT, "userId": user}, timeout=8.0)


def run(base: str, duration: float, rps: int, seed: int) -> dict:
    kinds = ("product", "recommendation", "ad", "cart", "checkout")
    randomizer = random.Random(seed)
    deadline = time.monotonic() + duration
    next_request = time.monotonic()
    interval = 1.0 / rps
    futures: list[Future[int]] = []
    scheduled = Counter()
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=max(32, rps * 4)) as executor:
        index = 0
        while next_request < deadline:
            if (wait := next_request - time.monotonic()) > 0:
                time.sleep(wait)
            kind = kinds[index % len(kinds)]
            product = randomizer.choice(PRODUCTS)
            user = str(uuid.UUID(int=randomizer.getrandbits(128)))
            futures.append(executor.submit(operation, base, kind, product, user))
            scheduled[kind] += 1
            index += 1
            next_request += interval
        statuses = Counter(future.result() for future in as_completed(futures))
    return {
        "duration_seconds": duration,
        "requests_per_second": rps,
        "attempts": len(futures),
        "operation_mix": dict(sorted(scheduled.items())),
        "statuses": dict(sorted(statuses.items())),
        "seed": seed,
        "dispatch_rate": len(futures) / max(duration, 1e-9),
        "elapsed_seconds": time.monotonic() - started,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:15014")
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--rps", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args()
    print(json.dumps(run(args.base, args.duration, args.rps, args.seed), sort_keys=True))
