# M12 Claim Registry

## Zero-shot new-system transfer

- CLAIM: Zero-shot new-system transfer.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: WEAK.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: M11 Top-5 vs chance and generic metric heuristic.
- METRIC: AC@1/MRR.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: [0.1652845238095238, 0.4275994047619048].
- CLUSTER CI: [0.1469410714285715, 0.4552458333333331].
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.

## M11 Top-5 gain transfer

- CLAIM: M11 Top-5 gain transfer.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: NOT_SUPPORTED.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: Frozen M10D Top-3.
- METRIC: AC@1/MRR with AC@3 guardrail.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: [-0.0020000000000000018, 0.006333333333333413].
- CLUSTER CI: [-0.0029999999999998916, 0.008000000000000007].
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.

## Candidate-universe coverage

- CLAIM: Candidate-universe coverage.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: SUPPORTED.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: Full metadata-derived service universe.
- METRIC: candidate coverage.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: not applicable.
- CLUSTER CI: not applicable.
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.

## Frozen service-invariant representation usefulness

- CLAIM: Frozen service-invariant representation usefulness.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: WEAK.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: Chance and generic metric heuristic.
- METRIC: AC@1/MRR.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: [-0.10578571428571415, 0.02454761904761883].
- CLUSTER CI: [-0.13028571428571423, 0.045428571428571485].
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.

## Production-like telemetry adapter feasibility

- CLAIM: Production-like telemetry adapter feasibility.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: SUPPORTED_WITH_QUALIFICATION.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: one-second Prometheus metrics.
- METRIC: coverage/adapter failures.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: not applicable.
- CLUSTER CI: not applicable.
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.

## Missing-modality behavior

- CLAIM: Missing-modality behavior.
- HYPOTHESIS: The frozen service-invariant pipeline remains useful without M12 training.
- STATUS: DESCRIPTIVE_ONLY.
- DATASET: M12 Hotel Reservation locked-v1.
- DATA ROLE: USED_TEST.
- SYSTEM: DeathStarBench Hotel Reservation.
- PROTOCOL: `docs/m12-protocol.md`; one-time evaluation after SHA-256 freeze.
- DENOMINATOR: 50 independently valid incidents.
- BASELINE: frozen missing-trace semantics.
- METRIC: ranking metrics.
- RESULT: AC@1 0.5400; MRR 0.6797; coverage 1.0000.
- INCIDENT CI: not applicable.
- CLUSTER CI: not applicable.
- LIMITATION: one public system, five container-scoped fault families; trace features absent from canonical inference.
