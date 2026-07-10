# L3.30-L3.36 Final Evidence Audit — 2026-07-10

Status: `partial_not_green`. This is a publication-safe aggregate audit of current code, configs, sanitized reports, Git history, remote synchronization, verification gates, and selected Kanban evidence. It does not run live inference, load or download models, send image requests, or modify an external runtime.

Timestamp: 2026-07-10T18:35:36+05:00

## Audit verdict

The Gemma closure series has a valid accepted core, but it is not family-wide green:

- accepted default scope: E2B, E4B, and 12B at context 8192 for transcript cleanup, structured simple, and structured blocks;
- accepted narrow extensions: E2B/E4B L3.31a 16k canary, E2B/E4B L3.32a complex JSON canary, E4B L3.33a session-loaded quality canary, and one-asset E4B native image plain text;
- partial or blocked: 12B blocks at 16k, 12B complex JSON, 12B cache/session, and structured/broad Gemma vision admission;
- not run: 26B structured/cache/vision expansion, L3.35 image screening, and 32k admission;
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
| L3.30 vision preparation | `prepared_only` | accepted as preparation, not model admission | Public-safe assets, schemas, validators, and capability-gated configs are committed. No L3.30 live image inference was run. The historical text-only registry posture was later superseded by runtime metadata, but no structured or broad image output was admitted. |
| L3.31 context | `partial` | E2B and E4B accepted for the 9-cell 16k canary scope; 12B transcript cleanup and structured simple accepted; 12B structured blocks blocked | The original aggregate was 8/9 with cleanup zero. The single durable 12B blocks repair also failed at explicit `max_tokens=1024`, `finish_reason=length`, `completion_tokens=1024`; no retry or widening followed. |
| L3.32 complex JSON | `accepted_narrow` plus blocked 12B | E2B/E4B complex at 8192 accepted; 12B bounded case blocked; 26B not admitted | E2B/E4B aggregate: 4/4 pass. The single 12B case used bounded adaptive stages `512 -> 1024` and failed at the truncation ceiling. L3.32c broad screening and L3.32d 26B were not run. |
| L3.33 cache/session | `partial` | E4B accepted narrowly for `session_loaded` with `none` and `warmup_first`; 12B blocked/research-only | L3.33a was 22/24 with two 12B hard failures. A focused repeated-16k 12B comparison then produced 6/6 invalid length-limited outputs; 62.08x exact-repeat and 1.58x stable-prefix timing improvements are research signals only because runtime `cached_tokens` was unavailable. Cleanup ended at zero. |
| L3.34 image route | `partial_route_only` | Native E4B plain text proven; structured image output not admitted | Compat PNG data URI probes failed structured output for all four models. Native E4B `/api/v1/chat` returned 506 non-empty characters for one asset, then minimal JSON failed malformed without truncation; adaptive escalation correctly stopped. |
| L3.35 image screening | `blocked` / `not_run` | no model admitted; zero screening attempts | Stop condition was correctly applied after the required native minimal-JSON gate failed. Plain-text route success alone did not authorize screening. |
| L3.36 synthesis | `partial_not_green` | accepted as a truthful partial synthesis, not as family closure | The canonical synthesis and model cards correctly retain blocked/not-run modes and do not claim KV reuse, cache benefit, structured/broad image support, or broad 26B admission. |

## Per-model admission

| model | accepted | partial / blocked | not run / prepared only | current role |
|---|---|---|---|---|
| `google/gemma-4-e2b` | 8192 transcript/simple/blocks; L3.31a 16k transcript/simple/blocks; L3.32a complex JSON | vision not admitted | L3.33 cache/session; 32k; broad image matrix | lightweight baseline |
| `google/gemma-4-e4b` | 8192 transcript/simple/blocks; L3.31a 16k transcript/simple/blocks; L3.32a complex JSON; narrow L3.33a session-loaded quality scope; native one-asset image plain text | native minimal JSON and broader vision blocked; KV reuse and cache benefit unproven | 32k; L3.35 image matrix | strongest current general candidate |
| `google/gemma-4-12b-qat` | 8192 transcript/simple/blocks; L3.31a 16k transcript and structured simple | durable 16k blocks repair, bounded 8192 complex, and repeated-16k cache/session outputs failed | vision, 32k | high-quality candidate requiring output-validity repair evidence |
| `google/gemma-4-26b-a4b-qat` | controlled 8192 transcript cleanup only | no broad family admission | structured simple/blocks/complex, cache/session, vision, 16k/32k expansion | research/capacity constrained |

## Actual code and config audit

Verified from the current checkout:

