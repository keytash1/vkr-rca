# M9B ablation study

## Modality ablation on identical cross-system/out-of-fault test cases

Each subset is retrained on the corresponding RE2 training fold with unchanged fold hyperparameters.

| Modalities | Columns | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|---:|
| metrics_only | 206 | 216 | 64.4% | 86.6% | 76.8% |
| traces_only | 26 | 216 | 47.2% | 69.9% | 61.5% |
| topology_only | 20 | 216 | 27.3% | 53.2% | 44.7% |
| metrics_traces | 232 | 216 | 61.6% | 86.6% | 75.0% |
| metrics_topology | 226 | 216 | 66.7% | 86.6% | 77.5% |
| traces_topology | 46 | 216 | 30.1% | 62.5% | 51.4% |
| all | 253 | 216 | 70.4% | 89.4% | 80.6% |

## Metric one-group-drop ablation

Each variant is retrained on all root-observable RE1 cases and evaluated on the same frozen 360-case RE2/RE3 corpus (336 root-observable cases).

| Removed group | Cases | AC@1 | AC@3 | MRR |
|---|---:|---:|---:|---:|
| without_cpu | 336 | 76.5% | 92.9% | 85.6% |
| without_memory | 336 | 84.2% | 96.7% | 90.5% |
| without_disk_io | 336 | 83.9% | 96.1% | 90.3% |
| without_socket | 336 | 83.9% | 96.1% | 90.3% |
| without_workload | 336 | 83.9% | 96.4% | 90.5% |
| without_latency_p50 | 336 | 86.0% | 95.8% | 91.4% |
| without_latency_p90 | 336 | 84.8% | 94.9% | 90.2% |
