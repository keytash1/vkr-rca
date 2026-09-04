# M8A healthy false-positive diagnostics

M5 thresholds are frozen at latency-z 3.5 and error-z 3.0. This report diagnoses false positives without retuning on test outcomes.

## Topology B

False-positive controls: 9

### m8a-b-00082

Observed anomalies: billing, portal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 17.001721 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 2.701240 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 2.120256 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 1.633615 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 5.703720 | 0.000000 | True | False |

### m8a-b-00203

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 3.507385 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 1.130087 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.156643 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.616382 | 0.000000 | False | False |

### m8a-b-00251

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 3.752922 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 0.790697 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.446322 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.304753 | 0.000000 | False | False |

### m8a-b-00279

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 6.478105 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.024138 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 0.797015 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.901437 | 0.000000 | False | False |

### m8a-b-00424

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 4.542044 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 0.780486 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.482555 | 0.000000 | False | False |

### m8a-b-00427

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 7.059388 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 1.071904 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.189688 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.811049 | 0.000000 | False | False |

### m8a-b-00497

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 4.102837 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 1.165436 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |

### m8a-b-00518

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 3.626221 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 0.711334 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 0.363824 | 0.000000 | False | False |

### m8a-b-00535

Observed anomalies: billing

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| billing | GET /work | 20 | 100 | 6.780581 | 0.000000 | True | False |
| catalog | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| fulfillment | GET /work | 20 | 100 | 0.958649 | 0.000000 | False | False |
| inventory | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| portal | GET /work | 20 | 100 | 1.036553 | 0.000000 | False | False |

## Topology C

False-positive controls: 17

### m8a-c-00033

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.081434 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.087202 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 7.142143 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 1.526077 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.790459 | 0.000000 | False | False |

### m8a-c-00036

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.466647 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.652972 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 8.776666 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.811943 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 2.624421 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.497163 | 0.000000 | False | False |

### m8a-c-00096

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.417292 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 1.598510 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 3.838897 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 0.709399 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.679077 | 0.000000 | False | False |

### m8a-c-00159

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.324684 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.648695 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 0.000000 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 10.110046 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 2.107107 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.423596 | 0.000000 | False | False |

### m8a-c-00231

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.114605 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 3.719154 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.684810 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 1.565699 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.955645 | 0.000000 | False | False |

### m8a-c-00311

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 3.861744 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 0.836446 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |

### m8a-c-00359

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.348418 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 2.692231 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 6.657058 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 0.559282 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |

### m8a-c-00363

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.547864 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.901032 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 0.000000 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 4.205135 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 0.069448 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.543531 | 0.000000 | False | False |

### m8a-c-00408

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.335749 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.614568 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 6.878919 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.681354 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.205027 | 0.000000 | False | False |

### m8a-c-00421

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.152288 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.402335 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 0.123187 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 8.007840 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 1.792641 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.085636 | 0.000000 | False | False |

### m8a-c-00429

Observed anomalies: entry, journal, notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 3.061988 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 4.459026 | 0.000000 | True | False |
| journal | GET /work | 20 | 200 | 5.395652 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 6.684872 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 2.214749 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 2.633699 | 0.000000 | False | False |

### m8a-c-00476

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.599337 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 1.091191 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 9.407852 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 0.528709 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 2.851425 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.211491 | 0.000000 | False | False |

### m8a-c-00486

Observed anomalies: journal, notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.697880 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.694853 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 8.142311 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 10.361201 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 2.235436 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.217330 | 0.000000 | False | False |

### m8a-c-00492

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.000000 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 5.369325 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 3.298287 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 2.245892 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.290884 | 0.000000 | False | False |

### m8a-c-00497

Observed anomalies: journal

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.290561 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.531551 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 7.955791 | 0.000000 | True | False |
| notifier | GET /work | 20 | 100 | 1.967692 | 0.000000 | False | False |
| settlement | GET /work | 20 | 100 | 1.293562 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.996394 | 0.000000 | False | False |

### m8a-c-00544

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.383930 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.604224 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 0.000000 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 7.370108 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 1.847730 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 0.891661 | 0.000000 | False | False |

### m8a-c-00613

Observed anomalies: notifier

| Service | Operation | Current | Baseline | LatencyZ | ErrorZ | Latency anomalous | Error anomalous |
|---|---|---:|---:|---:|---:|---|---|
| checkout | GET /work | 20 | 100 | 0.369228 | 0.000000 | False | False |
| entry | GET /work | 20 | 100 | 0.436881 | 0.000000 | False | False |
| journal | GET /work | 20 | 200 | 0.000000 | 0.000000 | False | False |
| notifier | GET /work | 20 | 100 | 4.346783 | 0.000000 | True | False |
| settlement | GET /work | 20 | 100 | 1.173475 | 0.000000 | False | False |
| warehouse | GET /work | 20 | 100 | 1.597081 | 0.000000 | False | False |
