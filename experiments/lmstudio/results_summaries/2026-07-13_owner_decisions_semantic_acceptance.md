# Owner decision O10 — task semantic acceptance and canary policy

Date: 2026-07-13

Status: recommended configurable policy for owner approval. This report does not admit a model or task profile, authorize implementation, or authorize live execution.

Machine-readable companion: `2026-07-13_owner_decisions_semantic_acceptance.json`.

## Decision

Approve semantic acceptance as a versioned, task-specific policy above transport, raw parsing, full schema, business identity, cancellation, and persistence gates.

Do not create one universal quality score. Preserve one verdict per required dimension and one typed product outcome:

- `accepted`: every deterministic gate and every required task-semantic dimension passed;
- `fallback_original`: a cleanup or translation candidate failed, and the exact original target is returned unchanged;
- `abstain`: the task contract explicitly permits a model abstention and no candidate output is published;
- `review_required`: structure passed, but a required semantic dimension has no deterministic authority or crossed its review boundary;
- `unavailable`: the task has no safe original-output equivalent or required evaluator/evidence is absent;
- `failed`: transport, control, persistence, or other terminal execution failure;
- `cancelled`: the request generation is stale or cancelled and the result is inert.

`review_required`, `abstain`, `fallback_original`, `unavailable`, and `cancelled` are not accepted model outputs. Provider schema enforcement and local schema validation establish structure only.

## Evidence boundary

### Retained executed evidence

The 202-call structured text/context study is heterogeneous and covers one sanitized recording and one selected model. It includes 12 first-pass cleanup calls, 140 per-chunk summaries, five whole-recording summary calls, repeats/cache probes, and short-context parallel screening. It reported 199/202 parseable or practically valid structured responses, but it is not 202 independent semantic observations. Cleanup semantics were deeply reviewed only on representative source positions; no audio-grounded truth, blind multi-rater review, or end-to-end host persistence/read-back was available.

The 40-call structured vision closure covers four models and four fixtures. All 36 applicable strict calls passed raw JSON and independent schema validation. Direct review remained mixed: exact visible text in 25/39 image rows, salient text complete in 31/39, no unsupported claim in 36/39, and no forbidden private/person claim in 39/39. The controller rejected 35/35 strict image rows because partial allow-lists and warning policy were not valid open-world semantic authorities. That validator result is retained as failure evidence, not an admission denominator.

Current LabKit validators provide useful deterministic layers:

- strict raw parsing, schema-shape or JSON Schema validation, expected ID diagnostics, exact order, uniqueness, non-empty strings, finish state, and reasoning-leak checks;
- strict-vision text/object recall and precision checks against frozen ground truth plus forbidden-claim matching.

They do not establish production semantic acceptance. The general structured helper explicitly labels its schema check as minimal rather than complete JSON Schema validation, and the vision ground truth proved too sparse for an open-world binary gate.

### Missing executed evidence

No retained execution establishes semantic admission for translation, audio-grounded short microphone cleanup, generic microphone commands, a second recording, broad summary quality, host persistence/read-back, or a production canary. Therefore every task policy below is `requires_shadow_calibration`; none is `approve_now` for production.

## Evaluation model

### Ordered gates

Every candidate follows this order, and every intermediate result is retained separately:

1. current request generation and cancellation;
2. transport, response surface, safe completion, output-cap and repetition/reasoning checks;
3. untouched raw parsing for native structured tasks;
4. complete local closed-schema validation;
5. application-owned identity, count, uniqueness, order, target/reference separation, and strict non-empty types;
6. deterministic task invariants, including protected values and forbidden side effects;
7. task-specific semantic dimensions;
8. final generation/cancellation fence;
9. atomic or recoverable persistence and read-back where the task persists output.

Failure at gates 1–5 never enters a semantic denominator. Failure at gates 6–7 is a semantic rejection. Failure at gates 8–9 is a product-behavior failure even if the candidate text was good.

### Denominators

Report at least these denominators independently for each exact `(task contract, prompt version, validator version, model/route revision, request-shape bucket)`:

- submitted calls;
- usable transport completions;
- raw-parse eligible and passed;
- schema eligible and passed;
- business-identity eligible and passed;
- deterministic-semantic eligible and passed;
- human-reviewed and passed without correction;
- accepted product outcomes;
- `fallback_original`, `abstain`, `review_required`, `unavailable`, `failed`, and `cancelled` counts;
- persistence/read-back eligible and passed.

Never use submitted calls as the denominator for a semantic dimension that only applies after structure, and never count fallback or review as success. Report Wilson 95% intervals for reviewed binary dimensions; the interval is evidence, not a replacement score.

## Per-task acceptance matrix

