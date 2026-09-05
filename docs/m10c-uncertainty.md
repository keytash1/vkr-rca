# M10C reliability, conformal sets and abstention

Calibration uses a 60-incident partition reserved before feature selection,
expert fitting and external evaluation. OOD statistics are
training median/IQR and 1%-99% fences. OOD enters reliability reporting only,
never candidate ranking.

## Split-conformal rank sets

The nonconformity score is truth rank divided by candidate count. Only marginal
coverage is claimed.

| Nominal | External empirical | Mean size | Median | P90 |
|---|---:|---:|---:|---:|
| 90% | 0.9111 | 2.683 | 2 | 5 |
| 95% | 0.9500 | 3.719 | 2 | 7 |

Both empirical coverage gates pass and the 90% average set meets the strong
size target.

## Selective Top-1

Thresholds combine top-score margin, modality coverage and training-fitted OOD
distance. They are selected for maximum calibration coverage at each target and
then frozen.

| Target | Calibration accuracy / coverage | External accuracy / coverage | External selective MRR |
|---|---:|---:|---:|
| 90% | 0.9167 / 1.0000 | 0.7889 / 1.0000 | 0.8690 |
| 95% | 0.9636 / 0.9167 | 0.8283 / 0.9222 | 0.8917 |

External AURC is 0.0873. Both thresholds fail to preserve their nominal
accuracy under system transfer. This observed failure was not corrected after
looking at test results. The required 90% selective accuracy gate therefore
fails and `ABSTAIN_TOP1` is not promoted as a guaranteed policy.
