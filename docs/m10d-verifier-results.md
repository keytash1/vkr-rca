# M10D-B Diagnostic Evidence Verifier results

## Verdicts

`VERIFIER: INCONCLUSIVE`

`VERIFIER_RERANK: PROMOTED`

The deterministic evidence profiles are implemented and useful for inspection,
but the only valid development corpus, RE1, has no trace-bearing candidates.
It therefore cannot validate transfer of multi-source status thresholds. The
known RE2/RE3 set is not used to turn that gap into a promotion.

The separate learned Top-3 reranker passes its exact promotion rule with clean
system-out-of-fold development predictions and a positive paired interval. It
also improves the post-freeze external result, although that result did not
select its schema, weights or hyperparameters.

## Deterministic verifier

On 375 nested RE1 held-out predictions, the base AC@1 is 0.7200. The
development-calibrated statuses produce no `VERIFIED`, 358
`PARTIALLY_SUPPORTED`, 15 `INSUFFICIENT_EVIDENCE` and two `CONTRADICTED`
cases. Both contradicted cases are ranking errors, but 2/375 is not meaningful
coverage. Synthetic A/B/C checks all pass: propagated wait is distinguished
from local evidence, a metric-only candidate remains verifiable, and an
inconsistent affected topology region creates a contradiction.

The frozen policy is descriptive on the post-M10C external 360:

| Status statistic | Result |
|---|---:|
| `VERIFIED` | 83/360 (23.06%) |
| Accuracy within `VERIFIED` | 98.80% |
| `CONTRADICTED` | 118/360 (32.78%) |
| Error fraction within `CONTRADICTED` | 36.44% |
| Base error fraction | 21.11% |

The verifier-only abstention rule accepts `VERIFIED` cases. It has zero
coverage in nested RE1 and 23.06% external coverage at 98.80% selective AC@1.
This is encouraging post-hoc evidence, not a transferable reliability claim;
the deterministic verdict remains `INCONCLUSIVE`.

Cross-system external status behavior is heterogeneous. Verified precision is
1.0 in RE2-OB, RE2-TT and RE3-TT, but no cases are verified in RE2-SS or
RE3-SS, and the single RE3-OB verified case is wrong. This is exactly why the
overall external number is not used to tune or promote the status layer.

## Learned verifier reranking

The learned verifier uses only clean OOF evidence and reranks the M10C Top-3.
It does not change Top-3 membership.

| Development metric | Frozen M10C architecture, OOF | Verifier rerank | Delta |
|---|---:|---:|---:|
| AC@1 | 0.7200 | **0.7813** | +0.0613 |
| AC@2 | 0.8907 | **0.9040** | +0.0133 |
| AC@3 | 0.9307 | 0.9307 | 0 |
| MRR | 0.8326 | **0.8655** | +0.0329 |

With 10,000 paired bootstrap resamples, AC@1 delta is +0.0613 with 95% CI
[+0.0320, +0.0907], and MRR delta is +0.0329 with CI
[+0.0173, +0.0489]. Both lower bounds are positive.

| Held-out development system | Base AC@1 | Rerank AC@1 | Base MRR | Rerank MRR |
|---|---:|---:|---:|---:|
| Online Boutique / RE1-OB | 0.6960 | **0.7760** | 0.8234 | **0.8648** |
| Sock Shop / RE1-SS | 0.8480 | **0.9200** | 0.9227 | **0.9587** |
| Train Ticket / RE1-TT | 0.6160 | **0.6480** | 0.7518 | **0.7732** |

Five-seed development AC@1 is 0.7813 mean, 0.0029 standard deviation and
[0.7787, 0.7867] range. MRR is 0.8655 mean, 0.0018 standard deviation and
[0.8642, 0.8691] range.

The post-freeze external 360 evaluation is:

| External metric | M10C | Verifier rerank | Delta |
|---|---:|---:|---:|
| AC@1 | 0.7889 | **0.8361** | +0.0472 |
| AC@2 | 0.9000 | **0.9306** | +0.0306 |
| AC@3 | 0.9417 | 0.9417 | 0 |
| MRR | 0.8690 | **0.8977** | +0.0287 |

External paired CIs are [+0.0250, +0.0722] for AC@1 and
[+0.0167, +0.0417] for MRR. Every external dataset improves descriptively:

| Dataset | Base AC@1 | Rerank AC@1 | Base MRR | Rerank MRR |
|---|---:|---:|---:|---:|
| RE2-OB | 0.8667 | 0.9111 | 0.9193 | 0.9452 |
| RE2-SS | 0.9111 | 0.9222 | 0.9519 | 0.9593 |
| RE2-TT | 0.6889 | 0.7667 | 0.8030 | 0.8512 |
| RE3-OB | 0.8667 | 0.9000 | 0.9072 | 0.9239 |
| RE3-SS | 0.6667 | 0.7667 | 0.7964 | 0.8464 |
| RE3-TT | 0.5333 | 0.5667 | 0.7022 | 0.7356 |

Five-seed external AC@1 is 0.8344 mean, 0.0045 standard deviation and
[0.8278, 0.8417] range. MRR is 0.8973 mean, 0.0022 standard deviation and
[0.8940, 0.9010] range.

## Honest case studies

All profiles below were generated before joining truth for reporting.

| Required case | Incident | Outcome |
|---|---|---|
| Correct, strongly verified | `re2tt_ts-route-service_socket_3` | correct, `VERIFIED` |
| Correct, weakly supported | `re3ss_carts_f4_1` | correct, `PARTIALLY_SUPPORTED` |
| Wrong, contradicted | `re2tt_ts-train-service_delay_3` | wrong, `CONTRADICTED` |
| Wrong, falsely verified | `re3ob_currencyservice_f1_3` | wrong, `VERIFIED` |
| Trace-missing correct | `re3ob_cartservice_f1_3` | correct, `PARTIALLY_SUPPORTED` |
| Metric-only candidate correct | `re3ob_cartservice_f1_3` | correct, `PARTIALLY_SUPPORTED` |

The false verification is retained explicitly. Full component scores,
contradictions and dominant metric families are in `case-studies.jsonl`.

## Failure and performance audit

Among the 76 external base-ranking errors, the overlapping taxonomy counts 58
OOD/domain-shift flags, 44 metric ambiguities, 32 missing-modality cases, 13 close-score candidate
ambiguities, one false verification and 33 contradiction misses. These labels
are diagnostic categories, so counts intentionally overlap. Planner bad action
is zero/not applicable to this isolated branch.

Measured on this machine, frozen rank inference took 2.65 ms per incident,
deterministic verification 0.43 ms and five-model learned scoring 0.06 ms. The
five learned models total 97,002 bytes. The full cached experiment took about
25-40 seconds in repeated runs; raw truth-free feature generation is a separate frozen step.

No causal-proof, calibrated-probability or conditional-coverage claim is made.
`VERIFIER_RERANK: PROMOTED` means the isolated challenger passed the M10D-B
reranking gate; it does not modify M10C or authorize integration without the
separate three-branch review.
