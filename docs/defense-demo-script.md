# RCA defense demo script

This is an operational script, not a presentation and not a source of new research claims.

## 0:00 — Architecture and boundaries

- Open **Architecture**.
- Say: “The research method is frozen at M10A. This interface only demonstrates it.”
- Point to the two paths. Live Lab uses the controlled Go runtime and M6 explainable baseline. Benchmark Replay uses pinned RCAEval features and the frozen M9B LambdaMART fold.

## 0:30 — Healthy baseline

- Open **Live Lab**.
- Click **Reset & calibrate**.
- While it runs, explain that faults, the graph, and current anomaly windows are cleared; 50 healthy requests establish the baseline; a Collector drain barrier prevents stale traces from entering the next incident.
- Select **Healthy** only if a clean request needs to be shown.

## 1:00 — Inject Payment latency

- Select **Payment latency**. The fixed value is 700 ms.
- Click **Generate 20 requests**.
- Point out that the fault controller knows the scenario but ground truth is not passed into the RCA algorithm.

## 1:30 — Cascading symptoms

- Show the graph `gateway → orders → payment` reconstructed from OTLP parent-child relationships.
- Show that Gateway and Orders are slow because they wait for a downstream service.
- Contrast their low local exclusive ratio with Payment’s high local duration/evidence.

## 2:00 — Explainable online ranking

- Show the `hybrid_v1` ranking with Payment at Top-1.
- Say “ranking score” and “diagnostic evidence”; do not say probability or calibrated confidence.
- If the live acceptance result is not ready, show the explicit error/state, reset, and repeat. Do not claim a fake success.

## 2:30 — Trace evidence

- Show the retained trace ID and service evidence table.
- Explain latency z-score, error evidence, exclusive ratio, topology consistency, and local evidence.
- State that this Live Lab is not the final M9B benchmark result.

## 3:00 — Frozen external replay

- Open **Benchmark Replay**.
- Choose **External CPU case A** for a success or **External CPU case B** for a miss.
- Before analysis, point out that only system, dataset, incident timestamp, candidate count, and telemetry coverage are visible.
- Click **Analyze incident**.
- Show the exact frozen fold route and Top-K output. Select candidates to inspect human-readable contribution names while retaining technical names underneath.
- Say: “These are predictive contributions, not causal proof.”

## 4:00 — Reveal truth

- Click **Reveal ground truth**.
- For the success, show Top-1 correctness.
- For the miss, show both predicted Top-1 and the unchanged actual-root rank. Do not replace or reorder the prediction.

## 4:30 — Frozen research results

- Open **Research Results**.
- Show metric LambdaMART on all 360 cases versus BARO on the same denominator.
- Show the matched fusion AC@1 point difference and explain that only the MRR interval is strictly positive.
- Show autonomous M5 recall/FPR/end-to-end limitations if asked.
- Show M9A: 100%/0% on synthetic validation but 99.6%/99.6% externally, therefore rejected.

## 5:00 — Limitations and close

- Open the claim registry and highlight supported, partially supported, coverage-qualified, and rejected statuses.
- State the main limitations: external trigger, service-level target, unobservable roots, synthetic plus RCAEval validation, no logs, no calibrated probabilities, no causal claim, no simultaneous multi-root evaluation, and a limiting autonomous detector.
- End: “The research is frozen. M10B adds a reproducible defense interface, not a new experiment.”
