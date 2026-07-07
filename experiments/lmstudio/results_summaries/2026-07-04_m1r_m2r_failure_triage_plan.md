# M1r/M2r Failure Triage Plan — LM Studio Lab

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: triage contract and offline tooling preparation
- Live experiment policy for this slice: no new live runs
- Goal: turn M1/M2 first-pass failures into explicit failure modes before any production profile conclusion

## Why this exists

M1/M2 first-pass screening produced useful facts, but those facts are not a final model ranking. Several failures may be request-profile failures rather than model capability failures:

```text
empty structured content
finish_reason=length
response_format=json_schema interaction
reasoning/content split
app_concurrency degradation
prompt/max_tokens policy mismatch
```

The next live triage run must capture enough safe envelope data to classify those failures without storing raw prompts, raw responses or provider bodies.

## Safe triage envelope

Every triage metric/error payload should expose only:

```text
content_empty
content_chars
content_hash
reasoning_content_present
finish_reason
output_tokens
prompt_tokens
total_tokens
json_parse_pass
schema_pass
business_pass
error_category
```

Raw values remain forbidden:

```text
no raw response text
no raw reasoning text
no raw prompts/messages
no transcripts
no provider bodies
no local paths
no token values or secrets
```

## Offline tooling added before live triage

The Lab metrics layer now persists two additional privacy-safe booleans:

```text
content_empty
reasoning_content_present
```

These are written to metrics and structured error payloads for both structured and plain/concurrency diagnostics. They are safe booleans only and are restored after privacy sanitization without preserving raw content.

## M1r structured triage targets

| Case | First-pass symptom | Triage question | Required safe signals |
| --- | --- | --- | --- |
| `qwen35_4b_q4km` small structured | `0/3`, empty content, token usage present | Did output route to reasoning/non-content field, or did `response_format=json_schema` produce empty content? | `content_empty`, `reasoning_content_present`, `finish_reason`, `output_tokens`, validation flags |
| `gemma4_e4b_q4km` app_concurrency=2 | sequential ok, concurrent `1/4` valid | Is this scheduler/concurrency degradation? | per-chunk validation flags, finish reason, content/hash chars, timing |
| `qwen35_9b_q4km` app_concurrency=2 | sequential ok, concurrent `2/4` valid | Is this scheduler/concurrency degradation or response-format instability? | per-chunk validation flags, finish reason, content/hash chars, timing |

Important correction: the first-pass app_concurrency=2 runs loaded models with `parallel=1`, so they measured queue pressure (`1 processing + 1 queued`) rather than true native `parallel=2`. The Lab tooling now rejects this mismatch unless queue-pressure mode is explicit. A later true-parallel gate requires loading the model with `parallel=2` and matching the run config metadata.

Current corrected true-parallel evidence:

```text
gemma4_e2b_q4km: true parallel=2 / app_concurrency=2 passed 4/4, effective_speedup≈1.34
```

## M1r acceptance

```text
each failure has a classified failure mode
no raw response/reasoning/prompt stored
triage states whether retry/prompt/response_format/scheduler changes are plausible
no production model rejection based on first-pass alone
```

## M2r plain text triage targets

| Case | First-pass symptom | Triage question |
| --- | --- | --- |
| `qwen35_4b_q4km` | `0/4`, finish_reason=length | Does constrained output length or higher max_tokens unblock useful plain artifacts? |
| `gemma4_e4b_q4km` | `3/4`, one length failure | Is only `lecture_notes` over-budget for the prompt policy? |
| `qwen35_9b_q4km` | `0/4`, finish_reason=length | Is the model verbose under current prompt/max_tokens policy? |

## M2r planned live knobs

Run only after this offline tooling/spec slice is committed:

```text
temperature = 0
app_concurrency = 1 first
app_concurrency = 2 only if baseline green
parallel = 1 for queue-pressure triage, or explicitly load parallel=2 for true-parallel triage
max_tokens = 512 and 768
output constraint = 120–160 words
tasks = summary_short, lecture_notes, mic_command_answer, freeform_rewrite
```

## M2r acceptance

```text
finish_reason=length is eliminated or confirmed
token-normalized and char-normalized timing are reported
plain artifact profile remains separate from structured JSON profile
no production default is selected before compact model matrix
```

## Next after triage

After M1r/M2r, create a compact model screening matrix with verdict classes instead of production judgments:

```text
baseline
structured_candidate
plain_candidate
needs_prompt_policy
needs_reasoning_off_or_response_routing
too_heavy_for_current_profile
not_candidate_yet
```

Only after that should S0 `lmstudio_managed` skeleton start.
