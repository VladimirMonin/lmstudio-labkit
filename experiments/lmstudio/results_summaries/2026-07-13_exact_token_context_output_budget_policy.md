# Exact token, context-fit, and adaptive output-budget policy

Date: 2026-07-13

Status: read-only product-contract recommendation. No model load, tokenizer capture, inference, cloud request, benchmark rerun, host change, commit, or push was performed.

Machine-readable companion: `2026-07-13_exact_token_context_output_budget_policy.json`.

## Decision

Use a two-gate planner:

1. a **pre-load estimate** chooses whether a request is eligible to load and selects the smallest approved context tier with sufficient conservative headroom;
2. an **exact loaded-instance gate** applies the selected loaded model's chat template, tokenizes that exact formatted prompt, confirms the observed context length, and admits generation only when the exact prompt count plus separately classified non-chat overhead, output reserve, and safety margin fit.

The SDK count is exact only for the exact loaded instance, model revision, resolved message history, prompt template, and tokenizer invocation that produced it. It is not a reusable count for changed text, a different schema, unresolved placeholders, another model revision, or another loaded configuration.

Output-budget escalation is allowed only for independently observed truncation. Complete malformed JSON, schema failure, business-identity failure, semantic failure, repetition, reasoning leakage, or protected-value damage must not receive a larger output budget. A structural retry, where the task policy allows one, stays a separate reason and consumes the same global call ceiling.

## Evidence boundary

### Executed exact-token evidence

The retained four-model capture contains four loaded-instance captures and 80 request rows. For every row, the runner:

- bound one exact model key, instance ID, load configuration, request digest, and plan digest;
- built the SDK chat history;
- called `apply_prompt_template` on the loaded instance;
- called `tokenize` on the resulting formatted prompt;
- retained only hashes and `exact_token_count` publicly;
- verified zero loaded models before capture and after unload.

Across those 80 executed rows, exact formatted-prompt counts ranged from 925 to 12,797 tokens. A later task-axis fit artifact combined the retained exact counts with fixed reserves of 512 tokens for short normalization and structural retention, 2,048 tokens for long normalization, and a conservative 256-token request-change allowance. All 80 resulting upper bounds fit their configured context tiers. This is executed evidence for those frozen requests only, not a universal product calibration.

### Executed usage evidence

The LabKit metrics surface distinguishes estimated input, actual or prompt tokens, completion tokens, total tokens, finish reason, and the configured output cap. Retained context-study evidence also shows why these fields must stay separate:

- current-only chunk summaries had a median of 786 prompt and 373 completion tokens;
- two extended-context chunk summaries reached a 1,024-token cap and became structurally unusable;
- one repeated full-context cleanup reached 4,096/4,096 completion tokens and returned malformed JSON;
- the runtime did not expose request-linked cached-token counts in the bounded cache probe.

These observations support bounded reserves and truncation detection. They do not establish a universal completion distribution or production retry policy.

### Static contracts reused

- `evaluate_context_fit` computes `estimated_input_tokens + max_tokens <= floor(effective_context_length * safety_ratio)`.
- `AdaptiveOutputBudgetPolicy` provides bounded increasing stages and observations based on finish reason, completion usage, parse state, schema state, and quality state.
- The managed executor records prompt/completion usage and each adaptive attempt.

Product reuse should preserve these pure ideas but tighten one behavior: LabKit currently permits escalation for an apparently incomplete JSON document even without an independent truncation signal. The product contract below permits a larger output budget only when truncation is independently observed.

## Required planner inputs

The host owns one immutable logical-request plan containing only in-memory source content and privacy-safe persisted metadata:

- logical request ID and request generation;
- task profile and approved model profile;
- exact model key/revision when known;
- selected context strategy;
- ordered target units and reference-only units;
- fully resolved system/user messages;
- fully resolved summary and context placeholders;
- API-bound response schema and schema version;
- application-owned expected IDs/order and protected-value digest;
- context-tier candidates and safety ratio;
- output-budget stages and task hard maximum;
- transport retry limit, structural retry eligibility, and total model-call ceiling;
- digests of messages, schema, source selection, and planner version.

An unresolved placeholder is a planning failure. Empty optional context must be serialized in its canonical empty form or omitted by a versioned rule; it must never be filled after exact tokenization.

