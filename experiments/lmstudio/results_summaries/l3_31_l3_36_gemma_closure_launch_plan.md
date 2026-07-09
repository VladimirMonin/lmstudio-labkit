# L3.31-L3.36 Gemma Closure Launch Plan

Status: launch-planning artifact.

No live inference, model load, model download, image request, cache benchmark, stress run, or raw prompt/response artifact was produced for this document.

## Purpose

This document turns the Gemma closure strategy into a launchable execution plan.

The closure target is not a yes/no answer to "does Gemma work". The target is an admission matrix:

```text
model x task x JSON structure x language x context x cache/session x image route
```

Every cell must end with one of:

- `accepted`
- `accepted_with_constraints`
- `prepared_only`
- `runner_blocked`
- `blocked`
- `research_only`
- `unsupported_modality`
- `needs_capability_proof`

## Models in scope

```yaml
gemma_models:
  - google/gemma-4-e2b
  - google/gemma-4-e4b
  - google/gemma-4-12b-qat
  - google/gemma-4-26b-a4b-qat
```

## Accepted baseline before this closure wave

L3.29 accepted the executable 8192 live slice:

```yaml
executed_attempt_count: 113
pass_count: 113
fail_count: 0
hard_fail_count: 0
privacy_scan_status: pass
final_loaded_like_count: 0
```

Accepted at `context_tier=8192`:

| model | transcript_cleanup/simple | structured_json/simple | structured_json/blocks | notes |
|---|---:|---:|---:|---|
| `google/gemma-4-e2b` | accepted | accepted | accepted | 8192 proven |
| `google/gemma-4-e4b` | accepted | accepted | accepted | 8192 proven |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted | 8192 proven |
| `google/gemma-4-26b-a4b-qat` | accepted controlled only | blocked | blocked | controlled transcript cleanup only |

Structured JSON is not currently a Gemma weakness after the L3.28d.1 repair and L3.29 structured JSON result.

## Already prepared in the current pushed slice

Commit:

```text
5159c87719bef55b71c9243ba425f462ba9823ca
```

Prepared/pushed artifacts:

### L3.31

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_31a_gemma_context_canary.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_31b_gemma_context_screening.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_31c_gemma_26b_context_controlled.yaml
experiments/lmstudio/results_summaries/l3_31_gemma_context_screening_decision_record.md
docs/live_demo/latest_gemma_context_screening/README.md
```

Important launch boundary:

- `matrix.l3_31a_gemma_context_canary.yaml` is the only initial live candidate after explicit live approval.
- `matrix.l3_31b_gemma_context_screening.yaml` remains prepared-only until split by context tier or runner grouping is explicitly implemented.
- `matrix.l3_31c_gemma_26b_context_controlled.yaml` remains prepared-only/controlled.

### L3.32

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_32b_gemma_complex_json_canary_12b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_32c_gemma_structured_json_complexity_screening.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_32d_gemma_26b_structured_json_tiny.yaml
experiments/lmstudio/results_summaries/l3_32_gemma_json_complexity_decision_record.md
docs/live_demo/latest_gemma_json_complexity/README.md
```

Important launch boundary:

- L3.32a is the first complex JSON live candidate after explicit approval.
- L3.32b starts only after L3.32a is green.
- L3.32c is capped prepared screening; do not run the broad shape before canaries.
- L3.32d is 26B simple-only tiny prepared control; no 26B complex in L3.32.

## Execution order

Strict order:

1. L3.31 context windows.
2. L3.32 JSON complexity.
3. L3.33 cache/session/warmup.
4. L3.34 image route capability.
5. L3.35 image matrix, only if L3.34 proves at least one eligible image-capable Gemma route.
6. L3.36 final Gemma model card synthesis.

Do not run L3.35 before L3.34.

Do not mix cache/session work with parallel/stress.

Do not run Qwen in Gemma phases.

---

# L3.31 launch contract — context windows

## Goal

Close higher context windows as `accepted` or `runner_blocked`, not as model failures.

## Live candidates

### L3.31a — 16k context canary

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_31a_gemma_context_canary.yaml
```

Expected shape:

```yaml
models:
  - google/gemma-4-e2b
  - google/gemma-4-e4b
  - google/gemma-4-12b-qat
