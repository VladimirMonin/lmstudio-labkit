# L3.32 Gemma JSON Complexity Decision Record

Status: historical preparation record, reconciled with the bounded live canaries below.

## Prepared configs

- `matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml` — 4-request E2B/E4B complex canary.
- `matrix.l3_32b_gemma_complex_json_canary_12b.yaml` — 4-request 12B complex canary, gated on L3.32a.
- `matrix.l3_32c_gemma_structured_json_complexity_screening.yaml` — broader prepared screening; theoretical cartesian 216, live cap 96.
- `matrix.l3_32d_gemma_26b_structured_json_tiny.yaml` — 2-request 26B simple-only tiny.

## Current admission status

- simple: accepted for E2B/E4B/12B at 8192 from L3.29.
- blocks: accepted for E2B/E4B/12B at 8192 from L3.29 hardened contract.
- complex: prepared, not admitted.
- 26B structured JSON: prepared tiny simple-only, not admitted.

## Offline coverage

- Complex nested JSON tasks now have non-live schema fixture coverage in
  `tests/lmstudio_labkit/test_l3_31_l3_32_gemma_closure_configs.py`.
- The coverage validates each prepared complex task's exact expected output against
  its response contract and proves nested schema failures are caught before any
  broad screening claim.
- L3.32 configs keep the LabKit matrix schema variant `hardened_const`; the legacy
  live-smoke alias `per_position_id_const` is not reintroduced into these configs.

## Prepared decision table

No live structured generation has been run for L3.32. The table below is a
publication-safe placeholder for the first approved live report; prepared-only
entries must not be read as model-quality claims.

| model family | simple | blocks | complex | L3.32 status |
|---|---|---|---|---|
| Gemma E2B | accepted from L3.29 | accepted from L3.29 | prepared canary only | complex blocked pending L3.32a live approval/result |
| Gemma E4B | accepted from L3.29 | accepted from L3.29 | prepared canary only | complex blocked pending L3.32a live approval/result |
| Gemma 12B QAT | accepted from L3.29 | accepted from L3.29 | prepared canary only | complex blocked pending green E2B/E4B canary |
| Gemma 26B A4B QAT | prepared tiny simple-only control | not prepared | not prepared | simple-only tiny control; blocks/complex blocked |

## Live report placeholders

These fields are intentionally present before live execution so that any later
report has a fixed sanitized shape:

| field | current prepared value | first live evidence source |
|---|---|---|
| schema failure taxonomy | none; no L3.32 live failures exist | sanitized `failure_summary.csv` / snapshot aggregates |
| language degradation | none; offline fixtures only validate expected outputs | sanitized language-path validation aggregates |
| retry impact | not measured; retry axes are prepared for 12B and screening only | per-cell retry/status aggregates |
| finish_length rate | not measured; expected target is 0 before admission | sanitized finish-reason aggregates |
| 26B structured status | simple-only tiny prepared control; no blocks/complex admission | 26B tiny sanitized run summary, if explicitly approved |
| complex admitted/blocked status | blocked/prepared-only | L3.32a then L3.32b canary decision evidence |

## Admission guardrails

- L3.32a must prove complex nested schema viability for E2B/E4B before any broad
  complex screening claim.
- L3.32b must remain gated on L3.32a; 12B complex is not an independent first
  probe.
- L3.32c is a prepared screening shape, not an admissible broad run, until the
  canaries produce sanitized green evidence.
- L3.32d keeps 26B to simple-only tiny structured JSON; blocks and complex 26B
  cells are not admitted in L3.32.
- `hardened_const` remains the only LabKit matrix schema variant in prepared
  L3.32 configs; the legacy `per_position_id_const` alias remains limited to
  historical live-smoke artifacts.

## Launch attempt status

Recorded on 2026-07-10, after owner approval to follow the staged live order:

```yaml
config: experiments/lmstudio/structured_matrix/configs/matrix.l3_32a_gemma_complex_json_canary_e2b_e4b.yaml
preflight_status: pass
planned_request_count: 4
live_attempt_count: 0
classification: blocked_after_l3_31a_not_accepted
model_failure: false
```

L3.32a did not run live because the accepted order requires L3.31a acceptance
or explicit deferral first, and L3.31a was blocked by runtime unavailability.
The runtime was also unavailable at `http://127.0.0.1:1234`, so no model output
was produced.

Do not run L3.32b, L3.32c, or 26B structured cells until L3.32a has accepted
live evidence or is explicitly reclassified.

## Closure evidence update — 2026-07-10

The blocked launch attempt above was later superseded by explicit owner approval
to continue the independent probes:

```yaml
l3_32a_e2b_e4b:
  attempts: 4
  pass: 4
  fail: 0
  status: accepted_narrow
  privacy: pass
  final_loaded_count: 0
l3_32b_12b_bounded_case:
  planned_cells: 1
  output_budget_attempts: 2
  output_budgets_used: [512, 1024]
  finish_reason: length
  completion_tokens: 1024
  status: fail
  stop_reason: observed_truncation_limit_reached
  final_loaded_count: 0
l3_32c_broad_screening: not_run
l3_32d_26b: not_run
```

Complex JSON is admitted only for the four-cell E2B/E4B canary scope. The
single 12B case is now executed and blocked by bounded truncation; it must no
longer be described as merely prepared or not run. No broad screening or 26B
structured expansion followed.