| Task | Deterministic gates | Human or authoritative semantic gate | Accepted outcome | Failure behavior |
|---|---|---|---|---|
| Cleanup text | Raw/closed `{text}` contract; non-empty output; no reasoning/repetition; protected names, numbers, dates, URLs, commands, placeholders and explicit literals preserved according to policy; no reference-only text copied; bounded edit envelope only as a review trigger | Reviewer answers one binary question: “Is the meaning preserved and only the requested cleanup performed, with no material omission or addition?” | All deterministic gates plus semantic pass | `fallback_original`; out-of-envelope but otherwise safe candidates become `review_required` in shadow, never auto-accepted |
| Cleanup blocks | Cleanup-text gates plus exact target count, unique ID sequence, original order, no reference ID, no cross-block ownership transfer, and source timestamps reattached outside the model | Binary per-block ownership/meaning review; whole batch passes only if every target block passes | Atomic accepted batch | Exact original block sequence as `fallback_original`; no partial merge under this contract |
| Translation text/blocks | Text/block structural gates; canonical target-language metadata; protected values and do-not-translate inventory exact; no source/reference leakage; language detector may flag but cannot prove quality | Binary adequacy, target-language compliance, terminology and fluency review; every required dimension passes | Accepted translation for the exact language pair and shape | Exact source as `fallback_original` with degraded state; language uncertainty is `review_required` |
| Chunk/recording summary | Closed bounded schema; exact source coverage metadata owned by application; no stale/partial child; exact child order and complete hierarchy coverage; bounded fields; no protected-value mutation | Each factual claim is source-supported; no decision is promoted from discussion; required source strata are covered; scope and usefulness pass. Human review is mandatory until a validated claim-alignment evaluator exists | Current immutable summary artifact only after commit/read-back | `review_required` for plausible but unauthoritative output; `unavailable` after rejection. Never fall back to a stale/partial summary or replace authoritative source |
| Vision closed-world extraction | Closed schema; exact fixture/request binding; exact visible text under a predeclared normalization policy; enum validity; forbidden private/person claims absent | Human review only for fields not covered by exhaustive gold | Accepted extraction for that exact fixture class | `review_required` when gold is incomplete; `unavailable` on mismatch. No repaired/defaulted field |
| Vision open-world description/objects | Closed schema; forbidden claims absent; any object/text gold must be explicitly exhaustive or treated as recall-only; warnings omitted by default unless evaluable | Grounding, salient completeness, unsupported claims, and warning relevance are separate binary dimensions; all required dimensions pass | Accepted only for the exact product rubric and image class | `review_required` when the rubric or ground truth is incomplete; `unavailable` on unsupported material claim |
| Microphone command | Deterministic anchored classifier; closed `{answer_text}`; non-empty plain projection; no trigger/cleanup/full-recording/summary/clipboard context by default; no reasoning/repetition; current-generation fence | Generic command correctness cannot be inferred from structure. The initial semantic gate is explicit user confirmation after displaying a candidate. A later bounded command class needs its own authoritative fixtures and review policy | User-confirmed answer, or a separately approved bounded command-class pass | `review_required` with display-only candidate and zero copy/paste; invalid/unsafe output is `failed` or `unavailable`, never transcript-as-answer |

### Deterministic validator limits

- Protected-value equality is a hard gate only for values the task policy says must remain exact. It must not freeze punctuation or words that the task is explicitly allowed to change.
- Edit distance, output/source length, language identification, embedding similarity, lexical overlap, and model self-critique are triage signals only. They route to review; they do not prove correctness.
- Summary claim matching and open-world vision grounding require an authoritative source/rubric. Sparse allow-lists must not be treated as exhaustive gold.
- Human review uses a frozen binary rubric with examples, independent reviewers where required, and adjudication. Reviewer disagreement is retained as a separate rate.

## Recommended starting evidence gates

These are configurable starting defaults, not claims derived from the retained denominators.

### Before shadow

For every exact task/profile/route/shape:

1. all ordered offline gates and typed outcomes are implemented and versioned;
2. at least 30 publication-safe fixtures cover ordinary, boundary, empty, malformed, adversarial, cancellation, stale-generation, retry-ceiling, fallback and persistence-failure cases;
3. every hard deterministic fixture passes; all injected defects fail in the expected typed state;
4. two reviewers independently pilot at least 20 semantic fixtures, resolve rubric ambiguity, and freeze the rubric before shadow collection;
5. shadow output has zero user-visible, clipboard, source-mutation, search/export, or persistent-current side effect;
6. a per-contract kill switch and stale-generation fence pass offline tests.

Fixture count is a minimum coverage floor, not a statistical admission denominator.

### Before canary

For the exact task/profile/route/shape:

