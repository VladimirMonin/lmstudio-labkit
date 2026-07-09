# L3.25 Canary Decision Record

## Verdict

L3.25 canary is accepted for infrastructure and transcript-cleanup readiness, but not for promoting term-normalization to a product lane.

## Accepted next lane

Proceed only to L3.26 `transcript_cleanup/simple` benchmark after owner approval.

## Not accepted

Do not promote `term_normalization/simple` as a user-facing/product lane. It remains controlled/dev-only.

## Evidence

- Live canary attempts: 6.
- Pass/fail: 5/1.
- E4B: 3/3 pass.
- E2B: 2/3 pass; one term-normalization row failed via Markdown fence leakage.
- Near-identity warnings: 0.
- Language-drift detections: 0.
- Raw review pack: `/tmp/labkit-l325-raw-review-pack`, local-only, metadata sampled cases with `raw_case_count=0` because raw prompt/response persistence is disabled for publication safety.
- Public sanitized snapshot: `docs/live_demo/latest_prompt_tightening_canary/`.

## Non-claims

- No broad benchmark was run.
- No 12B/26B/Qwen model, image live, blocks, paragraphing, complex schema, throughput, parallel, session/warmup, overnight/stress, `/v1/responses`, or route matrix was run.
- No raw prompts/responses/private transcripts were committed.
