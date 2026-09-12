# M13 Claim Registry

## learned model vs metric heuristic

- CLAIM: learned model vs metric heuristic
- HYPOTHESIS: learned model vs metric heuristic
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: metric heuristic
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.4247916666666668, 0.6666666666666666], "groups": 60, "observed_delta": 0.5416666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.44166666666666665, 0.6416666666666666], "groups": 120, "observed_delta": 0.5416666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.33333333333333337, 0.575], "groups": 60, "observed_delta": 0.45833333333333326, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3666666666666667, 0.55], "groups": 120, "observed_delta": 0.45833333333333326, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.275, 0.5166666666666666], "groups": 60, "observed_delta": 0.3916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.30833333333333335, 0.4833333333333333], "groups": 120, "observed_delta": 0.3916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.34669915674603174, 0.5386183186026937], "groups": 60, "observed_delta": 0.44242334054834054, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3684697195165946, 0.5160353385040886], "groups": 120, "observed_delta": 0.44242334054834054, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.3684697195165946, 0.5160353385040886]
- CLUSTER CI: [0.34669915674603174, 0.5386183186026937]
- LIMITATION: single development system

## traces incremental value

- CLAIM: traces incremental value
- HYPOTHESIS: traces incremental value
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: metrics only
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.31666666666666665, 0.5666666666666667], "groups": 60, "observed_delta": 0.4416666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.33333333333333337, 0.5416666666666667], "groups": 120, "observed_delta": 0.4416666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.2666666666666666, 0.475], "groups": 60, "observed_delta": 0.3666666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.275, 0.45833333333333337], "groups": 120, "observed_delta": 0.3666666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.125, 0.32499999999999996], "groups": 60, "observed_delta": 0.22499999999999998, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.1499999999999999, 0.30833333333333324], "groups": 120, "observed_delta": 0.22499999999999998, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.2623173100048099, 0.44909059343434343], "groups": 60, "observed_delta": 0.3547474747474749, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.2775617484367484, 0.4284228896103895], "groups": 120, "observed_delta": 0.3547474747474749, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.2775617484367484, 0.4284228896103895]
- CLUSTER CI: [0.2623173100048099, 0.44909059343434343]
- LIMITATION: trace and propagation enter together in primary contrast

## disappearance evidence

- CLAIM: disappearance evidence
- HYPOTHESIS: disappearance evidence
- STATUS: PARTIALLY_SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: same model without disappearance
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.0, 0.20833333333333326], "groups": 12, "observed_delta": 0.08333333333333337, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [0.0, 0.20833333333333337], "groups": 24, "observed_delta": 0.08333333333333337, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.0, 0.125], "groups": 12, "observed_delta": 0.04166666666666674, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [0.0, 0.125], "groups": 24, "observed_delta": 0.04166666666666674, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.0, 0.25], "groups": 12, "observed_delta": 0.08333333333333337, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [0.0, 0.20833333333333337], "groups": 24, "observed_delta": 0.08333333333333337, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.0, 0.11944444444444435], "groups": 12, "observed_delta": 0.05694444444444435, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [0.001388888888888884, 0.12364583333333294], "groups": 24, "observed_delta": 0.05694444444444435, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.001388888888888884, 0.12364583333333294]
- CLUSTER CI: [0.0, 0.11944444444444435]
- LIMITATION: service-unavailable subset

## propagation evidence

