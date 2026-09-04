# M9B case studies and score explanations

Cases are deterministic lexicographic examples. Contributions are predictive TreeSHAP values and are not causal explanations.

## Model gain importance

- `train_RE2-OB_test_TT`: `[('metric_memory_rolling_30_median', 116.9408), ('metric_cpu_p90_shift_z', 76.2394), ('metric_latency_p90_abs_location_z', 64.3521), ('metric_max_shift_score', 59.1685), ('metric_max_shift_score_percentile', 40.6452), ('trace_local_evidence', 40.0589), ('trace_topology_f1_percentile', 28.0697), ('metric_latency_p50_max_shift', 26.4534), ('metric_latency_p90_signed_location_z', 25.1693), ('metric_latency_p50_rolling_30_median', 13.0667), ('metric_latency_p50_p90_shift_z', 10.1427), ('metric_latency_p90_max_run_fraction', 9.9672), ('metric_cpu_max_persistence', 8.044), ('metric_cpu_rolling_60_score', 6.7911), ('metric_memory_p90_shift_z', 3.7472)]`
- `train_RE2-TT_test_OB`: `[('metric_cpu_max_persistence_percentile', 206.2686), ('metric_latency_p50_max_persistence_percentile', 114.9818), ('metric_latency_p90_max_persistence_percentile', 95.5138), ('metric_socket_rolling_60_fraction', 92.9836), ('metric_latency_p90_signed_location_z', 86.2321), ('metric_latency_p90_rolling_120_fraction', 77.508), ('metric_socket_signed_location_z', 76.7332), ('metric_latency_p90_rolling_60_fraction', 59.0441), ('trace_normalized_in_degree_percentile', 58.4899), ('metric_latency_p50_signed_location_z', 35.653), ('metric_latency_p90_p90_shift_z', 34.2996), ('trace_median_downstream_wait_ratio', 28.3389), ('trace_median_exclusive_ratio_percentile', 27.4775), ('trace_log1p_median_exclusive_duration_ms', 20.9963), ('trace_median_exclusive_ratio', 17.8663)]`

## RE2 CPU success: re2ob_checkoutservice_cpu_2

Suite `RE2-OB`, fault `cpu`, truth `checkoutservice`, rank `1` of `7`.

Top ranking: `[('checkoutservice', 0.5248), ('emailservice', -0.2766), ('recommendationservice', -0.7601), ('currencyservice', -0.8863), ('productcatalogservice', -0.8863)]`.

Root metric evidence: `[('socket', 222222.22222222222), ('cpu', 243.4920072457678), ('memory', 32.73874378690243)]`; trace latency/error `0.835/0.000`; topology F1 `0.000`.

Root top contributions: `[{'feature': 'metric_latency_p90_max_persistence_percentile', 'value': 0.19189982116222382}, {'feature': 'trace_median_exclusive_ratio_percentile', 'value': -0.1564619243144989}, {'feature': 'metric_socket_signed_location_z', 'value': 0.12092375010251999}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': 0.09763402491807938}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': 0.09159655123949051}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.07754812389612198}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.07591579854488373}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.07337653636932373}, {'feature': 'trace_median_downstream_wait_ratio', 'value': 0.05394887924194336}, {'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': 0.038206398487091064}]`.

This is a success: the strongest root metric families were [('socket', 222222.22222222222), ('cpu', 243.4920072457678)], while the highest-absolute model contribution was `metric_latency_p90_max_persistence_percentile`. Their joint score put the truth first.

## RE2 CPU failure: re2ob_checkoutservice_cpu_1

Suite `RE2-OB`, fault `cpu`, truth `checkoutservice`, rank `2` of `7`.

Top ranking: `[('emailservice', 0.2422), ('checkoutservice', -0.3574), ('paymentservice', -0.7816), ('currencyservice', -0.8863), ('productcatalogservice', -0.8863)]`.

Root metric evidence: `[('socket', 222222.22222222222), ('cpu', 296.86956090662073), ('memory', 18.42109207548301)]`; trace latency/error `0.113/0.000`; topology F1 `0.000`.

