# M13.1 Claim Registry

## Nested selection procedure vs chance

- CLAIM: nested selection procedure vs chance
- HYPOTHESIS: nested procedure improves AC@1 or MRR
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: five-fold outer grouped validation with inner-only selection
- DENOMINATOR: 120 incidents / 60 clusters
- BASELINE: chance
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.7333333333333334, 0.8916666666666667], "groups": 60, "observed_delta": 0.8166666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.75, 0.8833333333333333], "groups": 120, "observed_delta": 0.8166666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.7166666666666667, 0.875], "groups": 60, "observed_delta": 0.8, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.7250000000000001, 0.8666666666666667], "groups": 120, "observed_delta": 0.8, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.5416666666666667, 0.725], "groups": 60, "observed_delta": 0.6333333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.55, 0.7166666666666667], "groups": 120, "observed_delta": 0.6333333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.6456278333934584, 0.7552905017436267], "groups": 60, "observed_delta": 0.7011823593073594, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.6504248136123135, 0.7506612403799903], "groups": 120, "observed_delta": 0.7011823593073594, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.6504248136123135, 0.7506612403799903]
- CLUSTER CI: [0.6456278333934584, 0.7552905017436267]
- LIMITATION: one development system; final cross-system test remains untouched

## Nested selection procedure vs metric_heuristic

- CLAIM: nested selection procedure vs metric_heuristic
- HYPOTHESIS: nested procedure improves AC@1 or MRR
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: five-fold outer grouped validation with inner-only selection
- DENOMINATOR: 120 incidents / 60 clusters
- BASELINE: metric_heuristic
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.4083333333333333, 0.6583333333333334], "groups": 60, "observed_delta": 0.5333333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4333333333333333, 0.6333333333333333], "groups": 120, "observed_delta": 0.5333333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.3416666666666667, 0.5833333333333334], "groups": 60, "observed_delta": 0.4666666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.375, 0.5583333333333333], "groups": 120, "observed_delta": 0.4666666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.275, 0.5166666666666666], "groups": 60, "observed_delta": 0.3916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.30833333333333335, 0.4833333333333333], "groups": 120, "observed_delta": 0.3916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.34420326779701776, 0.5395233435545934], "groups": 60, "observed_delta": 0.44117334054834056, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.36612866762866764, 0.5147189153439155], "groups": 120, "observed_delta": 0.44117334054834056, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.36612866762866764, 0.5147189153439155]
- CLUSTER CI: [0.34420326779701776, 0.5395233435545934]
- LIMITATION: one development system; final cross-system test remains untouched

## Nested selection procedure vs frozen_m11

- CLAIM: nested selection procedure vs frozen_m11
- HYPOTHESIS: nested procedure improves AC@1 or MRR
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: five-fold outer grouped validation with inner-only selection
- DENOMINATOR: 120 incidents / 60 clusters
- BASELINE: frozen_m11
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.375, 0.625], "groups": 60, "observed_delta": 0.49999999999999994, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4000000000000001, 0.6], "groups": 120, "observed_delta": 0.49999999999999994, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.3833333333333334, 0.6166666666666667], "groups": 60, "observed_delta": 0.5, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.41666666666666663, 0.5916666666666666], "groups": 120, "observed_delta": 0.5, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.375, 0.6083333333333334], "groups": 60, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4083333333333333, 0.5833333333333333], "groups": 120, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.3499662698412699, 0.5480170304232804], "groups": 60, "observed_delta": 0.4489451058201058, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3724666005291004, 0.52685582010582], "groups": 120, "observed_delta": 0.4489451058201058, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.3724666005291004, 0.52685582010582]
- CLUSTER CI: [0.3499662698412699, 0.5480170304232804]
- LIMITATION: one development system; final cross-system test remains untouched
