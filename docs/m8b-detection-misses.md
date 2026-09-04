# External detection and eligibility misses

Cases: **113**. Detector v1 was not retuned.

| Dataset | Fault | Status | Count |
|---|---|---|---:|
| RE2-OB | cpu | detection_miss | 10 |
| RE2-OB | delay | detection_miss | 3 |
| RE2-OB | disk | detection_miss | 8 |
| RE2-OB | loss | detection_miss | 3 |
| RE2-OB | mem | detection_miss | 3 |
| RE2-OB | socket | detection_miss | 11 |
| RE2-TT | cpu | detection_miss | 1 |
| RE2-TT | delay | detection_miss | 1 |
| RE2-TT | disk | detection_miss | 6 |
| RE2-TT | loss | detection_miss | 6 |
| RE2-TT | mem | detection_miss | 1 |
| RE2-TT | socket | detection_miss | 2 |
| RE2-TT | socket | insufficient_baseline | 1 |
| RE3-OB | f1 | detection_miss | 3 |
| RE3-OB | f1 | root_not_observable | 3 |
| RE3-OB | f2 | detection_miss | 3 |
| RE3-OB | f3 | detection_miss | 3 |
| RE3-OB | f3 | root_not_observable | 3 |
| RE3-OB | f4 | detection_miss | 3 |
| RE3-OB | f4 | root_not_observable | 3 |
| RE3-OB | f5 | detection_miss | 3 |
| RE3-OB | f5 | root_not_observable | 3 |
| RE3-TT | f1 | detection_miss | 7 |
| RE3-TT | f2 | detection_miss | 7 |
| RE3-TT | f3 | detection_miss | 10 |
| RE3-TT | f4 | detection_miss | 6 |

## Case diagnostics