- `lmstudio_labkit/requests.py` defines `ExecutionOptions.max_tokens` and includes it in safe metadata.
- `lmstudio_labkit/benchmarks.py` parses the `max_tokens` axis into request plans and parses `request_timeout_s` into `timeout_s`.
- The matrix runner rejects live `warmup_first` unless `execution_mode=session_loaded`.
- L3.33a is now valid by construction: `session_loaded`, cache modes `none` and `warmup_first`, repeats 3, 24 planned rows, timeout 600 seconds, parallel 1.
- `ManagedHostRunner.chat_completion`, `ManagedLMStudioExecutor`, and `LocalLMStudioHostRunner` now preserve explicit `plan.options.max_tokens`; omission remains backward compatible for legacy runner signatures.
- `lmstudio_labkit/output_budget.py` adds a bounded contract-derived adaptive policy that escalates only for observed truncation or incomplete structure and stops on malformed, schema-invalid, quality-invalid, or valid complete output. Explicit caller caps override the policy unchanged.
- The managed executor preserves runtime-reported `cached_tokens` through `RequestResult.token_counts`, JSONL rows, and CSV summaries. A positive reported value plus a valid response can mark `kv_reuse_proven`; missing accounting remains unknown and cannot prove reuse.
- `lmstudio_labkit/managed_executor.py` still supports text-only OpenAI-compatible structured JSON. It explicitly rejects image requests and native endpoints; the native vision evidence remains a guarded direct-route result outside this executor.
- The committed L3.34 config remains non-live and yields unsupported-modality skips because committed model specs are text-only. The historical direct live image probes therefore remain outside the managed matrix executor.

The earlier managed max-token forwarding gap is resolved for the current diff.
Adaptive policy injection is an executor capability, not a claim that every CLI
profile automatically enables it. Native image execution remains outside the
managed matrix path.

## Live aggregate evidence audit

The current sanitized aggregate reports support these exact counts:

| evidence | attempts | pass | fail | privacy | cleanup |
|---|---:|---:|---:|---|---|
| L3.29 accepted 8192 executable slice | 113 | 113 | 0 | pass | final loaded-like count 0 |
| L3.31a 16k context | 9 | 8 | 1 | pass | final loaded count 0 |
| L3.32a E2B/E4B complex JSON | 4 | 4 | 0 | pass | final loaded count 0 |
| L3.33a second cache/session attempt | 24 | 22 | 2 | pass | final loaded count 0 |
| L3.34 compat image route probe | 4 | 0 accepted schema results | 4 | sanitized summary | each final loaded count 0 |
| L3.34.1 E4B plain-text image repair | 1 | 0 | 1 | sanitized summary | final loaded count 0 |
| bounded 12B blocks@16k repair | 1 | 0 | 1 | pass | final loaded count 0 |
| bounded 12B complex@8192 adaptive case | 2 output-budget attempts for 1 cell | 0 | 1 terminal failure | pass | final loaded count 0 |
| focused 12B repeated-16k cache comparison | 6 | 0 valid | 6 | raw local records ignored; aggregate summary only | final loaded count 0 |
| native E4B image gate | 2 gates attempted | 1 plain-text route pass | 1 minimal-JSON fail | sanitized summary | final global loaded count 0 |
| L3.35 image screening | 0 | 0 | 0 | not applicable | not run |

The ignored raw live-run directories are not treated as publication artifacts. The audit relies on tracked sanitized aggregates and their hashes/counts, not raw prompts, raw responses, or image bytes.

## Pre-final-closure Git baseline

The L3.30-L3.36 closure lineage is present in `main`, including:

- `23fd599` — prepare L3.30 Gemma vision matrix;
- `5159c87` — prepare L3.31 and L3.32 gates;
- `ba9a73c` — prepare L3.33 and L3.34 gates;
- `d41d222` — record launch blockers;
- `612d6f6` — record L3.31-L3.36 live rerun;
- `12f29dc` — add repair forensics and admission matrix;
- `a3808f5` — add explicit max-token plan/artifact support;
- `b1dff02` — record source-application cache and route evidence;
- `caa2d34` — update final Gemma admission synthesis;
- `903a816` — commit the first independent final evidence audit.

Remote verification before the final closure commit, after `git fetch` and
`git ls-remote`:

```text
local HEAD:  903a8161aff59e6ce21288e3ef73aad7758a29df
origin/main: 903a8161aff59e6ce21288e3ef73aad7758a29df
remote main: 903a8161aff59e6ce21288e3ef73aad7758a29df
ahead/behind: 0/0
```

The final closure slice consists of the reviewed implementation, tests,
sanitized evidence reports, and documentation reconciliation described in this
audit. `.hermes/`, raw live runs, caches, and build artifacts remain unrelated
local/runtime state and are excluded from the closure commit.

## Verification run for this audit