- CLAIM: propagation evidence
- HYPOTHESIS: propagation evidence
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: metrics plus traces
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.025000000000000022, 0.19166666666666665], "groups": 60, "observed_delta": 0.10833333333333339, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.04166666666666663, 0.18333333333333335], "groups": 120, "observed_delta": 0.10833333333333339, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [-0.02499999999999991, 0.07500000000000007], "groups": 60, "observed_delta": 0.025000000000000022, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [-0.01666666666666672, 0.06666666666666665], "groups": 120, "observed_delta": 0.025000000000000022, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [-0.06666666666666665, 0.0], "groups": 60, "observed_delta": -0.025000000000000022, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "cluster"}, "incident": {"ci95": [-0.05833333333333335, 0.0], "groups": 120, "observed_delta": -0.025000000000000022, "resamples": 10000, "seed": 20260906, "supported_positive": false, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.018690476190476257, 0.11430753968253965], "groups": 60, "observed_delta": 0.06494047619047616, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.023848710317460366, 0.10744196428571422], "groups": 120, "observed_delta": 0.06494047619047616, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.023848710317460366, 0.10744196428571422]
- CLUSTER CI: [0.018690476190476257, 0.11430753968253965]
- LIMITATION: handcrafted topology features

## Top-5/full-candidate recovery

- CLAIM: Top-5/full-candidate recovery
- HYPOTHESIS: Top-5/full-candidate recovery
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: frozen M11 Top-5 membership
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.2833333333333333, 0.5333333333333333], "groups": 60, "observed_delta": 0.4083333333333334, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.30833333333333335, 0.5083333333333333], "groups": 120, "observed_delta": 0.4083333333333334, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.3583333333333333, 0.5916666666666667], "groups": 60, "observed_delta": 0.475, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3833333333333333, 0.5666666666666667], "groups": 120, "observed_delta": 0.475, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.375, 0.6083333333333334], "groups": 60, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4083333333333333, 0.5833333333333333], "groups": 120, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.27982051917989403, 0.4918902943121692], "groups": 60, "observed_delta": 0.3854728835978837, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3046677414021164, 0.4682342923280423], "groups": 120, "observed_delta": 0.3854728835978837, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.3046677414021164, 0.4682342923280423]
- CLUSTER CI: [0.27982051917989403, 0.4918902943121692]
- LIMITATION: development-only conditional gate

## cross-fault robustness

- CLAIM: cross-fault robustness
- HYPOTHESIS: cross-fault robustness
- STATUS: SUPPORTED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: frozen M11 per-fault performance
- METRIC: AC@1 or MRR
- RESULT: {"ac_at_1": {"cluster": {"ci95": [0.3916666666666667, 0.625], "groups": 60, "observed_delta": 0.5083333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4164583333333335, 0.6083333333333333], "groups": 120, "observed_delta": 0.5083333333333333, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_3": {"cluster": {"ci95": [0.375, 0.6083333333333334], "groups": 60, "observed_delta": 0.49166666666666664, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4, 0.5833333333333333], "groups": 120, "observed_delta": 0.49166666666666664, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "ac_at_5": {"cluster": {"ci95": [0.375, 0.6083333333333334], "groups": 60, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.4083333333333333, 0.5833333333333333], "groups": 120, "observed_delta": 0.4916666666666667, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}, "mrr": {"cluster": {"ci95": [0.352420138888889, 0.5472016369047618], "groups": 60, "observed_delta": 0.4501951058201058, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "cluster"}, "incident": {"ci95": [0.3723966600529102, 0.5290855654761905], "groups": 120, "observed_delta": 0.4501951058201058, "resamples": 10000, "seed": 20260906, "supported_positive": true, "unit": "incident"}}}
- INCIDENT CI: [0.3723966600529102, 0.5290855654761905]
- CLUSTER CI: [0.352420138888889, 0.5472016369047618]
- LIMITATION: five fault families on one development system

## GNN escalation

- CLAIM: GNN escalation
- HYPOTHESIS: GNN escalation
- STATUS: NOT_JUSTIFIED
- DATASET: DeathStarBench Social Network
- DATA ROLE: NEW_DEVELOPMENT
- PROTOCOL: grouped OOF; repetitions kept in clusters
- DENOMINATOR: 120
- BASELINE: strongest non-GNN challenger
- METRIC: AC@1 or MRR
- RESULT: {}
- INCIDENT CI: null
- CLUSTER CI: null
- LIMITATION: residual errors do not establish propagation as the remaining bottleneck