lanes:
  - transcript_cleanup/simple
  - structured_json/simple
  - structured_json/blocks
context_tier:
  - 16384
retry_policy:
  - off
repeats: 1
expected_attempts: 9
```

Can launch live only after explicit approval.

Acceptance:

```yaml
attempt_count: 9
hard_fail_count: 0
applied_context: 16384 for every cell
applied_parallel: 1
privacy_scan_status: pass
final_loaded_like_count: 0
```

### L3.31b — context screening

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_31b_gemma_context_screening.yaml
```

Prepared-only until one of these is true:

1. The config is split into homogeneous per-context live configs.
2. The runner gains explicit grouping so each managed executor handles exactly one context tier.

If launched without that support, cells must be classified `runner_blocked`.

### L3.31c — 26B controlled context

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_31c_gemma_26b_context_controlled.yaml
```

Prepared-only until 26B 16k load/context proof is separately accepted.

---

# L3.32 launch contract — JSON complexity

## Goal

Close complex JSON separately from simple/blocks and avoid broad cartesian expansion before canaries pass.

## Live candidates

### L3.32a — complex schema E2B/E4B canary

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml
```

Expected shape:

```yaml
models:
  - google/gemma-4-e2b
  - google/gemma-4-e4b
response_schema_complexity:
  - complex
languages:
  - ru_ru
  - ru_en_mixed
context_tier:
  - 8192
retry_policy:
  - off
expected_attempts: 4
```

Acceptance:

```yaml
json_parse: 100%
schema: 100%
language: 100%
finish_length: 0
privacy_scan_status: pass
final_loaded_like_count: 0
```

### L3.32b — complex schema 12B canary

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_32b_gemma_complex_json_canary_12b.yaml
```

Start only after L3.32a passes.

### L3.32c — capped structured screening

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_32c_gemma_structured_json_complexity_screening.yaml
```

Prepared/capped screening. Do not run before L3.32a and L3.32b pass.

### L3.32d — 26B tiny structured control

Config:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_32d_gemma_26b_structured_json_tiny.yaml
```

Simple-only tiny 26B. No complex 26B in L3.32.

---

# L3.33 launch contract — cache/session/warmup

## Goal

Evaluate cache/session/warmup strategy without contaminating it with throughput, scheduler pressure, image, or parallel experiments.

## Prerequisite artifact

Create/import first:

```text
experiments/lmstudio/results_summaries/l3_33_gemma_cache_session_warmup_evidence_import.md
```

This artifact must summarize prior source-application-derived evidence for:

- `stateful_root_branches`
- `stateless_full_prefix`
- `compact_memory`
- `/v1/responses` research-only cache accounting

## Configs to prepare

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_33a_gemma_cache_session_canary.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_33b_gemma_prompt_prefix_reuse.yaml
```

## L3.33a — cache canary

Expected shape:

```yaml
models:
  - google/gemma-4-e4b
  - google/gemma-4-12b-qat
lanes:
  - transcript_cleanup/simple
  - structured_json/blocks
context_tier:
  - 8192
execution_mode:
  - cold_per_request
  - session_loaded
cache_mode:
  - none
  - warmup_first
repeat_group:
  - same_input_repeat_3
expected_request_rows: 48
```

Session rule:

```text
load once -> request 1 warmup -> request 2 measured -> request 3 measured -> cleanup once
```

Do not claim KV reuse unless runtime reports it.

If cache signal is absent:

```yaml
cache_hit_reported: unknown
cache_hit_inferred: true_or_false_from_timing_only
kv_reuse_proven: false
```

## Required telemetry fields

```yaml
execution_mode
cache_mode
cache_group_id
session_id
session_request_index
is_warmup_request
stable_prefix_hash
schema_hash
prompt_template_hash
dynamic_input_hash
same_input_hash
ttft_ms
prompt_processing_ms
total_latency_ms
tokens_per_sec
cache_hit_reported
cache_hit_inferred
kv_reuse_proven
```

## Report target

```text
docs/live_demo/latest_gemma_cache_session/README.md
experiments/lmstudio/results_summaries/l3_33_gemma_cache_session_decision_record.md
```