Root top contributions: `[{'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': 0.3020429015159607}, {'feature': 'metric_latency_p90_signed_location_z', 'value': -0.21859391033649445}, {'feature': 'metric_latency_p90_max_persistence_percentile', 'value': -0.1725158393383026}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': -0.16105234622955322}, {'feature': 'metric_socket_signed_location_z', 'value': 0.08724522590637207}, {'feature': 'metric_latency_p90_rolling_120_median', 'value': -0.07871504127979279}, {'feature': 'metric_latency_p50_signed_location_z', 'value': -0.06845267117023468}, {'feature': 'trace_median_exclusive_ratio_percentile', 'value': -0.05748516321182251}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': 0.04900159314274788}, {'feature': 'metric_latency_p90_p90_shift_z', 'value': -0.043757904320955276}]`.

This is a miss: the strongest root metric families were [('socket', 222222.22222222222), ('cpu', 296.86956090662073)], while the highest-absolute model contribution was `trace_log1p_median_exclusive_duration_ms`. The learned cross-system score instead preferred `emailservice`.

## RE2 DISK success: re2ob_checkoutservice_disk_2

Suite `RE2-OB`, fault `disk`, truth `checkoutservice`, rank `1` of `7`.

Top ranking: `[('checkoutservice', 0.5788), ('emailservice', -0.2766), ('productcatalogservice', -0.6231), ('currencyservice', -0.8863), ('frontendservice', -1.0447)]`.

Root metric evidence: `[('socket', 333333.3333333333), ('memory', 1036.4455324035232), ('cpu', 273.60697986993773)]`; trace latency/error `1.124/0.000`; topology F1 `0.000`.

Root top contributions: `[{'feature': 'metric_latency_p90_max_persistence_percentile', 'value': 0.19189982116222382}, {'feature': 'trace_median_exclusive_ratio_percentile', 'value': -0.1564619243144989}, {'feature': 'metric_socket_signed_location_z', 'value': 0.12092375010251999}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': 0.09159655123949051}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.07754812389612198}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.07591579854488373}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.07337653636932373}, {'feature': 'trace_median_downstream_wait_ratio', 'value': 0.05884631350636482}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': 0.04900159314274788}, {'feature': 'metric_socket_rolling_60_fraction', 'value': 0.0408971905708313}]`.

This is a success: the strongest root metric families were [('socket', 333333.3333333333), ('memory', 1036.4455324035232)], while the highest-absolute model contribution was `metric_latency_p90_max_persistence_percentile`. Their joint score put the truth first.

## RE2 DISK failure: re2ob_checkoutservice_disk_1

Suite `RE2-OB`, fault `disk`, truth `checkoutservice`, rank `2` of `7`.

Top ranking: `[('emailservice', 0.2422), ('checkoutservice', -0.243), ('currencyservice', -0.8863), ('productcatalogservice', -0.8863), ('frontendservice', -0.8931)]`.

Root metric evidence: `[('socket', 333333.3333333333), ('memory', 657.0410307959427), ('cpu', 232.72177083320753)]`; trace latency/error `0.177/0.000`; topology F1 `0.000`.

Root top contributions: `[{'feature': 'metric_latency_p90_signed_location_z', 'value': -0.25173842906951904}, {'feature': 'metric_latency_p90_max_persistence_percentile', 'value': -0.16615355014801025}, {'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': 0.1585221290588379}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': 0.1143348440527916}, {'feature': 'metric_latency_p90_rolling_120_median', 'value': -0.07871504127979279}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.07591579854488373}, {'feature': 'metric_socket_signed_location_z', 'value': 0.07247800379991531}, {'feature': 'metric_latency_p50_signed_location_z', 'value': -0.053685449063777924}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': 0.04900159314274788}, {'feature': 'metric_latency_p90_p90_shift_z', 'value': -0.043757904320955276}]`.

This is a miss: the strongest root metric families were [('socket', 333333.3333333333), ('memory', 657.0410307959427)], while the highest-absolute model contribution was `metric_latency_p90_signed_location_z`. The learned cross-system score instead preferred `emailservice`.

