# LM Studio Lab Managed Runner Live Report

## Run

- experiment_id: `l3_10f_gemma4_12b_qat_business_retry`
- run_id: `l3-10f-gemma4-12b-qat-business-retry-20260707`
- mode: `managed_runner_medium_chunked_sequential_live`
- L3.9 Blocks JSON sequential managed-live proof through ManagedLabRunner: `true`
- true live/GPU/LM Studio used: `true`
- not true_parallel proof: `true`
- not production default: `true`
- not host application runtime integration: `true`
- exact unload cleanup required/verified: `true`
- raw_prompt_response_stored: `false`

## Scope

- dataset_id: `blocks_json_medium_chunked`
- dataset_hash: `sha256:blocks-json-medium-chunked-v1`
- structured_prompt_variant: `baseline`
- structured_schema_variant: `baseline`
- business_failure_retry_limit: `1`
- model_key: `gemma4_12b_qat`
- model_id: `google/gemma-4-12b-qat`
- app_concurrency: `1`
- queue_pressure_mode: `false`
- parallel_semantics: `sequential`

## Lifecycle

- load_verified: `True`
- applied_context_length: `8192`
- applied_parallel: `1`
- parallel_verified: `True`
- cleanup_status: `cleanup_verified`
- cleanup_verified_count: `1`
- final_loaded_instances: `0`

## Validation

- json_parse_pass_count: `4`
- schema_pass_count: `4`
- business_pass_count: `4`
- retry_attempt_count: `1`
- retry_recovered_count: `1`
- retry_failed_count: `0`
- ids_exact_pass_count: `4`
- all_ids_covered: `True`
- finish_length_count: `0`
- reasoning_leak_count: `0`
- structured_error_count: `0`

## Notes

- Sequential managed-live proof validates one allowed L3.9 Blocks JSON candidate config at a time.
- Native load/unload uses exact owned instance cleanup only; wildcard unload is forbidden.
- This artifact set is a Lab-only managed-live proof and does not claim host application runtime integration.
- privacy_scan_status: `pass`

## Output Files

- `environment.json`
- `experiment.yaml`
- `run_config.json`
- `metrics.jsonl`
- `structured_errors.jsonl`
- `batch_summary.json`
- `structured_validation_summary.json`
- `structured_validation_summary.csv`
- `privacy_scan.json`
- `report.md`
- `system_samples.jsonl`
- `system_summary.json`
