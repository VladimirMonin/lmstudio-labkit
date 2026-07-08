# L3.15 Full Matrix Preparation Plan

This plan defines the next non-live hardening wave after `8e413ed`. It is based on the current source tree, the existing L3.13 readiness plan/report, and the managed-backend research documents for model lifecycle, parallel inference, prompt cache, structured output, and benchmark metrics.

No live inference, model load, model download, image live execution, stress run, overnight run, or route-matrix live execution is part of this stage.

## 1. Current source-state analysis

### 1.1 Implemented and usable now

The current LabKit has a safe base for a first controlled live-small text screening later:

- `lmstudio-benchmark plan`, `run`, `summarize`, and `compare` exist.
- `run` supports guarded live profile validation with:
  - `--live`
  - `--operator-live-managed`
  - `--allow-model-loads`
  - `--allow-remote-base-url`
- Core safety config rejects default/offline model loads, model downloads, raw prompt/response artifacts, image live, and stress unless explicit safety flags allow a future path.
- `BenchmarkConfig` parses models, tasks, axes, repeats, and safety budgets.
- The matrix planner filters incompatible task/model/axis combinations.
- `FakeTransport` gives deterministic offline execution.
- `LiveBridgeTransport` and `ManagedLMStudioTransport` keep raw responses in memory and persist only privacy-safe hashes/counts/status/metrics.
- Artifact writers produce `planner_summary.json`, `cell_results.jsonl`, CSV summaries, `privacy_scan.json`, and `report.md`.
- Existing CSV contracts cover JSON/schema/business/id/language/image/finish-length/retry/timing fields.
- Existing live-small configs cover a minimal Russian text structured run:
  - `matrix.live_small_text.e2b_e4b.yaml`
  - `matrix.live_small_text.e2b_e4b_12b.yaml`
- The source already contains research documents for:
  - model lifecycle and KV/context concerns;
  - parallel requests to one loaded model;
  - prompt cache, stateful context, and prefix reuse;
  - cache/parallel benchmark hypotheses;
  - structured output and JSON Schema validation;
  - metrics and result format.

### 1.2 Gaps blocking a larger suite

The repository is not yet ready for a one-command screening/overnight suite because these capabilities are missing or incomplete:

1. **No suite runner**
   - There is no `preflight-suite`, `plan-suite`, `run-suite`, `summarize-suite`, or `compare-suite` command.
   - There is no suite YAML format or suite output directory contract.
   - There is no incremental suite result stream or stop-on-failure policy.

2. **No resume semantics**
   - Current CLI rejects an existing run directory except for a narrow plan-only case.
   - There is no per-config skip/rerun decision based on `privacy_scan.json`, `report.md`, or incomplete `cell_results.jsonl`.

3. **No read-only preflight subsystem**
   - There is no command that validates configs, budgets, output roots, model visibility, loaded state, and asset manifests without generation or model load.
   - LM Studio availability probing is currently operator/manual, not an artifacted preflight stage.

4. **Managed load verification is too permissive for future live execution**
   - `LocalLMStudioHostRunner.load_model()` currently returns `load_verified: True` after a successful HTTP load response and falls back to requested context/parallel values when echoed config fields are missing.
   - `_load_verified(...)` accepts missing applied config and allows observed context/parallel values greater than or equal to requested values.
   - Future live execution needs strict evidence that applied context and applied parallel exactly match the requested profile before generation.

5. **Cleanup verification is not strict enough for live-small**
   - `count_loaded_instances(...)` can return `None`, and `ManagedLMStudioExecutor` currently accepts final loaded instances in `(0, None)`.
   - Future live-small should fail when cleanup state is unknown, because a dirty loaded state invalidates later retry/cache/parallel measurements.

6. **Structured schema strictness is hard-coded off**
   - `ManagedLMStudioExecutor` currently sends OpenAI-compatible `response_format` with `strict: False`.
   - The future suite needs `structured_runtime.strict_json_schema: true` as the default and must fail clearly if the runtime does not accept strict schemas.

7. **Managed retry lifecycle is not supported**
   - Core `run_matrix(...)` can retry validation failures when `retry_policy=retry1`.
   - `ManagedLMStudioTransport.execute(...)` rejects `attempt_index != 1`, so managed live retry is currently unavailable.
   - Future retry must be a clean lifecycle per attempt: load, request, cleanup, verify final zero; then repeat.

