# Qwen 3.5 full-GPU matrix model cards

Date: 2026-07-14

Status: evidence-scoped cards for a zero-inference capability stop. These are not general model cards or deployment recommendations.

Machine-readable companion: `2026-07-14_qwen35_full_gpu_model_cards.json`.

## Shared evaluation boundary

The reviewed matrix contains 66 candidate rows and 68 planned inference calls. All 66 rows were stop-gated and no inference call executed. Consequently, neither card contains a quality, ranking, or production recommendation.

### Qwen 3.5 4B — Q4_K_M

**Candidate identity**

- Catalog model: `qwen/qwen3.5-4b`
- Exact selected variant: `qwen/qwen3.5-4b@q4_k_m`
- Catalog modality: text and vision
- Advertised reasoning control: `off` and `on`

**Executed evidence**

- 36 candidate rows and 37 planned inference calls
- 1 CLI load attempt and 1 successful materialization
- Maximum GPU placement requested
- Observed context length 8192 and parallelism 1
- GPU KV-cache placement observed
- 1 unload request and verified return to global loaded count zero
- 0 inference calls and 0 raw inference responses

**Admission decision**

`not_proven_fail_closed`

The executed runtime snapshot did not provide authoritative all-layer GPU placement or the explicit negative fallback, downgrade, and thrash facts required by the hard gate. The successful lifecycle load does not admit the model to inference.

**Supported use statement**

No workload use is recommended from this matrix. The evidence only shows that the pinned variant can complete the bounded CLI load/unload lifecycle at the requested materialization shape.

**Not evaluated**

Inference transport, strict route behavior, JSON Schema, business validation, semantic fidelity, 8k inference, 16k context, cache/session behavior, concurrency, vision grounding, OCR, and repeatability.

**Re-entry condition**

A new reviewed canary must positively attest all required full-GPU and explicit-negative runtime facts before any model-quality call.

### Qwen 3.5 9B MTP — Q4_K_S catalog candidate

**Candidate identity**

- Catalog model: `qwen3.5-9b-mtp`
- Catalog quantization: Q4_K_S
- Catalog modality: text and vision
- Selected execution variant: unavailable
- Advertised reasoning control in the captured metadata: none; the manifest omitted the field rather than inventing support

**Executed evidence**

- 30 candidate rows and 31 planned inference calls
- 0 load attempts
- 0 materialized instances
- 0 inference calls and 0 raw inference responses
- All 30 rows stop-gated because immutable execution identity was unavailable

**Admission decision**

`execution_identity_unavailable_fail_closed`

The model was not loaded. This decision says nothing about whether the candidate could satisfy full-GPU placement after a correctly identity-bound load.

**Supported use statement**

No workload use is recommended from this matrix. The captured catalog entry is insufficient to bind an executed model instance.

**Not evaluated**

Lifecycle load, full-GPU execution, inference transport, strict route behavior, JSON Schema, business validation, semantic fidelity, context, cache/session behavior, concurrency, vision grounding, OCR, and repeatability.

**Re-entry condition**

Pin an immutable selected-variant and artifact identity, then run a newly reviewed full-GPU canary. Do not infer execution identity from the catalog key, parameter count, quantization label, or memory estimate alone.

## Cross-card comparison boundary

No comparative result exists. The 4B candidate reached materialization while the 9B MTP candidate stopped before load; neither reached inference. The cards must not be used to rank quality, speed, memory efficiency, schema adherence, long-context behavior, cache reuse, concurrency, or vision quality.

## Deployment boundary

Neither candidate is production-admitted, deployment-ready, or approved for unattended processing by this matrix. A future positive recommendation requires a new execution denominator, raw response review, semantic adjudication, and workload-specific safety gates after full-GPU admission.
