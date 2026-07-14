# Local Structured Request Integration Analysis Plan

Status: ACTIVE PLAN

## Goal

Produce an evidence-backed, publication-safe architecture recommendation for reusing LM Studio LabKit structured-output capabilities in a host desktop application across text cleanup, short and long microphone postprocessing, file/media postprocessing, summaries, and image analysis.

## Primary workdir and boundaries

```text
PRIMARY WORKDIR: repository root
BOARD: lmstudio-labkit
EXTERNAL SOURCE: host-application repository
ACCESS: read-only source/tests/docs
MAY EDIT: this plan; unique analysis reports under experiments/lmstudio/results_summaries/; one final strategy document under docs/
READ ONLY: existing LabKit evidence/code/tests; external host-application code/tests/docs
MUST NOT EDIT: external source repository; runtime behavior; prompts; credentials; private artifacts
OUTPUT / EVIDENCE: publication-safe Markdown+JSON reports and final strategy document
```

## Approved stage

Read-only architecture and evidence analysis. No live inference, model loading, downloads, cloud calls, benchmark reruns, implementation, commits, or pushes.

## Evidence questions

1. Which current host-application request paths already use API-bound JSON Schema, and which still rely on plain text or prompt-only JSON?
2. Which LabKit modules are genuinely reusable as a package rather than experiment-only scaffolding?
3. What structured request contract should be used for:
   - short microphone cleanup;
   - long microphone/file cleanup split into chunks;
   - per-chunk and whole-recording summaries;
   - image analysis and OCR-like extraction;
   - generic postprocessing of existing text?
4. When should context be current-only, boundary-neighbor, adjacent-chunk, or full-recording?
5. Which IDs, timestamps, ordering, protected values, retries, fallbacks, and persistence state must remain application-owned?
6. What gaps block a safe migration, and which are transport, schema, validation, product, or evidence gaps?

## Stages

### Stage 1 — Parallel evidence inventory

Produce four independent Markdown+JSON report pairs:

1. Current request-flow inventory.
2. LabKit reusable-package and integration-seam assessment.
3. Task-specific context and schema policy.
4. Validation, retry, fallback, persistence, and migration-risk analysis.

### Stage 2 — Red-team

Attempt to falsify the four reports. Classify claims as confirmed, overstated, unsupported, or contradicted. No implementation.

### Stage 3 — Synthesis

Create `docs/local_structured_request_integration_strategy.md` with:

- current-state map;
- target contracts per task;
- context policy matrix;
- package reuse recommendation;
- phased migration plan;
- explicit non-goals and evidence gaps;
- concrete implementation cards proposed but not dispatched.

## Done conditions

- Four report pairs exist and JSON parses.
- Red-team report pair exists and identifies corrections.
- Final strategy cites the evidence reports and distinguishes transport, structure, semantics, product behavior, and unexecuted assumptions.
- Reports remain product-neutral and pass publication-safety checks.
- External source repository remains unmodified.
- No live/model/network activity occurs.

## Non-goals

- No production code changes.
- No prompt rewrites.
- No model admission or new live benchmark.
- No claim that schema validity proves semantic quality.
- No default full-transcript-per-chunk design.
- No commit or push without separate authorization.

## Stop conditions

Stop and return to the owner if the analysis requires a new live experiment, private prompt/raw transcript publication, source-application mutation, model download/load, or a material expansion beyond the listed request classes.
