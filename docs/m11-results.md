# M11 Results — Generalization & Error-Driven Hardening

## Candidate recovery

| Top-K | AC@1 | AC@2 | AC@3 | AC@5 | AC@10 | MRR | Promotion gate |
|---:|---:|---:|---:|---:|---:|---:|:---:|
| 3 | 0.7813 | 0.9040 | 0.9307 | 0.9840 | 0.9920 | 0.8655 | False |
| 5 | 0.7947 | 0.9200 | 0.9573 | 0.9840 | 0.9920 | 0.8775 | True |
| 10 | 0.7867 | 0.9120 | 0.9520 | 0.9813 | 0.9920 | 0.8715 | False |

Decision: **PROMOTE_TOP5**; selected K = **5**.
The decision was made only from RE1 system-OOF predictions and cluster bootstrap
with 10,000 resamples. Incident-level improvements are not promoted when the
cluster interval crosses zero.

Primary Top-5 vs Top-3 intervals:

- AC@1 incident CI: [0.0027, 0.0267]; cluster CI: [0.0027, 0.0267].
- MRR incident CI: [0.0044, 0.0207]; cluster CI: [0.0028, 0.0235].

Per-system, per-fault, pooled, macro-system and five-seed results are preserved in
`ml/models/m11/evaluation.json`.

Rejected hypothesis: Top-10 does not satisfy the pre-registered primary gate;
its AC@1 cluster CI `[-0.0107, 0.0187]` and MRR cluster CI
`[-0.0046, 0.0183]` cross zero. Candidate-universe discovery was not tested,
rather than rejected, because the candidate universe was held fixed.

## Generalization gates

- New-development adapter: **BLOCKED**.
- One-time locked new test: **BLOCKED**.
- Candidate recovery: **PROMOTED**.
- Trace/topology incremental study: **INCONCLUSIVE**.
- GNN: **NOT_JUSTIFIED**.
- Reliability v3: **BLOCKED**.
- New-system transfer: **BLOCKED**.
- Architecture: **PROMOTE_M11_RESEARCH_CHAMPION**.

## Historical non-regression

The frozen historical M10D benchmark remains AC@1
`0.8361111111`, AC@2
`0.9305555556`, AC@3
`0.9416666667`, and MRR
`0.8977211099`.
The selected Top-5 architecture is reported separately at AC@1
`0.8416666667`
and MRR `0.9039248136`;
these read-only outcomes did not affect promotion.

Protocol deviation: RE2/RE3 were executed three times during implementation.
Two uncommitted pre-release outputs were superseded while the reporting schema was
corrected and expanded. All runs froze the same RE1-only Top-5 decision first, so
model selection was unaffected; nevertheless, the requested single historical
execution was not met. No locked new-domain dataset existed or was opened.

## Scope

M11 supports only claims recorded in `docs/m11-claim-registry.md`. It does not
claim causal proof, calibrated probabilities, memory/log/event support, LLM
reasoning, or validated transfer to a new public domain.

## Reproduction

```bash
git switch research/m11-generalization-hardening
make m11-experiment
PYTHONPATH=ml .venv/bin/python -m unittest discover -s ml/tests -v
go test ./...
go vet ./...
go test -race ./...
git diff --check
```
