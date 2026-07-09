# Gemma Family Model Cards

Status: scaffold / current evidence summary. Final L3.36 closure is blocked until L3.31-L3.35 evidence is complete.

No live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifact was produced for this scaffold.

## Current model cards

| model | load status | max proven context | transcript cleanup | structured simple | structured blocks | structured complex | vision route | cache/session | recommended role |
|---|---|---:|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | proven in prior accepted slices | 8192 | accepted | accepted | accepted | prepared only | no image route available in committed metadata | pending | lightweight baseline |
| `google/gemma-4-e4b` | proven in prior accepted slices | 8192 | accepted | accepted | accepted | prepared only | no image route available in committed metadata | pending | quality candidate |
| `google/gemma-4-12b-qat` | proven in prior accepted slices | 8192 | accepted | accepted | accepted | gated after E2B/E4B complex | no image route available in committed metadata | pending | high-quality candidate |
| `google/gemma-4-26b-a4b-qat` | controlled only | 8192 controlled / 16k prepared | accepted controlled only | blocked/not run | blocked/not run | blocked | no image route available in committed metadata | pending | research/capacity constrained |

## Current blocked modes

- 16k/32k live context acceptance: blocked until L3.31a runtime is available and applied context is proven.
- Complex JSON: blocked until L3.32a live canary after L3.31a acceptance or explicit deferral.
- Cache/session: prepared only; no KV reuse proof.
- Vision: blocked/unsupported until metadata-positive image route proof.
- Image matrix: blocked until L3.34 route proof.
- Qwen: out of Gemma closure scope.

## Non-claims

This scaffold does not claim final model-family closure. It records the current accepted baseline and the evidence still required for final L3.36 closure.
