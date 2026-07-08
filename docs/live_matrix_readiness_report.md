# Live Matrix Readiness Report

This report summarizes the L3.13 live-matrix-readiness hardening wave. The default path remains offline/fake. No true live LM Studio run, model download, model load, stress/overnight run, image live run, or raw prompt/response artifact was executed or stored during this wave.

## 1. What is implemented

- Core benchmark safety configuration and budget guards:
  - `planned_requests > max_requests` fails.
  - `model_count > max_models` fails.
  - `context_tier > max_context_tier` fails.
  - `repeats > max_repeats` fails.
  - `volume=stress` with `allow_stress=false` fails.
  - `modality=image` with `live=true` and `allow_image_live=false` fails.
  - `allow_raw_prompt_response_artifacts=true` is rejected in public/default mode.
  - `allow_model_downloads=true` is rejected because downloads are not supported by this public harness.
- Task/axis compatibility filtering with structured skip reasons.
- Scoped ID validation for nested structures via explicit `id_paths` and `collect_ids_by_path(...)`.
- Task-specific language validation policies: `strict_ru`, `strict_en`, `mixed_ru_en`, `allow_code_terms`, `labels_only`, and `skip`.
- Flattened validation metrics in cell and model CSV summaries.
- Privacy-safe live metadata sidecars that store only `base_url_kind` and `base_url_scheme`, never a full URL or host.
- Artifact privacy scanning across generated summaries and sidecars.
- Matrix transport interface with fake/default transport and a guarded `LiveBridgeTransport` path through an injected executor.
- Mocked managed LM Studio executor adapter for text structured JSON requests only.
- Live-small text matrix configs for plan-only and future explicitly approved live screening.
- CLI live-small profile guard that validates the profile but fails without a host-managed executor.

## 2. What was fixed after L3.12

- Safety checks were moved into core planning/execution paths rather than only CLI-level assumptions.
- ID validation was hardened for nested tasks and order preservation.
- Language validation was made task-specific instead of relying on a single global ratio.
- Reports now expose flattened validation status/count fields suitable for overnight diagnostics.
- Privacy scanning is no longer a placeholder: tests verify it catches unsafe sidecars.
- Live bridge code is wired to `run_matrix(...)` through explicit transport injection instead of an implicit network path.
- Managed execution no longer loads a model unless `allow_model_loads=true` is explicitly enabled.

## 3. Offline/fake evidence

Observed local gates during this wave:

- `uv run pytest -q tests/lmstudio_labkit` passed with `117 passed` for the B4/B5 targeted slice.
- `uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit` passed with `1036 passed` after B4/B5.
- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed with `143 files already formatted`.
- `python scripts/audit_publication_safety.py` passed.
- `uv build --out-dir ...` built both sdist and wheel successfully.
- `lmstudio-benchmark plan` for the live-small text config completed in plan-only mode and produced privacy-safe artifacts.
- The smoke privacy scan for generated plan artifacts returned `status: pass` and `violation_count: 0`.

## 4. Mocked-live evidence

Mocked live coverage includes:

- Injected transport execution through `run_matrix(...)`.
- Live path rejection when no executor is provided.
- Request-count guard enforcement for live transport.
- Image live rejection.
- Managed executor adapter behavior with mocked host runner only.
- Cleanup/final-instance policy checks.
- No raw-response artifact persistence.
- No host model-load call unless `allow_model_loads=true` is explicitly set.

## 5. True-live evidence

No true live evidence is claimed in this report.

True-live LM Studio execution was intentionally not run in this wave. GPU availability, LM Studio Link availability, loaded model state, and endpoint readiness must be verified in a separate, explicit live screening command.

## 6. Known limitations

- The managed executor adapter is v1-scoped to text structured JSON requests.
- Image live is intentionally unsupported.
- Stress and overnight profiles are intentionally unsupported in this readiness wave.
- Downloads are intentionally unsupported by the public harness.
- Remote base URLs require explicit opt-in and still persist only safe classification metadata.
- The live-small configs use public-safe model keys and IDs; local host/model mapping belongs to the host-managed executor layer.

## 7. Overnight blockers

Before any overnight run:

1. Run and inspect a true live-small text screening with explicit approval.
2. Confirm LM Studio Link/GPU availability and model residency outside the public artifact stream.
3. Confirm no model download is required.
4. Confirm no raw prompt/response artifact is needed for debugging.
5. Review live-small outputs and failure taxonomy.
6. Decide whether to widen model count, task count, repeats, or context tier.
7. Add a separate explicit overnight profile with stricter runtime and artifact retention rules.

## 8. Recommended first overnight profile

The recommended sequence is not to start overnight immediately:

1. Plan-only: `matrix.live_small_text.e2b_e4b.yaml`.
2. Explicit live-small text screening for the 2-model config.
3. If clean, explicit live-small text screening for the 3-model config.
4. Only after reviewing artifacts, create a separate overnight profile with bounded repeats, no image live, no downloads, no raw artifacts, and explicit runtime limits.

## 9. Non-claims

This wave does not claim:

- That LM Studio is currently running.
- That GPU acceleration is available.
- That LM Studio Link is reachable.
- That any model was loaded.
- That any model was downloaded.
- That a 12B or larger model was executed.
- That image live is supported.
- That stress or overnight runs are ready without another explicit approval step.
- That raw prompt/response artifacts are safe to persist.
