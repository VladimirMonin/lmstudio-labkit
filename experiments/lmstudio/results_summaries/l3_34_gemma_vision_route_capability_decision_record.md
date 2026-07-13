# L3.34 Gemma Vision Route Capability Decision Record

Status: historical preparation record, reconciled with compat and native route evidence below.

No live image request was run in the original preparation slice. Later bounded
route evidence is recorded separately in the closure update.

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

## Historical metadata posture

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

## Historical downstream decision

L3.35 image matrix work remains blocked until L3.34 proves at least one eligible Gemma image route. If no eligible route is proven, close image benchmarking as `unsupported_modality` / `blocked`, not as a failed quality benchmark.

## Closure evidence update — 2026-07-10

Runtime metadata later reported vision capability for the target Gemma models,
superseding the committed text-only metadata posture for that runtime. Bounded
route probes then established:

```yaml
compat_png_data_uri_probe:
  models: [E2B, E4B, 12B, 26B]
  payload_accepted: true
  schema_pass: 0
  finish_length: 4
  each_final_loaded_count: 0
native_e4b_gate:
  route: /api/v1/chat
  plain_text:
    status: pass
    non_empty_chars: 506
    max_output_tokens: 128
  minimal_json:
    status: fail
    structure_status: parse_invalid
    truncation_observed: false
    adaptive_action: stop
  tiny_screening: skipped_by_minimal_json_failure
  final_loaded_global_count: 0
```

The native E4B route is proven for non-empty plain text in this one-asset shape.
Structured image output and broader vision screening remain blocked; route
acceptance and plain-text success are not model-quality or JSON admission.

## Superseding full strict-schema route update — 2026-07-13

The historical measurements above remain unchanged. The exact outbound contract
of the four-call compatibility probe is not retained, so those calls are still
contract-unverified rather than schema-bound evidence. The native E4B result also
remains a plain/prompt-only route diagnostic.

A later content-addressed run and reviewed continuation now supersede only the old
conclusion that API-bound structured image transport was unproven:

```yaml
route: /v1/chat/completions
request_contract: image_data_url_plus_response_format_json_schema_strict_true
schemas: [simple_description, medium_objects_text]
models: [E2B, E4B, 12B, 26B]
executed_strict_simple_rows: 16
executed_strict_medium_rows: 16
executed_repeat_rows: 3
strict_image_http_200: 35
strict_image_raw_json: 35
strict_image_schema_pass: 35
controller_validator_rejections: 35
controller_validator_status: preserved_partial_gold_failure_record
semantic_binary_admission: not_assessed_under_valid_gate
production_admission: none
final_global_loaded_count: 0
```

This confirms compatible-route image transport plus strict simple/medium schema
response contracts for 35/35 bounded strict-image rows. Direct pixel/raw review
found 15/16 medium object inventories grounded and all three executed UI repeat
pairs byte-identical. These results remain bounded and do not establish ranking,
broad determinism, or production admission.

The earlier 0/16 controller verdict is no longer binding semantic evidence. Its
partial allow-lists and warning policy were invalid for open-world precision; the
0/16 and 35/35 rejection counts remain preserved as a validator failure record. See
`2026-07-13_native_structured_vision_closure.md` for the qualified decision.
