# L3.30-L3.36 Final Evidence Audit — 2026-07-10

Status: `partial_not_green`. This is a publication-safe aggregate audit of committed code, configs, sanitized reports, Git history, remote synchronization, verification gates, and selected Kanban evidence. It does not run live inference, load or download models, send image requests, or modify an external runtime.

Timestamp: 2026-07-10T11:37:10+05:00

## Audit verdict

The Gemma closure series has a valid accepted core, but it is not family-wide green:

- accepted default scope: E2B, E4B, and 12B at context 8192 for transcript cleanup, structured simple, and structured blocks;
- accepted narrow extensions: E2B/E4B L3.31a 16k canary, E2B/E4B L3.32a complex JSON canary, and E4B L3.33a session-loaded quality canary;
- partial or blocked: 12B blocks at 16k, 12B cache/session, and all Gemma vision admission;
- not run: 12B complex JSON, 26B structured/cache/vision expansion, L3.35 image screening, and 32k admission;
- prepared only: the broad L3.30 image matrix and later bounded expansion configs;
- not proven: physical KV reuse or cache benefit.

The current canonical admission sources are:

1. `experiments/lmstudio/results_summaries/l3_31_l3_36_gemma_admission_matrix.md`;
2. `experiments/lmstudio/results_summaries/l3_36_gemma_family_final_synthesis.md`;
3. `docs/gemma_family_model_cards.md`.

Older phase records remain useful as chronological evidence, but several are stale and must not override those canonical sources.

## Per-phase outcome

| phase | evidence class | outcome | verified evidence and limit |
|---|---|---|---|
| L3.30 vision preparation | `prepared_only` | accepted as preparation, not model admission | Public-safe assets, schemas, validators, and capability-gated configs are committed. No L3.30 live image inference was run. The historical text-only registry posture was later superseded by runtime metadata, but no usable image output was admitted. |
| L3.31 context | `partial` | E2B and E4B accepted for the 9-cell 16k canary scope; 12B transcript cleanup and structured simple accepted; 12B structured blocks blocked | Sanitized live aggregate: 9 attempts, 8 pass, 1 fail, privacy pass, final loaded count 0. The failed 12B blocks cell ended at `finish_reason=length`, 16261 completion tokens, and empty extracted content. The optional capped repair attempt is `inconclusive_recorder_error`, not evidence. |
| L3.32 complex JSON | `accepted_narrow` plus `not_run` | E2B/E4B complex at 8192 accepted; 12B and 26B complex not admitted | Sanitized live aggregate: 4 attempts, 4 pass, privacy pass, final loaded count 0. The owner explicitly allowed this independent probe after red L3.31. L3.32b/c/d remain unexecuted in this closure series. |
| L3.33 cache/session | `partial` | E4B accepted narrowly for `session_loaded` with `none` and `warmup_first`; 12B blocked | Second live attempt: 24 attempts, 22 pass, 2 hard failures, privacy pass, final loaded count 0. First attempt was a runtime stall with no artifacts and was cleaned up. Timing is quality/route evidence only; `kv_reuse_proven=false`, `cache_benefit_claimed=false`. |
| L3.34 image route | `blocked` | API payload acceptance proven; usable Gemma image output not proven | Four-model compat route probe accepted PNG data URI payloads but all four ended at length with no JSON/schema pass. L3.34.1 E4B plain-text repair returned HTTP 200 but empty content at explicit 256-token cap. This separates route acceptance from usable generation. |
| L3.35 image screening | `blocked` / `not_run` | no model admitted; zero screening attempts | Stop condition was correctly applied because L3.34/L3.34.1 produced no non-empty plain text or JSON/schema-pass image result. |
| L3.36 synthesis | `partial_not_green` | accepted as a truthful partial synthesis, not as family closure | The canonical synthesis and model cards correctly retain blocked/not-run modes and do not claim KV reuse, cache benefit, image support, or broad 26B admission. |

## Per-model admission

| model | accepted | partial / blocked | not run / prepared only | current role |
|---|---|---|---|---|
| `google/gemma-4-e2b` | 8192 transcript/simple/blocks; L3.31a 16k transcript/simple/blocks; L3.32a complex JSON | vision not admitted | L3.33 cache/session; 32k; broad image matrix | lightweight baseline |
| `google/gemma-4-e4b` | 8192 transcript/simple/blocks; L3.31a 16k transcript/simple/blocks; L3.32a complex JSON; narrow L3.33a session-loaded quality scope | vision blocked by empty length-limited output; KV reuse and cache benefit unproven | 32k; L3.35 image matrix | strongest current general candidate |
| `google/gemma-4-12b-qat` | 8192 transcript/simple/blocks; L3.31a 16k transcript and structured simple | 16k structured blocks blocked; L3.33a blocked by two finish-length hard failures | complex JSON, vision, 32k | high-quality candidate requiring capped repair evidence |
| `google/gemma-4-26b-a4b-qat` | controlled 8192 transcript cleanup only | no broad family admission | structured simple/blocks/complex, cache/session, vision, 16k/32k expansion | research/capacity constrained |