All non-live gates passed on the complete current diff after reconciliation:

```text
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
1260 passed in 10.46s on the final post-write run

focused implementation review suite
63 passed in 0.33s

uv run ruff check .
All checks passed.

uv run ruff format --check .
204 files already formatted

python scripts/audit_publication_safety.py
Publication safety audit passed.

git diff --check
passed

read-only final runtime check
/api/v1/models: 49 models, 0 loaded-like
/v1/models: 46 models, 0 loaded-like
```

The `uv` commands emitted only the expected warning that the active Hermes virtual environment differs from the project `.venv`; `uv` ignored it and used the project environment.

## Stale and conflicting reports

Historical phase records were reconciled in this review. Earlier preparation and
runtime-unavailable sections remain as chronology, while explicit closure-update
sections now state the current evidence:

| file | classification | conflict | audit handling |
|---|---|---|---|
| `l3_31_l3_36_live_launch_status_report.md` | `stale_historical` | Records runtime unavailable and zero live attempts before the later rerun. | Retain as launch-history evidence; never use as current admission state. |
| `l3_31_gemma_context_screening_decision_record.md` | `reconciled_historical` | Earlier sections record preparation/runtime-unavailable states. | Closure update records 8/9 L3.31a and the failed durable 12B 1024-token repair. |
| `l3_32_gemma_json_complexity_decision_record.md` | `reconciled_historical` | Earlier sections record prepared-only and blocked-launch states. | Closure update records E2B/E4B 4/4 and the blocked bounded 12B case. |
| `l3_33_gemma_cache_session_decision_record.md` | `reconciled_historical` | Earlier sections describe the original prepared 48-row shape. | Closure update records the valid 24-row L3.33a and focused 12B repeated-context residual gap. |
| `l3_34_gemma_vision_route_capability_decision_record.md` | `reconciled_historical` | Earlier sections preserve committed text-only preparation posture. | Closure update records runtime vision metadata, compat failures, native plain-text success, and minimal-JSON failure. |
| `l3_34_1_vision_probe_repair_decision_record.md` | `reconciled_historical` | Compat-envelope plain text was empty. | Superseding note prevents generalizing that result to the later successful native plain-text route. |
| `l3_35_gemma_vision_screening_decision_record.md` | `reconciled_current` | Initial capability blocker was superseded. | Current header and decision now block L3.35 after native minimal JSON failed; screening remains zero attempts. |
| `l3_31_l3_36_structured_output_code_evidence_report.md` | `stale_code_snapshot` | Predates managed max-token forwarding and adaptive output-budget support. | Retained as historical code evidence; this audit's current-code section overrides it. |
| `l3_30_gemma_vision_matrix_preparation_report.md` | `accepted_prepared_only` with superseded metadata note | Preparation is valid, but its committed text-only capability posture was superseded by runtime metadata. | Keep as L3.30 preparation evidence only. |

The admission matrix, final synthesis, and model cards were updated in this
review. They retain `partial_not_green`, add the failed bounded 12B evidence,
admit only native E4B image plain text, and keep structured/broad vision blocked.

## Kanban evidence audit

Verified closure-lane evidence includes:

- bounded 12B blocks@16k and complex@8192 evidence with explicit caps, sanitized summary, and cleanup zero;
- managed max-token/adaptive-budget implementation with focused non-live tests;
- focused 12B exact-repeat/stable-prefix cache comparison with timing-only conclusions and cleanup zero;
- native E4B sequential vision gate with plain-text pass, minimal-JSON fail, enforced stop condition, and cleanup zero.

Kanban completion state is evidence of workflow/review, not a substitute for code, tracked reports, Git history, or test output. This audit resolves conflicts in favor of current code and sanitized aggregate evidence.

## Residual gaps after bounded closure

This review closes the evidence wave truthfully rather than creating another
automatic live expansion. Future work, if explicitly approved, must remain
one-variable and bounded:

1. 12B output validity for blocks@16k and complex@8192 after both 1024-token ceilings.
2. Runtime-reported cache accounting plus valid 12B output before any physical KV-reuse claim.
3. Native E4B minimal JSON repair before a four-to-eight-request L3.35 simple-description canary.

No residual gap justifies Qwen, broad 26B, 32k, full-cartesian, parallel/stress,
or complex image expansion.

## Final non-claims

This audit does not claim:

- full green Gemma family closure;
- accepted 12B blocks at 16k;
- accepted 12B or 26B complex JSON;
- physical KV reuse or cache benefit;
- structured/broad Gemma image admission or L3.35 screening;
- 32k context admission;
- raw prompt, raw response, raw image, private endpoint, RAM, or VRAM evidence;
- any new live execution performed by this audit.
