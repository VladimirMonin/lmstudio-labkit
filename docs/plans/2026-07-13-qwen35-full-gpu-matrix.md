# Qwen 3.5 Full-GPU Matrix Plan

**Status:** ACTIVE PLAN; Stage 3 now binds runtime events to the exact immutable SDK instance reference and starts process monitoring before materialization, but the installed contracts expose no explicit negative authority for CPU fallback or resource downgrade. Those facts remain unknown and fail closed, so no canary, model load, or inference is authorized.

**Goal:** Evaluate the installed Qwen 3.5 4B and 9B models across the reusable LabKit matrices under verified 100% GPU offload, preserve raw evidence, review semantic quality directly, and publish bounded recommendations.

**Models:**

- `qwen/qwen3.5-4b` — Q4_K_M, vision, estimated 3.76 GiB GPU at context 8192.
- `qwen3.5-9b-mtp` — Q4_K_S, vision, estimated 6.89 GiB GPU at context 8192; estimate confidence is low.

No download is needed or authorized. Exact installed identifiers and file hashes must be pinned before live execution.

## Hard runtime gate

Every measured lane is serial and starts from global loaded count zero. Load with explicit full offload (`lms load <model> --gpu max`, or equivalent REST ratio `1.0` with echoed load configuration), context 8192, parallel 1 unless the concurrency lane explicitly changes parallelism.

A model is runnable only when all are observed after materialization:

1. exact model/variant identity;
2. authoritative loaded-instance runtime telemetry proving `gpu_layers == total_layers > 0`; a requested or echoed 100% GPU ratio is not execution evidence;
3. KV cache GPU placement when supported;
4. requested context and parallelism;
5. no CPU fallback, resource-guardrail downgrade, or sustained memory thrashing;
6. successful unload and global loaded count zero.

If full offload is not proven, stop that model before inference and report a zero-call matrix. Partial offload is not an alternative.

## Bounded matrices

The launch manifest must freeze exact calls and keep the cumulative inference ceiling at **80**. Retries are off inside measured cells; one explicit repair attempt is allowed only outside the measured denominator after a classified transport/runtime failure.

1. **Lifecycle and strict-route canary** — exact identity, full-GPU load, one API-bound strict JSON call per model, unload/global-zero.
2. **Structured text** — publication-safe small/medium/long fixtures; simple and blocks schemas; reasoning off and on recorded separately only where the model exposes the control.
3. **Context and cache/session** — 8k baseline plus 16k only after a fresh full-GPU estimate/materialization PASS; cold versus warm/prefix/session evidence kept separate.
4. **Concurrency** — sequential baseline and bounded parallel=2 only after a dedicated full-GPU materialization PASS; no wider parallelism.
5. **Strict structured vision** — the same four content-addressed PNG fixtures, native plain baseline, strict `simple_description`, strict `medium_objects_text`, and one exact UI repeat per admitted model.

The repaired inventory freezes 66 candidate rows and accounts for 68 actual HTTP/inference calls in `experiments/lmstudio/qwen35_full_gpu/launch_manifest.json` (manifest SHA-256 `46264eda0caef52a0634832fa69013c42e1a44926007c704c8542e24c867b5fc`): 36 rows for `qwen/qwen3.5-4b` and 30 for `qwen3.5-9b-mtp`, with each of the two `parallel_pair` rows consuming two calls. The difference between model row counts is deliberate: the exact installed 4B metadata advertises `off` and `on` reasoning controls, while the 9B MTP metadata advertises no reasoning control, so its rows omit the field rather than inventing support. Planned cells are not executed evidence; failed identity, base, 16k, or parallel-2 full-GPU materialization leaves explicit zero-call rows.

