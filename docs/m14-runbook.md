# M14 locked experiment runbook

Run from the repository root on `research/m14-final-locked-transfer`.
The scientific contract is `docs/m14-protocol.md`; deployment-only exceptions
are recorded in `docs/m14-engineering-log.md`. Never change the frozen method
in response to Astronomy Shop predictions.

## Build and readiness

The upstream checkout must match the SHA in `deploy/m14/config.json` with no
tracked modifications. `scripts/m14/setup.sh` prepares that checkout.
Allow enough free space on both the host and the Docker data filesystem.
Do not prune other projects' data or stop their containers without permission.

For resource-constrained machines, build the 12 candidate images individually:

```sh
export M14_ROOT="$PWD"
export DEMO_VERSION=m14-locked
docker compose --project-name vkr-rca-m14 \
  -f external-data/m14/opentelemetry-demo/compose.yaml \
  -f deploy/m14/compose.yml build SERVICE
```

Candidates: `ad`, `cart`, `checkout`, `currency`, `email`, `frontend`,
`frontend-proxy`, `payment`, `product-catalog`, `quote`, `recommendation`,
`shipping`. Once built, the collection command builds the two small tooling
images and starts the stack, reusing cached application layers:

```sh
.venv/bin/python scripts/m14/run.py up
.venv/bin/python scripts/m14/run.py ready
.venv/bin/python scripts/m14/workload.py --duration 20
```

Inspect healthy HTTP outcomes, Docker restart/OOM state and metric/trace
coverage. Do not begin collection while any image build is still running.
Record co-resident containers and any approved temporary suspension. The
experiment is a single-host controlled deployment, not production evidence.

## Collect without predictions

```sh
.venv/bin/python scripts/m14/run.py healthy
.venv/bin/python scripts/m14/run.py canary
.venv/bin/python scripts/m14/run.py corpus
```

Use the default locked durations: 300-second warm-up, 900-second baseline,
30-second incidents. Healthy-only baselines are fitted before injection.
Canaries validate mechanisms only; they are not part of the 50-incident corpus.
Corpus progress is checkpointed under
`external-data/m14/runs/locked-v1/locked/`. Resume with the same `corpus`
command after checking that the stack and baseline context remain valid.
Never delete failed attempts to improve a ranking. Mechanical failures and
retries must be disclosed. A missing or corrupt checkpoint is not permission
to fabricate or silently drop an incident.

## Seal, score once, open once

```sh
.venv/bin/python scripts/m14/run.py freeze
```

Review and commit the fitted healthy artifacts, frozen dependency inventory
and freeze manifest before scoring. Once the seal exists, the collection CLI
refuses commands that would overwrite readiness, plans, baselines or corpus;
shutdown remains available. The scorer verifies dependency and input
hashes and does not read the sealed truth file:

```sh
PYTHONPATH=ml .venv/bin/python -m rca_ml.m14_evaluate score
PYTHONPATH=ml .venv/bin/python -m rca_ml.m14_evaluate open
```

Do not remove scoring/opening markers or alter sealed files to rerun the test.
Opening changes the data role to `USED_TEST` and the research status to
`FINAL_RESEARCH_FREEZE`, regardless of the verdict. Publish the full denominator,
pooled and grouped results, uncertainty, error analysis and limitations.
If the mechanical experiment cannot be completed, report `BLOCKED`, not an
invented scientific verdict.

## Verification and cleanup

```sh
go test ./...
PYTHONPATH=ml .venv/bin/python -m unittest discover -s ml/tests
git diff --check
.venv/bin/python scripts/m14/run.py down
```

`down` targets only the M14 Compose project and does not delete volumes. Restore
only the exact unrelated containers temporarily stopped with user approval.
Keep raw experimental evidence; it is ignored by Git, not disposable cache.
