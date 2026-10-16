"""Exercise the real application and expose observed request counts to Prometheus."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time
from urllib.request import urlopen


counts = {"started": 0, "succeeded": 0, "failed": 0, "dropped": 0}
lock = threading.Lock()
slots = threading.BoundedSemaphore(16)


def perform(url):
    with lock:
        counts["started"] += 1
    try:
        with urlopen(url, timeout=5) as response:
            response.read()
            ok = response.status == 200
    except OSError:
        ok = False
    with lock:
        counts["succeeded" if ok else "failed"] += 1
    slots.release()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/metrics":
            self.send_error(404)
            return
        with lock:
            data = "".join(f"acceptance_requests_{name}_total {value}\n" for name, value in counts.items()).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, action="append")
    parser.add_argument("--rate", type=float, default=5)
    args = parser.parse_args()
    if not 0 < args.rate <= 20:
        parser.error("rate must be in (0, 20]")
    server = ThreadingHTTPServer(("0.0.0.0", 9101), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with ThreadPoolExecutor(max_workers=16) as pool:
        index = 0
        while True:
            started = time.monotonic()
            if slots.acquire(blocking=False):
                pool.submit(perform, args.url[index % len(args.url)])
                index += 1
            else:
                with lock:
                    counts["dropped"] += 1
            time.sleep(max(0, 1 / args.rate - (time.monotonic() - started)))
