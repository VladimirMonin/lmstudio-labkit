# Development Plan v2

## Goal

LM Studio LabKit is evolving into a reusable request core plus an extensible benchmark harness for LM Studio experiments across text, image, chat, structured, and non-structured workloads.

The near-term roadmap is documentation-first: describe the public facade, request abstractions, benchmark matrix, privacy-safe artifacts, and host-application integration boundary before expanding implementation. Default gates stay offline. Live LM Studio calls, model downloads, and large overnight runs remain explicit opt-in work.

## Non-goals for the documentation/planning slice

- Do not run live LM Studio.
- Do not download models.
- Do not edit historical experiment results except documentation/planning files.
- Do not claim planned lanes as implemented until code and tests exist.

## Phase 0 — Baseline extraction and publication safety

Preserve the extracted standalone baseline while keeping the repository publishable.

Scope:

- Keep the existing managed backend under `libs/lmstudio_managed/` and lab tools under `tools/lmstudio_lab/` working.
- Keep copied experiment documentation and result summaries sanitized.
- Keep the default test suite offline.
- Keep publication-safety checks as a required gate before committing docs.

Acceptance gate:

```bash
python scripts/audit_publication_safety.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv build
```

## L3.12 — Matrix Harness Hardening + Live Bridge

Status: implemented as an offline/default-safe hardening slice. No live LM Studio calls or model downloads are required by this phase.

Implemented scope:

- Hardened JSON Schema subset support for `type`, `required`, `properties`, `items`, `prefixItems`, `const`, `enum`, `additionalProperties: false`, `minItems`, `maxItems`, `minLength`, `maxLength`, `minimum`, and `maximum`.
- Exact ID validation now supports string and integer IDs, nested IDs, duplicate/missing/unexpected counts, preserved order, and first mismatch index.
- Business validators now cover empty output for non-empty input, length-ratio bounds, placeholder text, Markdown fence leakage, language compliance, image ground-truth labels, and finish-reason length failures.
- Schema builders exist for simple flat, Blocks JSON, complex nested, and image task families. The Blocks JSON `hardened_const` variant uses per-position `const` IDs.
- Public-safe task manifests exist under `experiments/lmstudio/structured_matrix/datasets/` with a loader in `lmstudio_labkit.datasets`.
- Offline fake transport supports deterministic failure/retry modes including invalid JSON, schema violation, missing/duplicate/reordered IDs, wrong language, placeholder text, Markdown-wrapped JSON, finish-length, retry recovery, deterministic retry failure, and image ground-truth misses.
- Artifact writing now performs a real privacy scan instead of emitting an unconditional pass.
- Reports now include per-model, per-axis, per-language, per-modality, per-complexity, per-schema-variant, retry-impact, and failure-taxonomy summaries.
- A guarded live bridge interface exists in `lmstudio_labkit.live_bridge`; it requires explicit `live=True`, rejects remote URLs without an explicit flag, rejects stress/overnight profiles without an explicit flag, and uses an injected executor so unit tests do not make network calls.
- CLI profiles distinguish offline and guarded live intent. Offline remains the default; live profiles fail without explicit flags and currently require a host-managed executor.

