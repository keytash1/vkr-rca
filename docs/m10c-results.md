# M10C Robust RCA Core v2 results

## Final verdict

`KEEP_FROZEN_M10A_CORE`

The M10C challenger improves several descriptive outcomes but does not pass the
pre-registered reliability and strong-promotion gates. M10A remains the thesis
Champion; M10C results are retained as a controlled challenger and negative
result rather than silently merged into the demo.

## Champion versus selected challenger

| Metric | Frozen M10A | M10C stacked challenger | Delta |
|---|---:|---:|---:|
| Root-observable coverage | 336/360 | **360/360** | +24 cases |
| Telemetry features | 253 | **32** | -87.4% |
| Full/conditional cases | 360 / 336 | **360 / 360** | no conditional exclusion |
| Full AC@1 | 0.7639 | **0.7889** | +0.0250 |
| Full AC@2 | not frozen | 0.9000 | — |
| Full AC@3 | 0.8972 | **0.9417** | +0.0444 |
| Full MRR | 0.8359 | **0.8690** | +0.0331 |

The 10,000-resample paired incident bootstrap gives AC@1 delta CI
[-0.0139, 0.0667] and MRR delta CI [0.0014, 0.0664]. MRR improves with a
positive paired interval; AC@1 still crosses zero.

## Missing-telemetry stress for the selected method

| Condition | AC@1 | AC@2 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| Complete | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| Traces missing | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| Topology missing | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| 30% spans removed | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| 50% spans removed | 0.7889 | 0.9000 | 0.9417 | 0.8690 |
| CPU family missing | 0.6361 | 0.8250 | 0.8778 | 0.7675 |
| CPU + latency missing | 0.4444 | 0.5972 | 0.6750 | 0.5920 |
| All metrics missing | 0.1056 | 0.1667 | 0.2417 | 0.2599 |

The model degrades gracefully without traces/topology because the selected
stack largely trusts metric evidence. That is robustness, but also shows that
this corpus did not validate a genuinely balanced multi-modal expert. Removing
the dominant metric families causes the expected substantial degradation.

## Gate decision

Passed: AC@1 floor, MRR floor, 360/360 root coverage, feature reduction,
conformal marginal coverage and no-trace degradation. Failed: 90% selective
Top-1 transfer at meaningful coverage. Strong accuracy also fails because the
gain is +2.5 rather than +3 points. The other strong-robust properties pass,
including a 2.683 mean 90% set size, but the mandatory selective reliability
gate still blocks promotion.

Rejected or not selected hypotheses: equal rank fusion, RRF, early fusion,
stacked adaptive fusion, calibrated 90% Top-1 acceptance as a transferable
guarantee, and M10C replacement of M10A. Workload residuals and the strict
subset pass their training-side component gates but do not change the final
verdict.

The selected compact model artifact is 15,508 bytes. A complete cached experiment run
took about 28 seconds on this machine; full truth-free regeneration over 735
local cases is a separate preprocessing step. Machine-readable details and the
full risk-coverage curve are in `ml/models/m10c-v2/evaluation.json`.