8. **Execution/cache/parallel axes are not represented in the matrix model**
   - `DEFAULT_AXES` does not include `execution_mode`, `cache_mode`, `lmstudio_parallel`, `app_concurrency`, or `queue_pressure_mode`.
   - Reports do not include applied parallel, parallel verification, queue wait, TTFT, prompt-processing duration, cache-mode labels, RAM/VRAM peaks, or cleanup status.

9. **Config pack is too small**
   - Current structured configs are only smoke plus two live-small files.
   - There is no text suite for simple/medium/complex, Russian-first screening, mixed RU/EN, English control, extended Gemma, Qwen examples, or throughput/parallel screening.

10. **Image assets are not packaged for offline readiness**
    - Image live remains intentionally unsupported, but there is no offline fixture manifest, expected ground-truth format, or image-readiness suite.

## 2. Stage goal

Prepare the full non-live harness layer required for future controlled runs:

```text
preflight -> plan-suite -> dry-run/fake -> true-live tiny -> true-live screening -> extended/overnight
```

L3.15 is complete when the project can validate and dry-run a suite end-to-end without live inference, and when the next live window can start from a single reviewed command rather than ad-hoc manual steps.

## 3. Hard constraints

### 3.1 Forbidden in L3.15

- True live inference.
- Model load.
- Model download.
- 12B generation.
- 26B generation.
- Qwen generation.
- Image live.
- Stress or overnight execution.
- `/v1/responses` execution.
- Route-matrix live execution.
- Raw prompt artifacts.
- Raw response artifacts.
- Full raw local/remote base URL artifacts.
- Private/source-application coupling.
- Historical artifact mutation.

### 3.2 Required flags for any future live artifacts

Any future live artifact path must persist these lab-only flags:

```yaml
production_default: false
wvm_runtime_integration: false
kv_reuse_proven: false
final_user_facing_recommendation: false
raw_prompt_response_stored: false
```

## 4. Workstream A — strict managed lifecycle verification

### A1. Strict load verification

Update `LocalLMStudioHostRunner.load_model()` and managed executor verification so a load is accepted only when the runtime provides proof of the applied config.

Acceptance:

- Exact `applied_load_config` pass.
- Exact `load_config` pass.
- Requested-value fallback without applied config fails.
- `applied_context_length != requested_context_length` fails before generation.
- `applied_parallel != requested_parallel` fails before generation.
- Loaded instance must be visible after load.
- The owned loaded instance or unambiguous loaded count must be recorded.
- Missing loaded-state proof fails before generation.

Required test file:

- `tests/lmstudio_labkit/test_local_load_verification_strict.py`

Required cases:

- exact `applied_load_config` pass;
- exact `load_config` pass;
- requested fallback without applied config fails;
- context mismatch fails;
- parallel mismatch fails;
- post-load loaded count zero fails;
- ambiguous loaded-state proof fails.

### A2. Strict cleanup verification

Cleanup must be provable after each managed attempt.

Acceptance:

- Cleanup verified and final loaded instances `0` passes.
- Cleanup status missing/ambiguous fails for live-small.
- Final loaded instances `None` fails for live-small.
- Final loaded instances greater than `0` fails after cleanup attempt.
- The failure is reported as cleanup verification failure, not as generation failure.

Required test file:

- `tests/lmstudio_labkit/test_local_load_verification_strict.py`

## 5. Workstream B — strict JSON Schema runtime option

Add strict JSON Schema control to managed execution.

Proposed config shape:

```yaml
structured_runtime:
  strict_json_schema: true
```

Proposed executor option:

```python
strict_json_schema: bool = True
```

Acceptance:

- Managed executor emits `response_format.json_schema.strict: true` by default.
- Config can explicitly set strict mode through parsed runtime config.
- If the runtime rejects strict schemas, the command fails and reports:
  - `strict_schema_runtime_support=false`
  - `hardened_schema_validation_available=true`
- There is no silent fallback from strict to non-strict.
- Offline/fake execution remains deterministic.

Required test file:

- `tests/lmstudio_labkit/test_managed_executor_strict_schema.py`

## 6. Workstream C — managed retry lifecycle

Enable retry for managed transport without reusing dirty state.

Required lifecycle for every attempt:

```text
load -> request -> cleanup -> verify final zero
```

For retry1:

```text
attempt 1: load -> request -> cleanup -> verify final zero
attempt 2: load -> request -> cleanup -> verify final zero
```

Acceptance:

