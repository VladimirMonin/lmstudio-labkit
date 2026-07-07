# LM Studio Lab L3.7d Structured JSON Validation Matrix

Status: live-updated matrix with one successful controlled managed Gemma E2B live-smoke artifact.

## Route policy

- Strict JSON pass requires non-empty public assistant `content`.
- JSON visible only in `reasoning_content` is a failure, not a pass.
- Qwen 4B remains blocked for strict structured output under current evidence.
- Qwen 9B remains recovery/experimental only unless exact-build evidence proves otherwise.
- Gemma E2B now has a passing controlled live smoke, but it remains lab-only and is not a production promotion.

## Successful live artifact

- Artifact directory: `experiments/lmstudio/results_summaries/run_l3-7d-structured-json-live-smoke-20260707_l3_7d_structured_json_live_smoke_gemma4_e2b/`
- Acceptance evidence: `applied_context_length=8192`, `applied_parallel=1`, `request_succeeded=true`, `public_content_pass=true`, `reasoning_content_present=false`.
- Structured output gate: `json_parse_pass=true`, `schema_pass=true`, `business_pass=true`, `structured_gate_status=passed`.
- Cleanup/privacy evidence: `cleanup_verified=true`, `final_loaded_instances=0`, `privacy_scan.status=pass`, `privacy_scan.violation_count=0`.
- Guardrails stay false: `production_default=false`, `wvm_runtime_integration=false`, `kv_reuse_proven=false`.

## Matrix

| Model key | Model id | Status | Live in L3.7d | Notes |
| --- | --- | --- | --- | --- |
| `gemma4_e2b_q4km` | `google/gemma-4-e2b` | `passed` | `true` | Controlled L3.7d strict JSON chat-completions live smoke passed in artifact `experiments/lmstudio/results_summaries/run_l3-7d-structured-json-live-smoke-20260707_l3_7d_structured_json_live_smoke_gemma4_e2b/`; keep lab-only with no production promotion. |
| `qwen35_4b` | `qwen3.5-4b` | `blocked_current_evidence` | `false` | Blocked under current evidence: public assistant content stayed empty while JSON was observed only in reasoning fields. |
| `qwen35_9b` | `qwen/qwen3.5-9b` | `passed` | `false` | Recovery/experimental only. Keep blocked from promotion until exact-build evidence closes the remaining gaps. |
| `gemma4_e4b_q4km` | `google/gemma-4-e4b` | `not_started` | `false` | Pending no-live and load-only replay first; excluded from L3.7d live work unless a separate slice explicitly authorizes it. |
| `gemma4_12b_qat` | `google/gemma-4-12b-qat` | `unverified_candidate` | `false` | Future intake candidate only; no structured JSON live work in L3.7d. |
| `gemma4_26b_a4b_qat` | `google/gemma-4-26b-a4b-qat` | `unverified_candidate` | `false` | Future intake candidate only; no structured JSON live work in L3.7d. |
| `qwen3_6_35b_a3b` | `qwen/qwen3.6-35b-a3b` | `unverified_candidate` | `false` | Future intake candidate only; no structured JSON live work in L3.7d. |

## L3.7d live gate scope

- Allowed managed live gate: `gemma4_e2b_q4km` only.
- Route classification: `strict_json_chat_completions`.
- Helper mode may stay `json_schema_single`, but artifacts and acceptance classify the run as strict JSON chat completions.
- Owned native load/unload, cleanup verification, privacy-safe artifacts, and `production_default=false` remain mandatory.
