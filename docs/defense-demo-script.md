# RCA defense demo script

This is an operational script, not a presentation and not a source of new research claims.

## 0:00 — Architecture and boundaries

- Open **Архитектура**.
- Say: “The research method is frozen at M10A. This interface only demonstrates it.”
- Point to the two paths. Live Lab uses the controlled Go runtime and M6 explainable baseline. Benchmark Replay uses pinned RCAEval features and the frozen M9B LambdaMART fold.

## 0:30 — Healthy baseline

- Open **Живая демонстрация**.
- Click **Сбросить и откалибровать**.
- While it runs, explain that faults, the graph, and current anomaly windows are cleared; 50 healthy requests establish the baseline; a Collector drain barrier prevents stale traces from entering the next incident.
- Select **Healthy** only if a clean request needs to be shown.

## 1:00 — Inject Payment latency

- Select **Задержка Payment**. The fixed value is 700 ms.
- Click **Сгенерировать 20 запросов**.
- Point out that the fault controller knows the scenario but ground truth is not passed into the RCA algorithm.

## 1:30 — Cascading symptoms

- Show the graph `gateway → orders → payment` reconstructed from OTLP parent-child relationships.
- Show that Gateway and Orders are slow because they wait for a downstream service.
- Contrast their low local exclusive ratio with Payment’s high local duration/evidence.

## 2:00 — Explainable online ranking

- Show the **Гибридный метод M6** ranking with Payment at Top-1. The internal name `hybrid_v1` is secondary technical metadata.
- Say “оценка ранжирования” and “diagnostic evidence”; do not say probability or calibrated confidence.
- If the live acceptance result is not ready, show the explicit error/state, reset, and repeat. Do not claim a fake success.

## 2:30 — Trace evidence

- Show the retained trace ID and service evidence table.
- Explain latency z-score, error evidence, exclusive ratio, topology consistency, and local evidence.
- State that this Live Lab is not the final M9B benchmark result.

## 3:00 — Frozen external replay

- Open **Внешний набор данных**.
- Choose the neutral **Внешний инцидент A** for a success or **Внешний инцидент B** for a miss. Do not disclose their internal identifier, root, or fault family yet.
- Before analysis, point out that only system, dataset, incident timestamp, candidate count, and telemetry coverage are visible.
- Click **Проанализировать инцидент**. Point out the blind-analysis notice and, when it completes, the statement that the prediction is fixed.
- Show the Top-K output. Select candidates to inspect human-readable contribution names while retaining technical names underneath. Expand **Технические сведения о модели** only if exact version, fold, SHA, schema, 253 features, training systems, or artifact are requested.
- Say: “These are predictive contributions, not causal proof.”

## 4:00 — Reveal truth

- Click **Показать фактическую первопричину**. Only now show the internal Case ID, root, fault family, and actual rank.
- For the success, show Top-1 correctness.
- For the miss, show both predicted Top-1 and the unchanged actual-root rank. Do not replace or reorder the prediction.

## 4:30 — Frozen research results

- Open **Результаты исследования**.
- Show **LambdaMART по метрикам** on the full set of 360 cases versus BARO on the same full set.
- Show the matched fusion AC@1 point difference and explain that only the MRR interval is strictly positive.
- Show autonomous M5 recall/FPR/end-to-end limitations if asked.
- Show M9A: 100%/0% on synthetic validation but 99.6%/99.6% externally, therefore rejected.

## 5:00 — Limitations and close

- In the claim registry, highlight supported, partially supported, coverage-qualified, and rejected statuses.
- State the main limitations: external trigger, service-level target, unobservable roots, synthetic plus RCAEval validation, no logs, no calibrated probabilities, no causal claim, no simultaneous multi-root evaluation, and a limiting autonomous detector.
- End: “The research is frozen. M10B adds a reproducible defense interface, not a new experiment.”
