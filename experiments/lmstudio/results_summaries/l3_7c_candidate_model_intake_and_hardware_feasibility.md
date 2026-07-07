# LM Studio Lab L3.7c Candidate Model Intake and Hardware Feasibility

Status: no-live planning and registry slice only.

## Scope

- Add intake-only candidate records for the next text-core screening wave.
- Keep every candidate unverified and not promoted.
- Capture hardware feasibility as policy metadata only.
- Do not run generation, model loading, localhost calls, or endpoint probes in this slice.

## Candidate status vocabulary

- `unverified_candidate`
- `unverified_for_this_model`
- `no_live_feasibility_pending`
- `load_only_pending`
- `live_smoke_pending`
- `structured_json_pending`
- `route_matrix_pending`
- `not_approved_current_evidence`
- `blocked_by_current_evidence`
- `needs_retest_on_new_model_or_build`
- `vision_deferred`

## Candidate intake registry

| Model key | Model id | Family | Size class | Profile type | Expected backend | Current status |
| --- | --- | --- | --- | --- | --- | --- |
| `gemma4_e4b_q4km` | `google/gemma-4-e4b` | `gemma4` | `medium` | `q4_k_m` | `lmstudio` | `unverified_candidate` |
| `gemma4_12b_qat` | `google/gemma-4-12b-qat` | `gemma4` | `large` | `qat` | `lmstudio` | `unverified_candidate` |
| `gemma4_26b_a4b_qat` | `google/gemma-4-26b-a4b-qat` | `gemma4` | `large` | `a4b_qat` | `lmstudio` | `unverified_candidate` |
| `qwen3_6_35b_a3b` | `qwen/qwen3.6-35b-a3b` | `qwen36` | `large` | `a3b` | `lmstudio` | `unverified_candidate` |

Route planning for every intake candidate stays conservative:

- `compact_memory` -> `no_live_feasibility_pending`
- `native_chat_stateful` -> `no_live_feasibility_pending`
- `stateless_full_prefix` -> `no_live_feasibility_pending`
- `openai_responses` -> `unverified_for_this_model`
- `strict_json_chat_completions` -> `structured_json_pending`

## Context test plan

Each candidate carries the same first-pass context plan:

| Context tier | Requirement | Planned status | Notes |
| --- | --- | --- | --- |
| `16k` | required | `load_only_pending` | Must pass before any live smoke. |
| `32k` | required | `load_only_pending` | Must pass before route comparison work. |
| `48k` | optional | `load_only_pending` | Only after 16k and 32k stay stable. |
| `64k` | optional | `load_only_pending` | Stretch tier after smaller contexts succeed. |

## Hardware feasibility policy

This slice stores planning metadata only; it does not perform runtime probing.

| Field | Value |
| --- | --- |
| OS | `windows` |
| CPU | `not_probed_in_l3_7c` |
| RAM | `not_probed_in_l3_7c` |
| GPU | `cuda_lab_gpu_present_not_reprofiled_in_l3_7c` |
| VRAM | `not_probed_in_l3_7c_use_existing_privacy_safe_summaries` |
| CUDA notes | Current planning assumes a CUDA-backed LM Studio host, but no new hardware probe happens here. |
| MLX notes | Deferred in this text-core intake slice. |
| Allowed context tiers by policy | `16k`, `32k`, `48k`, `64k` |
| Load-only required before live | `true` |

Interpretation:

- existing privacy-safe summaries may inform later feasibility review;
- no new host facts are collected here;
- no candidate is approved for production defaults, runtime integration, or final user-facing recommendation.

## Evidence scoping rule for the responses route

- The current long-context block is scoped only to the exact `gemma4_e2b_q4km` evidence build from L3.7b.
- That exact block stays `blocked_by_current_evidence` for that specific model/build scope only.
- That exact block does not automatically transfer to new candidate models.
- Future or unlisted candidates remain `unverified_for_this_model`, not `blocked_by_current_evidence`.
- Re-screening on a new model or a new LM Studio build remains `needs_retest_on_new_model_or_build`.

## Deferred non-text-core note

- `qwen/qwen3-vl-4b` is tracked as `vision_deferred` and is intentionally excluded from the text-core intake path.

## Per-candidate matrix gates

Each candidate follows the same staged order:

1. A — `no_live_feasibility_pending`
2. B — `load_only_pending` for `16k` and `32k`
3. C — `live_smoke_pending`
4. D — `structured_json_pending`
5. E — `route_matrix_pending` only after A-D pass

## Production block remains intact

- `production_default=false`
- `wvm_runtime_integration=false` by omission from the intake contract
- `final_user_facing_recommendation=false`

This report is a planning artifact only.
