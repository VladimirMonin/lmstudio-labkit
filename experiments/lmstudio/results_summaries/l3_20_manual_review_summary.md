# L3.20 Manual Review Summary

## Scope

A local-only review pack was exported from the offline tiny fake run:

```text
/tmp/labkit-review-pack
```

The review pack itself is not committed. It contains sanitized metadata samples and a rubric only; no raw live prompts/responses, secrets, or base URLs.

## Local-only pack contents

```text
README.md
sampled_cases.md
rubric.yaml
reviewer_notes.md
```

## Manual review status

No live model outputs were manually scored in L3.20 because L3.20 is an offline redesign slice.

The pack format is ready for L3.21 live pilot review. The intended rubric is:

- meaning_preserved: 0..2
- punctuation_quality: 0..2
- paragraphing_quality: 0..2
- term_handling: 0..2
- no_new_facts: 0..2

## Decision

Commit only this summary and the exporter/tests. Keep review packs local-only unless a future run creates an explicitly sanitized public summary.
