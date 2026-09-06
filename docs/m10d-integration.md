# M10D integration: Evidence-Aware Top-3 Reranker

## Decision

This branch integrates exactly one promoted M10D component:

| Component | Verdict | Integrated into the final M10D pipeline |
|---|---|---|
| Reliability v2 | `REJECTED` | No |
| Deterministic verifier | `INCONCLUSIVE` | No |
| Evidence-Aware Top-3 Reranker | `PROMOTED` | Yes |
| Active diagnostic planner | `REJECTED` | No |

`M10D_INTEGRATION: EVIDENCE_RERANKER_ONLY`

The integrated component is a **model of reranking with diagnostic evidence**. It is not described as a causal verifier, causal proof, or calibrated probability. The research-only verifier statuses and abstention policy from M10D-B are not exposed by the integration API.

## Architecture

```text
M10C compact LambdaMART
→ initial full ranking
→ initial Top-3
→ truth-free diagnostic evidence feature extraction
→ frozen five-seed shallow XGBoost reranker
→ reordered Top-3
→ unchanged tail
→ final ranking
```

The reranker uses the exact 13-feature frozen schema:

- nine diagnostic evidence components;
- aggregate `support_score`;
- base-rank percentile;
- relative base score;
- Top-1 base margin.

Service identifiers are candidate-matching keys only. They are never numeric model features. Inference rejects `label`, `root`, `root_service`, `ground_truth`, `fault`, `system`, and `dataset` fields.

## Data protocol and promotion basis

Development predictions are system-out-of-fold across `RE1-OB`, `RE1-SS`, and `RE1-TT`. For each held-out system, all five models are trained only on incidents from the other two systems. Train and test incident identifiers are checked to be disjoint.

The primary promotion evidence is the positive system-OOF development result. External 360 has the following explicit role:

- `external_used_for_training: false`;
- `external_used_for_feature_selection: false`;
- `external_used_for_hyperparameter_selection: false`;
- `external_used_for_model_selection: false`;
- `external_used_for_final_non_degradation_guard: true`.

External 360 was opened after freeze for post-hoc evaluation and the pre-specified non-degradation guard. It was not used to revise the method after the result was observed.

## Exact reproduced evaluation

### Development system-OOF, 375 incidents

| Model | AC@1 | AC@2 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| Frozen M10C base | 0.7200 | 0.8907 | 0.9307 | 0.8326 |
| Evidence-Aware Top-3 Reranker | **0.7813** | **0.9040** | 0.9307 | **0.8655** |

Paired bootstrap, 10,000 resamples, seed `20260906`:

- ΔAC@1: `+0.0613`, 95% CI `[+0.0320; +0.0907]`;
- ΔMRR: `+0.0329`, 95% CI `[+0.0173; +0.0489]`.

Both development confidence intervals are strictly above zero.

### External post-freeze, 360 incidents

| Model | AC@1 | AC@2 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| Frozen M10C base | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| Evidence-Aware Top-3 Reranker | **0.8361** | **0.9306** | 0.9417 | **0.8977** |

Paired bootstrap:

- ΔAC@1: `+0.0472`, 95% CI `[+0.0250; +0.0722]`;
- ΔMRR: `+0.0287`, 95% CI `[+0.0167; +0.0417]`.

The exact M10D-B numerical results were reproduced within a `1e-12` serialization tolerance. No retraining or tuning of the promoted frozen models was performed.

## Interpretability ablation

This ablation is evaluated only as a predeclared interpretability study on development system-OOF predictions. It is not used to select or change the promoted model.

| Variant | Features | AC@1 | MRR | ΔAC@1 vs base | ΔMRR vs base |
|---|---|---:|---:|---:|---:|
| A. Base ranking | None | 0.7200 | 0.8326 | — | — |
| B. Ranking context only | rank percentile, relative score, margin | 0.7200 | 0.8322 | 0.0000 | -0.0004 |
| C. Diagnostic evidence only | 9 components + support score | **0.7787** | **0.8611** | **+0.0587** | **+0.0284** |
| D. Full evidence-aware | evidence + ranking context | **0.7813** | **0.8655** | **+0.0613** | **+0.0329** |

