# Native E4B Vision Sequential Gate Decision Record

Status: stopped after Gate 2 by the required stop-on-failure policy.

Task: `t_91fd364e`

Timestamp: 2026-07-10T13:29:08Z

## Scope

The live run was restricted to:

- model `google/gemma-4-e4b`;
- one public-safe synthetic image, `ui_settings_ru_001`;
- native `POST /api/v1/chat`;
- sequential execution with one loaded instance;
- context length 8192 and temperature 0;
- hashes, counts, route metadata, and sanitized validation aggregates only.

The image request demonstrably used the native route and native envelope:

```yaml
route: /api/v1/chat
payload_shape: input:[text(content),image(data_url)]
response_top_level_keys:
  - model_instance_id
  - output
  - response_id
  - stats
```

No raw prompt, raw response, or embedded image data is stored in this record.

## Gate order and stop policy

```yaml
gate_order:
  - gate1_plain_text
  - gate2_minimal_json
  - gate3_tiny_screening
stop_on_first_failed_gate: true
```

## Gate 1: plain text

Result: pass.

```yaml
http_status: 200
max_output_tokens: 128
native_output_envelope: true
non_empty_plain_text: true
output_text_char_count: 506
finish_reason_reported: false
latency_ms: 9473.806
load_verified: true
cleanup_verified: true
final_loaded_global_count: 0
```

The runtime accepted the image through the native route and returned non-empty output from `output[]`. The response did not report a length stop.

## Gate 2: minimal JSON with adaptive budget

Result: fail; adaptive policy stopped after the first stage.

```yaml
adaptive_budget_stages:
  - 256
  - 512
  - 1024
attempt_count: 1
attempt_1:
  http_status: 200
  max_output_tokens: 256
  native_output_envelope: true
  non_empty_output_text: true
  output_text_char_count: 1048
  structure_status: parse_invalid
  truncation_observed: false
  budget_action: stop
  budget_reason: malformed_json
parse_pass: false
schema_and_quality_pass: false
load_verified: true
cleanup_verified: true
final_loaded_global_count: 0
```

This is a structured-output failure, not an image payload rejection. The adaptive policy correctly did not escalate: the response was malformed JSON rather than incomplete JSON, and the native response reported neither a length stop nor token-count evidence of truncation.

## Gate 3: tiny image screening

Result: not run.

```yaml
blocked_by: gate2_minimal_json_failed
```

Running Gate 3 after the failed minimal-JSON gate would have violated the required ordering and stop condition.

## Final decision

```yaml
native_plain_text_route: accepted
minimal_json_route: failed_malformed_json_without_truncation
image_payload_rejected: false
tiny_screening_status: skipped_by_gate2_failure
broader_vision_matrix_status: blocked
final_loaded_global_count: 0
final_cleanup_verified: true
```

The native E4B image route is proven for non-empty plain text in this bounded shape. It is not admitted for structured image output or broader image screening because the minimal JSON gate failed.

## Non-claims

- No Qwen, E2B, 12B, or 26B model was run.
- No 32k context, stress, parallel execution, session mode, or broad vision matrix was run.
- No raw prompt, raw response, or image bytes are committed.
- Plain-text route success is not a claim of structured-output or image-quality acceptance.
