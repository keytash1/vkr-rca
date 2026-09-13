# Final Research Freeze after M14

Effective 2026-09-13. Status: **FINAL_RESEARCH_FREEZE**.
Final held-out verdict: **SUPPORTED_TRANSFER**. Astronomy Shop is **USED_TEST**.

## Immutable research method

The final research model is the original M13 `full_candidate_challenger`:
five-seed XGBoost LambdaMART, 63 identity-free features, depth 3, eta 0.08,
24 rounds. Model hashes, complete feature schema and selected architecture are
in `ml/models/m13/freeze-manifest.json`. They were not replaced by a new M14 fit.
M13.1 audited the selection procedure; it did not retune the final M13 model.

The architecture remains canonical resource metrics plus native spans,
healthy-only expectations and expected edges, metric/trace/propagation and
disappearance features, frozen M11 ranking context, and full-candidate M13
ranking. Service names are join keys, not learned identity features. M14 fits
only healthy target baselines before injection, not a new scorer or calibrator.

The M14 method, transitive inference dependencies, deployment configuration,
protocol and input hashes are sealed in `ml/models/m14/frozen-inputs.json` and
`freeze-manifest.json`. Seal commit:
`669d49a82c719ebc27921b45895c59a8a21107fd`, published before scoring.
The prediction hash was committed before truth opening in `053f5ea`.

## Final evidence and roles

`ml/models/m14/data-ledger.json` supersedes earlier role snapshots without
rewriting them. RE1 remains development; synthetic data remains auxiliary;
RE2/RE3 and M12 remain used-test/read-only; M13 Social Network remains
development; M13.1 remains nested development validation. Astronomy Shop has
completed its one-time final evaluation and must never become development data.

Preserve all historical model artifacts, negative results, ablations, claims,
protocols and integrity manifests. In particular, M12 weak transfer is not
erased, M13 disappearance evidence remains only partially supported, and the
M13.1 nested result is not a second untouched-system result. The final ledger
does not retroactively change historical protocol snapshots.

M14 full results, error taxonomy and all uncertainty estimates are in
`ml/models/m14/evaluation.json` and `docs/m14-results.md`. The final claim
registry is `docs/m14-claim-registry.md`. The compact evaluation inputs permit
independent arithmetic verification without recollection or rescoring.
The raw corpus, rejected attempt, original sealed truth and predictions are
retained under `external-data/m14/runs/locked-v1/`; Git ignores do not make them
disposable cache. Local source-built images are also evidence, not cleanup junk.

`ml/models/m14/final-research-freeze.json` inventories historical research
artifacts, current claims/results, code and deployment files by SHA-256. It
does not replace the original pre-scoring seal. The original seal deliberately
retains its historical `SEALED_UNSCORED` state; the separate opening marker and
final ledger establish the later state, without rewriting pre-test evidence.

## What the evidence does and does not support

On this one controlled new system, M13 significantly improves AC@1 and MRR over
all three comparators. AC@1 is 25/50 and AC@5 is 39/50. Strong-transfer gates
fail because AC@3=.70 and AC@5=.78 are below .80/.90. Payment AC@1=.10 and ad
AC@5=.50 prevent a claim of uniform service-level reliability. Bootstrap does
not remove single-host, single-workload, temporal carryover or co-load limits.

Do not claim arbitrary unseen-fault transfer, causal root proof, calibrated
probabilities, production readiness, universal RCA or measured MTTR reduction.
Do not turn a 32 MiB allocation into a claim of genuine memory exhaustion.
All precollection build/resource exceptions and mechanical retries remain
disclosed. Rank scores are diagnostic associations, not probabilities.

## Permitted next work

Integrate the frozen research inference path into the product without changing
its mathematical behavior, expose model version and evidence/missingness,
prepare a stable demo, and write technical/experimental/architecture chapters.
Software unit, integration, regression and E2E testing are distinct from RCA
accuracy experiments and remain necessary for that integration.

The existing Go Gateway → Orders → Payment demo is not automatically a live
M13 integration merely because M14 offline inference succeeded. M14 does not
claim a newly completed product E2E or a production deployment. API/packaging/UI
work must preserve the frozen ranking contract and identify this separate scope.

Forbidden: retraining, tuning features/thresholds/reliability, post-test model
selection, new challengers, GNN, logs/events/incident-memory/LLM scorers or extra
test systems. Do not remove the one-time markers or overwrite sealed data.
Any independently discovered correctness defect must be reported explicitly;
it cannot silently authorize a new final test.
