# L3.24 — Raw-Output Quality Review Summary

## Status

L3.24 is a local-only raw-output quality review for the accepted simple postprocessing lane.

This summary commits only sanitized conclusions. Raw prompts, raw responses, and local review inputs are not committed.

## Local review dataset

Dataset mode used:

```text
Variant B — public-safe synthetic realistic snippets
```

Local-only dataset location:

```text
/tmp/labkit-l324-synthetic-review-inputs/
```

The local synthetic set contains 10 realistic ASR-like snippets covering:

1. short noisy dictation;
2. technical dictation with Django / Qwen / embedding terms;
3. Python lesson fragment;
4. bug explanation fragment;
5. English technical terms;
6. repeats and self-corrections;
7. no-punctuation text;
8. long sentence;
9. product/model names;
10. conversational style.

The dataset is public-safe synthetic, but it still remains local-only for this review workflow.

## Raw-output review pack

Local-only pack:

```text
/tmp/labkit-l324-raw-output-review-pack/
```

Export command shape:

```bash
uv run lmstudio-benchmark export-review-pack \
  --run-dir <L3.24-run-dir> \
  --output-dir /tmp/labkit-l324-raw-output-review-pack \
  --include-raw-outputs-local-only \
  --limit 40
```

Guard behavior:

- raw-output pack must not be written inside the repository;
- output under the platform temp directory (`tempfile.gettempdir()`) is allowed;
- raw base URLs, credentials, tokens, and secrets are not exported;
- README contains a local-only raw-output warning;
- pack is not tracked by Git.

## Run scope

Models:

```text
google/gemma-4-e2b
google/gemma-4-e4b
```

Modes:

```text
transcript_cleanup/simple
term_normalization/simple
```

Runtime:

```text
context_tier: 8192
temperature: 0
execution_mode: cold_per_request
cache_mode: none
parallel: 1
retry_policy: off
```

Request count:

```text
attempt_count: 20
pass_count: 20
fail_count: 0
pass_rate: 1.0
```

Per model:

```text
gemma4_e2b: 10/10 pass
gemma4_e4b: 10/10 pass
```

Per mode:

```text
transcript_cleanup/simple: 14/14 pass
term_normalization/simple: 6/6 pass
```

## Rubric

Each sampled output was reviewed using this rubric:

```yaml
meaning_preserved: 0..2
asr_noise_reduced: 0..2
no_new_facts: 0..2
term_handling: 0..2
naturalness: 0..2
style_overediting: 0..2
overall_acceptability: 0..2
```

Product-prototype threshold:

```text
overall_acceptability_avg >= 1.5
no_new_facts_min >= 1
meaning_preserved_min >= 1
```

## Review answers

### 1. Does transcript_cleanup/simple preserve meaning?

Yes in this small local review.

```text
E2B: 7/7 meaning preserved
E4B: 7/7 meaning preserved
```

No transcript-cleanup sample showed an obvious meaning break.

### 2. Does it remove ASR noise without over-editing?

E4B performed better.

```text
E2B: mostly near-identity output; safe but often not useful cleanup
E4B: visibly improved punctuation/capitalization/readability in most cleanup samples
```

Interpretation:

- E2B often preserved text by doing almost nothing;
- E4B more often produced the product behavior expected from transcript cleanup;
- neither model showed severe over-editing in transcript-cleanup mode in this sample.

### 3. Does it avoid adding facts?

No obvious factual additions were found in transcript-cleanup samples.

Caveat:

- sample size is small;
- snippets are synthetic;
- no-new-facts should remain a hard product invariant and a review item before broader use.

### 4. Does it preserve RU/EN technical terms?

Transcript cleanup mostly preserves technical terms.

Term normalization covers target terms but is less stable stylistically.

Observed issue:

```text
term_normalization/simple can normalize terms correctly while drifting into English phrasing.
```

### 5. Does term_normalization/simple produce natural text?

Not reliably enough for user-facing exposure.

```text
E2B: 1/3 language-preserving natural outputs
E4B: 2/3 language-preserving natural outputs
```

Conclusion:

```text
term_normalization/simple remains advanced/operator-only and disabled by default.
```

### 6. Is E2B enough as default?

Not confirmed by L3.24 raw quality.

E2B is fast and validation-stable, but for transcript cleanup it often behaves like a no-op.

Use E2B as:

- lightweight fallback;
- latency/resource candidate;
- possible minimal-cleanup mode after explicit product decision.

Do not claim E2B is the quality default based only on L3.22 validation reliability.

### 7. Is E4B meaningfully better?

Yes for raw transcript-cleanup quality in this slice.

E4B is slower but more likely to produce visible readability improvement.

Timing in this local run:

```text
E2B average latency: ~793 ms
E4B average latency: ~999 ms
```

Recommendation:

```text
Use E4B as the hidden/dev transcript-cleanup candidate when quality matters.
Keep E2B as fallback and future resource-review candidate.
```

### 8. Is retry1 necessary?

No.

This L3.24 run used:

```text
retry_policy: off
```

and passed:

```text
20/20
```

Retry1 should remain optional only for malformed JSON/schema failures. It should not mask semantic quality problems.

### 9. Which mode can move into host app first?

Only:

```text
transcript_cleanup/simple
```

and only as hidden/dev integration, not public UI.

Do not expose yet:

- term normalization to normal users;
- model family selector;
- raw validator internals;
- blocks;
- paragraphing;
- complex schema;
- 12B;
- 26B;
- Qwen model family;
- image live;
- throughput;
- parallel;
- session/warmup.

## Product default recommendation after L3.24

L3.23 default was E2B unless raw review says otherwise.

L3.24 raw review says otherwise for quality:

```text
quality candidate: google/gemma-4-e4b
lightweight fallback: google/gemma-4-e2b
mode: transcript_cleanup/simple
schema: simple
prompt_variant: strict_no_new_facts_v2
context_tier: 8192
retry_policy: off
fallback: original text
```

This is a hidden/dev recommendation, not a user-facing release decision.

## Stop-condition review

No stop condition was triggered:

- raw pack was outside repo;
- raw private transcripts were not committed;
- no repeated factual additions were observed;
- no blocked mode was required;
- privacy audit passed in the final gate.

## Definition of done status

```text
local-only raw-output review pack exists outside repo: yes
quality review summary committed: yes
integration adapter plan committed: yes
product recommendation confirmed or changed: changed to E4B for hidden/dev quality
raw outputs/prompts/transcripts committed: no
repo clean and pushed: verified after commit
```
