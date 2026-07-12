# Gemma 4 Admission Matrix

Status: statistical closure after real-transcript repeats, native structured-output repeats, and P2/P4 runtime probes. 12B QAT is the primary bounded rehearsal candidate; no model has unconditional unattended-production admission.

Timestamp: 2026-07-12

## Statistical closure addendum

The later closure study adds 20 independent long/plain calls, 60 native
structured-output calls, true P2/P4 probes, and a focused GPU-placement check.
Its authoritative report is
[Gemma 4 Whisper, structured-output, and parallel statistics](2026-07-12_gemma4_whisper_structured_parallel_statistics.md).

The operational result supersedes the older recommendation to begin long cleanup
with E2B:

- 12B QAT is the primary long-cleanup and structured-block rehearsal candidate;
- P2 passed on all four models; the initial const-heavy positional P4 schema returned
  HTTP 400, while a generic blocks schema repaired P4 to 5/5 batches and 20/20
  requests per model with exact post-generation ID/order validation;
- E2B remains the strongest raw-JSON follower but did not perform adequate cleanup
  in five deterministic long/plain repeats;
- E4B remains blocked for unattended M05 cleanup by deterministic runaway;
- 26B did not demonstrate a stable quality or schema advantage over 12B;
- `--gpu max` did not improve the focused 12B P2 run or increase its reported load
  footprint.

The recommended bounded configuration is 12B QAT, reasoning disabled, plain or
compact JSON-block full context, explicit chunk boundaries, and an adequate output
budget. Concurrency is workload-qualified: the bounded 8k generic-schema lane passed
P2 and structural P4, while two concurrent approximately 23k full-prefix requests
were rejected 0/4 before generation in the tested 32k runtime. Use sequential P1 for
that full-prefix shape. Exact IDs, URLs, commands, placeholders, and critical digits
must be validated separately from semantic value.

The application-shaped closure added 15 attempts. E2B long schema-output failed
deterministically 2/2 through hidden reasoning and output-budget exhaustion; E4B
completed one narrow same-prompt schema-output cell. The 12B plain and block lanes
both completed all three positions after sequential capacity recovery. Plain semantic
review retained 13/13 exact protected numeric values; the block merge retained 24/24
IDs in exact order. These are reviewable-draft and mechanical-merge results, not
unattended production, persistence, or fallback admission. The authoritative bounded
interpretation is in
[Gemma 4 final practical recommendations](2026-07-12_gemma4_final_practical_recommendations.md).

## Authoritative 2026-07-12 result

