# LM Studio Lab L3.9d Gemma4 26B A4B QAT Load-Only 8k Report

| Field | Value |
| --- | --- |
| experiment_id | `l3_9d_gemma4_26b_a4b_qat_load_only_8k` |
| endpoint_family | `model_lifecycle` |
| model_key | `gemma4_26b_a4b_qat` |
| model_id | `google/gemma-4-26b-a4b-qat` |
| load_context_tiers | `8192` |
| requested_parallel | `1` |
| app_concurrency | `1` |
| allow_remote | `false` |
| generation_allowed | `false` |
| production_default | `false` |
| wvm_runtime_integration | `false` |
| kv_reuse_proven | `false` |
| final_loaded_instances | `0` |
| decision | `load_only_passed` |

## Per-tier attempts

| Tier | Requested context | Applied context | Applied parallel | Model-list ctx metadata | Model-list parallel metadata | Model-list applied metadata verified | Cleanup verified | Decision | Failure reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1` | `8192` | `8192` | `1` | `false` | `false` | `unknown` | `true` | `load_only_passed` | `None` |

## Notes

- This gate is load-only: no inference, no native chat, no responses, and no chat-completions endpoints are allowed.
- Acceptance requires every configured tier to materialize exactly one WVM-owned instance in the post-load model list, match the requested context_length and parallel in the native load response, and clean up back to zero target loaded instances.
- Model-list context_length/parallel arrays are optional telemetry only; when present they are reported, but they do not gate acceptance.
- This report remains lab-only: not production default, not WVM runtime integration, no live generation, and no user-facing recommendation proof.
- Cleanup must be explicitly verified after the final unload and the final target loaded instance count must remain 0.

## Output Files

- `environment.json`
- `run_config.json`
- `load_attempts.jsonl`
- `load_response_sanitized.jsonl`
- `models_summary.jsonl`
- `system_samples.jsonl`
- `system_summary.json`
- `privacy_scan.json`
- `report.md`
