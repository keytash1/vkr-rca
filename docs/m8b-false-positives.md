# External healthy-window false positives

Cases: **17**. Detector v1 was not retuned.

| Dataset | Fault | Status | Count |
|---|---|---|---:|
| RE2-TT | cpu | detection_miss | 1 |
| RE2-TT | cpu | ready | 5 |
| RE2-TT | delay | ready | 3 |
| RE2-TT | disk | detection_miss | 3 |
| RE2-TT | disk | ready | 2 |
| RE2-TT | loss | detection_miss | 1 |
| RE2-TT | loss | ready | 1 |
| RE2-TT | socket | ready | 1 |

## Case diagnostics

- `re2tt_ts-auth-service_cpu_2` — RE2-TT, cpu, root `ts-auth-service`, state `ready`, candidates 25, baseline/current=420/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_cpu_3` — RE2-TT, cpu, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=430/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_disk_1` — RE2-TT, disk, root `ts-auth-service`, state `detection_miss`, candidates 27, baseline/current=405/20, latency_z=0.9639219603788651, error_z=0.0, root anomalous=False.
- `re2tt_ts-auth-service_loss_1` — RE2-TT, loss, root `ts-auth-service`, state `detection_miss`, candidates 26, baseline/current=403/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_cpu_3` — RE2-TT, cpu, root `ts-order-service`, state `ready`, candidates 25, baseline/current=878/129, latency_z=6.6014954117116815, error_z=0.0, root anomalous=True.
- `re2tt_ts-order-service_disk_3` — RE2-TT, disk, root `ts-order-service`, state `detection_miss`, candidates 20, baseline/current=62/40, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-order-service_socket_1` — RE2-TT, socket, root `ts-order-service`, state `ready`, candidates 26, baseline/current=1034/120, latency_z=5.953258872485396, error_z=0.0, root anomalous=True.
- `re2tt_ts-route-service_cpu_1` — RE2-TT, cpu, root `ts-route-service`, state `ready`, candidates 25, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-route-service_delay_3` — RE2-TT, delay, root `ts-route-service`, state `ready`, candidates 26, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=True.
- `re2tt_ts-route-service_disk_2` — RE2-TT, disk, root `ts-route-service`, state `ready`, candidates 20, baseline/current=677/20, latency_z=0.23525853439615582, error_z=0.0, root anomalous=False.
- `re2tt_ts-route-service_disk_3` — RE2-TT, disk, root `ts-route-service`, state `detection_miss`, candidates 24, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-train-service_cpu_3` — RE2-TT, cpu, root `ts-train-service`, state `ready`, candidates 26, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-train-service_delay_2` — RE2-TT, delay, root `ts-train-service`, state `ready`, candidates 26, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=True.
- `re2tt_ts-train-service_disk_2` — RE2-TT, disk, root `ts-train-service`, state `ready`, candidates 26, baseline/current=1000/20, latency_z=0.0, error_z=0.0, root anomalous=False.
- `re2tt_ts-train-service_loss_2` — RE2-TT, loss, root `ts-train-service`, state `ready`, candidates 27, baseline/current=1000/20, latency_z=0.19920239048097033, error_z=0.0, root anomalous=False.
- `re2tt_ts-travel-service_cpu_1` — RE2-TT, cpu, root `ts-travel-service`, state `ready`, candidates 26, baseline/current=1409/99, latency_z=0.0, error_z=0.0, root anomalous=True.
- `re2tt_ts-travel-service_delay_3` — RE2-TT, delay, root `ts-travel-service`, state `ready`, candidates 26, baseline/current=1395/100, latency_z=0.13869310737494978, error_z=0.0, root anomalous=True.