For ranking-context-only, the paired intervals include zero:

- ΔAC@1 CI `[-0.0107; +0.0107]`;
- ΔMRR CI `[-0.0058; +0.0049]`.

For diagnostic-evidence-only, both paired intervals are positive:

- ΔAC@1 CI `[+0.0133; +0.1040]`;
- ΔMRR CI `[+0.0040; +0.0529]`.

Therefore, the improvement is not explained by simply relearning the original scores and ranks. Diagnostic evidence provides the dominant new predictive signal. Ranking context supplies a smaller complementary improvement in the full model.

## Frozen-model predictive importance

`total_gain` is reported independently for all five frozen seeds. The table contains mean and population standard deviation across seeds. These are predictive importances, not causal effects.

| Feature or group | Mean total gain | Std |
|---|---:|---:|
| `component_MetricSupport` | 1670.42 | 245.84 |
| Base-ranking context, total | 1387.51 | 99.14 |
| └ `base_relative_score` | 1133.85 | 70.32 |
| └ `base_margin` | 239.71 | 32.15 |
| └ `base_rank_percentile` | 13.94 | 9.81 |
| `support_score` | 995.38 | 212.89 |
| Coverage/OOD group | 1.03 | 2.07 |
| Trace evidence group | 0.00 | 0.00 |
| Topology evidence group | 0.00 | 0.00 |

The current verified gain is chiefly metric-evidence-driven. RE1 contains insufficient trace-bearing evidence, and the frozen models assign zero total gain to the direct trace and topology features. Consequently, this experiment does **not** establish cross-domain transfer of the trace modality or a proven multi-source verifier. Full per-seed values are versioned in `ml/models/m10d-integration/evaluation.json`.

## Ranking invariants

The following invariants hold for every development and external incident:

```text
set(initial Top-3 services) == set(final Top-3 services)
```

and the relative ordering of all candidates below rank three is identical. Both mismatch lists are empty in the evaluation artifact.

## Supported claim and limitations

Supported:

> Evidence-aware Top-3 reranking improves the ordering of candidates already present in the initial Top-3.

Not supported:

- the reranker improves candidate discovery;
- the output is a causal verification or causal proof;
- the score is a calibrated probability;
- trace-modality cross-domain transfer has been demonstrated.

The central limitation is structural: **the reranker cannot recover a true root cause ranked below Top-3 by the base M10C ranker**. AC@3 is therefore invariant by construction.

## Frozen models and provenance

Source research commit:

`e7a03959494bd89bb8df02fb51f5ce65e8bc6060`

Frozen model SHA-256:

| Model | SHA-256 |
|---|---|
| `reranker-seed-20260906.json` | `880f7870eab35a73cfa37adaeddd8f80d7ddba92abd4cf6223b4828446b3a5da` |
| `reranker-seed-20260907.json` | `06c0d4343bb48c679084b89e8896e2b76d0e207ffba31801dcb3ced596785b44` |
| `reranker-seed-20260908.json` | `22b32193cd7c7d7b5e84833315761166a88415be55073cc71d73c5f6647bdc07` |
| `reranker-seed-20260909.json` | `0b63c093f9d9d29b2f5412f8194a57cf04c9cc0bc6fcd2664f5bbba63fe27a0b` |
| `reranker-seed-20260910.json` | `88648e01f8e67d6fc06d5eaf5b2d16cf6d386ef498df93724249b15bd87f156c` |

The integration manifest also records the frozen M10A/M10B/M10C integrity results and hashes of the truth-free M10C and M9B inputs.

## Reproduction

From the repository root, with the existing benchmark inputs available under `external-data`:

```bash
PYTHONPATH=ml .venv/bin/python -m ml.rca_ml.m10d_integration_experiment
```

The command validates all frozen hashes before evaluation and stops if any of the four development/external AC@1 or MRR regression values differs by more than `1e-12`.
