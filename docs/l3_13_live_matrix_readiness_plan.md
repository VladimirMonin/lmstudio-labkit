# L3.13 Live Matrix Readiness Plan

This plan tracks the post-`bcebc10` hardening wave. The default execution mode remains offline/fake. No true live LM Studio run, model download, model load, stress/overnight run, image live run, or raw prompt/response artifact is allowed in this wave.

## A2 — benchmark safety config and budget guard coverage

Acceptance:

- `planned_requests > max_requests` fails.
- `model_count > max_models` fails.
- `context_tier > max_context_tier` fails.
- `repeats > max_repeats` fails.
- `volume=stress` with `allow_stress=false` fails.
- `modality=image` with `live=true` and `allow_image_live=false` fails.
- `allow_raw_prompt_response_artifacts=true` is rejected in public/default mode.
- `allow_model_downloads=true` is rejected unless a future explicit command supports it.

Required tests:

- `tests/lmstudio_labkit/test_benchmark_safety_config.py`
- `tests/lmstudio_labkit/test_budget_guards.py`

## A3 — scoped ID validation for complex nested tasks

Acceptance:

- Add response-contract validation controls equivalent to:
  - `id_paths: tuple[str, ...] = ()`
  - `id_field_names: tuple[str, ...] = ("id",)`
  - `preserve_order: bool = True`
- Add `collect_ids_by_path(value, path="blocks[*].id")`.
- Blocks schema validates only `blocks[*].id` by default.
- Complex nested schemas can validate:
  - `document.sections[*].id`
  - `document.sections[*].blocks[*].id`
- Section IDs must not pollute block ID checks.
- Integer/string IDs normalize consistently.

Required test:

- `tests/lmstudio_labkit/test_id_path_validation.py`

## A4 — task-specific language policy

Acceptance:

- Add task/contract language policy values:
  - `strict_ru`
  - `strict_en`
  - `mixed_ru_en`
  - `allow_code_terms`
  - `labels_only`
  - `skip`
- `ru_ru` default requires Cyrillic ratio >= 0.5.
- `allow_code_terms` allows Cyrillic ratio >= 0.25 with at least one Cyrillic char.
- `ru_en_mixed` must contain Cyrillic or explicit mixed expected hints; Latin is not required in every output.
- `en_en` requires Latin ratio >= 0.5.
- Image labels validate expected label presence rather than global language ratio.

Required test:

- `tests/lmstudio_labkit/test_language_policy.py`

## A5 — artifact CSV contract and validation metrics flattening

Acceptance:

`cell_summary.csv` must include at least:

- `cell_id`, `model_key`, `model_id`, `task_id`, `modality`, `language`, `structure_complexity`, `volume`, `context_tier`, `schema_variant`, `retry_policy`, `repeat_index`, `status`
- `json_parse_status`, `json_schema_status`, `business_status`, `id_exact_status`, `language_status`, `image_ground_truth_status`, `finish_reason_length_status`
- `missing_id_count`, `unexpected_id_count`, `duplicate_id_count`, `order_mismatch`, `first_mismatch_index`
- `placeholder_hit_count`, `markdown_fence_count`, `finish_reason`, `retry_count`, `retry_recovered`, `error_category`
- `latency_ms`, `prompt_tokens`, `completion_tokens`, `response_char_count`

`model_summary.csv` must include at least:

- `model_key`, `model_id`, `attempt_count`, `pass_count`, `fail_count`, `pass_rate`
- `json_parse_pass_rate`, `schema_pass_rate`, `id_exact_pass_rate`, `language_pass_rate`
- `retry_attempted_count`, `retry_recovered_count`, `retry_dependency_rate`, `finish_length_count`
- `median_latency_ms`, `p95_latency_ms`

Required tests:

- `tests/lmstudio_labkit/test_artifact_csv_contract.py`
- `tests/lmstudio_labkit/test_validation_metrics_flattening.py`

## A6 — privacy scanner policy refinement

Acceptance:

- Artifacts never include full `base_url`.
- Artifacts never include `base_url_host=127.0.0.1`.
- Live metadata stores only safe classification:
  - `base_url_kind: local|remote`
  - `base_url_scheme: http|https`
- Privacy scanner scans generated sidecars too:
  - `summary.json`
  - `summary.csv`
  - `axis_summary.csv`
  - `failure_summary.csv`
  - `retry_impact.csv`
  - `compare_summary.json`
  - `compare_summary.md`

Required tests:

- `tests/lmstudio_labkit/test_safe_live_metadata.py`
- `tests/lmstudio_labkit/test_privacy_scanner_sidecars.py`

