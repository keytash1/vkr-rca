# M10B defense demo guide

M10B is a presentation layer over the research method frozen at M10A. It does not retrain a model, regenerate an experiment, or introduce a new claim. The UI deliberately separates the controlled live runtime from the pinned external benchmark replay.

## Russian interface and first-run guidance

All primary controls, headings, status labels, scenario names, explanations, and outcomes in the defense UI are in Russian. Technical names such as RCA, trace/span, LambdaMART, AC@1, MRR, SHAP, service IDs, dataset IDs, and model versions remain visible where they are part of the method. Every required term has a short Russian tooltip available by hover, keyboard focus, or click.

On the first visit in each browser-tab session, a welcome dialog offers two paths: **Показать инструкцию** opens the self-contained **Как пользоваться** tab, while **Перейти к демонстрации** opens the live lab. The choice is stored only in `sessionStorage`, so a newly opened tab shows the introduction again.

The instruction tab contains:

- a six-step Quick Start using the Payment-latency scenario;
- a plain-language explanation of the system and the propagated-latency problem;
- the distinction between local/exclusive duration and CPU time;
- the incident-to-ranking pipeline and explanations of metrics, traces, and topology;
- separate instructions for the live M6 path and frozen M9B RCAEval replay;
- Learning-to-Rank, identity-free features, prediction contributions, and truth isolation;
- AC@1, AC@3, MRR, confidence-interval definitions, frozen research results, the rejected M9A result, and limitations.

Research values in both **Результаты исследования** and **Как пользоваться** are loaded from the same verified frozen API response. They are not copied into the HTML or JavaScript as presentation constants.

## Prerequisites

- Docker with Docker Compose;
- Python 3.12+ environment created by `make ml-setup`;
- `curl` and Go 1.26 for preparation and smoke checks;
- free local ports `18000`, `18080`, `8081`, `8082`, `18090`, and `16686` by default.

All demo and fault-control endpoints are development-only. The demo port binds to `127.0.0.1`; do not expose this stack as a production control plane.

## Prepare once while online

```bash
make demo-prepare
```

Preparation verifies the M10A freeze manifest, the pinned RCAEval index hash and raw Parquet schemas. It downloads only the eight cases listed in `demo/cases.json` when they are absent. For each case it reuses the existing M8B Go adapter and M9B feature extractor, runs the appropriate frozen M9B cross-system fold, persists a truth-free prediction, and only then writes the separate evaluation label.

Raw metrics, traces, derived features, predictions, and labels live under ignored `demo-data/` and `external-data/`. Nothing from the raw RCAEval corpus is committed.

After preparation, verify that `demo-data/manifest.json` and `demo-data/integrity.json` exist. Re-running preparation is deterministic and validates predictions against the frozen expected Top-1 and actual-rank outcomes.

## Start and stop

```bash
make demo-up
```

Open `http://127.0.0.1:18000`.

The combined Compose configuration starts Gateway, Orders, Payment, the OpenTelemetry Collector, Jaeger, RCA, and the read-only demo server. The ordinary `docker-compose.yml` is not changed; `docker-compose.demo.yml` only adds the defense UI/backend.

Stop everything:

```bash
make demo-down
```

Prepare and start in one command:

```bash
make demo
```

Run the complete acceptance smoke:

```bash
make demo-smoke
```

The smoke calibrates the live baseline, verifies the Orders latency acceptance case, replays one frozen success and one frozen miss, reveals their labels separately, checks research results, and revalidates all research hashes.

## Five-to-seven-minute walkthrough

1. Open **Архитектура** and point out the two isolated paths: **Живая демонстрация** is M6 online trace/topology RCA; **Внешний набор данных** is frozen M9B multi-source inference.
2. Open **Живая демонстрация**, click **Сбросить и откалибровать**, and wait for the known healthy state.
3. Select **Задержка Payment**, click **Сгенерировать 20 запросов**, and show the graph `gateway → orders → payment`. All services inherit latency, while Payment has the strongest local/exclusive evidence and should rank first.
4. Select **Задержка Orders**, generate traffic again, and show that Orders ranks first despite Gateway also being slow. Use the evidence table to contrast local exclusive time with propagated wait.
5. Open **Внешний набор данных** and select a blind external case. Before analysis, show only dataset/system/time/coverage. Click **Проанализировать инцидент** and inspect the frozen model route, Top-K ranking, and grouped predictive contributions.
6. Click **Показать фактическую первопричину**. For a miss, keep the original ranking visible and point out the actual rank; do not replace it with the label.
7. Open **Результаты исследования**. Show the 360-case metric result and BARO comparison, the qualified fusion claim, and the rejected M9A CUSUM result.
8. End with limitations: external trigger, service granularity, unobservable roots, no logs, no calibrated probabilities, predictive—not causal—explanations, and a limiting autonomous detector.

## Offline defense mode

`make demo-prepare` is the only step that may require the network. It also builds the local offline adapter and validates all prepared predictions. Once the required Docker images have been built by one successful `make demo-up`, disconnecting the network does not affect:

- the live lab;
- the eight prepared RCAEval replays;
- research results and claims;
- architecture and model registry pages.

To rehearse the exact offline scenario: run `make demo-prepare`, run `make demo-up` once to build images, run `make demo-down`, disconnect the network, and run `make demo-up` again.

## Port overrides and recovery

Override host ports without changing container addresses:

```bash
DEMO_PORT=18100 GATEWAY_PORT=18180 RCA_HTTP_PORT=18190 make demo-up
```

Open the corresponding `DEMO_PORT`. If startup fails, run the same variables with `make demo-down`, inspect `docker compose -f docker-compose.yml -f docker-compose.demo.yml logs`, then retry.

If a live operation times out, confirm all containers are healthy, click Reset again, and wait for calibration to finish. The UI aborts frontend operations and the backend maps upstream timeouts to a visible error instead of leaving an infinite spinner.

## Known limitations

- The Live Lab has trace/topology/anomaly evidence and M6 rankings; it is not presented as the M9B metric model.
- The external replay set is a curated demonstration set, not a new evaluation sample. Frozen aggregate claims remain in M10A.
- Replay analysis serves predictions prepared with the frozen Python pipeline so the defense remains fast and offline.
- Ground truth is physically separate from prediction input/output, but the case list is public in the repository for reproducibility.
- The demo server intentionally has no authentication and binds locally.
- Scores are ranking/diagnostic scores, not probabilities or calibrated confidence.
