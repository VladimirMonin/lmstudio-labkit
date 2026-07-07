# S3 lmstudio_managed Bridge Readiness

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Evidence level: deterministic Lab/contract bridge checks, not live LM Studio proof
- Purpose: close S3 Lab-to-`lmstudio_managed` bridge work before S4 client design
- Non-goals: no HTTP client, no host application runtime integration, no `src/**`, no QueueManager/UI/SQLite/migrations, no live/GPU/model-matrix run

## S3 bridge inventory

| Slice | Bridge area | Status | Contract proof |
| --- | --- | --- | --- |
| S3.1 | Parallel semantics | ✅ done | Lab diagnostics use managed true-parallel / queue-pressure policy while preserving legacy artifact fields |
| S3.2 | Lifecycle policy | ✅ done | Lab lifecycle wrapper delegates to managed policy and keeps Lab legacy status names / safe hashes |
| S3.3 | Validation mapping | ✅ done | Lab categories continue to serialize as `reasoning`, `finish`, `json`, `schema`, `business`, `empty` while mapping through managed failure kinds |
| S3.4 | Metrics contracts | ✅ done | Lab metric records convert to managed request, batch and system summary DTOs without raw prompt/response fields |
| S3.5 | Registry/profile bridge | ✅ done | `candidates.yaml` payloads map to managed registry DTOs using safe `candidate_key`, `summary_ref` and evidence refs |
| S3.6 | Generation response envelope | ✅ done | Lab structured/concurrency paths derive safe hash/chars/token/finish fields via managed `GenerationResponseEnvelope` while preserving Lab tri-state artifact semantics |

## S3.6 acceptance details

S3.6 added a fake-first generation envelope bridge only. It does not add a real HTTP client.

Key guarantees:

- Managed `GenerationResponseEnvelope` contains only safe summary fields:
  - `content_empty`
  - `content_chars`
  - `content_hash`
  - `reasoning_content_present`
  - `finish_reason`
  - token counts
  - optional managed `error_kind`
- Raw provider content remains transient Lab-internal data for validation only.
- Lab artifacts keep legacy field names and values.
- Missing reasoning state remains tri-state in Lab artifacts: `None` is not normalized to `False` in metrics or structured errors.
- Empty content with reasoning present still maps to managed `REASONING_CONTENT_ONLY` while the Lab legacy category remains `empty`.

## Verification snapshot

Latest S3.6 QA gate passed with:

```text
tests/tools/test_lmstudio_lab_live_smoke.py: 97 passed
tests/libs/test_lmstudio_managed_s0_contracts.py
tests/libs/test_lmstudio_managed_s2_rest_contracts.py
tests/architecture/test_lmstudio_managed_boundaries.py: 48 passed
tests/architecture/test_import_boundaries.py: 5 passed
ruff check: passed
ruff format --check: passed
git diff --check: passed
```

No `src/**` changes were part of S3.1-S3.6 bridge work.

## Dependency boundary

Allowed direction:

```text
tools/lmstudio_lab -> libs/lmstudio_managed
```

Forbidden directions remain blocked:

```text
libs/lmstudio_managed -> tools/lmstudio_lab
libs/lmstudio_managed -> src/**
tools/lmstudio_lab -> host application runtime integration
```

## Privacy boundary

S3 bridge artifacts may contain safe metadata only:

- hashes
- char counts
- token counts
- timing fields
- boolean/tri-state validation flags
- safe category strings
- safe candidate/profile/evidence refs

They must not contain raw prompts, raw responses, messages, raw provider bodies, API keys, file paths, URLs, job IDs or instance IDs.

## S4 readiness

S3 is ready for S4 fake-first HTTP client work.

S4 must still begin without live/GPU requirements and without host application runtime wiring. The first S4 slice should stay inside `libs/lmstudio_managed` contracts/client tests and keep Lab integration fake-first until an explicit live conformance gate is approved.

Stop gates before S4 execution:

- real HTTP client boundary design must be explicit before implementation;
- any live LM Studio / GPU run requires explicit approval;
- host application runtime integration remains out of scope;
- QueueManager, UI, SQLite and migrations remain untouched;
- model matrix v2, vision, embeddings and cache remain deferred.
