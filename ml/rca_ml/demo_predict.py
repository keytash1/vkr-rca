"""Truth-blind thin inference wrapper for the frozen M9B demo replay."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import xgboost as xgb

from .dataset import sha256_file
from .m9b_schema import FEATURE_COLUMNS_M9B, TOPOLOGY_COLUMNS
from .train import save_json

ROUTES = {
    "RE2-OB": "train_RE2-TT_test_OB",
    "RE3-OB": "train_RE2-TT_test_OB",
    "RE2-TT": "train_RE2-OB_test_TT",
    "RE3-TT": "train_RE2-OB_test_TT",
}
MODEL_FILES = {
    "train_RE2-TT_test_OB": "ml/models/m9b-v1/multisource-folds/train_RE2-TT_test_OB.json",
    "train_RE2-OB_test_TT": "ml/models/m9b-v1/multisource-folds/train_RE2-OB_test_TT.json",
}
MODEL_HASHES = {
    "train_RE2-TT_test_OB": "1e3e3525815a0c682d4b8a591300a2ed524a0e21a0c7df94e9bc207fae2c59ff",
    "train_RE2-OB_test_TT": "54378ca63f1a6a29a43f24bdda7596010944714dd31dfac5cc2c0569800bca83",
}
FORBIDDEN_OUTPUT_KEYS = frozenset({"root", "root_service", "fault", "fault_family", "label", "ground_truth", "truth"})

HUMAN_LABELS = {
    "metric_cpu_max_persistence": "Устойчивость отклонения CPU",
    "metric_cpu_max_persistence_percentile": "Относительная устойчивость отклонения CPU",
    "metric_cpu_max_shift_percentile": "Относительная величина отклонения CPU",
    "metric_cpu_p90_shift_z": "Z-оценка сдвига p90 CPU",
    "metric_cpu_rolling_60_score": "Локальная оценка CPU в окне 60",
    "metric_latency_p50_max_persistence_percentile": "Относительная устойчивость отклонения p50 задержки",
    "metric_latency_p50_max_shift": "Максимальный сдвиг p50 задержки",
    "metric_latency_p50_max_shift_percentile": "Относительный сдвиг p50 задержки",
    "metric_latency_p50_rolling_30_fraction": "Доля отклонения p50 задержки в окне 30",
    "metric_latency_p50_rolling_30_median": "Медиана p50 задержки в окне 30",
    "metric_latency_p50_signed_location_z": "Z-оценка положения p50 задержки",
    "metric_latency_p90_max_persistence_percentile": "Относительная устойчивость отклонения p90 задержки",
    "metric_latency_p90_max_run_fraction": "Максимальная доля устойчивого отклонения p90 задержки",
    "metric_latency_p90_max_shift_percentile": "Относительный сдвиг p90 задержки",
    "metric_latency_p90_p90_shift_z": "Z-оценка сдвига p90 задержки",
    "metric_latency_p90_rolling_120_fraction": "Доля отклонения p90 задержки в окне 120",
    "metric_latency_p90_rolling_120_median": "Медиана p90 задержки в окне 120",
    "metric_latency_p90_signed_location_z": "Z-оценка положения p90 задержки",
    "metric_max_shift_score": "Максимальный сдвиг диагностической оценки",
    "metric_max_shift_score_percentile": "Относительный максимальный сдвиг диагностической оценки",
    "metric_memory_p90_shift_z": "Z-оценка сдвига p90 памяти",
    "metric_memory_rolling_30_median": "Медиана памяти в окне 30",
    "metric_socket_rolling_60_fraction": "Доля отклонения сокетов в окне 60",
    "metric_socket_signed_location_z": "Z-оценка положения сокетов",
    "metric_workload_p90_shift_z": "Z-оценка сдвига p90 нагрузки",
    "trace_median_exclusive_ratio": "Доля локального времени сервиса",
    "trace_median_exclusive_ratio_percentile": "Относительная доля локального времени сервиса",
    "trace_log1p_median_exclusive_duration_ms": "Локальная длительность сервиса",
    "trace_median_downstream_wait_ratio": "Доля ожидания нижестоящих сервисов",
    "trace_topology_f1": "Согласованность с графом распространения",
    "trace_topology_f1_percentile": "Относительная согласованность с графом распространения",
    "trace_normalized_in_degree": "Относительное число входящих зависимостей",
    "trace_normalized_in_degree_percentile": "Позиция по числу входящих зависимостей",
    "trace_normalized_out_degree": "Относительное число исходящих зависимостей",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    prepared = json.loads(args.input.read_text(encoding="utf-8"))
    result = predict_prepared(prepared, args.root)
    if args.output:
        save_json(args.output, result)
    else:
        print(canonical_json(result), end="")


def predict_prepared(prepared: dict, root: Path) -> dict:
    validate_prepared(prepared)
    dataset = str(prepared["dataset"])
    route = ROUTES.get(dataset)
    if route is None:
        raise ValueError(f"no frozen M9B multisource route for {dataset}")
    model_path = root / MODEL_FILES[route]
    actual_hash = sha256_file(model_path)
    if actual_hash != MODEL_HASHES[route]:
        raise ValueError(f"frozen model hash mismatch for {route}")

    services = sorted(prepared["features"]["services"], key=lambda value: value["service"])
    matrix = np.asarray(
        [[float(service["vector"][column]) for column in FEATURE_COLUMNS_M9B] for service in services],
        dtype=np.float32,
    )
    if not np.isfinite(matrix).all():
        raise ValueError("prepared M9B matrix contains NaN/Inf")
    data = xgb.DMatrix(matrix, feature_names=list(FEATURE_COLUMNS_M9B))
    model = xgb.Booster()
    model.load_model(model_path)
    scores = model.predict(data)
    contributions = model.predict(data, pred_contribs=True)

    ranked = []
    for service, score, contrib in zip(services, scores, contributions, strict=True):
        details = contribution_details(contrib[:-1])
        ranked.append({
            "service": service["service"],
            "score": float(score),
            "evidence": details[:6],
            "top_predictive_groups": contribution_groups(details),
        })
    ranked.sort(key=lambda value: (-value["score"], value["service"]))
    for index, value in enumerate(ranked, 1):
        value["rank"] = index

    vectors = [service["vector"] for service in services]
    trace_services = sum(float(vector.get("has_trace", 0)) > 0 for vector in vectors)
    topology_edges = round(sum(float(vector.get("trace_out_degree", 0)) for vector in vectors))
    metric_families = max((float(vector.get("metric_available_family_count", 0)) for vector in vectors), default=0)
    result = {
        "version": "m10b-replay-v1",
        "external_case_id": prepared["external_case_id"],
        "dataset": dataset,
        "system": prepared["system"],
        "incident_timestamp": prepared["incident_timestamp"],
        "model": {
            "version": "m9b-multisource-lambdamart-v1",
            "schema": "m9b-v1",
            "route": route,
            "artifact": MODEL_FILES[route],
            "sha256": actual_hash,
            "routing_reason": f"frozen {dataset} evaluation route from M9B",
        },
        "candidate_count": len(ranked),
        "telemetry": {
            "metric_family_count": int(metric_families),
            "metric_mapping_coverage": prepared["features"].get("mapping_coverage", {}),
            "trace_services": trace_services,
            "trace_coverage": trace_services / len(vectors) if vectors else 0.0,
            "topology_edges": topology_edges,
        },
        "ranking": ranked,
        "explanation_notice": "Predictive explanation, not causal proof.",
    }
    validate_prediction(result)
    return result


def validate_prepared(prepared: dict) -> None:
    required = {"external_case_id", "dataset", "system", "incident_timestamp", "features"}
    missing = sorted(required - set(prepared))
    if missing:
        raise ValueError(f"prepared case missing fields: {missing}")
    features = prepared["features"]
    if features.get("schema_version") != "m9b-v1" or not features.get("services"):
        raise ValueError("prepared case has invalid M9B features")
    if any(key in prepared for key in FORBIDDEN_OUTPUT_KEYS):
        raise ValueError("prediction input contains ground-truth metadata")


def validate_prediction(result: dict) -> None:
    def visit(value: object) -> None:
        if isinstance(value, dict):
            leaked = FORBIDDEN_OUTPUT_KEYS & set(value)
            if leaked:
                raise ValueError(f"prediction leaks ground truth: {sorted(leaked)}")
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("prediction contains NaN/Inf")
    visit(result)
    ranking = result.get("ranking", [])
    if not ranking or [value["rank"] for value in ranking] != list(range(1, len(ranking) + 1)):
        raise ValueError("prediction ranking is empty or not contiguous")
    expected = sorted(ranking, key=lambda value: (-value["score"], value["service"]))
    if ranking != expected:
        raise ValueError("prediction ranking is not deterministic")


def contribution_details(values: np.ndarray) -> list[dict]:
    details = []
    for feature, raw in zip(FEATURE_COLUMNS_M9B, values, strict=True):
        contribution = float(raw)
        details.append({
            "technical_name": feature,
            "display_name": human_label(feature),
            "group": presentation_group(feature),
            "contribution": contribution,
            "direction": "raises ranking" if contribution >= 0 else "lowers ranking",
            "magnitude": abs(contribution),
        })
    details.sort(key=lambda value: (-value["magnitude"], value["technical_name"]))
    return details


def contribution_groups(details: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    for detail in details:
        totals[detail["group"]] = totals.get(detail["group"], 0.0) + detail["magnitude"]
    denominator = sum(totals.values()) or 1.0
    result = [{"group": group, "share": value / denominator} for group, value in totals.items()]
    return sorted(result, key=lambda value: (-value["share"], value["group"]))


def presentation_group(feature: str) -> str:
    if feature in TOPOLOGY_COLUMNS:
        return "Topology"
    if feature == "has_trace" or feature.startswith("trace_"):
        return "Traces"
    return "Metrics"


def human_label(feature: str) -> str:
    if feature in HUMAN_LABELS:
        return HUMAN_LABELS[feature]
    value = feature.removeprefix("metric_").removeprefix("trace_")
    replacements = {
        "cpu": "CPU", "memory": "память", "disk_io": "дисковый I/O", "socket": "сокеты",
        "workload": "нагрузка", "error": "ошибки", "latency_p50": "p50 latency",
        "latency_p90": "p90 latency", "max_shift": "максимальный сдвиг",
        "max_persistence": "устойчивость отклонения", "percentile": "относительно сервисов",
        "rolling_30_score": "локальный score окна 30", "rolling_60_score": "локальный score окна 60",
        "rolling_120_score": "локальный score окна 120", "topology_f1": "согласованность с topology",
        "local_evidence": "локальное trace evidence", "trace_coverage": "покрытие трассами",
    }
    for technical, label in sorted(replacements.items(), key=lambda item: -len(item[0])):
        value = value.replace(technical, label)
    return value.replace("_", " ").strip().capitalize()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


if __name__ == "__main__":
    main()
