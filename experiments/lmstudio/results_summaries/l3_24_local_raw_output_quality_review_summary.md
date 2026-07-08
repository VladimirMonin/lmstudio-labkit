# L3.24 — Local Raw-Output Quality Review Summary

## Status

L3.24 performed a local-only raw-output quality review for the accepted simple postprocessing lane.

This is not a broad model matrix and not a product integration commit.

## Scope

Reviewed scope:

- models:
  - `google/gemma-4-e2b`
  - `google/gemma-4-e4b`
- modes:
  - `transcript_cleanup/simple + strict_no_new_facts`
  - `term_normalization/simple + term_glossary`
- context tier: `8192`
- execution: `cold_per_request`
- cache: `none`
- parallel: `1`
- retry policy: `off`
- attempts: `20`

Task mix:

- transcript cleanup: 7 synthetic realistic ASR-like snippets x 2 models = 14 attempts;
- term normalization: 3 synthetic realistic ASR-like snippets x 2 models = 6 attempts.

Forbidden axes were not included:

- blocks;
- paragraphing;
- complex schema;
- 12B;
- 26B;
- Qwen as a model family;
- image live;
- throughput;
- parallel;
- session/warmup;
- overnight/stress;
- `/v1/responses`;
- route matrix.

## Run result

Sanitized validation result:

```text
attempt_count: 20
pass_count: 20
fail_count: 0
pass_rate: 1.0
retry_policy: off
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

Lifecycle stayed inside the accepted L3.22/L3.23 shape:

```text
load_scope: per_request
cleanup_scope: per_request
final_loaded_instances: 0
session_cleanup_verified: true
```

## Local-only raw review boundary

Raw prompts and raw responses were captured only in a local-only review pack outside the repository.

They are not committed.

Committed artifacts contain only sanitized conclusions, counts, and review decisions.

## Manual quality review answers

### 1. Does transcript cleanup preserve meaning?

Yes in this local sample.

Both E2B and E4B preserved the intended meaning across all transcript-cleanup cases reviewed:

```text
E2B: 7/7 meaning preserved
E4B: 7/7 meaning preserved
```

No case showed an obvious new factual claim in transcript-cleanup mode.

### 2. Does transcript cleanup remove or soften ASR noise?

This is where validation and human review diverge.

```text
E2B: 0/7 visibly improved readability
E4B: 5/7 visibly improved readability
```

E2B mostly returned near-identity text. That is safe but not a useful transcript-cleanup product experience.

E4B more often added punctuation, capitalization, and light readability cleanup while preserving meaning.

Conclusion:

```text
E2B is not confirmed as the product default by raw-output quality.
E4B is the better transcript-cleanup candidate in this L3.24 human review slice.
```

### 3. Does it avoid adding facts?

No obvious factual additions were found in the reviewed transcript-cleanup outputs.

However, this sample is still small and synthetic. It supports a hidden/dev adapter, not a broad user-facing release.

### 4. Does term normalization preserve natural Russian text?

Not reliably enough yet.

Term normalization passed validators, but raw review found language drift:

```text
E2B: 1/3 language-preserving natural outputs
E4B: 2/3 language-preserving natural outputs
```

Observed issue class:

- some outputs normalize terms correctly but drift into English phrasing;
- one E4B case preserved most Russian text but still introduced an English common word where Russian was expected.

Conclusion:

```text
term_normalization/simple remains a controlled developer/operator mode only.
It should not be exposed as a user-facing product feature until language-preservation checks are stronger.
```

### 5. Are warnings useful or noisy?

Warnings were not useful in the raw outputs reviewed.

```text
warnings were empty in reviewed raw responses
```

The existing public validation warnings are useful for developers, but model-generated user-facing warnings should not be shown directly yet.

### 6. Which model is preferable by human review?

Validation remains tied:

```text
E2B: 10/10 pass
E4B: 10/10 pass
```

Human raw-output review is not tied:

- E4B is preferable for transcript cleanup quality;
- E2B is faster and safer-looking, but often too close to identity output;
- E2B should not be selected as the user-facing default solely because it tied E4B on validation in L3.22/L3.23.

Timing in this local slice:

```text
E2B average latency: ~793 ms
E4B average latency: ~999 ms
```

Recommendation:

```text
For hidden/dev transcript-cleanup integration, prefer E4B when readability improvement matters.
Keep E2B as a lightweight fallback or candidate for a stricter minimal-cleanup mode.
Do not expose term normalization to users yet.
```

## Updated product decision after L3.24

L3.22/L3.23 proved validation reliability for the simple lane.

L3.24 adds raw prose quality evidence and changes the integration recommendation:

| Direction | L3.24 status |
|---|---|
| `transcript_cleanup/simple` | still the main product direction |
| `google/gemma-4-e4b` | preferred hidden/dev cleanup candidate by raw quality |
| `google/gemma-4-e2b` | lightweight fallback; not confirmed as quality default |
| `term_normalization/simple` | controlled/dev-only; needs stronger language-preservation gate |
| retry1 | not needed by this slice |
| blocked modes | still blocked |

## Acceptance conclusion

L3.24 is acceptable as a quality review and adapter-planning stage, but it should not trigger direct user-facing integration.

Next recommended step:

```text
L3.25 — Prompt/Validator Tightening for Simple Postprocessing
```

Focus:

- make transcript-cleanup prompts require visible but conservative readability cleanup;
- add a diagnostic for identity/no-op cleanup when ASR noise is present;
- strengthen term-normalization language preservation;
- then rerun a small local raw review before host-app prototype.
