# Third-party components and model provenance

This inventory applies to the explicit RCA Workbench product composition.
It is not a license for the complete research repository or for the services
connected by a user. Reviewed 2026-10-17 against installed Linux ARM64 wheels.
Full license/NOTICE files installed with each dependency must be retained when
redistributing a binary or image; a short SPDX label is not a replacement.
The inspected xgboost-cpu wheel lacks a separate license file; its upstream
copyright and license attribution are additionally supplied in THIRD_PARTY_NOTICES.

## Runtime dependencies

| Distribution | Pinned version | Declared license / notice location |
|---|---|---|
| numpy | 2.4.4 | BSD-3-Clause with bundled 0BSD/MIT/Zlib/CC0 notices; wheel license files |
| scipy | 1.18.1 | BSD-style project license plus bundled component notices; distribution LICENSE files |
| scikit-learn | 1.8.0 | BSD-3-Clause; COPYING |
| xgboost-cpu (Linux), xgboost (other supported platforms) | 3.2.0 | Apache-2.0; distribution license |
| joblib | 1.6.0 | BSD-3-Clause; LICENSE.txt |
| threadpoolctl | 3.6.0 | BSD-3-Clause; LICENSE |
| cloudpickle | 3.1.2 | BSD-3-Clause; LICENSE |

## Optional assistant environment

| Distribution | Pinned version | Declared license |
|---|---|---|
| PyJWT | 2.15.1 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause, bundled notices retained |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.11 | BSD-3-Clause |
| tiktoken | 0.12.0 | MIT |
| regex | 2026.9.29 | Apache-2.0 AND CNRI-Python |
| requests | 2.34.2 | Apache-2.0, LICENSE and NOTICE |
| certifi | 2026.7.22 | MPL-2.0 |
| charset-normalizer | 3.5.2 | MIT |
| idna | 3.20 | BSD-3-Clause |
| urllib3 | 2.8.0 | MIT |

The pinned Python base image and Debian/libgomp1 remain separately licensed.
Their installed notices are retained in the image, including Python's license
and Debian copyright files. A dependency inventory is not a vulnerability audit.
The optional source installation warms the tokenizer separately using the
official tiktoken distribution mechanism. The optional assistant image warms
the public o200k vocabulary at build time and checks SHA-256
`446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d`.
There is no vocabulary download during a worker job. Credentials are never
included in either composition. Public vocabulary data is not an LLM model
or a provider subscription.

## Parameters and benchmark boundaries

The JSON model parameters are locally trained research artifacts, not imported
pretrained models. Their hashes and feature lineage are recorded by the sealed
freeze manifest. Earlier model files still required by the frozen computation
are runtime dependencies; they are not additional methods offered to the user.
No raw training corpus, gold labels, fault controllers or benchmark applications
are part of the product allowlist.

The original training experiments used the Social Network benchmark from
[DeathStarBench](https://github.com/delimitrou/DeathStarBench). Its README and
license declarations need revision-specific treatment rather than assuming one
license for all benchmark contents. The source is not copied into this product.
The independent research experiment used the OpenTelemetry demo; the engineering
connection checks additionally used [Spring Petclinic Microservices](https://github.com/spring-petclinic/spring-petclinic-microservices).
These are experimental environments, not mandatory runtime dependencies or
applications owned by RCA Workbench. Cite the underlying benchmark publications
in the research report; do not relicense their source or illustrations as ours.

OpenAI is an optional external provider. Its service terms, disclosure policy,
account eligibility and allowance are independent of this source license.
The product neither includes a subscription nor promises access for another user.
