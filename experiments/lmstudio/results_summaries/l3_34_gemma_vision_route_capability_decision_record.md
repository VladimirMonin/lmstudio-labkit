# L3.34 Gemma Vision Route Capability Decision Record

Status: prepared-only. No live image request was run.

## Scope

L3.34 decides whether any Gemma model is eligible for image-route testing before image quality benchmarking. It is a capability gate, not an image quality benchmark.

Prepared config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml
```

Latest placeholder:

```text
docs/live_demo/latest_gemma_vision_route_probe/README.md
```

## Current metadata posture

The committed Gemma specs in the prepared config remain text-only:

| model | committed modalities | current L3.34 status |
|---|---|---|
| `google/gemma-4-e2b` | `text` | `no_image_route_available` |
| `google/gemma-4-e4b` | `text` | `no_image_route_available` |
| `google/gemma-4-12b-qat` | `text` | `no_image_route_available` |
| `google/gemma-4-26b-a4b-qat` | `text` | `no_image_route_available` |

Because the committed specs are text-only, the prepared image task should plan zero executable request cells and report `unsupported_modality` skips. This is not a model-quality failure.

## Prepared tiny route probe shape

```yaml
asset:
  - ui_settings_ru_001
schema:
  - simple_description
resize_profile:
  - max_side_1024
output_language:
  - ru_ru
max_requests_per_eligible_model: 1
```

The route-probe task preserves visible OCR text in its original language and uses `output_language` only for description/summary fields.

## Safety gates as committed

```yaml
live: false
allow_image_live: false
allow_model_loads: false
allow_model_downloads: false
allow_remote_base_url: false
allow_raw_prompt_response_artifacts: false
allow_stress: false
```

No live LM Studio call, model load, model download, remote inference, image request, stress run, raw prompt artifact, or raw response artifact is claimed by this record.

## Future live acceptance criteria

A future live L3.34 route probe may be considered accepted only if all of these are true:

- read-only metadata is image/multimodal-positive for an eligible Gemma model;
- image payload is accepted by the runtime route;
- JSON parse passes;
- `simple_description` schema validation passes;
- privacy scan passes;
- final loaded-like count is zero.

If the route rejects image payloads after metadata eligibility, classify the result as `route_rejected_image_payload` with `quality_failure=false`.

## Downstream decision

L3.35 image matrix work remains blocked until L3.34 proves at least one eligible Gemma image route. If no eligible route is proven, close image benchmarking as `unsupported_modality` / `blocked`, not as a failed quality benchmark.
