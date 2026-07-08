# L3.22 — Manual Review Summary

## Status

Local-only review pack exported:

```text
/tmp/labkit-l322-review-pack
```

It is not committed. This summary uses sanitized validation metadata only.

## Outputs that look product-useful

The validation metadata supports `transcript_cleanup/simple` as the strongest product-like candidate. It passed all rows across E2B/E4B, retry off/retry1, and five repeats per paired task.

`term_normalization/simple` also passed all rows and is useful as a controlled glossary/noisy-term mode.

## Acceptable failures for small local models

None occurred in this bounded main run:

- fail_count: 0
- hard_fail_count: 0

Diagnostic warnings remain expected for punctuation/filler/manual-review categories and should not be interpreted as hard product failures.

## Default candidate

Recommended product default candidate:

```text
transcript_cleanup/simple + strict_no_new_facts
```

Recommended optional mode:

```text
term_normalization/simple + term_glossary
```

## E2B vs E4B

No meaningful difference in this validation-only gate:

- E2B: 40/40 pass
- E4B: 40/40 pass

E4B is not better enough to matter based on this run alone.

## Boundary

This does not judge raw prose aesthetics because raw outputs are not committed. A future local-only human quality review can inspect raw outputs without publishing them.
