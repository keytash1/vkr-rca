# M8B RCAEval baseline reproducibility

Pinned RCAEval commit: `405c8fd24071af41ceb4b3aabb451e5e3e15d6c6` (1.7.0).

## TraceRCA smoke

- Dataset: RE2-OB.
- Deterministic Phase-0 case: `re2ob_checkoutservice_delay_2` (passed to the method as an opaque trace table; the method does not receive its ground truth).
- Input: pinned Hugging Face Parquet trace.
- Injection timestamp: pinned case index, converted to microseconds as required by the implementation.
- Runtime: 1.114 seconds for the method call on this host.
- Native result: 35 operation-level candidates.
- Native top five:
  1. `checkoutservice_Convert`
  2. `checkoutservice_GetProduct`
  3. `frontendservice_PlaceOrder`
  4. `checkoutservice_PlaceOrder`
  5. `checkoutservice_GetCart`

The official implementation reproduced without source modification after installing its runtime imports: scikit-learn 1.8.0, requests 2.30.0 and tqdm 4.65.0. The package returns operation-level strings. RCAEval's pinned runner supplies an explicit coarse conversion in `main.py`: split the operation token at `_`, strip `-db`, then stable-deduplicate services. The full M8B TraceRCA run reuses exactly that conversion, so its service metrics may be reported as an official coarse-grained comparison without inventing a private projection.

BARO and Multi-source BARO are metric/multi-source methods and cannot consume the locked trace-only corpus without fetching a different input modality. MicroRank is trace-based, but its pinned raw-trace implementation exceeded the 30-second smoke budget on this same case while traversing hundreds of thousands of spans. No upstream source was patched and no partial full-run metric is reported. Unsupported or unstable combinations are kept explicit rather than silently altered.
