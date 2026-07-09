# L3.28d.1 Structured JSON Repair Report

- cell_count: `16`
- passed: `16`
- failed: `0`
- hard_fail_count: `0`
- live: `true`
- privacy_scan: `pass`

## Model summary

- google/gemma-4-e2b: 4/4 pass
- google/gemma-4-e4b: 4/4 pass
- google/gemma-4-12b-qat: 8/8 pass

## Key finding

The L3.28 structured JSON failure was caused by under-specified prompt/validator design rather than a demonstrated model inability. Exact-shape prompts plus schema-specific language paths repaired the canary.