## Deterministic planning stages

### Stage 1 — canonical task assembly

1. Select the task-specific context policy.
2. Select target units and reference-only units.
3. Resolve summary/context placeholders.
4. Build the final ordered messages and API-bound schema.
5. Freeze message, schema, target, reference, and planner digests.
6. Select the task's initial output reserve and hard maximum.

Changing any model-visible message, role, ordering, placeholder, schema, generation control that affects templating, or model revision invalidates downstream token evidence.

### Stage 2 — pre-load estimate

The estimate is a conservative admission screen, not an exact count.

```text
E_chat = conservative token estimate for the final ordered messages
E_schema = conservative schema/grammar overhead estimate
E_task = conservative non-chat task/runtime overhead estimate
R0 = initial output-token reserve
M = fixed safety margin
B(C) = floor(C * safety_ratio)
required_estimate = E_chat + E_schema + E_task + R0 + M
estimate_fits(C) = required_estimate <= B(C)
```

Recommended defaults:

- `safety_ratio = 0.85` while calibration is immature;
- `M = 256` tokens as the retained bounded-study minimum, increased for an uncalibrated provider/runtime;
- if no tokenizer-specific calibration exists, `E_chat` uses the conservative one-token-per-UTF-8-byte bound over the final message serialization;
- `E_schema` uses the canonical schema byte length under the same conservative bound unless a matching runtime calibration provides a larger observed delta;
- `E_task` is a versioned non-negative allowance, never an unexplained negative correction.

Choose the smallest approved context tier for which `estimate_fits(C)` is true. If none fits, reduce only optional reference context according to the task policy, split the target on application-owned boundaries, choose a larger approved tier, or fail. Never silently truncate required target units, IDs, or schema fields.

### Stage 3 — load or attach under lifecycle ownership

Load or reuse only an instance whose exact model identity, revision, context length, parallelism, and purpose are compatible. Read back the materialized instance and its effective context length. Pre-load estimates do not authorize generation.

### Stage 4 — exact loaded-instance token gate

Build the SDK chat from the same frozen messages, then execute:

```text
formatted_prompt = loaded_instance.apply_prompt_template(chat)
T_sdk = len(loaded_instance.tokenize(formatted_prompt))
```

Bind the evidence to:

```text
model key + model revision + instance ID + instance configuration digest
+ effective context + message digest + formatted-prompt digest
+ token-ID digest + tokenizer/runtime version
```

The exact fit calculation is:

```text
H_schema = schema/grammar overhead classified as observed or estimated
H_task = other non-chat overhead classified as observed or estimated
required_exact_gate = T_sdk + H_schema + H_task + R0 + M
exact_gate_fits = required_exact_gate <= B(observed_effective_context)
```

Only `T_sdk` is called exact before generation. If schema or provider overhead remains estimated, the overall verdict is `exact_prompt_plus_estimated_overhead_fit`, not `exact_total_fit`.

If the exact gate fails, apply the same deterministic context-shedding/splitting policy as Stage 2 and rebuild a new immutable request plan. Do not generate with a request that merely passed the estimate.

### Stage 5 — generation and telemetry reconciliation

After every model call, retain privacy-safe telemetry:

- model/revision, instance/config and request digests;
- context tier, safety ratio, margin, and output cap;
- estimate class and `T_sdk` evidence class;
- server-reported prompt, completion, and total tokens;
- finish reason, response length, parse/schema/business/semantic verdicts;
- attempt reason, attempt index, and cumulative model-call count.

For the exact same request binding:

```text
D_usage = prompt_tokens_usage - T_sdk
```

A non-negative `D_usage` is an observed request-level delta, not automatically a reusable constant. Store it by provider/runtime version, exact model revision, schema family/version, task profile, and request-shape bucket. Promote it into `H_schema + H_task` calibration only after repeated matching observations establish a conservative upper bound. A missing prompt-token field leaves calibration unavailable. A negative delta or identity mismatch invalidates reconciliation and raises an instrumentation fault.

Cached-token fields, when present, describe billing/runtime reuse and must not reduce context-fit input tokens unless the runtime explicitly documents that they no longer occupy context. The bounded evidence did not establish such a rule.

### Stage 6 — truncation-only output escalation

Truncation is independently observed when either:

