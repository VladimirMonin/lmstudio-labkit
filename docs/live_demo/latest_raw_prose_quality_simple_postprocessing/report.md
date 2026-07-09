# LabKit run matrix_l3_27_raw_prose_quality_simple_postprocessing_e2b_e4b

- cell_count: `60`
- raw_cartesian_cell_count: `2400`
- filtered_cell_count: `60`
- skipped_cell_count: `2340`
- result_count: `60`
- passed: `60`
- failed: `0`
- hard_fail_count: `0`
- warning_count: `120`
- length_ratio_warning_count: `0`
- live: `true`
- privacy_scan: `pass`


## Warning summary

- warning_categories: `punctuation_metrics=60`
- length_ratio_failures: `count=0; task_ids=none; model_ids=none; min_actual_ratio=None; max_actual_ratio=None; policy_min=[]; policy_max=[]`

## Model summary

- gemma4_e2b: attempts `30`, pass `30`, fail `0`, pass_rate `1.0`
- gemma4_e4b: attempts `30`, pass `30`, fail `0`, pass_rate `1.0`

## Required axis summaries

### Language

- ru_en_mixed: attempts `6`, pass `6`, fail `0`, pass_rate `1.0`
- ru_ru: attempts `54`, pass `54`, fail `0`, pass_rate `1.0`

### Complexity

- simple: attempts `60`, pass `60`, fail `0`, pass_rate `1.0`

### Schema variant

- hardened_const: attempts `60`, pass `60`, fail `0`, pass_rate `1.0`

### Retry

- off: attempts `60`, retry_attempted `0`, recovered `0`, pass `60`, fail `0`

### Cache mode

- none: attempts `60`, pass `60`, fail `0`, pass_rate `1.0`

## Skipped cells

- input_profile_mismatch: `1080`
- language_mismatch: `1200`
- output_language_policy_mismatch: `60`

## Safety budget

- allow_image_live: `False`
- allow_model_downloads: `False`
- allow_model_loads: `True`
- allow_raw_prompt_response_artifacts: `True`
- allow_remote_base_url: `True`
- allow_stress: `False`
- live: `True`
- max_context_tier: `8192`
- max_models: `2`
- max_repeats: `3`
- max_requests: `60`
- max_runtime_minutes: `180`

## Live-screening readiness

- status: `guarded-live-screening-artifacts`
- note: `live execution is host-managed and never runs from the default offline CLI path`