- Retry disabled means exactly one managed attempt.
- `retry1` after business/validation failure performs a second full lifecycle.
- Each attempt has cleanup verified independently.
- Retry-recovered metrics are recorded.
- Retry-failed metrics are recorded.
- Transport/API errors remain distinct from business-validation failures.

Required test file:

- `tests/lmstudio_labkit/test_managed_retry_lifecycle.py`

## 7. Workstream D — suite runner

### D1. CLI commands

Add these commands:

```bash
lmstudio-benchmark preflight --config <config.yaml> --base-url <base-url>
lmstudio-benchmark preflight-suite --suite <suite.yaml> --base-url <base-url>
lmstudio-benchmark plan-suite --suite <suite.yaml> --output-root <dir>
lmstudio-benchmark run-suite --suite <suite.yaml> --output-root <dir> --profile offline-fake --resume
lmstudio-benchmark summarize-suite --suite-run-dir <dir>
lmstudio-benchmark compare-suite --left-suite-run-dir <a> --right-suite-run-dir <b>
```

`base-url` must be treated as sensitive operational input. Persist only safe classification fields such as base URL kind and scheme.

### D2. Suite config format

Create:

```text
experiments/lmstudio/structured_matrix/suites/
```

Add suite files:

```text
experiments/lmstudio/structured_matrix/suites/l3_15_text_quality_screening.yaml
experiments/lmstudio/structured_matrix/suites/l3_15_text_throughput_parallel.yaml
experiments/lmstudio/structured_matrix/suites/l3_15_image_offline_readiness.yaml
experiments/lmstudio/structured_matrix/suites/l3_15_overnight_candidate.example.yaml
```

Baseline suite shape:

```yaml
suite_id: l3_15_text_quality_screening
description: Russian-first text structured quality screening without image live.

defaults:
  profile: offline-fake
  live: false
  allow_model_loads: false
  allow_model_downloads: false
  allow_raw_prompt_response_artifacts: false
  allow_image_live: false
  allow_stress: false

preflight:
  require_lmstudio_reachable: false
  require_models_visible: false
  require_target_models_unloaded: false
  require_no_downloads: true
  require_output_root_empty_or_resume: true
  validate_assets: true
  validate_configs: true
  validate_request_budget: true

configs:
  - id: text_ru_tiny_e2b_e4b
    path: experiments/lmstudio/structured_matrix/configs/matrix.text_ru_tiny.e2b_e4b.yaml
    required: true

  - id: text_ru_screening_e2b_e4b
    path: experiments/lmstudio/structured_matrix/configs/matrix.text_ru_screening.e2b_e4b.yaml
    required: true
    run_after:
      - text_ru_tiny_e2b_e4b

  - id: text_ru_screening_e2b_e4b_12b
    path: experiments/lmstudio/structured_matrix/configs/matrix.text_ru_screening.e2b_e4b_12b.yaml
    required: false
    run_after:
      - text_ru_screening_e2b_e4b

  - id: text_mixed_ru_en_screening
    path: experiments/lmstudio/structured_matrix/configs/matrix.text_ru_en_mixed.e2b_e4b_12b.yaml
    required: false

budgets:
  max_total_requests: 300
  max_configs: 20
  max_models_per_config: 5
  max_repeats: 5
  max_context_tier: 8192
```

### D3. Suite output contract

A suite run directory must have this shape:

```text
suite_<timestamp>_<suite_id>/
├── suite_config.yaml
├── suite_preflight.json
├── suite_plan.json
├── suite_results.jsonl
├── suite_summary.json
├── suite_report.md
├── suite_decision_record.md
└── runs/
    ├── matrix_text_ru_tiny_e2b_e4b/
    ├── matrix_text_ru_screening_e2b_e4b/
    └── ...
```

Acceptance:

- Suite outputs pass privacy scan.
- Suite result records are appended incrementally.
- `stop_on_failure` stops after the first required config failure.
- Optional configs can fail without invalidating completed required configs, but the suite summary must show the optional failure.

Required test files:

- `tests/lmstudio_labkit/test_suite_runner.py`
- `tests/lmstudio_labkit/test_suite_resume.py`
- `tests/lmstudio_labkit/test_suite_report.py`

## 8. Workstream E — resume behavior

`--resume` must be explicit.

Acceptance:

- Without `--resume`, an existing suite/run directory is rejected.
- With `--resume`, a config run is skipped only when:
  - `privacy_scan.json` exists and passes;
  - `report.md` exists;
  - `cell_results.jsonl` is complete for the planned cell count.