- at least 100 shadow candidates complete the applicable structural pipeline;
- at least 50 stratified candidates receive frozen-rubric review; the first 20 are independently double-reviewed and adjudicated;
- no critical defect occurs: protected-value loss, wrong target/reference ownership, unsupported critical claim, forbidden private/person claim, stale/cancelled publication, persistence corruption, or command copy/paste without semantic authorization;
- reviewed pass without correction is at least 49/50 for cleanup, translation and a bounded command class;
- reviewed pass is at least 48/50 for summary and open-world vision, with every required semantic dimension reported separately;
- closed-world extraction is exact on every authoritative field; incomplete gold routes to review rather than acceptance;
- fallback/review/abstain rates, latency and reviewer disagreement are measured and accepted by the owner for that task; no denominator is pooled across tasks.

The 50-case gates are screening thresholds only. They do not provide a tight production estimate.

### Before production promotion

For the exact task/profile/route/shape, after canary operation:

- at least 200 stratified, frozen-rubric reviewed candidates;
- cleanup, translation and any bounded command class: at least 198/200 pass without correction; the Wilson 95% lower bound is approximately 0.964;
- summary and open-world vision: at least 196/200 pass every required dimension; the Wilson 95% lower bound is approximately 0.950;
- at least 300 independently countable critical-safety opportunities with zero critical defects; zero of 300 has a Wilson 95% upper bound of approximately 0.013, so this is still bounded evidence rather than proof of zero risk;
- 100% pass on deterministic identity, protected-value, cancellation, persistence/read-back, and zero-side-effect failure gates;
- no unresolved systematic reviewer disagreement, source-position failure cluster, language-pair gap, image-class gap, or request-shape gap;
- rollback has been exercised in a production-like fake or shadow environment and leaves original source authoritative.

Production approval remains per task, language pair, modality, model/route revision and request-shape bucket. A passing cleanup profile does not admit translation, summary, vision, command, another concurrency shape, or another model revision.

## Canary policy

### Initial canary

1. Enable one exact task contract and one exact approved profile/route behind a versioned feature flag.
2. Start with 25 eligible requests. Review all 25 before expansion; cleanup/translation continue to preserve the original fallback, summary/vision remain non-current until accepted, and command remains display-only pending confirmation.
3. Expand to 100 eligible requests only if no stop gate fires. Review at least 50% of the next 75, stratified by input size and task-specific risk strata.
4. Expand toward the 200 reviewed production denominator only after the first 100 are reconciled. Sampling may decrease only under a recorded owner decision and must still meet the reviewed denominator.
5. Keep immutable attempts and exact accepted-attempt traceability. Do not rewrite failed attempts after retry or review.

### Immediate stop gates

Disable the exact task/profile route and invalidate in-flight generations on any of these:

- one critical protected-value mutation, wrong block ownership, reference-only output, forbidden private/person claim, or unsupported critical claim;
- one stale/cancelled result published, one partial/corrupt persistence event, or one read-back mismatch;
- one command copy/paste side effect without an accepted semantic gate or explicit user confirmation;
- one schema/validator/prompt/model identity mismatch or silent structured-to-plain downgrade;
- ground truth or rubric shown to be non-authoritative for a gate, as occurred in the retained vision validator;
- rollback or kill-switch failure.

### Rate stop gates

The initial configurable operational defaults are:

- stop after 2 semantic rejects in the first 25 reviewed canary cases;
- after 25, stop when any required dimension falls below its canary-entry threshold in a rolling 50 reviewed cases;
- stop when transport plus structural fallback exceeds 5% in a rolling 50 eligible requests;
- stop after 3 consecutive transport/structure failures;
- stop when p95 latency exceeds the task's predeclared interactive/batch ceiling for two consecutive 50-request windows;
- pause for review when reviewer disagreement exceeds 10% in a rolling 50 double-reviewed cases.

Rate gates are safeguards, not quality scores. A critical stop gate overrides a good aggregate rate.

## Rollback seam

Rollback is per task contract and profile/route:

1. disable the feature flag and stop issuing new model requests;
2. increment request generation so every in-flight completion becomes inert;
3. cleanup/translation return the immutable original target as `fallback_original`;
4. summary and vision leave the result unavailable and preserve the authoritative source/current prior artifact;
5. microphone command removes copy/paste projections and leaves at most a clearly marked display-only review candidate;
6. retain readable prompt, schema, validator, policy and accepted-attempt versions for already committed artifacts;
7. verify persistence/read-back and owned local lifecycle cleanup; never unload an externally owned instance.

Rollback must not require data deletion, schema rewriting, prompt inference, or model-authored recovery.

## Minimum acceptance tests

### Policy and denominator tests

- unknown task policy, missing semantic dimension, missing evaluator authority or unknown validator version fails closed;
- every typed outcome is mutually exclusive and fallback/review/abstain cannot increment accepted counts;
- denominator eligibility follows the ordered gates and cannot pool tasks, models, language pairs or request shapes;
- Wilson interval calculation and threshold boundary cases use frozen fixtures.

