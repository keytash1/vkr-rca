#!/bin/sh
set -eu

port="${DEMO_PORT:-18000}"
base="http://127.0.0.1:${port}"
temporary="$(mktemp -d /tmp/vkr-rca-demo-smoke.XXXXXX)"
trap 'rm -rf "$temporary"' EXIT

request() {
  curl --fail --silent --show-error --retry 5 --retry-all-errors --retry-delay 1 "$@"
}

DEMO_PORT="$port" make --no-print-directory demo-up

request --max-time 10 "$base/" --output "$temporary/index.html"
request --max-time 10 "$base/app.js" --output "$temporary/app.js"
request --max-time 10 "$base/api/demo/health" --output "$temporary/health.json"
request --max-time 10 "$base/api/demo/replay/cases" --output "$temporary/cases.json"
request --max-time 65 --request POST "$base/api/demo/live/reset" --output "$temporary/reset.json"
request --max-time 15 --request POST \
  --header 'Content-Type: application/json' --data '{"scenario":"orders_latency"}' \
  "$base/api/demo/live/scenario" --output "$temporary/scenario.json"
request --max-time 65 --request POST \
  --header 'Content-Type: application/json' --data '{"requests":20}' \
  "$base/api/demo/live/traffic" --output "$temporary/live.json"

request --max-time 10 --request POST \
  --header 'Content-Type: application/json' --data '{"case_id":"re2ob_currencyservice_cpu_1"}' \
  "$base/api/demo/replay/analyze" --output "$temporary/replay-success.json"
request --max-time 10 --request POST \
  --header 'Content-Type: application/json' --data '{"case_id":"re2ob_currencyservice_cpu_1"}' \
  "$base/api/demo/replay/reveal" --output "$temporary/reveal-success.json"
request --max-time 10 --request POST \
  --header 'Content-Type: application/json' --data '{"case_id":"re2ob_checkoutservice_cpu_1"}' \
  "$base/api/demo/replay/analyze" --output "$temporary/replay-miss.json"
request --max-time 10 --request POST \
  --header 'Content-Type: application/json' --data '{"case_id":"re2ob_checkoutservice_cpu_1"}' \
  "$base/api/demo/replay/reveal" --output "$temporary/reveal-miss.json"
request --max-time 10 "$base/api/demo/research" --output "$temporary/research.json"

python3 - "$temporary" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
load = lambda name: json.loads((root / name).read_text())
index = (root / "index.html").read_text()
app = (root / "app.js").read_text()
assert all(tab in index for tab in (
    "Живая демонстрация", "Внешний набор данных", "Результаты исследования", "Архитектура", "Как пользоваться"
))
assert "Быстрый старт" in index and "Ограничения системы" in index
assert all(value in index for value in (
    "Как это работает", "Начать демонстрацию", "Слепой анализ",
    "Технические сведения о модели",
))
assert "Согласованность с графом (F1)" in app

cases = load("cases.json")["cases"]
assert [case["title"] for case in cases] == [f"Внешний инцидент {letter}" for letter in "ABCDEFGH"]

health = load("health.json")
assert health["freeze"]["status"] == "identical"
assert all(value["identical"] for value in health["freeze"]["files"])
assert health["replay_prepared"] is True

live = load("live.json")["result"]
edges = {(value["source"], value["target"]) for value in live["graph"]["edges"]}
assert ("gateway", "orders") in edges and ("orders", "payment") in edges
ranking = live["rca"]["rankings"]["hybrid_v1"]
assert ranking and ranking[0]["service"] == "orders", ranking
orders = next(value for value in live["features"]["services"] if value["service"] == "orders")
gateway = next(value for value in live["features"]["services"] if value["service"] == "gateway")
payment = next(value for value in live["features"]["services"] if value["service"] == "payment")
assert orders["median_exclusive_ratio"] > gateway["median_exclusive_ratio"]
assert orders["latency_anomalous"] is True and gateway["latency_anomalous"] is True
assert payment["latency_anomalous"] is False

success_prediction = load("replay-success.json")["prediction"]
assert success_prediction["model"]["route"] == "train_RE2-TT_test_OB"
assert success_prediction["ranking"][0]["service"] == "currencyservice"

def assert_truth_free(value):
    forbidden = {"root_service", "fault_family", "top1_correct", "actual_rank"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value), forbidden.intersection(value)
        for child in value.values():
            assert_truth_free(child)
    elif isinstance(value, list):
        for child in value:
            assert_truth_free(child)

assert_truth_free(success_prediction)
assert load("reveal-success.json")["ground_truth"]["top1_correct"] is True

miss_prediction = load("replay-miss.json")["prediction"]
assert miss_prediction["ranking"][0]["service"] == "emailservice"
assert_truth_free(miss_prediction)
miss_truth = load("reveal-miss.json")["ground_truth"]
assert miss_truth["top1_correct"] is False and miss_truth["actual_rank"] == 2

research = load("research.json")
assert research["metrics"]["metric_full_360"]["cases"] == 360
assert round(research["metrics"]["metric_full_360"]["ac_at_1"], 4) == 0.7639
assert len(research["claims"]) == 7
assert research["claims"][-1]["status"] == "REJECTED"
print(json.dumps({
    "status": "PASS",
    "live_top1": ranking[0]["service"],
    "live_edges": sorted([list(value) for value in edges]),
    "replay_success": success_prediction["external_case_id"],
    "replay_miss": miss_prediction["external_case_id"],
    "frozen_files": len(health["freeze"]["files"]),
}, indent=2, sort_keys=True))
PY
