# Corrected LM Studio Model Screening Matrix

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: corrected LM Studio Lab synthesis after R0/R1/R2
- Purpose: compact candidate matrix for future `lmstudio_managed` contracts
- Non-goals: no WVM runtime integration, no QueueManager/UI/SQLite, no production default selection

## Measurement semantics

Only rows satisfying all of the following are treated as true-parallel evidence:

```text
applied_parallel = 2
parallel_verified = true at load/probe boundary
app_concurrency = 2
queue_pressure_mode = false
parallel_semantics = true_parallel
```

Old `app_concurrency=2` rows with loaded `parallel=1` are retained only as queue-pressure evidence. They are not used as throughput proof.

## Compact matrix

| Model | Identity | Structured seq | Structured true c=2 | Plain true c=2 | VRAM peak | Old queue-pressure rows | Verdict |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| `gemma4_e2b_q4km` | verified native + compat | ✅ M1.2 `4/4` | ✅ R1 `12/12`, speedup `1.2196x` | ✅ R1 `12/12`, token-normalized `1.5202x` | `8884 MB` structured / `8789 MB` plain | Old M1.3/M2 appconc2 rows superseded; not true-parallel evidence | lab baseline candidate |
| `gemma4_e4b_q4km` | verified native + compat | ✅ M1.2 `4/4` | ✅ R2 `4/4`, speedup `1.2962x` | ✅ R2 `4/4` with `max_tokens=768`, token-normalized `1.2708x` | `9814 MB` structured / `10205 MB` plain | Old M1.3 appconc2 row superseded queue-pressure | heavier lab candidate |
| `qwen35_4b_q4km` | verified native + compat | ❌ MV2.4b: baseline, anti-reasoning prompt and `chat_template_kwargs.enable_thinking=false` all left `content_empty=true`, `reasoning_content_present=true` | — blocked for this phase | ❌ sequential `max512` and `max768` both `0/4`, `finish_length=4` | not accepted for profile | Old structured appconc2 not applicable after routing failure | closed for this phase: `reasoning_routing_unresolved` |
| `qwen35_9b_q4km` | verified native + compat | ✅ M1.2 `4/4` sequential | ⚠️ full 4-chunk c=2 timed out; `medium_pair` timeout120 passed `2/2` | ❌ sequential `max512` and `max768` both `0/4`, `finish_length=4` | `12255 MB` corrected structured follow-up | Old M1.3 appconc2 row superseded queue-pressure | heavy / timeout-policy candidate, not default |

## Evidence references

| Evidence block | Accepted runs / notes |
| --- | --- |
| R0 measurement repair | `409f53c0`, `21240352`, `b03b1bf7` |
| R1 Gemma E2B structured | `r1_structured_load_gemma4_e2b_parallel2_001`, `r1_structured_gemma4_e2b_appconc2_repeat3_001`, cleanup `r1_cleanup_gemma4_e2b_parallel2_001` |
| R1 Gemma E2B plain | `r1_plain_norm_gemma4_e2b_appconc2_true_01..03` |
| R2 qwen35_4b structured | `r2_qwen35_4b_structured_small_seq_001` |
| R2 Gemma E4B structured | `r2_gemma4_e4b_load_parallel2_001`, `r2_gemma4_e4b_structured_appconc2_true_001`, cleanup `r2_gemma4_e4b_cleanup_001` |
| R2 qwen35_9b structured | `r2_qwen35_9b_structured_appconc2_true_001`; follow-up `r2_qwen35_9b_medium_pair_true_timeout120_001` |
| R2 Gemma E4B plain | `r2_m2r_plain_gemma4_e4b_seq_max768_001`, `r2_m2r_plain_gemma4_e4b_appconc2_max768_001` |
| R2 Qwen plain failures | `r2_m2r_plain_qwen35_4b_seq_max512_001`, `r2_m2r_plain_qwen35_4b_seq_max768_001`, `r2_m2r_plain_qwen35_9b_seq_max512_001`, `r2_m2r_plain_qwen35_9b_seq_max768_001` |
| MV2.4b Qwen4B recovery closure | `2026-07-05_mv2_4b_qwen35_4b_structured_small_baseline_summary.md`, `2026-07-05_mv2_4b_qwen35_4b_anti_reasoning_summary.md`, `2026-07-05_mv2_4b_qwen35_4b_reasoning_control_summary.md` |

## Current Lab profiles

These are Lab profiles, not production defaults.

```yaml
profiles:
  - profile_id: gemma4_e2b_structured_medium_true_parallel2
    model: gemma4_e2b_q4km
    purpose: factual_blocks
    response_format: json_schema
    dataset: blocks_json_medium_chunked
    load_parallel: 2
    app_concurrency: 2
    status: lab_baseline
    production_default: false

  - profile_id: gemma4_e2b_plain_text_true_parallel2
    model: gemma4_e2b_q4km
    purpose: plain_text_artifacts
    diagnostic_kind: plain_text_artifacts_normalized
    load_parallel: 2
    app_concurrency: 2
    status: lab_baseline
    production_default: false

  - profile_id: gemma4_e4b_structured_medium_true_parallel2
    model: gemma4_e4b_q4km
    purpose: factual_blocks
    response_format: json_schema
    dataset: blocks_json_medium_chunked
    load_parallel: 2
    app_concurrency: 2
    status: lab_candidate_heavier
    production_default: false

  - profile_id: gemma4_e4b_plain_text_true_parallel2_max768
    model: gemma4_e4b_q4km
    purpose: plain_text_artifacts
    diagnostic_kind: plain_text_artifacts_normalized
    max_tokens: 768
    load_parallel: 2
    app_concurrency: 2
    status: lab_candidate_heavier
    production_default: false
```

## Parking lot: Qwen recovery track

Do not keep the main backend foundation blocked on Qwen-specific recovery.

```text
Q1: qwen35_4b_q4km closed for this phase after baseline, prompt-level anti-reasoning and request-shape enable_thinking=false all reproduced reasoning_routing_unresolved
Q2: concise plain-text prompt policy for Qwen 4B/9B
Q3: qwen35_9b wider timeout + smaller chunk profile
Q4: qwen35_9b sequential-only long-context candidate
```

## MV2.4b Qwen 4B update (2026-07-05)

`qwen35_4b_q4km` is no longer an active structured-output candidate for this phase.

The controlled Qwen 4B recovery probes tested three small sequential structured routes:

1. baseline structured small;
2. anti-reasoning system prompt;
3. request-shape `chat_template_kwargs.enable_thinking=false`.

All three completed normally at the transport/lifecycle level but produced the same structured-output failure:

```text
finish_reason=stop
content_empty=true
reasoning_content_present=true
response_chars=0
json_parse_pass=false
schema_pass=false
business_pass=false
error_category=empty
```

Decision:

```yaml
qwen35_4b_q4km:
  structured_output_status: reasoning_routing_unresolved
  production_default: false
  medium: blocked_for_this_phase
  chunked: blocked_for_this_phase
  true_parallel: blocked_for_this_phase
```

Do not use `reasoning_content` as a production structured-output source. The `factual_blocks.v1` contract remains public `content` -> JSON parse -> schema validation -> business validation.

## S0 readiness

R3 is sufficient to start a small `lmstudio_managed` skeleton with DTOs, enums and pure policy only:

```text
model identity DTO
download result DTO
lifecycle state DTO
idempotent lifecycle policy
parallel semantics enum
structured validation result DTO
```

Do not move HTTP clients, live runners, benchmark CLI, WVM runtime code, PySide6, SQLite, QueueManager or UI in S0.
