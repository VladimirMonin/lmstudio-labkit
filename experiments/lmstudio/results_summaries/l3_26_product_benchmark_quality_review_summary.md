# L3.26 Product Benchmark Quality Review Summary

## Scope

Sanitized product benchmark review for `transcript_cleanup/simple` only.

- Models: `google/gemma-4-e2b`, `google/gemma-4-e4b`.
- Prompt: `strict_no_new_facts_v2`.
- Context: 8192.
- Retry: off.
- Execution: cold per request.
- Main run: 10 public-safe synthetic ASR-like snippets × 2 models × 3 repeats = 60 attempts.

## Infrastructure result

| Metric | Value |
|---|---:|
| attempt_count | 60 |
| pass_count | 60 |
| fail_count | 0 |
| pass_rate | 1.0 |
| json/schema hard failures | 0 |
| near_identity_warning_count | 0 |
| final_loaded_instances | 0 per cell |
| raw prompt/response committed | 0 |

## Per-model sanitized metrics

| model | attempts | pass | fail | near_identity | near_identity_rate | median_latency_ms | p95_latency_ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| gemma4_e2b | 30 | 30 | 0 | 0 | 0.0 | 2801.683 | 3031.507 |
| gemma4_e4b | 30 | 30 | 0 | 0 | 0.0 | 3806.866 | 4373.885 |

## Raw-output review limitation

A local-only review pack was exported to:

```text
/tmp/labkit-l326-raw-output-review-pack
```

However, `raw_case_count=0` because the benchmark safety config keeps raw prompt/response persistence disabled. The committed review is therefore based on sanitized artifacts, validation metadata, latency, and near-identity diagnostics. It is not a full human raw-prose quality review.

This is intentional publication safety: raw prompts/responses/private transcripts were not committed and were not written inside the repository.

## Rubric status

The full human rubric could not be scored from raw prose in this run:

| Rubric item | Status |
|---|---|
| meaning_preserved | deferred to future local raw-prose review |
| asr_noise_reduced | partially covered by diagnostics; no raw prose score |
| no_new_facts | validator/prompt gate only; no raw prose score |
| term_handling | partially covered by fixtures/technical terms; no raw prose score |
| naturalness | deferred to future local raw-prose review |
| style_overediting | deferred to future local raw-prose review |
| overall_acceptability | deferred to future local raw-prose review |

## Quality interpretation

- Both models passed the 60-attempt infrastructure and schema gate.
- Near-identity warning rate was 0 for both models on this benchmark slice.
- E2B was faster in this run: median latency about 2801.683 ms vs E4B about 3806.866 ms.
- This benchmark does not prove E4B prose superiority because raw prose review was not available in committed artifacts.
- Prior L3.24 raw review still supports E4B as the quality candidate; L3.26 supports E2B as a strong lightweight fallback on reliability/latency.