- A config run is rerun when:
  - privacy scan is missing or failed;
  - `cell_results.jsonl` is incomplete;
  - the planner hash does not match the suite plan;
  - report artifacts are missing.
- Resume never overwrites historical artifacts outside the target suite output root.
- Suite-level `suite_results.jsonl` is append-safe and deduplicated by config id and run hash.

## 9. Workstream F — read-only preflight system

### F1. Config preflight

Read-only checks:

- Config parses.
- `run_id` is safe.
- Models are defined.
- Tasks are defined.
- Axes are valid.
- Task-axis compatibility produces at least one cell.
- Planned request count is within `safety.max_requests`.
- Context tier is within `safety.max_context_tier`.
- Repeats are within `safety.max_repeats`.
- Raw artifacts are disabled.
- Downloads are disabled.
- Image live is disabled unless a future explicit image-live profile exists.
- Output root is empty or resume-safe.

Required test file:

- `tests/lmstudio_labkit/test_preflight_config.py`

### F2. LM Studio read-only preflight

Read-only only. No model load and no generation.

Allowed operations:

- TCP reachability probe.
- `GET /v1/models`.
- `GET /api/v1/models`.

Checks:

- Endpoint reachable when required.
- Compat model list is available when required.
- Native model list is available when required.
- Target model IDs are visible when required.
- Target model type is `llm` or otherwise chat-like.
- Embedding and reranker models are excluded from generation candidates.
- Loaded instance counts are recorded.
- Max context is recorded when exposed by LM Studio.
- Target models are unloaded when the suite requires a cold start.

Output:

```text
preflight_summary.json
```

Persist only safe endpoint metadata classification, not the raw base URL or host.

Required test file:

- `tests/lmstudio_labkit/test_preflight_lmstudio_readonly.py`

### F3. Suite preflight

Acceptance:

- Aggregates config preflight results.
- Aggregates LM Studio read-only model visibility results when required.
- Aggregates asset manifest validation.
- Fails before any execution if required configs/assets/models are missing.
- Emits `suite_preflight.json`.

Required test file:

- `tests/lmstudio_labkit/test_preflight_suite.py`

## 10. Workstream G — text config pack

### G1. Model groups

Create reusable model groups through YAML anchors or separate include-like files if the parser supports them later. Until then, duplicate explicitly in configs.

Core group:

```yaml
models:
  - model_key: gemma4_e2b_q4km
    model_id: google/gemma-4-e2b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192, 16384, 32768]

  - model_key: gemma4_e4b_q4km
    model_id: google/gemma-4-e4b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192, 16384, 32768]
```

Extended Gemma group:

```yaml
  - model_key: gemma4_12b_qat
    model_id: google/gemma-4-12b-qat
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192, 16384]

  - model_key: gemma4_26b_a4b_qat
    model_id: google/gemma-4-26b-a4b-qat
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192]
```

Qwen group for examples only in this stage:

```yaml
  - model_key: qwen3_5_4b
    model_id: qwen/qwen3.5-4b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192]

  - model_key: qwen3_5_9b
    model_id: qwen/qwen3.5-9b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192]

  - model_key: qwen3_6_27b
    model_id: qwen/qwen3.6-27b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192]

  - model_key: qwen3_6_35b_a3b
    model_id: qwen/qwen3.6-35b-a3b
    endpoint_family: openai_compat
    supported_modalities: [text]
    supported_context_tiers: [8192]
```

Qwen configs are prepared only; Qwen generation is not allowed in this stage.

### G2. Configs to create

```text
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_tiny.e2b_e4b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_screening.e2b_e4b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_screening.e2b_e4b_12b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_extended_gemma.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_extended_qwen.example.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_ru_en_mixed.e2b_e4b_12b.yaml
experiments/lmstudio/structured_matrix/configs/matrix.text_en_control.e2b_e4b.yaml
```

### G3. Structure complexity levels

#### Simple

Expected JSON shape:

```json
{
  "id": 0,
  "title": "string",
  "summary": "string",
  "tags": ["string"],
  "language": "ru"
}
```

Validators:

- JSON parse.
- JSON Schema.
- Required fields.
- `minLength`/`maxLength`.
- Tags min/max.
- Language policy.
- No placeholder text.
- No Markdown fence.
- No reasoning leak.

#### Medium

Expected JSON shape:

