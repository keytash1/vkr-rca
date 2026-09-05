# Final RCA research summary

## Milestone history

| Milestone | Hypothesis | Result | Decision |
|---|---|---|---|
| M5 | Can robust baseline statistics detect service anomalies? | Implemented median/MAD latency and two-proportion error detection. | Retain as secondary autonomous trigger; external recall remains limiting. |
| M6 | Can trace topology and local evidence explain an incident? | Implemented deterministic max-severity, topology, local-evidence, and hybrid rankings over hard-gated candidates. | Retain as explainable historical baselines; remove hard gate from final primary mode. |
| M7 | Can service-invariant Learning-to-Rank improve RCA? | Same-system test AC@1 92.7%; truth isolation, permutation, root holdout, and SHAP checks passed. | Promising first learned ranker; external transfer still unproven. |
| M8A | Does the representation transfer to unseen synthetic topologies? | Frozen M7 AC@1 93.8%/94.0% on Topologies B/C; system-holdout remained strong. | Accept synthetic cross-topology transfer; require external benchmark. |
| M8B | Does trace-only RCA transfer to RCAEval? | M5 recall 52.9%; frozen M7 conditional AC@1 17.3%; detector and trace-domain shift limited the pipeline. | Partial external transfer; investigate detection and missing modalities. |
| M9A | Can a trace-only temporal CUSUM repair detection? | Synthetic recall 100% at 0% FPR, but external recall/FPR both 99.6%. | REJECT detector-v2; preserve the negative result. |
| M9B | Do robust metrics and multimodal soft evidence improve localization? | Metric LambdaMART AC@1 80.1%; all-modality AC@1 70.4%; matched fusion delta 6.0%. | Accept M9B as final research core, coverage-qualified. |

## Final frozen research architecture

```text
Incident trigger
      ↓
Metrics + distributed traces
      ↓
Automatically reconstructed topology
      ↓
Robust statistical and fixed-time temporal feature extraction
      ↓
Service-invariant diagnostic representation
      ↓
LambdaMART Learning-to-Rank
      ↓
Top-K root-cause services
      ↓
Machine-readable evidence and predictive explanation
```

Primary mode is externally triggered root-cause localization. Secondary mode is frozen M5/v1 detection followed by RCA. M9A detector-v2 is rejected and excluded.

## Final limitations

1. Primary localization requires an external incident trigger.
2. Output and truth are evaluated at service-level granularity.
3. Unobservable roots cannot be localized and are failures in full-denominator reporting.
4. Validation combines controlled synthetic systems and the RCAEval benchmark; it is not unrestricted production evidence.
5. Infrastructure/database entities are outside the current service candidate universe.
6. Logs are not used.
7. Ranking scores are not calibrated probabilities.
8. Gain importance and TreeSHAP are predictive, not causal.
9. Simultaneous multi-root incidents are not evaluated.
10. Frozen M5/v1 remains the limiting component in autonomous mode.

## Freeze

The research method is frozen after M10A. No GNN, causal model, log modality, detector-v3, or new ranker is justified by the current evidence. The next allowed milestone is demo/productization, not a new research method.