## B1/B2 — matrix transport interface and live bridge transport

Acceptance:

- Add `MatrixTransport` protocol:

```python
class MatrixTransport(Protocol):
    def execute(self, plan: RequestPlan, *, attempt_index: int = 1) -> tuple[str, RequestResult]: ...
```

- Add `FakeTransport` and `LiveBridgeTransport`.
- `run_matrix(config, output_root, *, transport=None, live_options=None)` accepts injected transport.
- Default transport remains fake/offline.
- Live transport requires `config.safety.live=true` and injected executor/bridge.
- Raw response stays in memory only.
- Artifacts persist only hashes/counts/status/metrics.
- Image live raises `NotImplementedError`.
- Stress/overnight without explicit allow is blocked.
- Remote base URL without allow flag is blocked.
- Request count is checked against max requests.

Required tests:

- `tests/lmstudio_labkit/test_matrix_transport_interface.py`
- `tests/lmstudio_labkit/test_run_matrix_with_injected_transport.py`
- `tests/lmstudio_labkit/test_live_bridge_transport.py`

## B3 — managed LM Studio executor adapter behind guardrails

Acceptance:

- Add `lmstudio_labkit/managed_executor.py` or `lmstudio_labkit/transports/managed_lmstudio.py`.
- Scope v1: text structured JSON only, `/v1/chat/completions`, context 8192, parallel 1, temperature 0.
- No `/v1/responses`, no native `/api/v1/chat`, no image, no route matrix, no parallel/concurrency.
- Add:

```python
@dataclass(frozen=True, slots=True)
class ManagedExecutionResult:
    raw_response: str
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    finish_reason: str | None
    load_verified: bool
    cleanup_verified: bool
    final_loaded_instances: int | None
```

- `ManagedLMStudioExecutor.execute(plan)` returns raw response in memory only.
- Adapter verifies context/parallel, one structured request, cleanup, and final loaded instances when a host runner is injected.
- Tests are mocked only.

Required tests:

- `tests/lmstudio_labkit/test_managed_executor_mocked.py`
- `tests/lmstudio_labkit/test_managed_executor_cleanup_policy.py`
- `tests/lmstudio_labkit/test_managed_executor_no_raw_artifacts.py`

## B4/B5 — live small text configs and CLI live profile guards

Acceptance:

- Add:
  - `experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b.yaml`
  - `experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b_12b.yaml`
- Planning the first config offline is allowed.
- CLI `run` supports guarded `live-small` profile but fails without host executor:
  - `live profile is valid, but no host-managed executor was provided`
- `--live` is required for live profiles.
- `safety.live=true` is required in config.
- `--allow-model-loads` is required if config allows model loads.
- Downloads unsupported; image live unsupported; stress/overnight unsupported without separate profile.

Required tests:

- `tests/lmstudio_labkit/test_cli_live_profile_guards.py`
- `tests/lmstudio_labkit/test_cli_live_executor_missing.py`

## D — readiness report and final gates

Acceptance:

- Add `docs/live_matrix_readiness_report.md` with:
  1. What is implemented
  2. What was fixed after L3.12
  3. Offline/fake evidence
  4. Mocked-live evidence
  5. True-live evidence, if explicitly run
  6. Known limitations
  7. Overnight blockers
  8. Recommended first overnight profile
  9. Non-claims

Required checks before final commit/push:

```bash
python scripts/audit_publication_safety.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv build
uv run lmstudio-benchmark --help
uv run lmstudio-benchmark plan --config experiments/lmstudio/structured_matrix/configs/matrix.smoke.yaml --output-root /tmp/labkit-plan
uv run lmstudio-benchmark run --config experiments/lmstudio/structured_matrix/configs/matrix.smoke.yaml --output-root /tmp/labkit-run --profile offline-fake
uv run lmstudio-benchmark summarize --run-dir /tmp/labkit-run/matrix_smoke
uv run lmstudio-benchmark plan --config experiments/lmstudio/structured_matrix/configs/matrix.live_small_text.e2b_e4b.yaml --output-root /tmp/labkit-live-plan
```

## Stop conditions

Stop and report if:

1. Completion requires a true live run without explicit permission.
2. A model download is required.
3. Raw prompt/response must be stored for debugging.
4. Historical artifacts must be changed.
5. Task/axis compatibility breaks existing smoke config.
6. Privacy scanner flags its own safe artifacts.
7. Live runner requires major changes to old `tools/lmstudio_lab` internals.
8. Managed executor cannot be done without private/source-application coupling.