- `finish_reason == "length"`; or
- finish reason is absent and `completion_tokens >= configured_output_cap`.

An explicit normal stop wins over `completion_tokens == cap`, matching the current tested LabKit observation rule.

Before a larger cap is attempted, rerun the fit equation with the next reserve:

```text
required_next = current_input_gate + next_output_reserve
required_next <= B(observed_effective_context)
```

If the next stage does not fit, do not steal required input space. Split the target, reduce optional reference context, or return `truncation_ceiling_reached`.

Do not escalate for:

- complete malformed JSON;
- complete schema or exact-ID/order failure;
- semantic, boundary, protected-value, or image-grounding failure;
- runaway repetition or reasoning leakage;
- cancellation, stale request generation, or persistence failure.

An incomplete JSON document with no finish/usage truncation evidence is a structural failure, not an output-budget signal.

### Stage 7 — global call ceiling

Every provider generation attempt consumes one counter, including transient transport retries, structural retries, and output-budget escalation. The budgets do not multiply.

```text
model_calls_used += 1 before each generation submission
allow_next_call = model_calls_used < total_model_call_ceiling
```

Recommended ceiling:

- simple/interactive tasks: 2 calls;
- long block transforms and hierarchical synthesis: 3 calls;
- no task exceeds 3 model calls without a separately approved product contract.

A typical three-call maximum permits `initial -> one truncation escalation -> one structural retry at the final cap`, or substitutes a transport retry for either later call. Cancellation, deadline, and request-generation checks run before every call and immediately before persistence.

## Task-specific output budgets

These are product-policy proposals bounded by retained evidence, not newly executed admissions.

| Task profile | Initial reserve | Allowed next reserve(s) | Hard maximum | Total call ceiling | Context policy |
|---|---:|---:|---:|---:|---|
| Short microphone cleanup | 512 | 1,024 | 1,024 | 2 | Current capture only |
| Long microphone/file block cleanup | 1,024 | 2,048; 4,096 only for a separately qualified large target | 4,096 | 3 | Current target blocks plus boundary references |
| Per-chunk summary | 512 | 1,024 | 1,024 | 2 | Current chunk only; boundary fallback requires a new plan |
| Direct whole-recording summary | 1,024 | 2,048 | 2,048 | 2 | One full-recording request if it fits |
| Hierarchical summary synthesis | 1,024 | 2,048; 4,096 | 4,096 | 3 | Ordered accepted chunk summaries, not raw full text per chunk |
| Generic self-contained postprocessing | 512 | 1,024; 2,048 when output size tracks a larger source | 2,048 | 3 | Current-only |
| Image analysis | 512 | 1,024 | 1,024 | 2 | Current image plus task-specific schema |

Additional rules:

- The initial reserve is raised to the smallest configured stage that covers the contract-derived output estimate; it is never lowered below the task table.
- Block-preserving transforms use target-text size, expected item count, and schema bounds. Reference-only neighbors do not increase expected output size.
- Summary contracts use schema string/list limits, not source length alone.
- Image descriptions use schema field limits; image bytes are not estimated as text tokens.
- The 4,096 stages are unexecuted product proposals for bounded larger outputs. The retained evidence includes a malformed full-context cleanup at 4,096/4,096, so 4,096 is a ceiling, not a reliability claim.
- The generic LabKit hard maximum of 8,192 remains a library guardrail, not a default host-product stage.

## Contract-derived reserve

The existing `AdaptiveOutputBudgetPolicy` estimates output shape from bounded schema capacity, expected output, and source-text length, rounds to a bounded power of two, and constructs increasing stages. Product planning may reuse this as a lower-bound helper:

```text
R_contract = bounded_power_of_two(max(schema_capacity,
                                      expected_output_size,
                                      target_output_ratio * target_source_size))
R0 = smallest task stage >= R_contract
```

Use tokenizer-calibrated estimates when available. Character-derived estimates remain estimates. If `R_contract` exceeds the task hard maximum, split or reject before generation rather than silently widening policy.

## Failure states

