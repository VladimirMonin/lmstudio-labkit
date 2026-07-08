# L3.22 — Next Matrix Recommendation

## Recommendation

Proceed toward product integration only for the simple postprocessing path.

Default candidate:

```text
transcript_cleanup/simple + strict_no_new_facts
```

Optional controlled candidate:

```text
term_normalization/simple + term_glossary
```

## Next gate

Add more realistic ASR-like fixtures and perform a local-only raw-output quality review. Keep public artifacts sanitized.

Keep excluded:

- blocks schema tasks until duplicate/missing id behavior is fixed;
- paragraphing hard gate until schema/policy redesign;
- 12B/26B/Qwen model families;
- image live;
- throughput/parallel;
- session/warmup.
