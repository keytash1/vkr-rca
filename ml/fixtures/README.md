# Deterministic ML fixture

The Python test suite uses rca_ml.fixtures.fixture_dataset as a small deterministic fixture. It creates truth-free m6-v1 snapshots separately from external labels for all root-service and fault-type pairs. It is intentionally synthetic and is never mixed with the live M7 experiment.
