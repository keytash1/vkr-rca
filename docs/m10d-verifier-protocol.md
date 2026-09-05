# M10D-B protocol: Diagnostic Evidence Verifier

Status: isolated challenger over commit `b18c70c4deddb86c637a5fad4c9f68a2ff465423`.
M10A, M10B and M10C inputs are immutable. This branch does not create an
integration layer.

## Research question

The frozen M10C ranker answers which service should be ranked first. M10D-B
asks a separate question: does the available telemetry support each Top-3
candidate? The verifier output is diagnostic decision support, not proof of a
causal relationship.

For every candidate the deterministic verifier emits:

- `MetricSupport`: robust shifts, incident-relative percentiles, persistence,
  workload-conditioned residuals and dominant metric families;
- `TraceLocalSupport`: local evidence, latency/error evidence, exclusive
  duration and exclusive ratio;
- `PropagationSupport`: precision-, recall- and F1-like consistency between
  the expected upstream region and observed symptoms;
- `TopologySupport`: propagation consistency, active-topology coverage and
  affected-region agreement;
- `DependencyWaitSupport`: positive local/exclusive evidence discounted when
  the candidate mostly waits for downstream work;
- `CoverageSupport`: metric, trace, topology and family availability;
- `ContradictionEvidence`: healthy candidate metrics, stronger local evidence
  elsewhere, downstream-wait dominance or topology mismatch;
- `OODPenalty`: fraction of compact M10C features outside development-only
  1st/99th percentile fences, with robust median/IQR retained in the artifact;
- `ExpertAgreement`: metric/trace expert rank agreement. It is fixed to a
  neutral 0.5 when either modality is absent so tie-breaking cannot leak a
  service name.

The propagation artifact calls its distance and unexpected-downstream fields
proxies: the sealed M9B/M10C tables retain topology precision/recall/F1 and
affected-region ratios, not raw edge-by-edge paths. No stronger graph-distance
claim is made.

## Truth and identity isolation

Evidence construction rejects `label`, root, fault, system and dataset fields.
Service and incident IDs are opaque routing keys and do not enter the numeric
verifier schema. Labels are joined only after profiles are complete.

The frozen compact ranker is evaluated on RE1 with an outer system holdout:
each OB, SS or TT incident is ranked by a model fitted on the other two
systems. Metric and trace expert ranks follow the same out-of-fold rule. OOD
statistics for each held-out system are fitted on the other two systems.

The 360 RE2/RE3 cases are already known from M10C. They are used only after
the status policy, learned schema, model shape, seeds and reranking rule are
frozen. The result is explicitly a post-M10C external evaluation, not pristine
external model selection.

## Deterministic statuses and abstention

The statuses are `VERIFIED`, `PARTIALLY_SUPPORTED`,
`INSUFFICIENT_EVIDENCE` and `CONTRADICTED`. A bounded, interpretable grid over
support, contradiction and minimum-coverage cutoffs is selected only on the
development side. In every RE1 outer fold, cutoffs are calibrated on the other
two systems before the held-out system is classified.

The deterministic verifier is promoted only if all of the following hold on
nested development output:

1. verified cases are more accurate than the unfiltered base ranker;
2. contradicted cases contain more errors than the base error rate;
3. at least five verified and five contradicted cases exist;
4. synthetic A/B/C semantic checks for local propagation, metric-only evidence
   and topology contradiction pass.

If the development corpus lacks the trace modality required to validate the
multi-source statuses, the verdict is `INCONCLUSIVE`, not a promotion based on
the known external set. Verifier-only abstention accepts the widest status set
that reaches 90% accuracy on the fitting side; its external result cannot
change that rule.

## Learned verifier reranking challenger

The optional learned challenger sees only the nine evidence components,
deterministic support, base rank percentile, relative score and Top-1 margin.
It is a shallow XGBoost binary model (`max_depth=2`, 24 rounds) with no identity
features or broad hyperparameter search. It reranks only the frozen Top-3;
candidates below Top-3 keep their relative positions.

Candidate predictions are strictly out of fold. For each held-out RE1 system,
five models (`20260906` through `20260910`) fit only the other two systems.
Their mean probability-like score is used to rerank the held-out incidents.
The score is a candidate verifier score, not a calibrated probability.

`VERIFIER_RERANK` is `PROMOTED` only when the lower bound of a 10,000-resample
paired incident bootstrap is positive for development AC@1 or MRR and the
frozen external evaluation does not lose more than one AC@1 percentage point.
Bootstrap seed: `20260906`. Five-seed mean, standard deviation and range are
reported.

## Outputs and reproducibility

Versioned outputs live only under `ml/models/m10d-verifier/`: policy, five
learned models, evaluation, integrity manifest, truth-free external Top-3
profiles and six honest case studies. Frozen M10C files are read and hash
checked, never overwritten.

Run:

```bash
PYTHONPATH=ml .venv/bin/python -m rca_ml.m10d_verifier_experiment \
  --root . \
  --m10c-artifacts artifacts/m10c/m10c-v2 \
  --m9b-truth-free artifacts/m9b/m9b-v1/truth-free.jsonl \
  --models ml/models/m10d-verifier
```