- `re2ob_checkoutservice_cpu_1` — RE2-OB, cpu, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1499/80, latency_z=0.12011800235521304, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_cpu_2` — RE2-OB, cpu, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1450/49, latency_z=1.3040221433406012, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_cpu_3` — RE2-OB, cpu, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1403/80, latency_z=1.6033805285664913, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_disk_1` — RE2-OB, disk, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1471/80, latency_z=0.19345446836720068, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_disk_2` — RE2-OB, disk, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1536/80, latency_z=2.078023330562406, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_disk_3` — RE2-OB, disk, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1525/80, latency_z=1.741141040088505, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_mem_2` — RE2-OB, mem, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1506/80, latency_z=0.1585650738699395, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_socket_1` — RE2-OB, socket, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1511/80, latency_z=0.22015807204310534, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_socket_2` — RE2-OB, socket, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1550/80, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2ob_checkoutservice_socket_3` — RE2-OB, socket, root `checkoutservice`, state `detection_miss`, candidates 7, baseline/current=1495/80, latency_z=0.06714151818727392, error_z=0.0, root anomalous=False.
- `re2ob_currencyservice_cpu_1` — RE2-OB, cpu, root `currencyservice`, state `detection_miss`, candidates 7, baseline/current=2120/60, latency_z=0.09163740710166596, error_z=0.0, root anomalous=False.
- `re2ob_currencyservice_socket_1` — RE2-OB, socket, root `currencyservice`, state `detection_miss`, candidates 7, baseline/current=2120/60, latency_z=0.021650655536034902, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_cpu_1` — RE2-OB, cpu, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=488/40, latency_z=0.7116929324757254, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_cpu_2` — RE2-OB, cpu, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=531/40, latency_z=0.16503852331128888, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_cpu_3` — RE2-OB, cpu, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=531/40, latency_z=0.9687841600004732, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_delay_1` — RE2-OB, delay, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=505/40, latency_z=0.06307933085570067, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_delay_2` — RE2-OB, delay, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=526/40, latency_z=0.2724409264203487, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_delay_3` — RE2-OB, delay, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=529/40, latency_z=0.004805382397752717, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_disk_1` — RE2-OB, disk, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=507/40, latency_z=0.5716845796577441, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_disk_2` — RE2-OB, disk, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=521/40, latency_z=0.33181634571003205, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_disk_3` — RE2-OB, disk, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=523/40, latency_z=0.23089502492675468, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_loss_1` — RE2-OB, loss, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=505/40, latency_z=0.3309964796354198, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_loss_2` — RE2-OB, loss, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=512/40, latency_z=0.2414321426715435, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_loss_3` — RE2-OB, loss, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=513/40, latency_z=0.2663601917388225, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_mem_2` — RE2-OB, mem, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=524/40, latency_z=0.47516190740648, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_mem_3` — RE2-OB, mem, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=522/40, latency_z=0.6810816925733623, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_socket_1` — RE2-OB, socket, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=515/40, latency_z=0.009610764795505364, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_socket_2` — RE2-OB, socket, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=533/40, latency_z=0.1391925789273693, error_z=0.0, root anomalous=False.
- `re2ob_emailservice_socket_3` — RE2-OB, socket, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=526/40, latency_z=0.004805382397752717, error_z=0.0, root anomalous=False.
- `re2ob_productcatalogservice_socket_2` — RE2-OB, socket, root `productcatalogservice`, state `detection_miss`, candidates 7, baseline/current=2240/80, latency_z=0.014824580275757011, error_z=0.0, root anomalous=False.
- `re2ob_productcatalogservice_socket_3` — RE2-OB, socket, root `productcatalogservice`, state `detection_miss`, candidates 7, baseline/current=2240/80, latency_z=0.014795335648247095, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_cpu_1` — RE2-OB, cpu, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=1.4862150255602884, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_cpu_2` — RE2-OB, cpu, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=3.132300024120771, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_cpu_3` — RE2-OB, cpu, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=2.0011233643832504, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_disk_1` — RE2-OB, disk, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=0.6033286006448656, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_disk_2` — RE2-OB, disk, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=1.861390877147726, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_socket_2` — RE2-OB, socket, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=0.038240964384034515, error_z=0.0, root anomalous=False.
- `re2ob_recommendationservice_socket_3` — RE2-OB, socket, root `recommendationservice`, state `detection_miss`, candidates 7, baseline/current=1240/40, latency_z=0.1449882942149383, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_cpu_3` — RE2-TT, cpu, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=841/20, latency_z=2.4279165355906724, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_delay_3` — RE2-TT, delay, root `ts-auth-service`, state `detection_miss`, candidates 27, baseline/current=835/20, latency_z=2.1238566663649108, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_disk_1` — RE2-TT, disk, root `ts-auth-service`, state `detection_miss`, candidates 27, baseline/current=816/20, latency_z=1.8898177258303597, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_disk_2` — RE2-TT, disk, root `ts-auth-service`, state `detection_miss`, candidates 25, baseline/current=834/20, latency_z=2.8223428316581756, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_disk_3` — RE2-TT, disk, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=855/20, latency_z=3.449565565615336, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_loss_1` — RE2-TT, loss, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=826/20, latency_z=0.005601864348719893, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_loss_2` — RE2-TT, loss, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=838/20, latency_z=1.1432489331423308, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_loss_3` — RE2-TT, loss, root `ts-auth-service`, state `detection_miss`, candidates 24, baseline/current=604/20, latency_z=0.6531345074264567, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_mem_1` — RE2-TT, mem, root `ts-auth-service`, state `detection_miss`, candidates 27, baseline/current=825/20, latency_z=3.486462231511507, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_socket_1` — RE2-TT, socket, root `ts-auth-service`, state `detection_miss`, candidates 27, baseline/current=818/20, latency_z=3.1999669529241466, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_socket_2` — RE2-TT, socket, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=814/20, latency_z=3.2569669508255834, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_disk_2` — RE2-TT, disk, root `ts-order-service`, state `detection_miss`, candidates 20, baseline/current=120/40, latency_z=0.14314669088586474, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_disk_3` — RE2-TT, disk, root `ts-order-service`, state `detection_miss`, candidates 20, baseline/current=132/40, latency_z=0.7737522162991706, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_loss_2` — RE2-TT, loss, root `ts-order-service`, state `detection_miss`, candidates 20, baseline/current=124/40, latency_z=0.12563317213968084, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_loss_3` — RE2-TT, loss, root `ts-order-service`, state `detection_miss`, candidates 20, baseline/current=125/40, latency_z=0.5365904627829821, error_z=0.0, root anomalous=False.
- `re2tt_ts-route-service_disk_3` — RE2-TT, disk, root `ts-route-service`, state `detection_miss`, candidates 24, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-route-service_loss_3` — RE2-TT, loss, root `ts-route-service`, state `detection_miss`, candidates 26, baseline/current=1000/20, latency_z=0.15406575441942572, error_z=0.0, root anomalous=False.
- `re2tt_ts-train-service_socket_1` — RE2-TT, socket, root `ts-train-service`, state `insufficient_baseline`, candidates 0, baseline/current=0/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_adservice_f3_1` — RE3-OB, f3, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f3_2` — RE3-OB, f3, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f3_3` — RE3-OB, f3, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f4_1` — RE3-OB, f4, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f4_2` — RE3-OB, f4, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f4_3` — RE3-OB, f4, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f5_1` — RE3-OB, f5, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f5_2` — RE3-OB, f5, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_adservice_f5_3` — RE3-OB, f5, root `adservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_cartservice_f1_1` — RE3-OB, f1, root `cartservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_cartservice_f1_2` — RE3-OB, f1, root `cartservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_cartservice_f1_3` — RE3-OB, f1, root `cartservice`, state `root_not_observable`, candidates 7, baseline/current=0/0, latency_z=0, error_z=0, root anomalous=False.
- `re3ob_emailservice_f1_1` — RE3-OB, f1, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=112/1, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f1_2` — RE3-OB, f1, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=121/4, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f1_3` — RE3-OB, f1, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=98/3, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f2_1` — RE3-OB, f2, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=118/1, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f2_2` — RE3-OB, f2, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=105/4, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f2_3` — RE3-OB, f2, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=135/4, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f3_1` — RE3-OB, f3, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=131/2, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f3_2` — RE3-OB, f3, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=116/2, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f3_3` — RE3-OB, f3, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=124/1, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f4_1` — RE3-OB, f4, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=101/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f4_2` — RE3-OB, f4, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=108/20, latency_z=0.3315687661258085, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f4_3` — RE3-OB, f4, root `emailservice`, state `detection_miss`, candidates 7, baseline/current=117/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f5_1` — RE3-OB, f5, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=115/2, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f5_2` — RE3-OB, f5, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=138/0, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3ob_emailservice_f5_3` — RE3-OB, f5, root `emailservice`, state `detection_miss`, candidates 6, baseline/current=116/0, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f1_1` — RE3-TT, f1, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=246/22, latency_z=0.0655824318969036, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f1_2` — RE3-TT, f1, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=248/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f1_3` — RE3-TT, f1, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=247/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f1_4` — RE3-TT, f1, root `ts-auth-service`, state `detection_miss`, candidates 11, baseline/current=253/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f2_1` — RE3-TT, f2, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=242/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f2_2` — RE3-TT, f2, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=241/22, latency_z=0.02167081750727345, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f2_3` — RE3-TT, f2, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=246/22, latency_z=0.030269510379946026, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f2_4` — RE3-TT, f2, root `ts-auth-service`, state `detection_miss`, candidates 11, baseline/current=249/22, latency_z=0.19611433929834207, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f3_1` — RE3-TT, f3, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=246/22, latency_z=0.6096211059457196, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f3_2` — RE3-TT, f3, root `ts-auth-service`, state `detection_miss`, candidates 16, baseline/current=238/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f3_3` — RE3-TT, f3, root `ts-auth-service`, state `detection_miss`, candidates 16, baseline/current=230/22, latency_z=0.13520810566652483, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f3_4` — RE3-TT, f3, root `ts-auth-service`, state `detection_miss`, candidates 12, baseline/current=248/22, latency_z=0.8790260746932635, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f4_1` — RE3-TT, f4, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=236/22, latency_z=0.14350337968348392, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f4_2` — RE3-TT, f4, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=239/22, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-auth-service_f4_3` — RE3-TT, f4, root `ts-auth-service`, state `detection_miss`, candidates 15, baseline/current=246/22, latency_z=0.0934509358219175, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f1_1` — RE3-TT, f1, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f1_2` — RE3-TT, f1, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.44432357811202433, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f1_3` — RE3-TT, f1, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.37534465918227544, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f2_1` — RE3-TT, f2, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.1835679156282012, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f2_2` — RE3-TT, f2, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.2878249416869584, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f2_3` — RE3-TT, f2, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_1` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_2` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 15, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_3` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_4` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=1.6058572120878205, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_5` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f3_6` — RE3-TT, f3, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f4_1` — RE3-TT, f4, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.07538503640448638, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f4_2` — RE3-TT, f4, root `ts-route-service`, state `detection_miss`, candidates 15, baseline/current=1000/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re3tt_ts-route-service_f4_3` — RE3-TT, f4, root `ts-route-service`, state `detection_miss`, candidates 17, baseline/current=1000/40, latency_z=0.3852909905022949, error_z=0.0, root anomalous=False.
