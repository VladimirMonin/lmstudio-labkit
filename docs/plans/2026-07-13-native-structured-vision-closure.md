# Native Structured Vision Closure Plan

> **For Hermes:** Execute this plan through the `project-coding-workflow` Kanban graph with independent review, durable read-only monitoring, raw-artifact inspection, and evidence-based Git closure.

**Goal:** Determine whether the installed Gemma 4 family can process real image inputs with API-bound strict JSON Schema output, separate that capability from prompt-requested JSON on the native route, and publish corrected evidence-backed recommendations.

**Architecture:** Keep the native `/api/v1/chat` image route as the plain/perception baseline. Add or reuse a bounded OpenAI-compatible `/v1/chat/completions` image route that sends the same content-addressed PNG fixture as an image data URL and attaches `response_format.type=json_schema` with `strict=true`. Store raw request/response evidence outside Git, apply deterministic schema and grounded fixture validators, then perform independent semantic review before publication.

**Tech Stack:** Python 3.11/3.12 under `uv`, LM Studio REST APIs, existing LabKit lifecycle/forensics helpers, JSON Schema validation, pytest, Ruff, publication-safety audit, Hermes Kanban.

---

## Project and boundaries

```text
PRIMARY WORKDIR: /home/v/code/lmstudio-labkit
BOARD: lmstudio-labkit
MAY EDIT: LabKit vision runner/tests/configs, public-safe plan and result reports
READ ONLY: existing L3.34/L3.38/L3.39 evidence and owner-only raw artifacts
MUST NOT EDIT: source application repository, source application prompts/code, private fixtures, credentials
OUTPUT / EVIDENCE: public-safe Markdown+JSON reports in experiments/lmstudio/results_summaries; owner-only raw artifacts outside Git
```

The working branch is already four commits ahead of `origin/main`. `.hermes/` and `.serena/` are unrelated untracked state and must not be staged. Push requires valid GitHub authentication; authentication failure is an external closure blocker, not permission to rewrite history.

## Evidence questions

1. Which historical image runs requested JSON only in the prompt, and which attached an API-level strict JSON Schema?
2. Does the installed OpenAI-compatible image request shape accept the pinned PNG data URL together with `response_format.type=json_schema`?
3. For E2B, E4B, 12B QAT, and 26B-A4B QAT, does strict structured vision produce raw JSON, pass schema, and remain grounded in fixture truth?
4. Does `simple_description` return correct description, visible text, and warnings?
5. Does `medium_objects_text` improve usable extraction without introducing unsupported objects or text?
6. Are failures transport, response-surface, reasoning, truncation, syntax, schema, or semantic grounding failures?
7. Which models, routes, schemas, and caps are actually admissible for future local structured vision work?

## Approved live scope

