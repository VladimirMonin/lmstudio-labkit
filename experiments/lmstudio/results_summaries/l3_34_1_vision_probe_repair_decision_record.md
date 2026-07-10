# L3.34.1 — Vision Structured Probe Repair Decision Record

Status: stopped at Phase 1 by design.

Timestamp: 2026-07-10T10:27:39+05:00

Sanitized local artifact:

```text
experiments/lmstudio/live_runs/l3_34_1_vision_probe_repair_20260710/sanitized_vision_probe_repair_summary.json
```

Live-demo summary directory:

```text
docs/live_demo/latest_gemma_vision_probe_repair/
```

No raw prompt/response text is committed.

## Scope constraints followed

Performed:

- E4B first;
- asset `ui_settings_ru_001`;
- PNG data URI object payload;
- plain text response;
- `max_tokens=256`;
- one attempt;
- cleanup final zero.

Not performed:

- Phase 2 minimal JSON;
- Phase 3 simple_description;
- E2B / 12B / 26B follow-up;
- 10 assets;
- medium/complex schema;
- full image matrix;
- Qwen VL;
- parallel/session/warmup.

## Phase 1 — text-only image route sanity

Request shape:

```yaml
model: google/gemma-4-e4b
asset: ui_settings_ru_001
payload: PNG data URI object
response: plain text
max_tokens: 256
output_language: ru_ru
```

Result:

```yaml
status: fail
http_status: 200
finish_reason: length
prompt_tokens: 298
completion_tokens: 256
response_char_count: 0
final_loaded_count: 0
load_verified: true
cleanup_verified: true
```

Decision:

```yaml
phase1_plain_text_status: failed_finish_length_empty_content
route_http_status: accepted_200
image_route_usable_for_gemma_runtime: false
stop_reason: plain_text_fails_with_finish_length
```

The route accepts the request at HTTP/API level, but Gemma E4B did not produce non-empty plain text before `finish_reason=length` at `max_tokens=256`.

Per the phase contract, the repair probe stops here.

## Phase 2 — minimal JSON

Not run.

Reason:

```yaml
blocked_by: phase1_plain_text_failed
```

## Phase 3 — simple_description

Not run.

Reason:

```yaml
blocked_by: phase1_plain_text_failed
```

## Other Gemma models

Not run.

Reason:

```yaml
blocked_by: E4B did not pass phases 1-3
```

## Required answers

### 1. Does image plain text work?

No for E4B in this runtime/probe shape.

```yaml
vision_plain:
  model: google/gemma-4-e4b
  status: blocked
  reason: finish_length_empty_content_at_256
```

### 2. Does minimal JSON work?

Unknown / not run. It is blocked by Phase 1 failure.

### 3. Does simple_description work?

Unknown / not run. It is blocked by Phase 1 failure.

### 4. Is failure max_tokens or route/model limitation?

The evidence separates API route acceptance from usable generation:

```yaml
api_route_acceptance: true
usable_plain_text_generation: false
observed_failure: finish_length_empty_content_at_explicit_256
```

Because plain text with an explicit small cap still returns empty content and `finish_reason=length`, the current classification is runtime/model route limitation for Gemma image generation, not a strict-schema issue.

Could a larger max_tokens repair plain text? Not tested by design. The requested Phase 1 acceptance required `finish_length=0` at `max_tokens=256`; it failed.

### 5. Which Gemma models are eligible for L3.35?

None.

```yaml
l3_35_eligible_models: []
blocked_reason: E4B phase1 plain text image sanity failed; other models were not eligible to run
```

## Decision

```yaml
l3_34_1_decision:
  image_payload_route: http_accepted
  phase1_plain_text: failed_finish_length_empty_content
  phase2_minimal_json: not_run
  phase3_simple_description: not_run
  l3_35_eligible_models: []
  l3_35_status: blocked
```