L3.12 acceptance gate:

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
```

## L3.13 — Axis compatibility, safety budgets, and report readiness

Status: implemented as an offline/default-safe readiness slice. No live LM Studio calls, model downloads, model loads, image live execution, stress profiles, or remote endpoints are enabled by default.

Implemented scope:

- Matrix planning records raw cartesian cells, filtered cells, skipped cells, and public skip reasons such as `language_mismatch`, `complexity_mismatch`, `volume_mismatch`, `unsupported_modality`, and `unsupported_context_tier`.
- Task and model metadata now drive compatibility filtering across model, language, complexity, volume, modality, context tier, `schema_variant`, and retry axes.
- `BenchmarkSafetyConfig` records the default safety budget: `live=false`, no downloads, no model loads, no raw prompt/response artifacts, no image live execution, no stress runs, and bounded request/model/context/repeat/runtime limits.
- Reports and summaries cover model outcomes, language, structure complexity, `schema_variant`, retry impact, skipped cells, safety budget, and guarded live-screening readiness.
- Guarded small text live screening remains host-managed through an injected executor and writes lab-only flags; offline `run_matrix` remains the default execution path.

L3.13 acceptance gate:

```bash
python scripts/audit_publication_safety.py
uv run ruff check .
uv run ruff format --check .
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv build
uv run lmstudio-benchmark plan-matrix --config experiments/lmstudio/structured_matrix/configs/matrix.smoke.yaml --output-root /tmp/labkit-l313-plan
uv run lmstudio-benchmark run-matrix --config experiments/lmstudio/structured_matrix/configs/matrix.smoke.yaml --output-root /tmp/labkit-l313-run --profile offline-fake
uv run lmstudio-benchmark summarize --run-dir /tmp/labkit-l313-run/matrix_smoke
```

## Phase 1 — Public package facade

Introduce a stable public facade package while preserving compatibility with the extracted layout.

Planned work:

- Add proposed public package namespace: `lmstudio_labkit`.
- Re-export stable request, benchmark, validation, artifact, and adapter types from the facade.
- Keep compatibility wrappers for existing `libs.lmstudio_managed` and `tools.lmstudio_lab` imports during the transition.
- Add import-smoke tests for installed package behavior.
- Document which modules are public API and which remain internal.

Done when:

- New code can import stable public symbols from `lmstudio_labkit`.
- Existing tests still pass through compatibility paths.
- README and API docs identify the public entry points without overpromising unfinished features.

## Phase 2 — Request core API

Design and implement the reusable request core that can express text, image, chat, structured, and non-structured LM Studio requests.

Planned work:

- Define request envelopes for chat messages, plain text prompts, image inputs, mixed text/image inputs, response-format expectations, and runtime options.
- Separate request planning from transport execution.
- Support structured and non-structured outputs through a common result envelope.
- Store only publication-safe request/response metadata in artifacts: hashes, counts, statuses, model IDs, timings, token/resource metrics, and validation outcomes.
- Keep raw prompts and raw responses out of default artifacts.

Done when:

- The request core can be tested offline with fake transports.
- Existing structured/text runners can be mapped onto the new envelope without live LM Studio.
- Privacy-safe artifact contracts are documented and tested.

## Phase 3 — Structured matrix benchmark harness

Build the matrix planner and executor for structured-output experiments.

Planned work:

- Use configurable axes for models, modality, language, structure complexity, volume, context tier, schema variant, retry policy, and repeats.
- Generate planned matrix cells without executing live requests by default.
- Run cells through the request core when live execution is explicitly enabled.
- Validate each cell with JSON parse, JSON Schema, business/Pydantic validation, exact ID checks, length ratios, placeholder detection, language checks, and optional image-ground-truth checks.
- Emit privacy-safe artifacts described in `docs/structured_matrix_design.md`.

Done when:

- Offline planner tests prove the matrix expands correctly.
- Fake-transport execution tests prove artifacts and validation summaries are deterministic.
- Live execution remains guarded behind explicit user/operator opt-in.

## Phase 4 — Text datasets and validators

Stabilize reusable text benchmark tasks and validators.

Planned work:

- Define text task families: simple flat extraction, medium block reconstruction, and complex nested structures.
- Keep dataset fixtures small enough for offline tests.
- Add validators for JSON structure, field-level business rules, ID exactness, language compliance, length ratio, duplicate/missing IDs, empty text, and placeholder text.
- Document how larger private datasets can be referenced without entering public artifacts.

Done when:

- Text validators can run independently of LM Studio.
- Dataset manifests describe privacy level, expected structure, and validation expectations.
- CLI profiles can select task families without editing code.

## Phase 5 — Image benchmark lane

Design the image and mixed text/image benchmark lane without claiming it is implemented before code exists.

Planned work:

- Define image task families: `ui_screenshot`, `code_screenshot`, `document_table`, `chart_graph`, `people_scene`, and `mixed_text_image`.
- Define image input manifests with file hashes, dimensions, synthetic/public-safe provenance, and expected ground-truth labels.
- Add validators for image-ground-truth alignment, extracted text fields, layout facts, object/scene labels, and structured result consistency.
- Keep raw image paths and private screenshots out of public artifacts.

Done when:

- Public-safe image fixtures or synthetic fixtures exist.
- Image lane artifacts use hashes and metadata rather than private local paths.
- The lane is clearly marked planned until request-core image execution is implemented and tested.

## Phase 6 — CLI profiles and overnight runner

Turn the benchmark harness into safe operator-facing CLI profiles.

Planned work:

- Add named profiles for no-live planning, offline fake-transport smoke, small live smoke, and long overnight runs.
- Keep the default CLI profile offline.
- Require explicit flags for live LM Studio calls, model loads, downloads, large context tiers, and long runs.
- Add resumable run IDs, partial summaries, and clear stop/resume behavior.
- Emit resource summaries suitable for overnight monitoring without raw prompts/responses.

Done when:

- Operators can run a no-live matrix plan from CLI.
- Overnight-capable profiles are explicit, guarded, and documented.
- Interrupted runs preserve enough metadata to resume or explain failure state.

## Phase 7 — Reports and synthesis

Produce useful reports from privacy-safe artifacts.

Planned work:

- Generate per-cell, per-model, per-axis, failure, retry, and resource summaries.
- Separate proven facts, lab-only candidates, blocked routes, and hypotheses.
- Add synthesis reports for model roles, request profiles, structured-output reliability, image-lane readiness, and non-promotion decisions.
- Keep reports product-neutral and publication-safe.

Done when:

- Reports can be generated from existing artifact files without rerunning live experiments.
- Synthesis output distinguishes implemented evidence from roadmap items.
- Publication-safety audit passes after report generation.

## Phase 8 — Host application integration adapter

Design a thin integration adapter for host applications without coupling the core LabKit package to any private product.

Planned work:

- Provide adapter interfaces for host-owned model selection, request scheduling, artifact storage, and UI/report consumption.
- Keep host-specific credentials, paths, workflows, and release policies outside the public package.
- Document the boundary between reusable request core, benchmark harness, and host application orchestration.
- Keep compatibility with private adapters through optional packages or local integration code.

Done when:

- A host application can depend on public `lmstudio_labkit` interfaces without importing lab internals.
- Private integration code can stay out of this repository.
- The public docs explain extension points without naming private products or workflows.

## Current next slice

The next implementation slice should stay narrow: canonicalize public package namespaces and import boundaries, keep `tools.*` compatibility wrappers tested, and add an installed-wheel smoke outside the repository. Continue to keep default gates offline and live LM Studio execution host-managed/explicit.