The final benchmark used publication-safe views derived from real sanitized Whisper
assets. It retained the normalization and long-structure difficulty needed for the
experiment without publishing raw private transcripts, prompts, or model outputs.
The exact tested family was:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`

Gemma 4 31B variants were explicitly excluded.

### Historical matrix and superseded interpretation

The first real-asset run executed all 64 planned cells and all 80 planned calls:
M01 and M05 at 8,192, 16,384, and 28,672 context, L02-L at 16,384,
loaded-session comparisons, and P1/P2/P4 fan-out. It embedded the schema in the
prompt rather than binding native structured output. All 80 strict verdicts were
rejected, but `accepted=0` did **not** mean that the models produced no useful
structure. The run already showed exact-schema results on M01/M05 and structural
retention up to 428/428 units; its old all-or-nothing capability interpretation is
superseded. The 64-cell/80-call evidence itself remains historical and unchanged.

Timing from that run is diagnostic only. It does not prove physical KV-cache reuse,
and rejected quality rows cannot establish production parallelism or capacity.

### Corrected native structured-output matrix

The focused correction ran one measured Responses API call for each model across
M01, M05, and L02-L: 12 calls total. Every request used `/v1/responses`, native
`text.format.type=json_schema`, the exact bound schema, `strict=true`,
`reasoning.effort=none`, temperature 0, and a 28,672-token context. Every envelope
reported `reasoning_tokens=0`. Output budgets were 512 tokens for M01 and L02-L,
and 4,096 for M05.

Scoring kept these axes separate instead of collapsing them into one verdict:

1. raw JSON;
2. extracted JSON, including fenced JSON;
3. exact schema;
4. semantic fidelity to the bound target;
5. placeholder fidelity;
6. L02-L structural retention;
7. strict end-to-end acceptance.

| Model | Raw JSON | Extracted/fenced JSON | Exact schema | Semantic fidelity | Placeholder fidelity | L02-L retention | Strict accepted |
|---|---:|---:|---:|---:|---:|---:|---:|
| E2B | 2/3 | 3/3 | 3/3 | 0/2 | 0/2 | 318/428 | 0/3 |
| E4B | 0/3 | 2/3 | 2/3 | 0/2 | 0/2 | 43/428 | 0/3 |
| 12B QAT | 0/3 | 3/3 | 2/3 | 0/2 | 0/2 | 428/428 | 0/3 |
| 26B MoE | 0/3 | 3/3 | 1/3 | 0/2 | 0/2 | 427/428 | 0/3 |

E2B is the strongest raw-JSON and schema follower. 12B QAT is the strongest
long-structure candidate and retained every L02-L unit. 26B MoE missed one unit and
followed the exact schema inconsistently. None of the models met semantic and
placeholder fidelity, so none passed strict acceptance.

### E4B/M05 runaway boundary

E4B/M05 exhausted three exact no-reasoning budgets under the same prompt, native
strict schema, temperature, model, and context contract:

| Maximum output | Reported output | Reasoning tokens | Result |
|---:|---:|---:|---|
| 4,096 | 4,096 | 0 | malformed non-JSON |
| 8,192 | 8,192 | 0 | full 4,096-run prefix, then continued malformed output |
| 16,384 | 16,384 | 0 | full 4,096- and 8,192-run prefixes, then continued malformed output |

All three envelopes reported `finish_reason=stop`, so exact budget exhaustion is
part of the length classification. The final call had a measured 1,175-token SDK
formatted input and 2,048-token safety margin; input + output + margin required
19,607 of 28,672 tokens, leaving 9,065 tokens of context headroom. The repeated
full-prefix continuation, malformed output, failed schema, and zero reasoning prove
a runaway generation for this exact contract—not reasoning-token competition or
context choking.

### Operational decision

- Use E2B as the first candidate when raw JSON and exact-schema following matter,
  but repair semantic and placeholder fidelity before admission.
- Use 12B QAT only as a structural-retention research candidate; fenced transport
  and normalization fidelity still block admission.
- Do not select 26B MoE as a quality ceiling from this evidence; it is slower,
  schema-inconsistent, and one L02-L unit short.
- Keep E4B/M05 blocked until the runaway generation is repaired under this exact
  native schema contract.
- Do not infer production parallelism, cache benefit, physical KV reuse, or timing
  superiority from rejected rows.

All model slices and both E4B boundary follow-ups ended with cleanup read-back
`loaded_total=0`; preflight and final global read-backs were also zero.

### Canonical evidence

- [Historical 64-cell/80-call synthesis](2026-07-12_four_model_real_asset_benchmark_synthesis.md)
- [Historical machine report](2026-07-12_four_model_real_asset_benchmark_synthesis.json)
- [Corrected 12-call native structured-output report](2026-07-12_gemma4_native_structured_output_correction.md)
- [Corrected machine report](2026-07-12_gemma4_native_structured_output_correction.json)
- Evidence commits: [`16bede4`](https://github.com/VladimirMonin/lmstudio-labkit/commit/16bede4), [`75565dd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/75565dd), [`a5080dd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/a5080dd), and [`fcfbefd`](https://github.com/VladimirMonin/lmstudio-labkit/commit/fcfbefd).

## Earlier L3.31-L3.38 evidence (historical)

The sections below preserve the earlier route-specific canaries and diagnostics.
Where they conflict with the authoritative 2026-07-12 result above, the later
real-asset native structured-output correction controls the current interpretation.

Legend:

- `accepted` — passed in the stated narrow evidence scope.
- `blocked` — executed/probed and failed, or gated by prior failed phase.
- `not_run` — not executed in this series/scope.
- `partial` — some cells accepted, some blocked.
- `research_only` — architecture/evidence imported, not direct model acceptance.
- `unsupported_or_unusable` — route/API may exist, but current runtime shape is not usable for admission.

## Matrix

| model | 8192_transcript_cleanup | 8192_structured_simple | 8192_structured_blocks | 8192_complex | 16k_transcript_cleanup | 16k_structured_simple | 16k_structured_blocks | cache_session | vision_plain | vision_min_json | vision_simple_description | status | blocked_reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `google/gemma-4-e2b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | not_run | not_run | not_run | not_run | accepted_text_json_only | vision not run after the required E4B native minimal-JSON gate failed; cache not run for E2B |
| `google/gemma-4-e4b` | accepted | accepted | accepted | accepted | accepted | accepted | accepted | accepted_narrow | accepted_native_narrow | blocked | blocked | partial | L3.38 accepted native image transport and text-only minimal JSON with reasoning off, but the image JSON returned the wrong grounded boolean; no KV reuse proof |
| `google/gemma-4-12b-qat` | accepted | accepted | accepted_native_reasoning_off_narrow | blocked | accepted | accepted | accepted_native_reasoning_off_narrow | blocked_research_only | not_run | not_run | not_run | partial_route_specific | L3.38 repeated-context reasoning-off showed timing effects but 0/6 strict-valid outputs; strict-route reasoning disable remains unproven and generated zero confirmation rows |
| `google/gemma-4-26b-a4b-qat` | accepted_controlled_transcript_only | not_run | accepted_native_canary | not_run | not_run | not_run | accepted_native_canary | not_run | not_run | not_run | not_run | research_only_limited | L3.38 native blocks canary passed 4/4 at 8192/16384 with reasoning off/on; reasoning off preserved the answer with substantially lower measured overhead, but broader admission remains blocked |

## Evidence notes

### 8192 text/JSON baseline

Earlier accepted baseline remains:

```yaml
8192:
  E2B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  E4B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  12B:
    transcript_cleanup: accepted
    structured_simple: accepted
    structured_blocks: accepted
  26B:
    transcript_cleanup: accepted_controlled_only
    structured_simple: not_run
    structured_blocks: not_run
```

L3.32a adds:

```yaml
8192_complex:
  google/gemma-4-e2b: accepted
  google/gemma-4-e4b: accepted
  google/gemma-4-12b-qat: blocked_bounded_512_to_1024
  google/gemma-4-26b-a4b-qat: not_run
```

### 16k context

L3.31b forensics narrows the L3.31a red result:

```yaml
E2B: all 3 L3.31a 16k cells passed
E4B: all 3 L3.31a 16k cells passed
12B:
  transcript_cleanup_simple: pass
  structured_simple: pass
  structured_blocks: blocked_finish_length_empty_content
26B: not_run
```

The 12B failure is not broad 16k context degradation by current evidence. L3.37
further localizes the earlier `12B + blocks + 16k` failure: the native route with
reasoning explicitly disabled produced schema-valid blocks JSON at 1024 for both
8192 and 16384. This is a narrow native/local-validation acceptance, not proof
that the OpenAI-compatible strict route is repaired.

With native reasoning enabled, visible output remained empty while reasoning
consumed 1021/1024, 2045/2048, 3069/3072, and 4093/4096 output tokens at both
contexts. Increasing the cap did not rescue visible output. The mechanism is
therefore reasoning-dominant cap exhaustion, not simple visible-output budget
insufficiency and not a context-size interaction.

### 12B complex JSON

The E2B/E4B L3.32a result remains 4/4 accepted. One bounded 12B complex case was
then run with adaptive stages `512 -> 1024`; it reached the upper stage with
`finish_reason=length`, empty extracted content, and no parse/schema/business
admission. This changes 12B complex from `not_run` to `blocked` without
authorizing broad L3.32c or 26B expansion.

### L3.37 reasoning and structured-route diagnosis

The bounded L3.37 staircase used the exact installed
`google/gemma-4-12b-qat` variant, whose native capability metadata advertised
`reasoning: off/on` with default `on`. It produced 12 privately retained attempts
and a sanitized companion summary:

Canonical public evidence pack: [L3.37 Gemma 12B reasoning and output-budget evidence](l3_37_gemma_12b_reasoning_output_budget/report.md).

```yaml
native_reasoning_off:
  8192: schema_valid_at_1024
  16384: schema_valid_at_1024
native_reasoning_on:
  8192: reasoning_dominant_cap_exhaustion_no_rescue_le_4096
  16384: reasoning_dominant_cap_exhaustion_no_rescue_le_4096
openai_strict_json:
  8192: empty_length_at_1024
  16384: empty_length_at_1024
context_interaction_supported: false
private_records: 12
cleanup_verified_for_every_record: true
final_global_loaded_count: 0
sanitized_summary_sha256: 8d83f83dbabf5ba5a6cb07baaf0fba39fc8bc3044c9299d15c6f707c615ee89e
```

This evidence rules out a general inability to produce the blocks schema and
does not support a runtime/template pathology on the native reasoning-off path.
The strict-route failures remain underdetermined between constrained-route,
chat-template, and default/hidden-reasoning interaction because that route has
no separately proven reasoning-off control in this experiment. They must not be
reported as a simple budget shortage or as broad 12B structured incapability.

### Cache/session

L3.33a result:

```yaml
E4B: 12/12 pass, accepted_narrow
12B: 10/12 pass, 2 finish_length hard failures, blocked
E2B: not_run
26B: not_run
kv_reuse_proven: false
cache_benefit_claimed: false
```

L3.33b source-application architecture import is `research_only` and changes the
interpretation, not the model result. The pinned evidence and corrected contract
are documented in [L3.33b cache evidence import](l3_33b_cache_evidence_import_from_source_application.md):

```yaml
source_evidence: static_plus_deterministic_owner_path_tests
source_parity_execution_mode: session_loaded
warmup_first: first_request_serialized_not_cache_materialization
stable_prefix: labkit_final_request_seam_requirement_not_source_application_proof
cache_prompt: requested_by_lmstudio_payload_builder
cached_tokens: nullable_provider_telemetry_not_proof_by_itself
max_output_tokens: explicit_and_bounded
cold_per_request: labkit_comparator_not_source_application_parity
kv_reuse_proven: false
cache_benefit_claimed: false
```

The imported lifecycle contract requires ownership-scoped cleanup: LabKit-owned
instances require unload and read-back confirmation, while classified
`external_preloaded` instances are neither removed nor treated as cleanup failure.
Architecture import alone does not change any cache/session admission cell.

The L3.38 focused 12B repeated-context follow-up at 16384 also remained blocked.
With native reasoning off and a 1024-token cap, exact-repeat and stable-prefix
comparisons showed 4.985x and 4.392x first-to-warm latency ratios respectively,
but all six outputs leaked Markdown fences and failed strict local JSON parsing.
This is timing-only research evidence, not KV-reuse or cache-benefit proof.

### Vision

L3.34 established that PNG data URI image payloads are accepted at API route level, but structured JSON failed with `finish_reason=length` for all four target models.

L3.34.1 repair probe then tested E4B plain text first:

```yaml
model: google/gemma-4-e4b
phase: plain_text
max_tokens: 256
http_status: 200
finish_reason: length
completion_tokens: 256
response_char_count: 0
final_loaded_count: 0
status: blocked
```

The later native E4B gate resolved the route/envelope question. Native
`/api/v1/chat` with `input` text/image `data_url` items and `output[]` extraction
returned 506 characters of non-empty plain text at `max_output_tokens=128`.
The immediately following minimal-JSON gate returned malformed, non-truncated
JSON, so the adaptive policy correctly stopped after one 256-token stage and
the tiny screening gate was skipped. Native plain text is accepted narrowly;
structured vision and L3.35 remain blocked.

L3.38 then retried the smallest reasoning-off chain. Plain text and text-only
minimal JSON passed. The image request returned valid, non-truncated JSON, which
accepts image transport but not understanding: its grounded boolean contradicted
the verified fixture. Structured vision therefore remains blocked for quality,
not for route transport or output-budget exhaustion.

### L3.38 reasoning-off follow-up

Canonical public evidence pack: [L3.38 reasoning-off follow-up](l3_38_reasoning_off_followup/report.md).

```yaml
generation_cells: 13
http_200_terminal: 13
private_records: 13
cleanup_verified: 13
final_global_loaded_count: 0
26b_native_blocks:
  8192: off_and_on_schema_valid
  16384: off_and_on_schema_valid
  recommendation: reasoning_off_for_this_exact_task
e4b_native_vision:
  text_minimal_json: accepted
  image_transport: accepted
  image_grounding: blocked_incorrect_boolean
12b_native_repeated_context:
  valid_rows: 0_of_6
  decision: research_only
12b_openai_strict_json:
  generation_rows: 0
  decision: blocked_route_contract_underdetermined
```

## Final admission decision

```yaml
gemma_family_closure: not_green
safe_default_context: 8192
16k:
  accepted:
    - google/gemma-4-e2b canary scope
    - google/gemma-4-e4b canary scope
    - google/gemma-4-12b-qat transcript/simple on the established route
    - google/gemma-4-12b-qat blocks on native reasoning-off with local schema validation only
  blocked:
    - google/gemma-4-12b-qat structured_blocks on OpenAI-compatible strict JSON
structured_json:
  best_current_models:
    - google/gemma-4-e2b
    - google/gemma-4-e4b
  blocked:
    - google/gemma-4-12b-qat bounded 8192 complex case
  route_specific:
    google/gemma-4-12b-qat:
      native_reasoning_off_blocks: accepted_narrow_at_8192_and_16384
      native_reasoning_on_blocks: reasoning_dominant_no_rescue_le_4096
      openai_strict_blocks: blocked_empty_length_at_1024
    google/gemma-4-26b-a4b-qat:
      native_blocks_canary_8192: accepted_off_and_on
      native_blocks_canary_16384: accepted_off_and_on
      recommended_reasoning_for_exact_task: off
      broader_structured_admission: blocked
cache_session:
  accepted_narrow:
    - google/gemma-4-e4b
  blocked:
    - google/gemma-4-12b-qat; L3.38 reasoning-off rerun remained 0/6 strict-valid
  kv_reuse_proven: false
vision:
  eligible_for_l3_35: []
  native_plain_text_accepted_narrow:
    - google/gemma-4-e4b one-asset gate
  image_transport_accepted_narrow:
    - google/gemma-4-e4b one-asset reasoning-off gate
  blocked_reason: L3.38 image JSON was valid and non-truncated but grounded the verified fixture incorrectly
next_repair_gates:
  - expose and verify an explicit reasoning-off contract for the OpenAI-compatible structured route, or keep the native reasoning-off path isolated as a narrow fallback
  - do not broaden 12B complex JSON from the blocks-only L3.37 result
  - repair E4B image grounding before any L3.35 matrix
```
