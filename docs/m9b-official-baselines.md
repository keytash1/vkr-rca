# M9B official RCAEval baselines

Pinned upstream source was used without patches. Service projection is reported only where the pinned evaluator defines it.

## baro

Status: `success`.

Expected/succeeded: `360/360`.

Service metrics: `{'overall': {'cases': 360, 'ac_at_1': 0.32222222222222224, 'ac_at_3': 0.8722222222222222, 'mrr': 0.6039284937027992, 'ndcg_at_1': 0.32222222222222224, 'ndcg_at_3': 0.657595386369061}, 'by_dataset': {'RE2-OB': {'cases': 90, 'ac_at_1': 0.17777777777777778, 'ac_at_3': 0.9222222222222223, 'mrr': 0.5487037037037037, 'ndcg_at_1': 0.17777777777777778, 'ndcg_at_3': 0.6329221772619231}, 'RE2-SS': {'cases': 90, 'ac_at_1': 0.15555555555555556, 'ac_at_3': 0.9111111111111111, 'mrr': 0.5346296296296297, 'ndcg_at_1': 0.15555555555555556, 'ndcg_at_3': 0.6177102856349392}, 'RE2-TT': {'cases': 90, 'ac_at_1': 0.5888888888888889, 'ac_at_3': 0.7444444444444445, 'mrr': 0.6926451917424139, 'ndcg_at_1': 0.5888888888888889, 'ndcg_at_3': 0.6797596420238124}, 'RE3-OB': {'cases': 30, 'ac_at_1': 0.1, 'ac_at_3': 0.9, 'mrr': 0.5055555555555555, 'ndcg_at_1': 0.1, 'ndcg_at_3': 0.6003794777381175}, 'RE3-SS': {'cases': 30, 'ac_at_1': 0.16666666666666666, 'ac_at_3': 0.8666666666666667, 'mrr': 0.5103174603174604, 'ndcg_at_1': 0.16666666666666666, 'ndcg_at_3': 0.5821315434523954}, 'RE3-TT': {'cases': 30, 'ac_at_1': 0.8333333333333334, 'ac_at_3': 0.9666666666666667, 'mrr': 0.9033333333333334, 'ndcg_at_1': 0.8333333333333334, 'ndcg_at_3': 0.9174573004761943}}}`.

Unmodified pinned RCAEval BARO; unavailable projected roots count as misses.

## mmbaro

Status: `compatibility_failed_missing_upstream_inputs`.

Expected/succeeded: `240/0`.

Compatibility failures: `{'missing_logts.csv': 240, 'missing_tracets_err.csv': 240, 'missing_tracets_lat.csv': 240}`.

Smoke stage: `blocked before invocation because required upstream-derived CSV inputs are absent`.

Pinned Hugging Face cases expose raw metrics/logs/traces Parquet, but the pinned upstream multi-source entrypoints require pre-derived logts.csv, tracets_err.csv, and tracets_lat.csv. No upstream patch or locally invented conversion was used.

## mmcirca

Status: `compatibility_failed_dependency_and_inputs`.

Expected/succeeded: `240/0`.

Compatibility failures: `{'missing_logts.csv': 240, 'missing_tracets_err.csv': 240, 'missing_tracets_lat.csv': 240}`.

Smoke stage: `blocked before invocation because required upstream-derived CSV inputs are absent`.

Entrypoint import failure: `ModuleNotFoundError: No module named 'causallearn'`.

Pinned Hugging Face cases expose raw metrics/logs/traces Parquet, but the pinned upstream multi-source entrypoints require pre-derived logts.csv, tracets_err.csv, and tracets_lat.csv. No upstream patch or locally invented conversion was used.

## mmrcd

Status: `compatibility_failed_dependency_and_inputs`.

Expected/succeeded: `240/0`.

Compatibility failures: `{'missing_logts.csv': 240, 'missing_tracets_err.csv': 240, 'missing_tracets_lat.csv': 240}`.

Smoke stage: `blocked before invocation because required upstream-derived CSV inputs are absent`.

Entrypoint import failure: `ModuleNotFoundError: No module named 'matplotlib'`.

Pinned Hugging Face cases expose raw metrics/logs/traces Parquet, but the pinned upstream multi-source entrypoints require pre-derived logts.csv, tracets_err.csv, and tracets_lat.csv. No upstream patch or locally invented conversion was used.
