# L3.27 Raw-Prose Quality Review Summary

This summary is sanitized. Raw source/output prose stayed local-only under the platform temp dir outside the repository and is not committed.

## Run facts

- attempts: 60
- pass_count: 60
- fail_count: 0
- raw_case_count: 60 local-only
- final_loaded_instances: 0 for all cells
- near_identity_warning_count: 0

## Model quality summary

| model | overall avg | meaning min | no-new-facts min | term avg | naturalness avg | critical issues |
|---|---:|---:|---:|---:|---:|---:|
| gemma4_e2b | 1.2 | 0 | 0 | 1.4 | 1.4 | 3 |
| gemma4_e4b | 1.7 | 1 | 2 | 1.9 | 1.8 | 0 |

## Findings

- E4B is the better quality default for hidden/dev prototype: higher overall acceptability and stronger term preservation.
- E2B is fast but not reliable enough as a quality default: it translated one mixed RU/EN technical case and lost E4B/E2B model-name distinctions in one product-name case.
- E4B is not perfect: one technical case changed Qwen to Kwen, and both models kept self-correction noise in the repeats/self-corrections case.
- Near-identity/no-op was not the main failure mode in this run; quality failures were term preservation and cleanup judgment.

## Decision

Proceed to L3.27 host-app hidden/dev prototype with E4B as guarded quality default and E2B as lightweight fallback only. Do not claim user-facing/default release quality yet; add term-preservation regression prompts before broader 12B family work.