```json
{
  "blocks": [
    {"id": 0, "text": "..."},
    {"id": 1, "text": "..."}
  ]
}
```

Validators:

- Exact IDs.
- Order preserved.
- Missing/extra/duplicate IDs.
- Non-empty text.
- Length ratio.
- Language policy.
- No reasoning leak.
- `finish_reason != length`.

#### Complex

Expected JSON shape:

```json
{
  "document": {
    "title": "...",
    "sections": [
      {
        "id": 0,
        "heading": "...",
        "blocks": [
          {
            "id": 0,
            "text": "...",
            "entities": [
              {"type": "library", "value": "PySide6"}
            ],
            "flags": {
              "unclear": false,
              "needs_review": false
            }
          }
        ]
      }
    ]
  }
}
```

Validators:

- Section ID paths.
- Block ID paths.
- Entity type enum.
- Boolean flags.
- `additionalProperties=false`.
- Length ratio.
- Language policy.
- No hallucinated entity types.
- No placeholder text.
- No Markdown fence.
- No reasoning leak.

## 11. Workstream H — execution, cache, lifecycle, and parallelism axes

Add optional axes to config parsing, planning summaries, artifact rows, and reports:

```yaml
execution_mode:
  - cold_per_request
  - session_loaded

cache_mode:
  - none
  - warmup_first
  - prompt_prefix_reuse
  - compact_memory_like

lmstudio_parallel:
  - 1
  - 2

app_concurrency:
  - 1
  - 2

queue_pressure_mode:
  - false
  - true
```

Definitions:

- `cold_per_request`: load, one request, cleanup. Safest and slowest baseline.
- `session_loaded`: load once, run multiple sequential requests, cleanup. Requires drift and cleanup tracking.
- `cache_mode=none`: no warmup baseline.
- `cache_mode=warmup_first`: first request warms shared prompt/schema/prefix, following requests reuse the stable prefix if the runtime supports it.
- `cache_mode=prompt_prefix_reuse`: same system prompt and schema prefix across requests; measure TTFT/prompt-processing deltas.
- `cache_mode=compact_memory_like`: lab-only approximation of compact-memory/stateful workflows; no production claim.
- `lmstudio_parallel`: requested LM Studio parallel/concurrent prediction setting; must be verified from applied load config.
- `app_concurrency`: concurrent app-side requests.
- `queue_pressure_mode`: intentionally submits more work than the loaded parallel setting; disabled for first live runs.

First future live profile must keep:

```yaml
lmstudio_parallel: [1]
app_concurrency: [1]
queue_pressure_mode: [false]
```

Later throughput profile can widen to:

```yaml
lmstudio_parallel: [1, 2]
app_concurrency: [1, 2]
queue_pressure_mode: [false, true]
```

Reports must include:

- `execution_mode`
- `cache_mode`
- `lmstudio_parallel`
- `app_concurrency`
- `queue_pressure_mode`
- `applied_parallel`
- `parallel_verified`
- `ttft_ms`
- `prompt_processing_ms`
- `queue_wait_ms`
- `total_latency_ms`
- `tokens_per_sec`
- `prompt_tokens`
- `completion_tokens`
- `ram_peak_mb`
- `vram_peak_mb`
- `cleanup_status`

Required test files:

- `tests/lmstudio_labkit/test_execution_axes.py`
- `tests/lmstudio_labkit/test_parallelism_axes.py`
- `tests/lmstudio_labkit/test_cache_mode_axes.py`

## 12. Workstream I — throughput and parallelism suite

Create but do not run live:

```text
experiments/lmstudio/structured_matrix/configs/matrix.throughput_text_ru.e2b_e4b.yaml
experiments/lmstudio/structured_matrix/suites/l3_15_text_throughput_parallel.yaml
```

Scope:

```yaml
models:
  - gemma4_e2b_q4km
  - gemma4_e4b_q4km

axes:
  modality: [text]
  language: [ru_ru]
  structure_complexity: [medium]
  volume: [single]
  schema_variant: [hardened_const]
  context_tier: [8192]
  execution_mode: [session_loaded]
  cache_mode: [none, warmup_first]
  lmstudio_parallel: [1, 2]
  app_concurrency: [1, 2]
  retry_policy: [off]

repeats: 3
```

Safety for future explicit live execution:

```yaml
safety:
  live: true
  allow_model_downloads: false
  allow_model_loads: true
  allow_raw_prompt_response_artifacts: false
  allow_image_live: false
  allow_stress: false
  max_requests: 48
  max_models: 2
  max_context_tier: 8192
  max_repeats: 3
```

