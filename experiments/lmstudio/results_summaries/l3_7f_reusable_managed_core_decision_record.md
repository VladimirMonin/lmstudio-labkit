# LM Studio Lab L3.7f Reusable Managed Core Decision Record

Status: accepted lab decision record, no new live inference in this step.

## Decision

L3.7 closes the reusable LM Studio managed-core foundation as a lab-only package of contracts, registries, gates, and internal policy drafts.

The current reusable core can represent:

- experiment identity and artifact schema;
- model registry and evidence refs;
- candidate intake and hardware-feasibility planning;
- structured JSON validation matrix and managed live gate evidence;
- internal recommendation draft.

The reusable core is **not** a host application runtime integration and is **not** a final user-facing recommendation engine.

Production guardrails remain unchanged:

- `production_default=false`
- `wvm_runtime_integration=false`
- `kv_reuse_proven=false`
- `final_user_facing_recommendation=false`

## Evidence summary

### L3.7a — core contracts and artifact schema

L3.7a added the stable lab contracts:

- experiment identity;
- safety flags;
- model, hardware, load and route profiles;
- artifact schema;
- result classifications;
- privacy validation policy;
- conservative recommendation draft defaults.

It proved that L3.5/L3.6 artifact bundles can be represented by the new contracts without promoting lab evidence into production defaults.

### L3.7b — model registry / profile layer

L3.7b added the initial model registry:

- `gemma4_e2b_q4km` — current primary lab candidate;
- `qwen35_4b` — strict structured-output blocked under current evidence;
- `qwen35_9b` — recovery/experimental only.

The `/v1/responses` policy is intentionally scoped:

- for `gemma4_e2b_q4km`, small-context responses remain `cache_accounting_candidate_small_context`;
- for `gemma4_e2b_q4km`, long-context responses are `blocked_by_current_evidence` because the current 16k probe failed with `internal_error`;
- for future/unlisted models and future LM Studio builds, long-context responses remain `unverified_for_this_model` and `needs_retest_on_new_model_or_build`.

This is **not** a global `/v1/responses` ban.

### L3.7c — candidate model intake + hardware feasibility

L3.7c added intake-only candidate records for the next wave:

- `gemma4_e4b_q4km` / `google/gemma-4-e4b`;
- `gemma4_12b_qat` / `google/gemma-4-12b-qat`;
- `gemma4_26b_a4b_qat` / `google/gemma-4-26b-a4b-qat`;
- `qwen3_6_35b_a3b` / `qwen/qwen3.6-35b-a3b`.

All remain `unverified_candidate` and must pass the staged matrix before any route-level recommendation:

1. no-live feasibility;
2. load-only 16k/32k;
3. tiny live smoke;
4. structured JSON smoke;
5. long-context route matrix after earlier gates pass.

`qwen/qwen3-vl-4b` is tracked only as `vision_deferred` and is not part of the text-core promotion path.

Hardware feasibility remains policy-only in L3.7c. No new host probing or production recommendation was added.

### L3.7d — structured JSON validation matrix and live gate

L3.7d added the structured JSON matrix and a managed live gate for current Gemma E2B.

Accepted live gate:

- run: `run_l3-7d-structured-json-live-smoke-20260707_l3_7d_structured_json_live_smoke_gemma4_e2b`;
- model: `gemma4_e2b_q4km` / `google/gemma-4-e2b`;
- applied `context_length=8192`;
- applied `parallel=1`;
- route: `strict_json_chat_completions` via `json_schema_single`;
- public assistant content: pass;
- reasoning-only JSON: false;
- JSON parse / schema / business validation: pass;
- cleanup verified: true;
- final loaded instances: `0`;
- privacy scan: pass with `0` violations.

L3.7d promotes only the **lab matrix state** for Gemma E2B strict JSON from pending to passed. It does not promote production defaults.

### L3.7e — internal recommendation draft

L3.7e added a deterministic internal recommendation draft over the L3.7 contracts.

Current internal draft:

- `gemma4_e2b_q4km` + `compact_memory` — internal primary candidate;
- `gemma4_e2b_q4km` + `strict_json_chat_completions` — internal primary candidate after L3.7d;
- `native_chat_stateful` — research accelerator;
- `stateless_full_prefix` — fallback/baseline;
- `/v1/responses` — small-context cache-accounting candidate and scoped long-context retest item;
- L3.7c candidates — unverified and gated;
- Qwen 4B — blocked for strict JSON under current evidence;
- Qwen 9B — recovery/experimental only.

No item is final user-facing.

## Architecture policy

The reusable managed core may be carried forward as an internal lab package.

It must not be wired into host application runtime, UI, QueueManager, Vision, or production defaults until separate production integration gates exist.

Required production-gate prerequisites remain open:

- stable model registry with exact-build evidence;
- repeatable hardware profile collection;
- load-only and live smoke gates for selected candidate models;
- structured JSON validation for selected candidate models;
- route matrix evidence for selected candidate models;
- explicit runtime integration design and tests.

## Recommended next series

Recommended next work is **L3.8 Candidate Execution Gates**:

1. L3.8a — no-live feasibility pack for candidate models.
2. L3.8b — load-only 16k/32k gates for the first selected candidate.
3. L3.8c — tiny live smoke for the first selected candidate.
4. L3.8d — structured JSON live smoke for the first selected candidate.
5. L3.8e — route matrix only after earlier gates pass.

Suggested first candidate order:

1. `gemma4_e4b_q4km` as a closer Gemma-family step.
2. `gemma4_12b_qat` if hardware/load-only gates are safe.
3. `gemma4_26b_a4b_qat` only after smaller Gemma candidates are understood.
4. `qwen3_6_35b_a3b` as a separate Qwen-family investigation.

`/v1/responses` long-context must be retested per exact model/build and must not inherit the Gemma E2B current-evidence block globally.
