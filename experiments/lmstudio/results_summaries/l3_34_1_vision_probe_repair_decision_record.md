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

## Follow-up route investigation

Status: research-only, no new live image request was run.

### Existing local evidence

Two sanitized local summaries now point to the same failure class:

- `experiments/lmstudio/live_runs/l3_34_gemma_vision_route_probe_20260710/sanitized_route_probe_summary.json` — all four Gemma models reached HTTP/API acceptance but ended with `finish_reason=length`, no JSON/schema pass, and final loaded count zero.
- `experiments/lmstudio/live_runs/l3_34_1_vision_probe_repair_20260710/sanitized_vision_probe_repair_summary.json` — the narrower E4B Phase 1 plain-text probe used PNG data URI object payload and `max_tokens=256`; it returned HTTP 200, `completion_tokens=256`, `finish_reason=length`, and `response_char_count=0`.

This is stronger evidence than a strict-schema failure: the route was accepted, but the compat response envelope did not produce usable assistant content.

### Current LM Studio API expectation

Current LM Studio docs distinguish three relevant shapes:

1. Native REST chat endpoint: `POST /api/v1/chat` accepts local image data as `input` array items. The documented image request shape is:

   ```json
   {
     "model": "qwen/qwen3-vl-4b",
     "input": [
       {"type": "text", "content": "Describe this image in two sentences"},
       {"type": "image", "data_url": "data:image/png;base64,..."}
     ],
     "context_length": 2048,
     "temperature": 0
   }
   ```

   Response text is returned under `output[]` message items, not under OpenAI-compatible `choices[].message.content`.

2. LM Studio Python/TypeScript SDK image input uses prepared image handles and documents JPEG, PNG, and WebP support. That supports the idea that image bytes are valid input only for VLM-capable models/routes, not for text-only model metadata.

3. `/v1/responses` supports vision-enabled models with `input_image` and `image_url` for remote image URLs. This is useful as a compatibility route check, but it is not the best first path for LabKit's local public-safe fixture unless the fixture is explicitly served or otherwise made available without committing/private leaking raw assets.

Sources checked:

- `https://raw.githubusercontent.com/lmstudio-ai/docs/main/1_developer/2_rest/chat.md`
- `https://raw.githubusercontent.com/lmstudio-ai/docs/main/1_python/1_llm-prediction/image-input.mdx`
- `https://raw.githubusercontent.com/lmstudio-ai/docs/main/2_typescript/2_llm-prediction/image-input.mdx`
- `https://lmstudio.ai/blog/openresponses`

### Likely cause and repair direction

The next repair hypothesis should not be “increase `max_tokens` and rerun the same compat payload” as the primary path. The observed `completion_tokens == max_tokens == 256` with empty extracted content can also mean LabKit is probing the wrong response surface for image generation:

- The existing probe used an OpenAI-compatible chat-completions-style envelope and extracted content from `choices[].message.content`.
- The current native LM Studio image route is documented as `/api/v1/chat` with `input` text/image objects and an `output[]` response envelope.
- The cap parameter also differs by route: `/api/v1/chat` uses `max_output_tokens`, while chat completions uses `max_tokens`.

Therefore the next narrow rerun should test route/envelope first, then cap:

```yaml
recommended_next_card: L3.34.2 native REST image route canary
scope:
  models: [google/gemma-4-e4b]
  asset: ui_settings_ru_001
  route_order:
    - /api/v1/chat
  payload:
    input:
      - {type: text, content: plain_text_ru_prompt}
      - {type: image, data_url: data:image/png;base64,...}
    temperature: 0
    max_output_tokens: 128
  extraction:
    response_surface: output[] message content
acceptance:
  - http_status: 200
  - non_empty_output_text: true
  - finish_or_stop_reason_not_length_if_reported: true
  - final_loaded_count: 0
  - no_raw_prompt_response_or_image_bytes_committed: true
stop_conditions:
  - if native route rejects image data_url: classify route_rejected_image_payload
  - if native route returns output[] empty with length at 128: optionally repeat same route once at max_output_tokens=512, then stop
  - do not run E2B/12B/26B, JSON phases, L3.35, or broader image matrix until plain text passes
```

If `/api/v1/chat` passes plain text, then a separate narrow card may test minimal JSON/simple_description on the same route and same model. If `/api/v1/chat` fails the same way, keep L3.35 blocked and classify the blocker as native-image-route/model capability failure for current Gemma runtime evidence, not as a validator/schema issue.