The manifest pins canonical installed-metadata identity hashes (`56f7b03d…39b09` for 4B and `204e9b63…ef78f` for 9B MTP), the executable production host hash (`948a148f…08139`), all reused runner/config hashes, the four existing content-addressed PNGs, serial row order, owner-only capture, exclusive locking, evidence-validated append-only resume, and per-load-group cleanup/global-zero. Catalog identity alone does not authorize a canary: before any model load, the operator must generate and re-validate an owner-only external pin with the `pin-artifacts` entrypoint against this exact manifest SHA-256; its ordered artifact files must match the frozen names, absolute path digests, sizes, and file SHA-256 values. The artifact-pin handoff uses canonical structural validation rather than Python class identity, so the frozen `python -m` entrypoint accepts the same exact owner-only pin while malformed or forged canonical bindings still fail closed. Every load group persists independent initial and final `lms ps --json` plus native API zero observations, and inference remains closed until the owner-only materialization attestation positively proves every required identity, shape, GPU, fallback, downgrade, and thrash field. Installed `loaded_instances[].id` and parent model key bind the API instance, while installed SDK 1.5.0 `listLoaded()` plus `getModelInfo()` provide the authoritative immutable `instanceReference`. The runtime event reference must equal that SDK reference exactly, and its PID must remain bound to one stable `/proc/<pid>/stat` process-start identity. Process monitoring starts before `lms load`, discovers the runtime PID from the identity-bound stream, and spans materialization through attestation for direct swap and major-fault evidence. The installed SDK/runtime schemas expose no explicit negative booleans for CPU fallback or resource downgrade; backend messages only expose positive fault signals. The production host therefore records exact installed-source capability-unavailable evidence and leaves both negative facts unknown rather than synthesizing false from silence. A same-model event with a foreign instance reference, missing SDK authority, unstable process identity, partial offload, or unknown required negative state remains fail-closed with zero inference. Fresh independent review is mandatory; Stage 4 remains closed.

## Evidence model

- Owner-only append-only requests, responses, image bytes, runtime/load configuration, and GPU observations remain outside Git.
- Public Markdown+JSON contain only sanitized denominators, timings, token counts, schema/semantic verdicts, and content hashes.
- Transport, response surface, raw parse, JSON Schema, business validation, semantic quality, repeatability, cache effects, and concurrency are separate dimensions.
- Image semantics are judged primarily by direct multimodal inspection of the PNG and raw response. Deterministic validators are secondary checks, never exhaustive open-world gold.
- Vision and structured-text acceptance remains false until an append-only, post-execution review record is bound to the exact private capture digest; structured text requires explicit content-fidelity adjudication.
- Every actual HTTP attempt is durably reserved with exact outbound bytes before send. Available raw response or typed transport evidence is persisted separately, including partial parallel failures. Resume never resends a reserved attempt, requires a contiguous manifest prefix, and stop-gates the unfinished tail of a partially completed stateful cache/session group.

## Stages

1. **Inventory and manifest:** map reusable Gemma matrices to Qwen, pin model IDs/assets/schemas/call ceiling, and add full-GPU evidence fields.
2. **Independent launch review:** verify no overlap with current work, exact ≤80 schedule, full-GPU fail-closed contract, privacy, raw capture, and cleanup.
3. **GPU canaries:** 4B then 9B. A model that cannot prove full offload is stop-gated with no measured inference.
4. **Live matrices:** execute only reviewed cells, serial by model and lane, with per-lane cleanup/global-zero.
5. **Manual review and red-team:** read every raw output, inspect every vision response against pixels, reconcile denominators and invalidate overclaims.
6. **Reports and Git readiness:** publish Qwen model cards/matrix report, run all offline gates, inspect staged scope, and stop at an explicit user gate before commit/push.

## Coordination

- Board: `lmstudio-labkit`; workdir: `/home/v/code/lmstudio-labkit`.
- The Qwen wave is blocked on the current structured-integration synthesis to avoid shared-checkout writers.
- One idempotent agent coordinator cron performs bounded reconciliation ticks every 5 minutes, follows newly created repair/re-review cards dynamically, and never runs overlapping writers.
- Material transitions must be delivered proactively. The coordinator removes itself only after final Git/runtime verification and a final delivery.

## Required gates

```bash
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
git diff --check
```

## Non-goals

- No model download, cloud/paid call, source-application edit, prompt disclosure, private artifact publication, audio/video matrix, parallelism above 2, context above 16k, force-push, reset, or unrelated cleanup.
- No production admission or model ranking from schema validity alone.
- No fallback to partial GPU offload.

## Done

The exact bounded schedule is executed or stop-gated, every output is independently reviewed, full-GPU claims are backed by observed runtime configuration, reports and raw evidence exist, models are unloaded, all gates pass, and the exact commit/push scope is prepared for explicit user authorization.