## Stop conditions

Stop if:

- `final_loaded_like_count` cannot be proven zero;
- cache work requires parallel/stress;
- raw prompt/response persistence would be needed;
- KV reuse would have to be claimed without runtime signal.

---

# L3.34 launch contract — image route capability

## Goal

Decide whether any Gemma model is eligible for image route testing before any image quality benchmark.

## Read-only metadata check first

For each Gemma model collect:

```yaml
model_id
native_metadata
compat_metadata
supported_modalities
vision_or_multimodal_flags
image_route_availability
loaded_count_before
```

Allowed read-only checks:

- `GET /v1/models`
- `GET /api/v1/models`
- static candidate registry inspection

If metadata says text-only:

```yaml
status: no_image_route_available
live_image_request: forbidden
```

## Tiny route probe config

Prepare:

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml
```

Only eligible metadata-positive models may enter the request path.

Expected shape:

```yaml
asset:
  - ui_settings_ru_001
schema:
  - simple_description
resize_profile:
  - max_side_1024
output_language:
  - ru_ru
max_requests_per_model: 1
```

Acceptance:

```yaml
image_request_accepted: true
json_parse: pass
schema: pass
privacy_scan_status: pass
final_loaded_like_count: 0
```

Unsupported image route must be classified:

```yaml
status: route_rejected_image_payload
quality_failure: false
```

## Report target

```text
docs/live_demo/latest_gemma_vision_route_probe/README.md
experiments/lmstudio/results_summaries/l3_34_gemma_vision_route_capability_decision_record.md
```

---

# L3.35 launch contract — image matrix

## Goal

Run image quality only after L3.34 proves at least one eligible image-capable Gemma model.

If L3.34 proves no image-capable Gemma route, L3.35 closes as `unsupported_modality` / `blocked`, not failed quality.

## Configs to prepare

```text
experiments/lmstudio/structured_matrix/configs/matrix.l3_35a_gemma_vision_tiny_canary.yaml
experiments/lmstudio/structured_matrix/configs/matrix.l3_35b_gemma_vision_simple_medium_screening.yaml
```

## L3.35a — tiny image canary

Expected shape:

```yaml
models:
  - eligible_gemma_models_only
assets:
  - ui_settings_ru_001
  - document_table_products_ru_001
  - chart_tasks_by_month_ru_001
  - code_python_editor_001
schema:
  - simple_description
resize:
  - max_side_1024
output_language:
  - ru_ru
max_requests: 4_to_8
```

## L3.35b — small screening

Only after L3.35a passes.

Expected shape:

```yaml
assets:
  - all_10_l3_30_assets
schema:
  - simple_description
  - medium_objects_text
resize:
  - max_side_1024
  - max_side_512
output_language:
  - ru_ru
  - en_en
task_intent:
  - image_description
  - ocr_visible_text
  - ui_understanding
  - table_extraction
  - chart_extraction
  - code_understanding
  - scene_understanding
  - slide_extraction