## RE2 MEM: re2ob_checkoutservice_mem_1

Suite `RE2-OB`, fault `mem`, truth `checkoutservice`, rank `1` of `7`.

Top ranking: `[('checkoutservice', 0.8046), ('emailservice', -0.1544), ('paymentservice', -0.8833), ('currencyservice', -0.8863), ('productcatalogservice', -0.8863)]`.

Root metric evidence: `[('socket', 444444.44444444444), ('memory', 1411.124600926301), ('cpu', 238.54844233725052)]`; trace latency/error `1.835/0.000`; topology F1 `0.667`.

Root top contributions: `[{'feature': 'metric_latency_p90_max_persistence_percentile', 'value': 0.21872296929359436}, {'feature': 'metric_socket_signed_location_z', 'value': 0.12092375010251999}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.09238828718662262}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': 0.09159655123949051}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.07754812389612198}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.07591579854488373}, {'feature': 'trace_median_downstream_wait_ratio', 'value': 0.05884631350636482}, {'feature': 'metric_latency_p90_rolling_120_fraction', 'value': 0.051142770797014236}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': 0.04900159314274788}, {'feature': 'metric_socket_rolling_60_fraction', 'value': 0.0408971905708313}]`.

This is a success: the strongest root metric families were [('socket', 444444.44444444444), ('memory', 1411.124600926301)], while the highest-absolute model contribution was `metric_latency_p90_max_persistence_percentile`. Their joint score put the truth first.

## RE2 DELAY: re2ob_checkoutservice_delay_1

Suite `RE2-OB`, fault `delay`, truth `checkoutservice`, rank `2` of `7`.

Top ranking: `[('paymentservice', 0.312), ('checkoutservice', 0.1611), ('emailservice', 0.048), ('productcatalogservice', -0.6231), ('currencyservice', -0.7212)]`.

Root metric evidence: `[('latency_p90', 420.65740366023834), ('latency_p50', 105.03070182012598), ('cpu', 3.436100740886454)]`; trace latency/error `3.495/0.000`; topology F1 `0.667`.

Root top contributions: `[{'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': 0.27284806966781616}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': -0.16732819378376007}, {'feature': 'metric_latency_p90_max_persistence_percentile', 'value': -0.15284520387649536}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.1166917234659195}, {'feature': 'metric_socket_signed_location_z', 'value': -0.10620748996734619}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.08887790143489838}, {'feature': 'trace_local_evidence', 'value': 0.07177148014307022}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': -0.054515253752470016}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.03729187324643135}, {'feature': 'metric_latency_p90_rolling_60_fraction', 'value': 0.035444632172584534}]`.

This is a miss: the strongest root metric families were [('latency_p90', 420.65740366023834), ('latency_p50', 105.03070182012598)], while the highest-absolute model contribution was `trace_log1p_median_exclusive_duration_ms`. The learned cross-system score instead preferred `paymentservice`.

## RE2 SOCKET/LOSS: re2ob_checkoutservice_loss_1

Suite `RE2-OB`, fault `loss`, truth `checkoutservice`, rank `1` of `7`.

Top ranking: `[('checkoutservice', 0.6625), ('emailservice', -0.2766), ('paymentservice', -0.8833), ('currencyservice', -0.8863), ('productcatalogservice', -0.8863)]`.

Root metric evidence: `[('socket', 1000000.0), ('latency_p50', 412.27444707817), ('latency_p90', 178.8311986612273)]`; trace latency/error `3.508/0.000`; topology F1 `0.667`.

Root top contributions: `[{'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': 0.18172717094421387}, {'feature': 'metric_latency_p90_max_persistence_percentile', 'value': 0.16403721272945404}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': 0.1285398155450821}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.1166917234659195}, {'feature': 'metric_socket_signed_location_z', 'value': -0.1046004369854927}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.08887790143489838}, {'feature': 'trace_median_downstream_wait_ratio', 'value': 0.057961028069257736}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': -0.054515253752470016}, {'feature': 'trace_normalized_in_degree_percentile', 'value': -0.03729187324643135}, {'feature': 'metric_latency_p90_rolling_60_fraction', 'value': 0.035444632172584534}]`.

