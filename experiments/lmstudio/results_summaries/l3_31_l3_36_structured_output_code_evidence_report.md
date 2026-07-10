# L3.31-L3.36 — Structured Output and Payload Evidence Report

Status: research-only evidence report.

Timestamp: 2026-07-10T10:55:24+05:00

Scope:

- Inspect current LM Studio documentation for structured output and multimodal payload shape.
- Inspect LabKit code for `response_format`, `max_tokens`, image payload handling, matrix transports, live bridge behavior, and managed executor behavior.
- Do not run live inference.
- Do not modify runtime behavior.

## Source evidence

### LM Studio developer documentation

Context7 source: `LM Studio Developer Docs` (`/websites/lmstudio_ai_developer`).

Relevant current documentation excerpts:

- OpenAI-compatible structured output uses `POST /v1/chat/completions` with `response_format.type=json_schema` and a nested `json_schema` object; generated JSON is returned as a string in `choices[0].message.content` and must still be parsed by the caller.
- The same structured-output example includes `max_tokens` in the request payload.
- Native `POST /api/v1/chat` supports text and image inputs through an `input` array with `type: text` or `type: image`; image objects use `data_url`, not `image_url`.

Documentation implication:

- LabKit's strict JSON route should continue to use OpenAI-compatible `/v1/chat/completions` with `response_format` when the target is structured JSON.
- A future image route should not invent `image_url` for the native route; the documented native shape is `data_url` in `/api/v1/chat` input objects.
- `max_tokens` is a first-class request control in the OpenAI-compatible structured-output route and should be explicit in guarded runs where a generation cap is part of the experimental contract.

## Code evidence

### Public request core and matrix transport

Evidence:

- `lmstudio_labkit/requests.py:172-180` defines `ExecutionOptions` with `model_id`, `endpoint_family`, `context_tier`, `temperature`, `timeout_s`, `retry_policy`, and `live`; it has no `max_tokens` or `max_output_tokens` field.
- `lmstudio_labkit/requests.py:47-65` defines `ImageInput` as safe metadata only: content hash, MIME type, dimensions, and label.
- `lmstudio_labkit/requests.py:235-250` can build an image `RequestEnvelope`, but it stores only `ImageInput` metadata and optional text prompt.
- `lmstudio_labkit/benchmarks.py:470-479` defines `MatrixTransport` as an execution seam that returns raw response text in memory plus privacy-safe `RequestResult` metadata.
- `lmstudio_labkit/benchmarks.py:752-756` rejects image live execution before transport dispatch.

Conclusion:

- LabKit has a safe abstract representation for image requests, but no implemented live image payload builder in the public matrix runner.
- Matrix live execution is still text-only by guardrail; this aligns with current L3.34/L3.35 blocking.
- The public request core cannot currently express an explicit per-request `max_tokens` cap, so any executor using only `RequestPlan.options` cannot forward that cap without a contract extension.

### Live bridge

Evidence:

- `lmstudio_labkit/live_bridge.py:53-68` and `lmstudio_labkit/live_bridge.py:88-118` route injected live execution through text-only guardrails.
- `lmstudio_labkit/live_bridge.py:90-92` raises `NotImplementedError` for image plans.
- `lmstudio_labkit/live_bridge.py:121-140` requires explicit live options, bounds request count, rejects stress runs, and requires `allow_remote=True` for non-local base URLs.
- `lmstudio_labkit/live_bridge.py:150-164` persists `base_url_kind` and `base_url_scheme`, not full hostnames.

Conclusion:

- The bridge is correctly safety-biased: it does not own LM Studio lifecycle, does not build image payloads, and does not persist private endpoint URLs.
- There is no evidence that live image execution can be admitted through this bridge today.

### Managed executor

Evidence:

- `lmstudio_labkit/managed_executor.py:42-70` defines `ManagedHostRunner.chat_completion(...)` with `endpoint_path`, `model_id`, `messages`, `response_format`, `temperature`, and `timeout_s`; it has no `max_tokens` parameter.
- `lmstudio_labkit/managed_executor.py:74-90` documents the v1 executor as a narrow text-only `/v1/chat/completions` adapter with explicit context lengths, parallel 1, and temperature 0.
- `lmstudio_labkit/managed_executor.py:91-100` enforces `/v1/chat/completions`, supported context lengths, `parallel=1`, and `temperature=0`.
- `lmstudio_labkit/managed_executor.py:188-197` calls the host runner with messages, `response_format`, temperature, and timeout, but not `max_tokens`.
- `lmstudio_labkit/managed_executor.py:237-253` rejects image modality, non-text modality, non-OpenAI-compatible endpoint families, mismatched context tiers, nonzero temperature, non-JSON response mode, and missing schema.
- `lmstudio_labkit/managed_executor.py:326-339` lowers request schemas into LM Studio `response_format.type=json_schema`.
- `lmstudio_labkit/managed_executor.py:342-351` explicitly lowers LabKit's stricter `prefixItems` schema shape to an LM Studio-compatible runtime schema and relies on LabKit post-generation validation for exact order and per-position constraints.
- `lmstudio_labkit/managed_executor.py:574-592` builds a local `/v1/chat/completions` payload with `model`, `messages`, `response_format`, and `temperature`, but no `max_tokens`.
- `tests/lmstudio_labkit/test_managed_executor_mocked.py:118-145` verifies mocked managed execution forwards `/v1/chat/completions`, temperature, `response_format`, context length, and parallel; it does not verify any `max_tokens` forwarding because the protocol has no such field.