max_requests: 120
```

Compatibility mapping must prune invalid combinations:

- no `chart_extraction` on people scene;
- no `code_understanding` on table image;
- no `table_extraction` on classroom scene.

Complex image schema remains prepared-only in L3.35.

## Validators

```yaml
json_schema: hard
forbidden_claims_check: hard
language_compliance: hard_or_warning_by_report_policy
visible_text_recall: warning_initially
visible_text_precision: warning_initially
object_label_recall: warning_initially
table_cell_accuracy: warning_initially
chart_value_accuracy: warning_initially
code_identifier_recall: warning_initially
ui_control_recall: warning_initially
person_count_accuracy: warning_initially
```

## Report target

```text
docs/live_demo/latest_gemma_vision_screening/README.md
experiments/lmstudio/results_summaries/l3_35_gemma_vision_screening_decision_record.md
```

---

# L3.36 launch contract — final synthesis

## Goal

Publish final Gemma family admission matrix/model cards after prior phase evidence exists.

## Required artifacts

```text
experiments/lmstudio/results_summaries/l3_36_gemma_family_final_synthesis.md
docs/gemma_family_model_cards.md
```

## Required fields per model

```yaml
model_id
load_status
max_proven_context
transcript_cleanup_status
structured_simple_status
structured_blocks_status
structured_complex_status
vision_route_status
cache_session_status
latency_summary
quality_notes
recommended_role
blocked_modes
next_research_needed
```

## Final decision categories

```yaml
accepted
accepted_with_constraints
research_only
blocked
unsupported_route
runner_blocked
prepared_only
```

## Synthesis must answer

1. Which Gemma model is best for transcript cleanup?
2. Which Gemma model is best for structured JSON?
3. Which context windows are safe?
4. Which JSON structures are stable?
5. Which languages degrade?
6. Which modes need retry?
7. Which cache/session strategy is useful?
8. Which Gemma models support image route, if any?
9. Which image tasks/schemas are stable?
10. Which models/modes remain blocked?

---

# Required gates after each phase

Run these after every non-live phase before commit/push:

```bash
git diff --check
python scripts/audit_publication_safety.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv build
uv run lmstudio-benchmark --help
```

After any live artifacts, additionally verify:

```yaml
loaded_count: 0 for all targeted models
raw_artifacts_tracked: false
privacy_scan_status: pass
```

# Global stop conditions

Stop immediately if:

1. cleanup final zero cannot be proven;
2. privacy scan fails;
3. raw prompt/response would be committed;
4. model download is required;
5. context is silently downgraded;
6. image live starts without L3.34 capability proof;
7. Qwen appears in Gemma phases;
8. full cartesian exceeds budget;
9. complex schema starts before simple/blocks pass;
10. 26B enters broad structured matrix before tiny proof.

# Kanban launch graph

Existing root/phase cards:

```text
t_e56d8fc9 — L3.33 cache session warmup closure
t_3dfa1c37 — L3.34 image route capability closure
t_e930df10 — L3.35 image matrix closure
t_54efb182 — L3.36 final Gemma model card synthesis
```

Required refined child cards before dispatching broad work:

## L3.33

1. evidence import card;
2. cache/session telemetry schema card;
3. L3.33a/L3.33b config preparation card;
4. non-live gates/report card;
5. live gate card, blocked pending explicit owner approval.

## L3.34

1. read-only metadata capability card;
2. vision route probe config/report card;
3. tiny live route gate card, blocked unless metadata proves image-capable models and owner approves.

## L3.35

1. image matrix preparation card, blocked on L3.34 eligible models;
2. tiny canary live gate, blocked on L3.34 proof and owner approval;
3. simple/medium screening gate, blocked on tiny canary pass.

## L3.36

1. synthesis draft card, blocked on L3.31-L3.35 evidence;
2. final model card/report card;
3. final publication gate.

# Immediate launch recommendation

The next safe launch is not L3.35 or L3.36.

Use two separate tracks depending on runtime availability.

## If inference is available

Live order:

1. L3.31a — 16k context canary.
2. L3.32a — complex JSON E2B/E4B canary.
3. L3.33a — cache/session canary, after context and complex canaries are accepted or explicitly deferred.
4. L3.34 — tiny image route probe, only after read-only metadata proves eligible image-capable Gemma model(s).
5. L3.35 — image matrix, only if L3.34 proves at least one eligible image-capable Gemma route.
6. L3.36 — final synthesis, only after L3.31-L3.35 evidence exists.

L3.31a must not be converted into a model failure if the runner blocks 16k or silently downgrades context. The status is `runner_blocked` unless `applied_context=16384` is proven for every cell.

L3.32a starts only after L3.31a is accepted or explicitly deferred by the owner/coordinator. If L3.32a fails, do not run 12B complex, broad L3.32c, or 26B structured.

## If inference is unavailable

Safe non-live work:

1. L3.33 evidence import.
2. L3.33 cache/session telemetry and config preparation.
3. L3.34 read-only image capability metadata preparation.
4. L3.34 route probe config/report preparation, without live image requests.

This non-live track does not supersede the live order. It only keeps the project moving while GPU/runtime inference is unavailable.

L3.35 remains blocked until L3.34 proves at least one eligible image-capable Gemma route.

L3.36 remains blocked until L3.31-L3.35 evidence is available.