| State | Meaning | Required behavior |
|---|---|---|
| `unresolved_request` | Placeholder, target/reference ownership, schema, or identity is incomplete | Do not estimate, load, or call |
| `estimate_unavailable` | No conservative estimate can be produced | Fail closed or use an explicitly approved degraded non-model path |
| `estimate_no_fit` | No approved tier fits the conservative estimate | Shed optional reference context, split, or fail |
| `load_identity_mismatch` | Loaded model/revision/config/context is not the planned one | Do not tokenize or generate; release only owned instances |
| `exact_tokenization_unavailable` | Loaded instance cannot apply the template/tokenize or returns invalid IDs | Do not label any count exact; use policy below |
| `exact_no_fit` | Exact prompt plus classified overhead/reserve exceeds safe context | Replan before generation |
| `usage_unavailable` | Prompt/completion usage is absent | Continue only within the predeclared cap; mark telemetry/calibration unavailable |
| `usage_reconciliation_fault` | Usage is negative relative to exact count or binding changed | Do not update calibration; flag instrumentation |
| `truncation_observed` | Independent finish/usage signal proves cap exhaustion | Escalate once if the next stage fits and calls remain |
| `truncation_ceiling_reached` | No larger allowed/fitting stage or no calls remain | Fail/fallback/split; no silent partial acceptance |
| `complete_structural_failure` | Complete output fails JSON/schema/identity | Optional one structural retry at the same cap; no budget escalation |
| `semantic_failure` | Output violates task scope, protected values, grounding, or completeness | Fail closed to original source; no budget escalation |
| `call_ceiling_reached` | Global generation counter is exhausted | Stop all retry classes |
| `cancelled_or_stale` | Request generation is no longer current | Late output is inert and cannot persist |

## Exact-tokenization unavailable policy

Three modes are explicit per approved task profile:

1. **`exact_required`** — default for long input, structured block transforms, whole-recording work, and any estimate above 50% of the safe context budget. Failure to obtain the loaded-instance exact count blocks generation.
2. **`conservative_estimate_allowed`** — allowed only for short, bounded, non-destructive tasks whose one-token-per-byte estimate plus schema/task allowances, output hard maximum, and margin fit within 50% of the safe context budget. The result is labeled `estimate_only`; usage telemetry may validate the completed call but cannot retroactively make preflight exact.
3. **`non_model_fallback`** — preserve original text, leave summary/image result unavailable, or use the existing non-model path.

Never reuse a retained exact count when the request digest, model revision, prompt-template/runtime version, schema binding, or instance configuration differs.

## Summary and context placeholders

- `summary` is model-visible only when the task policy selects it and a validated summary artifact exists.
- Missing summary data uses a canonical omitted/empty representation fixed before hashing; it is not generated implicitly during planning.
- Reference context is labeled reference-only and excluded from expected output size.
- Current targets, boundary references, chunk summaries, and whole-recording summaries have separate digests and token components.
- If optional context must be removed to fit, removal order is deterministic and task-specific. Required target units and application-owned identity metadata are never truncated.

## Privacy-safe observability

Persist counts, categorical outcomes, versions, caps, and digests only. Do not persist prompts, formatted prompts, token IDs, raw responses, source text, schema values that contain private content, image bytes, credentials, or local paths. Owner-only diagnostics, if separately authorized, remain outside the repository.

## Implementation order

1. Extract context-fit and output-budget primitives into the stable contract kernel.
2. Add a host-owned canonical request planner and task-profile registry.
3. Add a loaded-instance tokenizer port with evidence binding and exact/estimate labels.
4. Add schema/non-chat overhead accounting and usage reconciliation without automatic calibration promotion.
5. Add the global call counter and truncation-only escalation.
6. Add offline tests for every failure state, context-shedding order, ceiling interaction, and stale/cancelled attempt.
7. Run a later explicitly authorized shadow capture before selecting production calibration bounds or changing task stages.

## Limits and non-claims

- No exact count was captured for a host-product request in this work.
- Retained exact counts cover 80 frozen benchmark requests and four model/runtime bindings only.
- Schema/grammar overhead is not proven to be included in or excluded from every provider's prompt usage.
- Proposed task stages, 50% degraded-mode threshold, safety ratio, and three-call ceiling require product latency and quality validation.
- No retained run proves end-to-end exact preflight, generation, retry, fallback, persistence, and read-back in the host application.
- Usage telemetry is runtime-reported evidence, not an independent tokenizer oracle.
- Context fit does not prove semantic quality, cache reuse, throughput, or production admission.
