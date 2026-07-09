# L3.28 Gemma Family Expansion Plan

Status: planning artifact only. No live inference was run for this plan.

## Strategic decision

Continue LM Studio LabKit as a standalone laboratory bench. Do not integrate these results into a host application yet.

L3.27 is accepted as the current narrow green text path:

- mode: `transcript_cleanup/simple`
- prompt: `strict_no_new_facts_v2`
- context: `8192`
- retry: `off`
- quality candidate: `google/gemma-4-e4b`
- lightweight fallback: `google/gemma-4-e2b`
- evidence: 60 attempts, 60 passes, 0 failures, 60 local-only raw prose cases reviewed, no raw outputs committed

The next goal is to expand the Gemma family inside LabKit, not to broaden into host-app integration, Qwen, packaging, or a mixed all-axis matrix.

## Models in scope

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`

## Historical basis

### E2B/E4B

L3.27 raw-prose review established:

- E4B is the better quality candidate for transcript cleanup.
- E2B remains useful as a lightweight fallback/minimal cleanup mode.
- Near-identity was not the dominant issue in that run; term preservation and cleanup judgment were more important.

### 12B QAT

L3.9 showed that 12B QAT was load-capable and could pass parse/schema, but had deterministic ID/business drift under the loose Blocks JSON baseline.

L3.10 appeal changed the status from unresolved to conditionally viable:

- `structured_schema_variant=per_position_id_const` passed the Blocks JSON contract.
- one-shot sanitized business-fail retry recovered the deterministic baseline ID drift.
- 12B must not be used as a loose baseline-schema default.

### 26B A4B QAT

L3.9 showed load-only capacity evidence for 26B A4B QAT, but no live generation proof. It remains research/capacity-only until a separate tiny generation canary proves cleanup and privacy-safe artifacts.

## Expansion order

### L3.28a — 12B simple transcript-cleanup canary

Purpose: test whether 12B improves prose quality without touching its known structured Blocks JSON weakness.

Scope:

- model: `google/gemma-4-12b-qat`
- task: `transcript_cleanup/simple`
- prompt: `strict_no_new_facts_v2`
- context: `8192`
- retry: `off`
- snippets: same public-safe synthetic set used for L3.27, preferably 10 first
- max attempts: 10-20
- raw review: local-only, outside repo

Forbidden in this slice:

- blocks
- paragraphing
- complex schema
- 26B
- Qwen
- image live
- throughput/parallel/session/warmup

Decision gate:

- if prose quality clearly improves over E4B without adding facts or damaging terms, 12B can become a quality-mode candidate;
- if it is slower without quality gain, keep E4B as quality candidate;
- if it adds facts or over-edits, keep 12B out of transcript cleanup.

### L3.28b — Gemma simple text family matrix

Purpose: compare E2B/E4B/12B on simple text tasks after 12B canary.

Scope:

- models: E2B, E4B, 12B only if L3.28a passes
- modes: `transcript_cleanup/simple` only at first
- prompt: `strict_no_new_facts_v2`
- languages/profiles: `ru_ru`, `ru_en_mixed`, `en_en`
- context tiers: start `8192`; prepare `16384` only if 8192 is stable
- request count target: bounded 60-120 attempts
- raw review: sampled local-only pack, sanitized aggregates committed

Decision gate:

- preserve meaning and no-new-facts before latency wins;
- compare latency median/p95 only after quality gates are acceptable.

### L3.28c — Gemma structured JSON recovery matrix

Purpose: close structured JSON status across Gemma without mixing it with prose cleanup.

Scope:

- E2B/E4B: confirm existing Blocks JSON green path is still valid.
- 12B: run only hardened contract profiles:
  - `structured_schema_variant=per_position_id_const`; and/or
  - sanitized one-shot business-fail retry.
- 26B: no structured generation until a tiny generation canary proves it can complete and clean up.

Forbidden:

- loose 12B baseline-schema promotion;
- route matrix;
- `/v1/responses`;
- broad context/cache/session axes.

### L3.28d — 26B load and tiny generation proof

Purpose: determine whether 26B can move beyond capacity-only status.

Scope:

- model: `google/gemma-4-26b-a4b-qat`
- first: load-only proof at 8192 with cleanup `final_loaded_instances=0`
- second, only if load is clean: 1-3 tiny generation attempts under `transcript_cleanup/simple`
- no raw commit; sanitized result only

Stop immediately if:

- model download is required;
- load verification fails;
- cleanup final zero cannot be proven;
- latency/resource behavior is unsuitable for bounded lab work.

### L3.28e — Gemma vision readiness plan, not mixed text run

Purpose: prepare image/vision as a separate branch after text/structured Gemma results.

Scope to prepare later:

- resize levels: 1024 as primary, 512 as fallback
- pipeline: resize -> base64 -> VLM request -> structured output -> sanitized artifact
- explicit compatibility checks for LM Studio image processing constraints

Do not mix vision with L3.28a-c text/structured runs.

## Explicit non-goals

Do not include in L3.28:

- Qwen or Qwen VL
- image live in the text/structured slices
- app/host integration
- packaging/publication polish
- blocks mixed with transcript cleanup
- paragraphing
- complex schemas mixed with simple transcript cleanup
- throughput, parallel, session/warmup, overnight/stress
- `/v1/responses`
- route matrix
- raw prompts/responses in Git

## Publication-safety requirements

Committed artifacts may include:

- configs and suites;
- sanitized summaries;
- aggregate metrics;
- model-level scores;
- decision records.

Committed artifacts must not include:

- raw prompts;
- raw responses;
- private transcripts;
- raw local review packs;
- local private paths;
- base URLs, hostnames, tokens, or credentials.

## Proposed next concrete step

Start with L3.28a only:

1. create a tiny 12B transcript-cleanup/simple canary config;
2. verify config shape offline/preflight only;
3. do not run live until explicitly approved;
4. if approved later, run max 10-20 attempts with local-only raw review and sanitized summary.

This keeps the next step small enough to answer the one useful question: whether 12B improves prose quality over E4B before the broader Gemma matrix is justified.
