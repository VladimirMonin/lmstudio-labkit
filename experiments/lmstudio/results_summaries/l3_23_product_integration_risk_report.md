# L3.23 — Product Integration Risk Report

## Status

L3.23 is an integration-readiness stage for the L3.22 accepted simple postprocessing path.

It does not add new live matrix evidence and does not promote blocked modes.

## Accepted risks

### Validation-only quality evidence

L3.22 proves contract reliability for the selected simple modes, but raw-output prose quality remains a local-only review item.

Accepted mitigation:

- start with developer/operator-facing integration;
- keep a manual review requirement before user-visible release;
- do not commit raw outputs.

### Small local model behavior

E2B/E4B passed the selected simple matrix, but small local models may still over-edit, under-edit, or miss subtle transcript meaning in real data.

Accepted mitigation:

- fallback to original text on validation failure;
- expose postprocessing as assistive cleanup, not as authoritative correction;
- keep blocked modes out of user-facing UI.

### Diagnostic warnings

Punctuation and manual-review warnings are expected in the accepted contract.

Accepted mitigation:

- keep warnings in developer logs or structured result metadata;
- do not show noisy technical warnings to end users by default.

## Blocked modes

Keep blocked:

- blocks schema tasks;
- paragraphing hard gate;
- complex schema;
- 12B / 26B / Qwen model families;
- image live;
- throughput and parallel modes;
- session/warmup modes;
- overnight/stress runs.

Reasons:

- blocks schema previously showed duplicate/missing id behavior;
- paragraphing hard gate is not reliable under the current simple contract;
- stronger or different model families were not accepted by L3.22;
- performance/session/image claims were not tested in this product-like slice.

## Recommended defaults

### Default mode

```text
mode: transcript_cleanup
prompt_variant: strict_no_new_facts
schema: simple
model: google/gemma-4-e2b
context_tier: 8192
retry_policy: off
```

### Optional controlled mode

```text
mode: term_normalization
prompt_variant: term_glossary
schema: simple
model: google/gemma-4-e2b
context_tier: 8192
retry_policy: off
```

### Alternative model

```text
google/gemma-4-e4b
```

Use only if a later local raw-output quality or resource review justifies it. L3.22 validation quality does not justify E4B over E2B.

## Open questions

1. Does transcript cleanup preserve meaning across real host-application transcripts?
2. Does it remove ASR noise without over-editing style?
3. Are warnings useful enough for operator logs?
4. Should retry1 be enabled only for JSON/schema failures?
5. What latency budget is acceptable for interactive use?
6. Should term normalization require an explicit user toggle or glossary preview?

## What not to expose to users yet

Do not expose:

- blocks output mode;
- paragraph splitting mode;
- complex schemas;
- model family selector beyond accepted E2B/E4B candidates;
- Qwen/12B/26B options;
- image postprocessing;
- throughput or parallel tuning controls;
- session/warmup controls;
- raw validator internals.

## Fallback requirements

If postprocessing fails validation:

1. return original text;
2. include a safe warning such as `postprocessing_failed_validation`;
3. log sanitized failure category;
4. do not return invalid JSON;
5. do not expose raw prompt/response or backend details.

## Privacy requirements

Never commit or publish:

- raw prompts;
- raw model responses;
- user transcripts;
- base URLs;
- host names;
- tokens or credentials;
- private local paths.

Public artifacts may include only sanitized metrics, validation summaries, schemas, configs, and decision records.

## Integration recommendation

Proceed to a narrow host-application integration prototype for `transcript_cleanup/simple` only.

Keep `term_normalization/simple` as an optional controlled mode.

Do not broaden model/task scope until a local raw-output human review confirms quality on realistic transcripts.