## Actual code and config audit

Verified from current `main`:

- `lmstudio_labkit/requests.py` defines `ExecutionOptions.max_tokens` and includes it in safe metadata.
- `lmstudio_labkit/benchmarks.py` parses the `max_tokens` axis into request plans and parses `request_timeout_s` into `timeout_s`.
- The matrix runner rejects live `warmup_first` unless `execution_mode=session_loaded`.
- L3.33a is now valid by construction: `session_loaded`, cache modes `none` and `warmup_first`, repeats 3, 24 planned rows, timeout 600 seconds, parallel 1.
- `lmstudio_labkit/managed_executor.py` still supports text-only OpenAI-compatible structured JSON. It explicitly rejects image requests and native endpoints.
- Important remaining code gap: `ManagedHostRunner.chat_completion` and `ManagedLMStudioExecutor` do not currently accept or forward `plan.options.max_tokens`. Planner/artifact support is present, but a managed 12B capped repair rerun is not ready until forwarding is implemented and tested through this execution seam.
- The committed L3.34 config remains non-live and yields unsupported-modality skips because committed model specs are text-only. The historical direct live image probes therefore remain outside the managed matrix executor.

This code audit is stricter than the earlier Kanban self-report that described explicit `max_tokens` support as broadly implemented. The implementation is complete for request planning, safe artifacts, and selected diagnostic tooling, but not for the managed matrix host-runner call.

## Live aggregate evidence audit

The committed aggregate reports support these exact counts:

| evidence | attempts | pass | fail | privacy | cleanup |
|---|---:|---:|---:|---|---|
| L3.29 accepted 8192 executable slice | 113 | 113 | 0 | pass | final loaded-like count 0 |
| L3.31a 16k context | 9 | 8 | 1 | pass | final loaded count 0 |
| L3.32a E2B/E4B complex JSON | 4 | 4 | 0 | pass | final loaded count 0 |
| L3.33a second cache/session attempt | 24 | 22 | 2 | pass | final loaded count 0 |
| L3.34 compat image route probe | 4 | 0 accepted schema results | 4 | sanitized summary | each final loaded count 0 |
| L3.34.1 E4B plain-text image repair | 1 | 0 | 1 | sanitized summary | final loaded count 0 |
| L3.35 image screening | 0 | 0 | 0 | not applicable | not run |

The ignored raw live-run directories are not treated as publication artifacts. The audit relies on tracked sanitized aggregates and their hashes/counts, not raw prompts, raw responses, or image bytes.

## Commits and GitHub synchronization

The L3.30-L3.36 closure lineage is present in `main`, including:

- `23fd599` — prepare L3.30 Gemma vision matrix;
- `5159c87` — prepare L3.31 and L3.32 gates;
- `ba9a73c` — prepare L3.33 and L3.34 gates;
- `d41d222` — record launch blockers;
- `612d6f6` — record L3.31-L3.36 live rerun;
- `12f29dc` — add repair forensics and admission matrix;
- `a3808f5` — add explicit max-token plan/artifact support;
- `b1dff02` — record source-application cache and route evidence;
- `caa2d34` — update final Gemma admission synthesis.

Remote verification after `git fetch` and `git ls-remote`:

```text
local HEAD:  caa2d34eb0d3351d327644776b71d36e8f81e552
origin/main: caa2d34eb0d3351d327644776b71d36e8f81e552
remote main: caa2d34eb0d3351d327644776b71d36e8f81e552
ahead/behind: 0/0
```

The audit report itself is intentionally left uncommitted for human review. The only pre-existing unrelated untracked path at audit start was `.hermes/`.

## Verification run for this audit

All non-live gates passed on current `main` and were repeated after this report was written:

```text
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
1226 passed in 10.41s on the final post-write run

uv run ruff check .
All checks passed.

uv run ruff format --check .
202 files already formatted

python scripts/audit_publication_safety.py
Publication safety audit passed.

git diff --check
passed

uv build
sdist and wheel built successfully

uv run lmstudio-benchmark --help
passed
```

The `uv` commands emitted only the expected warning that the active Hermes virtual environment differs from the project `.venv`; `uv` ignored it and used the project environment.

## Stale and conflicting reports

These files are tracked historical records but stale relative to later committed evidence:

| file | classification | conflict | audit handling |
|---|---|---|---|
| `l3_31_l3_36_live_launch_status_report.md` | `stale_historical` | Records runtime unavailable and zero live attempts before the later rerun. | Retain as launch-history evidence; never use as current admission state. |
| `l3_32_gemma_json_complexity_decision_record.md` | `stale_conflicting` | Header and body still say prepared-only/no L3.32 live inference, while L3.32a later passed 4/4. | Canonical admission matrix and final synthesis override it. Update in a future docs-cleanup slice if phase records must be self-current. |
| `l3_33_gemma_cache_session_decision_record.md` | `stale_conflicting` | Says prepared-only/no L3.33 live inference and describes a 48-row canary; current config has 24 valid rows and live evidence is 22/24. | Canonical synthesis and live rerun report override it. |
| `l3_35_gemma_vision_screening_decision_record.md` | `stale_conflicting` | Says no live route request and text-only metadata; later runtime metadata and direct probes did send image route requests. The final L3.35 outcome remains blocked with zero screening attempts. | Preserve only its stop-policy logic; use later route reports for capability evidence. |
| `l3_31_l3_36_structured_output_code_evidence_report.md` | `stale_code_snapshot` | Its statement that LabKit does not forward `max_tokens` predates `a3808f5`; planner/artifact support now exists. Its image/native-route limitation remains current. | Use this audit's code section for current implementation status. |
| `l3_30_gemma_vision_matrix_preparation_report.md` | `accepted_prepared_only` with superseded metadata note | Preparation is valid, but its committed text-only capability posture was superseded by runtime metadata. | Keep as L3.30 preparation evidence only. |

No canonical model-card fact required modification in this audit: the current model cards already classify closure as partial, retain the blocked 12B and vision modes, and require max-token forwarding before the 12B repair rerun.

## Kanban evidence audit

Verified board evidence includes:

- `t_78cc2f11`: done; canonical synthesis/model-card update committed and pushed at `caa2d34`.
- `t_57ce6f66`: done after review; planner/artifact/diagnostic max-token support committed at `a3808f5`. Its broad wording overstates managed-executor readiness; actual code still lacks max-token forwarding in the host-runner seam.
- `t_4b58ebec`: done after review; source-application cache evidence sanitized and committed at `b1dff02`.
- `t_da799d90`: done; native image route investigation produced the next narrow gate.
- `t_e69fdb9d`: correctly blocked pending explicit owner approval. It was once auto-promoted and started, then reclaimed and terminated. No accepted result exists from that run.

Kanban completion state is evidence of workflow/review, not a substitute for code, tracked reports, Git history, or test output. This audit resolves conflicts in favor of current code and committed aggregate evidence.

## Follow-up cards required for true family closure

One concrete card already exists:

1. `t_e69fdb9d` — L3.34.2 gated native REST image route canary. Keep blocked until explicit owner approval. E4B only, one public-safe asset, native `/api/v1/chat`, `data_url`, `output[]` extraction, 128 tokens with one optional 512-token repeat, cleanup final zero. No JSON phase or L3.35 expansion until non-empty plain text passes.

The board still needs these narrowly scoped cards before a true closure claim:

2. **Managed max-token forwarding implementation and review**
   - Add `max_tokens` to `ManagedHostRunner.chat_completion` and forward `RequestPlan.options.max_tokens` from `ManagedLMStudioExecutor`.
   - Add mocked contract tests proving value propagation, omission when unset, recorder persistence, finish-length validation, and cleanup on success/error.
   - Non-live only; full project gates required.

3. **L3.31c one-attempt 12B blocks@16k capped repair live gate**
   - Depends on card 2 review acceptance and explicit owner live approval.
   - Exactly one 12B blocks request at 16384, explicit cap 1024, retry off, durable sanitized summary, privacy pass, final loaded count zero.
   - Admit only this cell if it passes; do not infer broad 12B 16k acceptance.

4. **L3.32b 12B complex JSON canary**
   - Depends on either successful card 3 or an explicit owner decision that 12B complex is independent of the blocks@16k repair.
   - Use the existing 4-request prepared config at 8192; no broad L3.32c screening, 26B, image, cache, parallel, or stress expansion.

5. **L3.33c 12B cache/session repair design and bounded rerun**
   - First isolate which two task/cache cells hit length and add explicit output caps without changing session-loaded ownership.
   - Live phase requires explicit approval; parallel 1, context 8192, stable prefix, final loaded count zero, sanitized telemetry.
   - Never claim KV reuse or cache benefit from timing alone.

6. **L3.35 tiny image canary**
   - Create only if card 1 proves non-empty native plain text and a subsequent minimal JSON/schema canary passes on the same model/route.
   - Four to eight requests maximum; simple description only; no complex image schema or full matrix.

7. **L3.36 final re-audit and synthesis**
   - Depends on cards 2-6 reaching accepted, explicitly waived, or durable blocked/not-run outcomes.
   - Re-run full non-live gates, publication audit, remote synchronization proof, stale-report reconciliation, and model-card update.
   - `full_green` is permitted only if every required mode is proven; otherwise retain `partial_not_green`.

Only the current `default` profile is available on this host. New live-gate cards were not auto-created by this audit because they require explicit owner approval and must remain human-gated rather than becoming dependency-promoted work.

## Final non-claims

This audit does not claim:

- full green Gemma family closure;
- accepted 12B blocks at 16k;
- accepted 12B or 26B complex JSON;
- physical KV reuse or cache benefit;
- usable Gemma image generation or L3.35 screening;
- 32k context admission;
- raw prompt, raw response, raw image, private endpoint, RAM, or VRAM evidence;
- any new live execution performed by this audit.