Models already installed locally:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`

Public-safe fixture classes already present in the LabKit asset pack:

- Russian UI settings screenshot;
- Russian document/table screenshot;
- Russian chart screenshot;
- Python code editor screenshot.

Measured cells:

1. One matrix-wide no-image strict-schema route preflight: 1 call.
2. One native plain/perception baseline per model on the UI fixture: 4 calls.
3. Strict `simple_description` on four fixtures per model: 16 calls.
4. Strict `medium_objects_text` on the same four fixtures per model: 16 calls, lane-gated per model after simple failures.
5. One exact repeat of the UI `simple_description` cell for the first three accepted models in execution order: at most 3 calls.

Maximum live host calls: 40. Runs are serial, retries are off inside measured cells, reasoning is disabled where supported, temperature is zero, max image side is 1024, and each model lifecycle must end at global loaded count zero. The no-image preflight runs once for the matrix, not once per strict image row. No model downloads, Qwen/VL, parallel image calls, complex schema, full cartesian matrix, or source-application integration are authorized.

## Stage 1 — Reconcile historical evidence

### Task 1: Build the prompt-only versus schema-bound evidence inventory

**Objective:** Produce a public-safe table that classifies L3.34, L3.38, L3.39, and the 202-call text series by route, image payload, response contract, extraction surface, and semantic gate.

**Files:**
- Create: `experiments/lmstudio/results_summaries/2026-07-13_structured_route_evidence_reconciliation.md`
- Create: `experiments/lmstudio/results_summaries/2026-07-13_structured_route_evidence_reconciliation.json`

**Done condition:** The report explicitly identifies the old 27-call representation run and L3.39 vision as non-schema-bound structured evidence, identifies the 202-call text series as schema-bound, and lists every superseded or unsupported claim.

**Checks:** JSON parse, publication audit, direct source/artifact citations without private paths or content.

## Stage 2 — Implement and review the strict image route

### Task 2: Add a bounded schema-bound vision runner

**Objective:** Add the smallest reusable runner seam needed to send image data URL content with `response_format.type=json_schema`, capture the exact outbound request shape privately, and classify transport/syntax/schema/grounding separately.

**Files:**
- Modify or create only the minimal files under `tools/lmstudio_lab/`, `lmstudio_labkit/`, and matching tests/configs.
- Test: existing vision schema/validator tests plus new request-shape and extraction tests.

**Required behavior:**
- OpenAI-compatible `/v1/chat/completions` image content;
- API-bound strict JSON Schema;
- dual reasoning-disable controls when accepted by the route;
- owner-only request/response capture outside Git;
- deterministic lifecycle and global-zero cleanup;
- no prompt-only JSON counted as schema-bound success.

**Done condition:** Unit/integration tests prove the outbound payload includes both the image input and strict `response_format`, and a no-image text preflight proves the route can enforce the same schema before any image call.

### Task 3: Independent launch review

**Objective:** Verify exact payload shape, installed-route compatibility, fixture identity, stop gates, privacy, and lifecycle before model loading.

**Done condition:** Independent PASS report with exact evidence locations and no unresolved launch blocker. One bounded repair and fresh review are allowed; a second architectural rejection stops execution and returns to this plan.

### Stage 2 amendment after the second architectural REJECT

The second independent review rejected Stage 3 because the frozen contract is declarative rather than executable. The isolated request seam remains useful, but no further review-only decomposition or live call is allowed until the following controller repair is complete. This amendment supersedes the original one-repair limit only for this single manifest-driven repair and one fresh independent review; another architectural REJECT returns the work to a blocked owner gate.

#### Task 3A: Implement the manifest-pinned serial launch controller

**Objective:** Make the frozen manifest the only live entry point and enforce the approved request, budget, ordering, stop, semantic, runtime-identity, capture, and cleanup contracts in executable code.

**Files:**
- Modify: `lmstudio_labkit/strict_vision.py`
- Modify: `lmstudio_labkit/__init__.py`
- Modify: `tools/lmstudio_lab/build_strict_vision_launch.py`
- Modify: `experiments/lmstudio/strict_vision/launch_manifest.json`
- Modify: `experiments/lmstudio/structured_matrix/schemas/vision/vision_schema_contracts.yaml` only if needed to keep one canonical schema body
- Test: `tests/lmstudio_labkit/test_strict_structured_vision_runner.py`
- Test: `tests/lmstudio_labkit/test_strict_vision_launch_gates.py`
- Test: `tests/lmstudio_labkit/test_vision_schema_contracts.py`
- Test: `tests/lmstudio_labkit/test_vision_validator_contracts.py`

**Required TDD slices:**
1. Add failing tests proving that execution requires an independently pinned manifest SHA-256 and that rows cannot be substituted, skipped, reordered, duplicated, or appended.
2. Add failing tests for exact host-call accounting. The amended schedule is one matrix-wide no-image strict-schema preflight, four native baselines, sixteen simple rows, up to sixteen conditional medium rows, and up to three conditional repeats selected in model execution order: at most 40 total host calls. Preflight is not repeated per cell, retries remain off, and call 41 must be impossible.
3. Add failing full-payload equality tests proving manifest controls reach the forwarding seam, including `stream: false`, strict schema, reasoning controls, temperature, output cap, prompt, model, and exact image data URL.
4. Select the existing schema contract in `vision_schema_contracts.yaml` as canonical for `medium_objects_text`; make the builder, manifest, validator, and tests consume the same body and digest. Remove the duplicate same-name shape.
5. Add failing tests for a distinct malformed response-surface outcome before parse/schema validation.
6. Add failing tests proving direct manifest-to-request construction without manual tuple/list thawing and proving every private capture/safe row binds manifest digest, ordinal, model, fixture digest, schema digest, and request controls.
7. Add failing adversarial semantic tests. Public fixture truth must explicitly define supported visible-text/object values and forbidden claims; unsupported text or objects must block semantic admission rather than merely reduce recall.
8. Add failing runtime tests proving exact installed model identity and vision capability before load, then observed exact model key, context `8192`, and parallelism `1` after materialization and before chat.
9. Add direct failing tests for dimension mismatch and for `cleanup_verified=true` with a nonzero final global loaded count.
10. Implement the minimum controller and validator changes needed to pass the tests, including native baseline handling, route-canary stop, per-model simple/semantic lane stops, append-only progress, exception-safe cleanup, and matrix-final global-zero read-back.

**Verification:**

```bash
uv run pytest -q tests/lmstudio_labkit/test_strict_structured_vision_runner.py tests/lmstudio_labkit/test_strict_vision_launch_gates.py tests/lmstudio_labkit/test_vision_schema_contracts.py tests/lmstudio_labkit/test_vision_validator_contracts.py tests/lmstudio_labkit/test_failure_forensics.py tests/lmstudio_labkit/test_managed_executor_strict_schema.py
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
git diff --check
```

**Done condition:** One offline fake-host execution proves the exact manifest-derived schedule, request equality, all stop paths, host-call ceiling, capture binding, exact post-load runtime identity, semantic precision, and final global zero. No model load or live inference is part of this repair.

#### Task 3B: Fresh independent controller launch review

**Objective:** Independently review the amended executable contract rather than repeat isolated payload/test/privacy audits.

**Review scope:** Read-only inspection of the full Stage 2 diff, canonical schema identity, manifest digest and schedule, fake-host traces, exact forwarding payloads, call accounting, semantic adversarial cases, post-load runtime observation, private capture binding, and cleanup paths.

**Done condition:** A single executable PASS or REJECT handoff cites exact evidence. PASS explicitly authorizes only the manifest's serial schedule of at most 40 host calls and only when global loaded count is zero. REJECT lists reproducible blockers; another architecture expansion is not auto-dispatched.

**Non-claims:** Green offline tests do not prove installed-route acceptance or visual quality. Stage 3 remains blocked until this fresh independent review returns PASS.

### Stage 2 continuation amendment after semantic-gold review

The first 21 calls and their raw artifacts remain immutable evidence under launch-manifest digest `9f1b7fba…942e`. They must not be rerun or rewritten. Direct pixel review of all four PNGs and direct inspection of all 16 strict simple raw responses confirmed that the original `supported_visible_text` and `supported_objects` arrays were salient subsets incorrectly used as exhaustive precision gold.

The continuation contract therefore supersedes those two precision allow-lists without changing the historical controller verdict:

- `ui_settings_ru_001`, `document_table_products_ru_001`, and `chart_tasks_by_month_ru_001` carry complete pixel-reviewed visible-text transcripts. Emitted combined phrases and warning semantics still require manual phrase adjudication rather than substring allow-list promotion.
- `code_python_editor_001` uses explicit open-world pixel adjudication for text because publication-safe truth cannot reproduce every visible project/editor string. It makes no exhaustive-transcript claim.
- Object labels are open-world for all four fixtures. Required objects continue to provide recall anchors, but object precision is manually adjudicated against pixels; the controller must never treat the small required-object list as an exhaustive vocabulary.
- The executable validator reports `manual_precision_review_required` for corrected-truth rows after deterministic recall and forbidden-claim checks. Schema validity remains structural evidence only.

Manual acceptance requires all four conditions: grounded description, exact emitted visible text, supported/relevant warnings, and no forbidden claim. Exactly five prior simple rows meet that rubric:

- `sv-04-e2b-simple-document_table_products_ru_001`;
- `sv-14-e4b-simple-document_table_products_ru_001`;
- `sv-15-e4b-simple-chart_tasks_by_month_ru_001`;
- `sv-33-26b-simple-ui_settings_ru_001`;
- `sv-34-26b-simple-document_table_products_ru_001`.

All observed errors remain frozen in `continuation_manifest.json`, including the incorrect Russian banner verb, chart-legend OCR error and omitted values, code-token errors, wrong model key, invented cursor occlusion, invalid literal warning value, and warning entries that merely translate or classify visible text instead of expressing uncertainty.

The continuation is exactly 19 calls: all 16 previously uncalled `medium_objects_text` rows plus UI repeats for E2B, E4B, and 26B. Those repeat models are the first three models in execution order with at least one manually accepted simple row; 12B has none and `sv-31-12b-repeat-ui` is permanently excluded. Medium rows are opened as manually reviewed evidence-gathering rows because the original model-wide simple gate was invalidated by defective precision gold; opening them does not retroactively accept failed simple rows or admit any model.

Before any continuation call, the controller must revalidate the base manifest, the exact prior 41-row progress ledger, the 21 executed call IDs and host indices `1..21`, the independent review ledger, and the five-row manual acceptance set by pinned SHA-256. It then permits only the frozen 19 IDs with cumulative host indices `22..40`. Any prior call ID, substituted evidence, reordered tail, extra repeat, or attempted cumulative call 41 fails before inference. Retries remain off and every corrected-truth output still requires independent manual semantic review.

No live call is authorized by this amendment alone. Fresh independent review of the continuation manifest, loader/controller, tests, and exact evidence bindings is required before execution.

## Stage 3 — Execute the live matrix

### Task 4: Run the approved serial cells

**Objective:** Execute up to 40 approved calls under one content-addressed manifest and append-only owner-only artifact roots.

**Execution order:** E2B → E4B → 12B → 26B; within each model: native plain baseline → simple schema cells → conditional medium cells → conditional exact repeat.

**Per-cell gates:**
- exact model and variant verified;
- HTTP/API transport recorded;
- non-empty correct response surface;
- reasoning output tokens zero where controllable;
- no output-cap truncation;
- raw JSON parse;
- strict schema validation;
- grounded fixture validators;
- privacy-safe public summary;
- unload and global-zero verification.

**Stop rules:**
- route-level rejection on the first E2B schema-bound image canary blocks the remaining matrix and triggers evidence/reporting, not a route workaround;
- a model's simple-schema hard failure blocks its medium and repeat cells;
- semantic grounding failure is recorded separately and blocks model admission even if schema passes;
- no automatic retry or cap increase inside measured cells.

## Stage 4 — Analyze artifacts and red-team claims

### Task 5: Independent structural and semantic review

**Objective:** Read raw outputs for every executed cell and score raw JSON, schema, visible-text recall/precision, object grounding, forbidden claims, uncertainty handling, and exact-repeat behavior.

**Done condition:** A private review ledger and public-safe aggregate exist; worker self-report alone is insufficient.

### Task 6: Red-team the combined evidence

**Objective:** Attempt to falsify route, schema, semantic, repeatability, model-ranking, and admission claims; reconcile denominators and stop-gated zero-call rows.

**Done condition:** Every final claim is classified as confirmed, overstated, unsupported, or contradicted, with mandatory report corrections listed.

## Stage 5 — Reports and Git closure

### Task 7: Publish corrected reports

**Objective:** Create final Markdown+JSON reports and update canonical admission/model-card documents without erasing historical measurements.

**Files:**
- Create: `experiments/lmstudio/results_summaries/2026-07-13_native_structured_vision_closure.md`
- Create: `experiments/lmstudio/results_summaries/2026-07-13_native_structured_vision_closure.json`
- Update: relevant L3.34/L3.35 decision records, admission matrix, and Gemma model cards.

**Done condition:** Reports distinguish prompt-only JSON, fence-normalized JSON, API-bound strict schema, schema validity, and semantic grounding. Image work is not called closed unless the executed evidence supports it.

### Task 8: Final gates, commit, and push

**Objective:** Verify the canonical chain and publish the logical slices.

**Commands:**

```bash
python3 -m json.tool <each new JSON report>
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
git diff --check
```

**Done condition:** Staged scope excludes private artifacts, `.hermes/`, `.serena/`, credentials, and raw fixtures; commits describe staged diffs; push succeeds and local/origin SHA equality is verified. If GitHub authentication remains invalid, preserve exact local SHAs and report that sole external blocker.

## Coordination and sleep-loop contract

- Real Kanban cards own the eight tasks above; `delegate_task` summaries are not called cards.
- A recurring read-only scheduler monitor runs every 10 minutes from first dispatch until final commit/push or a verified external blocker.
- Every tick reports board active front, exact worker/process identity, artifact progress, loaded-model state during live execution, and Git closure state.
- The monitor never dispatches, retries, completes, or accepts cards.
- At each terminal/review boundary the coordinator reads artifacts, reconciles the card in foreground, dispatches only the next approved stage, and verifies a replacement monitor.

## Non-goals

- No changes to the source application.
- No source-application integration or production rollout.
- No broad text/context/cache rerun.
- No Qwen/VL, 31B, parallel vision, complex schema, video, audio, or paid/cloud calls.
- No claim that syntactic JSON or schema validity proves visual understanding.
- No history rewrite, force-push, reset, or cleanup of unrelated working-tree state.

## Ready when

- Historical structured claims are reconciled by route and contract.
- At least the approved canary is executed with captured API-bound schema evidence, or a verified route-level blocker is documented.
- Every executed output is independently reviewed for syntax, schema, and grounding.
- Canonical reports are corrected and pass publication gates.
- Git closure is verified or reduced to one exact external authentication blocker.

## Stop and ask the user if

- a second independent review still requires a new architecture rather than a bounded repair;
- the installed LM Studio route cannot express image plus strict schema and an alternative route would materially change the plan;
- a model download, external repository edit, paid API, or broader than 40-call matrix becomes necessary;
- evidence contradicts the plan's route assumptions or fixture truth.