Conclusion:

- The current managed executor supports strict structured JSON over text only.
- It forwards `response_format` correctly, but it cannot forward an explicit generation cap today.
- The L3.31b forensic conclusion that no explicit `max_tokens` was sent by the managed executor is supported by current code.
- If L3.31b repair requires a cap such as 512/1024/2048, that is an implementation-card change to `ExecutionOptions`, `ManagedHostRunner.chat_completion`, `LocalLMStudioHostRunner.chat_completion`, and mocked executor tests.

### Older live smoke helper path

Evidence:

- `tools/lmstudio_lab/live_smoke.py:299-379` builds a strict `response_format` object with `type=json_schema`, `strict=True`, and a schema for factual blocks.
- `tools/lmstudio_lab/live_smoke.py:849-862` scales `max_tokens` from dataset size and caps it at 8192 with a minimum of 512.
- `tools/lmstudio_lab/live_smoke.py:2035-2041` sends `model`, `messages`, `response_format`, `temperature=0`, and `max_tokens` to `/v1/chat/completions` in the chunked structured live helper.
- `tools/lmstudio_lab/live_smoke.py:1080-1131` records context-fit failures with `estimated_input_tokens` and `max_tokens` in structured error metadata.
- `tools/lmstudio_lab/live_smoke.py:1200-1223` records `max_tokens`, `response_format`, prompt hash/chars, and load config in metrics.

Conclusion:

- The older `tools/lmstudio_lab/live_smoke.py` path already has explicit `max_tokens` semantics.
- The newer public `lmstudio_labkit` managed executor path does not.
- Any synthesis document should avoid treating these two code paths as equivalent.

### Offline vision configs and current image gate

Evidence:

- `experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml:35-52` defines an image task and prompt contract for the `ui_settings_ru_001` public-safe asset.
- `experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml:72-80` records the expected capability behavior: text-only models produce `no_image_route_available`, and live image requests are forbidden when the model is text-only.
- `experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml:146-153` keeps `live=false`, `allow_model_loads=false`, `allow_raw_prompt_response_artifacts=false`, `allow_image_live=false`, and `allow_stress=false`.
- `experiments/lmstudio/results_summaries/l3_34_1_vision_probe_repair_decision_record.md:46-55` records the one allowed repair probe shape as a PNG data URI object, plain text response, and `max_tokens=256`.
- `experiments/lmstudio/results_summaries/l3_34_1_vision_probe_repair_decision_record.md:57-80` records HTTP 200 route acceptance but empty content with `finish_reason=length`, and classifies the route as not usable for Gemma runtime in that probe shape.

Conclusion:

- The repo has offline image fixtures, expected outputs, and capability-gated configs.
- The public `lmstudio_labkit` live path still has no image execution implementation, and current Gemma evidence remains blocked for image admission.
- The documented LM Studio native image shape is `data_url`; repo code should not use `image_url` for a future `/api/v1/chat` implementation unless new docs or runtime evidence prove a different accepted shape.

## Durable conclusions

1. Structured JSON route: keep `/v1/chat/completions` plus `response_format.type=json_schema`; LabKit post-validation remains necessary because runtime schema lowering weakens some local constraints such as per-position `prefixItems` constants.

2. Max token cap gap: `tools/lmstudio_lab/live_smoke.py` has explicit `max_tokens`, but `lmstudio_labkit.ManagedLMStudioExecutor` does not. This is the main code-level gap relevant to the L3.31b finish-length/empty-content forensics.

3. Image payload gap: current public LabKit live transports reject image execution; current code contains no `image_url` or `data_url` live payload builder. Context7/LM Studio docs point to native `/api/v1/chat` with image `data_url` objects, while the OpenAI-compatible structured-output path remains text-oriented in current LabKit implementation.

4. Managed executor admission: the current managed executor is a guarded text-only strict JSON adapter. It is suitable for text structured JSON experiments, but not sufficient for image route repair or explicit generation-cap experiments until a separate implementation card extends the request contract.

5. Current L3 synthesis impact: do not promote Gemma 12B blocks@16k until explicit max-token repair evidence exists; do not promote Gemma image/vision until an implemented image payload route and successful non-empty plain-text sanity gate exist.

## Recommended implementation follow-ups

No runtime behavior was changed in this research card. If implementation is authorized separately, the smallest follow-up slices are:

1. Add explicit `max_tokens` to the public managed executor path:
   - extend `ExecutionOptions` with `max_tokens: int | None`;
   - pass it through `ManagedHostRunner.chat_completion`;
   - include it in `LocalLMStudioHostRunner.chat_completion` payload only when set;
   - add mocked tests proving it is forwarded and validated.

2. Add an image-route implementation only after a design card chooses the endpoint contract:
   - native `/api/v1/chat` with `input[].type=image` and `data_url` per current docs;
   - separate from `/v1/chat/completions` strict JSON text route unless runtime evidence proves a safe combined shape;
   - keep raw images and raw prompt/response out of public artifacts.

## Non-claims

- No live LM Studio inference was run for this research card.
- No model was loaded, downloaded, or unloaded by this research card.
- No runtime behavior was modified.
- This report does not claim image support, 12B repair success, or production admission.