### Cleanup and translation

- protected names, numbers, dates, URLs, commands, placeholders and configured terminology: unchanged, missing, duplicated and mutated cases;
- omission, unsupported addition, severe shortening/expansion, reference leakage and cross-block transfer route correctly;
- block count, duplicate, extra, missing, reordered, wrong-type, empty and partial batches all fail atomically;
- translation target conflict, wrong language, mixed-language leakage, untranslated span, protected-term mutation and fluent-but-wrong meaning require fallback/review;
- original text/blocks, IDs, order and timestamps survive fallback, persistence, export and read-back.

### Summary

- direct and hierarchical complete coverage, child order, source digest, stale child, partial hierarchy, unsupported claim, promoted decision, omitted required stratum and scope leakage;
- failed/review/stale/partial summaries cannot become current, enter prompts, FTS current-summary projection or normal export;
- reviewer rubric examples cover factual support, required coverage, uncertainty and usefulness separately.

### Vision

- exhaustive versus partial gold is explicit; partial allow-lists cannot drive precision rejection;
- exact OCR normalization is versioned and tested with confusables, punctuation, case and whitespace;
- object grounding, salient completeness, unsupported claims, warning relevance, forbidden claims and scene/language classification remain separate;
- repaired/defaulted/unknown-enum output cannot become accepted;
- the retained sparse-gold disagreement is a permanent regression fixture for `review_required` behavior.

### Microphone command

- full classifier matrix and exact suffix ownership;
- malformed, fenced, repaired, empty, repetitive, reasoning-bearing and semantically unauthoritative answers never copy/paste;
- user confirmation promotes only the current candidate; cancellation, replacement and rollback invalidate confirmation targets;
- command result never mutates transcript, cleanup, summary or source fields.

### Control, canary and rollback

- transport and structural retry share one total call ceiling and preserve immutable attempts;
- cancellation before request, during retry/backoff, after validation and during commit prevents publication;
- immediate and rate stop gates disable only the bound task/profile route and reject late completions;
- kill switch, generation bump, original-source fallback, unavailable state, zero clipboard side effects, persistence read-back and lifecycle cleanup are verified together.

## Decision classification

| Decision | Classification | Rationale |
|---|---|---|
| Separate deterministic, semantic and product verdicts | `approve_now` | Required by current architecture and demonstrated by structure/semantic disagreement |
| Typed `accepted/fallback_original/abstain/review_required/unavailable/failed/cancelled` outcomes | `approve_now` | Prevents fallback and review from inflating success |
| Per-task rubric and denominators; no universal quality score | `approve_now` | Tasks have different authority, risk and safe fallback behavior |
| Proposed sample floors and pass thresholds | `approve_configurable_default` | Practical starting gates; not established by retained evidence |
| Production semantic admission for any task/profile | `requires_shadow_calibration` | Current denominators are bounded, heterogeneous or absent |
| Generic microphone-command automatic semantic acceptance | `blocked_external_capability` | No deterministic authority exists for arbitrary command correctness; initial gate is user confirmation |

## Sources

Repository evidence:

- `experiments/lmstudio/results_summaries/2026-07-13_host_application_shaped_structured_context_summary.md`
- `experiments/lmstudio/results_summaries/2026-07-13_native_structured_vision_closure.md`
- `experiments/lmstudio/results_summaries/2026-07-13_strict_vision_40_call_manual_reconciliation.md`
- `experiments/lmstudio/results_summaries/2026-07-13_task_specific_context_schema_policy.md`
- `experiments/lmstudio/results_summaries/2026-07-13_structured_validation_migration_risks.md`
- `tools/lmstudio_lab/structured.py`
- `lmstudio_labkit/strict_vision.py`

Primary external references:

- JSON Schema Draft 2020-12 validation vocabulary: https://json-schema.org/draft/2020-12/json-schema-validation
- NIST AI Risk Management Framework 1.0: https://nvlpubs.nist.gov/nistpubs/ai/nist.ai.100-1.pdf
- NIST AI RMF Measure playbook: https://airc.nist.gov/airmf-resources/playbook/measure/

JSON Schema is used only as structural authority. NIST guidance supports context-of-use evaluation, documented metrics, ongoing measurement and risk response; it does not supply the task thresholds proposed here.

## Non-claims

- No model, task profile, language pair, image class, context size, concurrency or provider route is admitted.
- The proposed numeric floors are owner-configurable rollout defaults, not facts inferred from 202 text calls or 40 vision calls.
- No automated metric is claimed to replace authoritative human review for meaning preservation, translation adequacy, summary factuality, open-world vision grounding or generic command correctness.
- No live request, model operation, cloud call, tokenizer capture, host edit, migration, implementation card, commit or push was performed.