This suite must not be run until tiny live E2B/E4B passes.

## 13. Workstream J — image offline asset pack

Image live remains unsupported. Prepare only offline fixtures, manifests, schemas, and validators.

### J1. Fixture families

Prepare these six image fixture families:

- `ui_screenshot`
- `code_screenshot`
- `document_table`
- `chart_graph`
- `people_scene`
- `mixed_text_image`

### J2. Required assets

Assets must be public-safe and synthetic or explicitly approved:

1. UI screenshot: synthetic app/settings screen, no private names, no local paths.
2. Code screenshot: small public-safe Python/JavaScript snippet, no private repo names.
3. Document/table image: synthetic invoice/table/spreadsheet with 3-5 known rows.
4. Chart/graph: synthetic bar/line chart with known values and visible labels.
5. People/scene: public/stock/synthetic, non-identifying, no sensitive attributes.
6. Mixed text image: UI + text + small icon/chart, public-safe.

### J3. Fixture layout

```text
experiments/lmstudio/structured_matrix/datasets/image/
├── manifest.yaml
├── fixtures/
│   ├── ui_screenshot.png
│   ├── code_screenshot.png
│   ├── document_table.png
│   ├── chart_graph.png
│   ├── people_scene.png
│   └── mixed_text_image.png
└── expected/
    ├── ui_screenshot.expected.yaml
    ├── code_screenshot.expected.yaml
    ├── document_table.expected.yaml
    ├── chart_graph.expected.yaml
    ├── people_scene.expected.yaml
    └── mixed_text_image.expected.yaml
```

### J4. Ground-truth shape

```yaml
fixture_id: ui_screenshot_001
image_type: ui_screenshot
input_language: ru_ru
output_language: ru_ru
structure_complexity: medium

expected:
  visible_text:
    - Настройки
    - Модель
    - Сохранить
  object_types:
    - button
    - input
    - menu
  required_fields:
    - title
    - controls
    - warnings
```

Required future tests:

- `tests/lmstudio_labkit/test_image_manifest_offline.py`
- `tests/lmstudio_labkit/test_image_ground_truth_contract.py`

## 14. Proposed implementation order

1. Strict managed lifecycle verification.
2. Strict JSON Schema runtime option.
3. Managed retry lifecycle.
4. Read-only config/LM Studio/suite preflight.
5. Suite config parser and suite planning.
6. Suite dry-run execution with resume.
7. Suite summary/report/compare commands.
8. Text config pack.
9. Execution/cache/parallel axes and reporting fields.
10. Throughput/parallel suite definitions.
11. Image offline asset manifest and validators.
12. Runbook update for the later explicit live window.

## 15. Non-live verification gates for L3.15

Before committing implementation work in this stage, run at least:

```bash
git diff --check
python scripts/audit_publication_safety.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv build
```

For docs-only plan commits, the minimum gate is:

```bash
git diff --check
python scripts/audit_publication_safety.py
```

No command in this stage may call live generation endpoints or model lifecycle mutation endpoints.

## 16. Future explicit live sequence, not part of L3.15

Only after owner approval:

1. Run read-only preflight suite.
2. Run `plan-suite`.
3. Run `run-suite` with `offline-fake --resume`.
4. Run tiny live E2B/E4B only.
5. Inspect artifacts and privacy scan.
6. If clean, run text screening E2B/E4B only.
7. Only after review, consider optional 12B.
8. Do not run 26B, Qwen, image live, stress, or overnight without a separate approval and profile.

## 17. Open decisions for the owner

Before implementing the optional/extended packs, decide:

- Exact overnight candidate model list.
- Hard maximum request count.
- Hard maximum runtime hours.
- Hard maximum context tier.
- Whether 12B may be included after tiny E2B/E4B passes.
- Whether 26B remains documentation-only or may enter a later candidate pack.
- Whether Qwen remains example-only or enters a separate non-first-live suite.
- Whether the first optimization objective is quality or throughput.

## 18. Working conclusion

The project is ready for L3.15 as a non-live harness expansion. The main missing layer is not model availability; it is orchestration discipline: strict lifecycle proof, strict schema mode, retry lifecycle isolation, suite preflight, resume, richer text config packs, and explicit cache/parallel axes. Once these are implemented and dry-run verified, the later live window can start with a small reviewed suite instead of discovering harness gaps during a long run.