This is a success: the strongest root metric families were [('socket', 1000000.0), ('latency_p50', 412.27444707817)], while the highest-absolute model contribution was `trace_log1p_median_exclusive_duration_ms`. Their joint score put the truth first.

## RE3 success: re3ob_currencyservice_f1_1

Suite `RE3-OB`, fault `f1`, truth `currencyservice`, rank `1` of `5`.

Top ranking: `[('currencyservice', -0.0643), ('frontend', -0.1593), ('productcatalogservice', -0.3813), ('checkoutservice', -0.9104), ('recommendationservice', -1.0237)]`.

Root metric evidence: `[('socket', 1333333.3333333333), ('memory', 130.40665661062263), ('latency_p90', 118.94067596358975)]`; trace latency/error `0.197/0.000`; topology F1 `0.500`.

Root top contributions: `[{'feature': 'metric_latency_p90_max_persistence_percentile', 'value': -0.27076011896133423}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': -0.16105234622955322}, {'feature': 'metric_socket_signed_location_z', 'value': 0.12243074178695679}, {'feature': 'metric_socket_rolling_60_fraction', 'value': 0.10462987422943115}, {'feature': 'trace_normalized_in_degree_percentile', 'value': 0.10308801382780075}, {'feature': 'metric_latency_p90_signed_location_z', 'value': 0.09238828718662262}, {'feature': 'metric_latency_p50_signed_location_z', 'value': 0.07754812389612198}, {'feature': 'metric_latency_p90_rolling_120_fraction', 'value': -0.059217970818281174}, {'feature': 'metric_latency_p90_rolling_60_fraction', 'value': -0.05346544459462166}, {'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': -0.035228513181209564}]`.

This is a success: the strongest root metric families were [('socket', 1333333.3333333333), ('memory', 130.40665661062263)], while the highest-absolute model contribution was `metric_latency_p90_max_persistence_percentile`. Their joint score put the truth first.

## RE3 failure: re3ob_currencyservice_f1_2

Suite `RE3-OB`, fault `f1`, truth `currencyservice`, rank `3` of `5`.

Top ranking: `[('frontend', -0.2085), ('productcatalogservice', -0.5092), ('currencyservice', -0.8314), ('checkoutservice', -0.9722), ('recommendationservice', -1.0686)]`.

Root metric evidence: `[('socket', 1000000.0), ('memory', 113.96348587005491), ('latency_p90', 17.853064475468642)]`; trace latency/error `0.406/0.000`; topology F1 `0.500`.

Root top contributions: `[{'feature': 'metric_latency_p90_max_persistence_percentile', 'value': -0.23397864401340485}, {'feature': 'metric_latency_p90_signed_location_z', 'value': -0.1890684962272644}, {'feature': 'metric_latency_p50_max_persistence_percentile', 'value': -0.16732819378376007}, {'feature': 'trace_normalized_in_degree_percentile', 'value': 0.10308801382780075}, {'feature': 'metric_socket_signed_location_z', 'value': -0.08903548121452332}, {'feature': 'metric_latency_p90_rolling_120_fraction', 'value': -0.059217970818281174}, {'feature': 'metric_cpu_max_persistence_percentile', 'value': -0.054515253752470016}, {'feature': 'metric_latency_p90_rolling_60_fraction', 'value': -0.05346544459462166}, {'feature': 'metric_latency_p50_signed_location_z', 'value': -0.044026605784893036}, {'feature': 'trace_log1p_median_exclusive_duration_ms', 'value': -0.035228513181209564}]`.

This is a miss: the strongest root metric families were [('socket', 1000000.0), ('memory', 113.96348587005491)], while the highest-absolute model contribution was `metric_latency_p90_max_persistence_percentile`. The learned cross-system score instead preferred `frontend`.
