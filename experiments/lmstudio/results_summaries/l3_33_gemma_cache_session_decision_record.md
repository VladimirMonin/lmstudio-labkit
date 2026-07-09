# L3.33 Gemma Cache/Session Decision Record

Status: prepared-only. No L3.33 live inference has been run.

## Prepared configs

- `matrix.l3_33a_gemma_cache_session_canary.yaml` — 48-row prepared cache/session/warmup canary for Gemma E4B and 12B at 8192.
- `matrix.l3_33b_gemma_prompt_prefix_reuse.yaml` — 12-row prepared prompt-prefix reuse comparator with stable instruction/schema prefix and varied synthetic dynamic inputs.

## Current admission status

| scope | status | reason |
|---|---|---|
| inherited source-application-derived strategy evidence | prepared import | Strategy-level import exists in `l3_33_gemma_cache_session_warmup_evidence_import.md`; it is not a Gemma KV proof. |
| `cache_mode=none` baseline | prepared_only | Baseline rows are present for comparator shape; no live timings exist in this slice. |
| `cache_mode=warmup_first` | prepared_only | Config includes repeated requests; live semantics must be session-loaded load-once/warmup/measured/cleanup-once. |
| `cache_mode=prompt_prefix_reuse` | prepared_only | Prefix-stability comparator is prepared with synthetic dynamic-input variation only. |
| `kv_reuse_proven` | not_claimed | Must remain `false` until runtime reports explicit cache/KV reuse signal. |
| `/v1/responses` cache accounting | research_only | Imported as research-only; not included in first Gemma cache/session configs. |
| L3.33 live acceptance | blocked | Requires explicit owner approval, sanitized telemetry, privacy pass, and cleanup final-zero proof. |

## Required live report fields

The prepared artifact/report contract reserves these telemetry fields:

- execution mode and cache mode;
- cache/session group ids;
- session id and request index;
- warmup request marker;
- stable prefix, schema, prompt-template, dynamic-input, and same-input hashes;
- TTFT, prompt-processing, total latency, and tokens/sec;
- reported vs inferred cache hit fields;
- KV reuse proof flag;
- cleanup final-zero proof and privacy scan status.

## Admission guardrails

- L3.33 must not mix with parallelism, stress, image, Qwen, or higher-context exploration.
- `warmup_first` live execution is valid only when `execution_mode=session_loaded` uses one load for the full repeat group and one cleanup after measured requests.
- Timing-only cache improvement can be recorded as inferred evidence, not as physical KV proof.
- Raw prompt/response artifacts remain forbidden.
- Any live run must stop if final loaded-like count cannot be proven zero.

## Non-live verification recorded

Recorded on 2026-07-10 UTC, non-live only:

```text
uv run pytest -q tests/lmstudio_labkit/test_artifact_csv_contract.py tests/lmstudio_labkit/test_cache_warmup_telemetry.py tests/lmstudio_labkit/test_l3_31_l3_32_gemma_closure_configs.py
16 passed
uv run pytest -q tests/lmstudio_labkit
300 passed
uv run pytest -q tests/libs tests/tools tests/architecture tests/lmstudio_labkit
1227 passed
uv run ruff check .
All checks passed.
uv run ruff format --check lmstudio_labkit/artifacts.py tests/lmstudio_labkit/test_artifact_csv_contract.py tests/lmstudio_labkit/test_l3_31_l3_32_gemma_closure_configs.py
3 files already formatted
python scripts/audit_publication_safety.py
Publication safety audit passed.
git diff --check
passed
```

Full-repo `uv run ruff format --check .` was attempted and found an unrelated
pre-existing/sibling untracked L3.34 test file that would be reformatted. The
L3.33 touched Python files passed targeted format check.

This prepared-only record intentionally claims no live LM Studio calls, model loads, downloads, remote inference, stress runs, raw prompt artifacts, or raw response artifacts.
