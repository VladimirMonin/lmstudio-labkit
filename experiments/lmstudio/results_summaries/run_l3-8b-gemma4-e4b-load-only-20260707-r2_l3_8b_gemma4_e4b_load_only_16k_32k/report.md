# LM Studio Lab L3.8b Gemma4 E4B Load-Only 16k/32k Report

| Field | Value |
| --- | --- |
| experiment_id | `l3_8b_gemma4_e4b_load_only_16k_32k` |
| endpoint_family | `model_lifecycle` |
| model_key | `gemma4_e4b_q4km` |
| model_id | `google/gemma-4-e4b` |
| load_context_tiers | `16384, 32768` |
| requested_parallel | `1` |
| app_concurrency | `1` |
| generation_allowed | `false` |
| production_default | `false` |
| wvm_runtime_integration | `false` |
| kv_reuse_proven | `false` |
| final_loaded_instances | `0` |
| decision | `load_only_passed` |

## Per-tier attempts

| Tier | Requested context | Applied context | Applied parallel | Model-list ctx metadata | Model-list parallel metadata | Model-list applied metadata verified | Cleanup verified | Decision | Failure reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `1` | `16384` | `16384` | `1` | `false` | `false` | `unknown` | `true` | `load_only_passed` | `None` |
| `2` | `32768` | `32768` | `1` | `false` | `false` | `unknown` | `true` | `load_only_passed` | `None` |

## Notes

- This gate is load-only: no inference, no native chat, no responses, and no chat-completions endpoints are allowed.
- Acceptance requires both 16k and 32k tiers to materialize exactly one owned instance in the post-load model list, match the requested context_length and parallel in the native load response, and clean up back to zero target loaded instances.
- Model-list context_length/parallel arrays are optional telemetry only; when present they are reported, but they do not gate acceptance.
- Passing L3.8b does not prove production default, WVM runtime integration, KV reuse, user-facing recommendation, live quality, or structured JSON correctness.

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
