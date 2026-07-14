# Local Structured Request Integration Strategy

Date: 2026-07-13

Status: read-only architecture synthesis. This document proposes contracts and future work; it does not report implementation, live inference, model admission, migration readiness, or production acceptance.

Machine-readable companion: `experiments/lmstudio/results_summaries/2026-07-13_local_structured_request_integration_strategy.json`.

## Recommendation

The host application should migrate toward one host-owned structured-request control path, but it should not copy LabKit runners or treat LabKit recommendation records as runtime configuration.

The target boundary is:

```text
host task policy and approved model catalog
  -> host request/context mapper
  -> host async, cancellable transport and lifecycle adapters
  -> candidate LabKit contract kernel for pure DTO, parsing, schema, identity,
     lifecycle-policy, context-fit, and output-budget decisions
  -> host semantic decision, retry/fallback, persistence, export, and read-back
```

Five decisions govern the migration:

1. The host-owned approved model catalog is the only runtime selection authority. It must match exact model identity, explicit task capability, and explicit promotion state. LabKit registry and benchmark recommendations are non-promoting evidence inputs only.
2. API-bound JSON Schema is a server grammar constraint, not acceptance. Preserve separate transport, raw-parse, local-schema, business-identity, semantic-quality, and product-behavior outcomes.
3. Use compact generic block grammar plus exact application-side count, ID, uniqueness, and order checks. Do not use request-specific positional `const` grammar on the host path.
4. Treat the proposed dependency-light LabKit core and ports layout as a candidate architecture, not a stable package surface that already exists.
5. Keep all context defaults provisional at their actual evidence denominators. In particular, reject full-recording context repeated for every cleanup or chunk-summary request by default.

## Evidence and decision labels

- **Current:** verified by static source inspection.
- **Bounded evidence:** supported by retained executed artifacts within the stated denominator.
- **Proposed:** target architecture or policy without host end-to-end proof.
- **Blocked:** requires an explicit gate before implementation or rollout can be accepted.

The strategy incorporates all 11 corrections from the Stage-2 red-team. The red-team classified 37 claims as 19 confirmed, 11 overstated, 5 unsupported, and 2 contradicted.

## Current-state map

| Request class | Current request contract | Current post-response behavior | Migration consequence |
|---|---|---|---|
| Generic text postprocessing | Plain message text on compatibility chat completions; no API-bound response schema | Envelope extraction and thinking-tag cleanup only | Add a task contract only where deterministic structure or identity is required; preserve original text as application state |
| Short microphone cleanup | Plain text through the direct microphone coordinator | No JSON, identity, protected-value, or semantic acceptance | Current-only structured cleanup is proposed, not executed or audio-grounded |
| Long microphone or media cleanup | Independent character chunks in text mode, or block mode when stored blocks are available | Plain chunks are merged by request order; block mode parses JSON and checks missing IDs but tolerates other defects | Prefer identity-preserving blocks when available; fail closed on exact identity, order, type, boundary, and persistence |
| Block-preserving postprocessing | API-bound strict closed schema with `{blocks:[{id,text}]}` | Raw JSON parse plus partial ID coverage; bare arrays, type coercion, filtered extras, duplicates, and reorder defects are not all rejected | Harden application validation; do not mistake schema binding for full local schema validation |
| Per-chunk summary | Not implemented | Reserved storage is not a request or persistence owner | Define ownership, schema, provenance, persistence, and read-back before any live work |
| Whole-recording summary | Not implemented | Normal creation leaves the reserved summary field empty | Evaluate direct compact and hierarchical detailed candidates only after fake-client end-to-end contracts |
| Image analysis | API-bound strict closed schema over one image | Parser may repair truncated JSON, default missing fields, or normalize an unknown enum; no semantic grounding gate | Reject repaired/defaulted structure as acceptance and use multidimensional OCR/grounding outcomes with abstention or review |

All generation currently uses the OpenAI-compatible chat-completions namespace. Provider builders preserve a supplied response format, but payload plumbing is not proof that every configured provider or model accepts a schema at runtime. Native LM Studio routes remain lifecycle/health boundaries rather than generation evidence.

## Target ownership boundary

### Host-owned authority

The host application must own:

- approved model catalog, exact model identity, task capabilities, and explicit promotion state;
- prompts, source records, image materialization, IDs, timestamps, source order, and chunk assembly;
- request generation, cancellation, retry eligibility, total logical-call ceiling, and accepted attempt;
- protected values and placeholders;
- schema and validator versions;
- semantic thresholds, abstention, manual review, fallback, and user-visible status;
- persistence transaction or recovery protocol, export, and read-back;
- telemetry retention and identifier/digest threat model.

Model-authored IDs are echoes to validate, never authority. Timestamps and persistence keys stay outside model output.

### Candidate LabKit contract kernel

A future dependency-light package surface may contain only pure contracts and decisions:

- sanitized interchange DTOs;
- structural response-contract fields;
- strict JSON parsing with separately reported bounded normalization;
- compact generic schema builders;
- exact ID/count/order validators;
- an explicitly complete validator or a fail-closed tested schema-keyword allow-list;
- pure lifecycle ownership/compatibility decisions;
- relocated context-fit decisions;
- bounded output-budget observations and decisions;
- protocols for host-implemented transport and lifecycle execution.

This surface does not exist as a stable supported kernel today. Current DTO metadata emits some identifiers verbatim, `ResponseContract` mixes structural and lab semantic policy, pure utilities are split across repository-layout namespaces, and the top-level facade is broad. Extraction, sanitization, import-boundary tests, and a fake host compatibility test are prerequisites.

### Excluded from host runtime

Do not migrate or embed:

- benchmark, matrix, dataset, artifact, report, review-pack, and CLI orchestration;
- strict-vision launch/continuation controllers, fixture allowlists, private capture, or global-zero assumptions;
- the LabKit local host runner or fake-first generation client as product transport;
- candidate intake, recommendation drafts, or lab admission state as runtime model configuration;
- cache experiments as proof of product cache reuse;
- failure-forensics retention policy;
- benchmark-report consumption adapters as request execution seams.

## Layered acceptance contract

Every logical request must retain six independent outcomes:

1. **Transport:** route, typed transport category, cancellation, final response surface, finish reason, usage, and output-cap state.
2. **Raw parse:** untouched JSON parse result; any bounded fence normalization is recorded separately and is not raw success.
3. **Schema:** full closed-schema validation by a complete validator or a fail-closed tested keyword allow-list.
4. **Business identity:** exact target count, unique expected ID sequence, strict non-empty strings, and target/reference separation.
5. **Semantic quality:** completeness, grounding, protected-value preservation, boundary ownership, and unsupported additions.
6. **Product behavior:** retry, fallback, stale-completion fencing, persistence, export, read-back, rollback, and visible degraded/review state.

A later implementation must not collapse these into one `accepted` flag. Schema validity does not prove semantic quality, and semantic quality does not prove safe persistence or rollback.

## Target contracts by task

The response shapes below are target shapes. Summary and generic-text schemas are illustrative and unexecuted; their exact limits and field policy remain product decisions.

### Short microphone cleanup

- **Proposed context:** current capture only.
- **Response shape:** `{text: string}` for a self-contained capture, or the generic block shape if the application has already established block identity.
- **Host-owned state:** recording identity, raw transcription, timing, protected values, request generation, and fallback.
- **Acceptance:** all six layers, including audio-grounded semantic review criteria that do not yet exist.
- **Evidence boundary:** no retained structured, audio-grounded short-microphone execution; this is a scope-consistent proposal only.

### Long microphone or file cleanup

- **Proposed context:** current target blocks plus previous-tail and next-head blocks as reference-only context.
- **Response shape:** `{blocks:[{id: integer, text: string}]}` for target blocks only.
- **Grammar rule:** compact generic array item schema; no request-specific positional `const` values.
- **Host-owned state:** exact target sequence, reference/target roles, timestamps, merge order, source range, protected values, and immutable original blocks.
- **Acceptance:** exact count, uniqueness, sequence, strict strings, no reference-block output, no omission/addition/boundary leakage, then atomic persistence/read-back.
- **Evidence boundary:** provisional result from 12 cleanup calls, 36 evaluated blocks, three representative positions, one recording, and one model; no complete source-to-persistence run.

### Per-chunk summary

- **Proposed context:** current chunk only; boundary context only as a targeted fallback for an interrupted thought.
- **Illustrative shape:** `{summary: string, key_points: string[], uncertainties: string[]}` with bounded list and string lengths.
- **Host-owned state:** recording/chunk identity, ordinal, source range, timestamps, and provenance.
- **Acceptance:** summary scope, source support, omission/addition policy, and persistence/read-back in addition to structural gates.
- **Evidence boundary:** current-only produced 35/35 practically valid structured outputs in one recording/model study; the host summary feature does not exist.

### Whole-recording summary

- **Candidate A:** one full-recording request for a compact overview when exact token fit is safe.
- **Candidate B:** ordered current-only chunk summaries followed by hierarchical synthesis for detailed chronological output.
- **Illustrative shape:** `{overview: string, key_points: string[], open_questions: string[]}`.
- **Host-owned state:** recording identity, chunk order, source mapping, synthesis provenance, and staleness/version state.
- **Acceptance:** source coverage and provenance plus atomic persistence/read-back. Failed summaries remain unavailable; they are not replaced by a model guess.
- **Evidence boundary:** five first-pass and five repeat whole-summary calls on one recording; no blind scoring or host request/persistence owner.

### Generic existing-text postprocessing

- **Proposed context heuristic:** current-only for a self-contained target; boundary neighbors for an identity-preserving chunked transform; a single full-document request only when the task itself is document-level and fits safely.
- **Response shape:** illustrative `{text: string}` for a self-contained target; use block identity for chunked or persistence-sensitive work.
- **Acceptance:** task-specific protected-value, completeness, and boundary validators.
- **Evidence boundary:** the context heuristic is extrapolated from speech-derived evidence; no generic-document comparison establishes its quality.

### Image analysis

- **Context:** current image and explicit image task only.
- **Response shape:** a task-specific closed schema such as `{description, extracted_text, language, scene_type}`; add object arrays only when their open-world evaluation is defined.
- **Host-owned state:** image identity, dimensions, persistence key, source/request/schema digests, and retry state.
- **Acceptance:** reject repaired/defaulted structural failures; evaluate visible-text exactness, salient-text completeness, object grounding/completeness, unsupported claims, warning relevance, forbidden private/person claims, and scene/language classification separately. Use `abstain` or `review_required` when no valid threshold exists.
- **Evidence boundary:** 40/40 authorized calls had no transport error; 36/36 applicable calls passed raw JSON and independent schema checks, while manual semantic dimensions remained mixed. This grants no model ranking or production admission.

## Context policy matrix

| Task | Proposed default | Alternatives | Explicit default rejection | Evidence status |
|---|---|---|---|---|
| Short microphone cleanup | Current-only | Block identity only if already split | Adjacent/full context that is not the actual target | Proposed; no structured audio-grounded run |
| Long microphone/file cleanup | Boundary neighbors as reference-only | Current-only conservative alternative | Adjacent chunks and full recording per chunk | Provisional: 12 calls, 36 blocks, three positions, one recording/model |
| Per-chunk summary | Current-only | Boundary fallback for an interrupted thought | Adjacent or full-recording context per chunk | Bounded: 35/35 current-only practical validity on one recording/model |
| Whole-recording summary | One direct full request for compact output, or hierarchical synthesis for detailed output | Product must choose by output contract and exact fit | Repeating the full recording for every chunk | Candidate: five first-pass plus five repeat calls on one recording |
| Generic text | Current-only when self-contained; boundary neighbors when identity-preserving and chunked | One full request for a true document-level task | Full document repeated per chunk | Proposed extrapolation; no generic-document study |
| Image analysis | Current image only | Future multi-image context requires a separate relation contract | Transcript-neighbor context by analogy | Bounded transport/schema evidence on four fixtures; no semantic admission |

In the retained chunk-summary study, current-only used a median 786 prompt tokens and 8.04 seconds, while full-recording-per-chunk used 23,099 prompt tokens and 20.20 seconds. Across 35 calls the approximate totals were 26,700 versus 807,600 prompt tokens and 274.9 versus 700.7 seconds. These data support rejecting repeated full context as the default, not banning one full input for a true whole-recording task.

## Package reuse decision

| Area | Decision | Gate |
|---|---|---|
| Strict JSON parser and parse-stage vocabulary | Extract/adapt | Default strict mode; normalization separately observable |
| Exact count/ID/order collection and validation | Extract/adapt | Target-path tests and strict type/non-empty checks |
| Generic flat/block schema builders | Extract/adapt | Exclude positional `hardened_const`; test every accepted keyword |
| Request/result DTO shapes | Extract/adapt, not direct telemetry reuse | Sanitize or replace host identifiers before telemetry |
| Structural subset of `ResponseContract` | Extract/adapt | Separate structural fields from lab semantic/review policy |
| Full schema validation | Add a complete host-approved implementation or fail-closed allow-list | Adversarial tests for every accepted schema |
| Lifecycle, context-fit, output-budget decisions | Relocate/adapt | Stable core namespace and fake host compatibility test |
| Managed executors, clients, registry, cache, and vision concepts | Reuse through host adapters only | Async cancellation, ownership, exact catalog mapping, real body materialization |
| Lab orchestration and forensic machinery | Exclude | No host runtime dependency |

The dependency direction remains one-way: host application to package contracts. LabKit must not import host code, prompts, field names, persistence types, or product policy.

## Phased implementation plan

These phases are proposed and have not been authorized or executed.

### Phase 0 — Freeze authority and contracts

- Define the host-owned approved model catalog and exact identity/capability/promotion rules.
- Version task contracts and define approved schema keywords.
- Define telemetry identifier and digest retention policy.
- Preserve original source and six-layer outcome vocabulary.

Exit gate: exact-identity lookup, unsupported-task rejection, unknown-model fail-closed behavior, and no automatic promotion from LabKit evidence are covered offline.

### Phase 1 — Extract the candidate contract kernel

- Create a dependency-light core and protocols-only ports surface.
- Sanitize DTO metadata and split structural response fields from lab semantic policy.
- Include strict parsing, generic schemas, exact identity checks, lifecycle decisions, context fit, and output-budget decisions only after relocation review.
- Keep all lab controllers and reports outside the runtime dependency.

Exit gate: clean install/import in a fake host, import-boundary tests, schema-keyword tests, and no host reverse import.

### Phase 2 — Build host control and validation seams

- Implement host-native async/cancellable structured transport and lifecycle adapters.
- Add immutable attempts, request-generation fencing, one product-defined total logical-call ceiling, and pre-commit cancellation checks.
- Add full local schema validation, exact identity/order/type validation, and categorical semantic outcomes.
- Add transactional persistence or explicit pending/committed recovery with export and read-back.

Exit gate: adversarial fake-client and failure-injection tests close red-team blockers B4-B8 and B12. Rollback is not configuration-driven before this gate.

### Phase 3 — Harden current structured paths

- Make current block handling fail closed for bare arrays, duplicate/extra/reordered IDs, wrong types, empty text, and reference-target leakage.
- Make image handling reject repaired/defaulted structure as success and expose multidimensional review/abstention.
- Preserve original values and degraded state without reporting fallback as model success.

Exit gate: end-to-end fake transport-to-read-back tests for block and image paths. No live model call is implied.

### Phase 4 — Add new task contracts offline

- Add short structured cleanup, long block cleanup, per-chunk summary, direct whole summary, hierarchical summary, and generic text as separate contracts.
- Keep context policies provisional and task-specific.
- Establish deterministic protected-value, boundary, source-coverage, and provenance fixtures.

Exit gate: each contract independently passes fake-client request, validation, retry/fallback, cancellation, persistence, export, and read-back tests.

### Phase 5 — Separately authorize evidence collection

Shadow, read-only comparison, canary, and broader rollout are proposals only. Each requires separate authorization, privacy-safe instrumentation, task-specific thresholds, a kill switch, runtime safety, and evidence review. A successful task or model does not admit another task or model.

## Proposed implementation cards — not created or dispatched

1. **Define approved model catalog authority** — exact identity, task capability, explicit promotion, unknown-model rejection, and evidence-only LabKit imports.
2. **Extract dependency-light contract kernel** — package topology, sanitized DTO metadata, structural contract split, and boundary tests.
3. **Select and verify schema validation policy** — complete validator or fail-closed keyword allow-list with adversarial schema fixtures.
4. **Implement exact block acceptance** — object-only response, strict strings, exact count/sequence/uniqueness, reference separation, and original-value fallback.
5. **Implement request attempt and cancellation fencing** — immutable attempts, total logical-call ceiling, stale-completion rejection, and pre-commit checks.
6. **Make persistence acceptance atomic or recoverable** — aggregate/block/attempt state, failure injection, export, and exact read-back.
7. **Define task semantic validators** — protected values, omission/addition, boundary leakage, summary coverage, and explicit abstain/review dispositions.
8. **Harden image structural and semantic outcomes** — no repaired/defaulted success; separate OCR, grounding, completeness, unsupported-claim, and review states.
9. **Add summary ownership and provenance contracts** — direct and hierarchical schemas, bounded fields, staleness, persistence, and read-back.
10. **Add fake host adapter compatibility suite** — async cancellation, transport surface, lifecycle ownership, schema wrappers, model catalog mapping, and privacy-safe metrics.
11. **Design contract-specific kill switches and rollback state** — version readability, traceable accepted attempt, generation invalidation, and rollback tests.
12. **Prepare separately authorized shadow evidence plan** — task-specific denominators, manual review rubric, privacy audit, and explicit no-write behavior.

These are planning records only. They are deliberately non-runnable in this stage and do not authorize implementation, external-repository edits, live inference, model operations, network calls, commits, or pushes.

## Mission blockers and evidence gaps

Before migration can be claimed safe, close all of the following:

- no stable dependency-light package core or host install proof;
- unsafe direct telemetry reuse of verbatim request/cell/expected IDs;
- positional-const grammar conflict, resolved in strategy by excluding it;
- no full local production schema validator or proven fail-closed allow-list;
- tolerant block defects that do not all fail closed;
- no immutable attempts, request-generation fence, or total logical-call ceiling;
- no atomic/recoverable aggregate-plus-block persistence, export, or read-back proof;
- no production thresholds/fixtures for protected values, boundaries, omissions, or unsupported additions;
- tolerant image structure and no valid binary semantic-admission rubric;
- no summary owner, exact final schemas, provenance, persistence, or read-back;
- narrow context evidence: one recording/model for task-specific text and no audio-grounded short-microphone truth;
- no kill switches, readable validator state, or rollback traceability;
- no host-owned approved model catalog mapping configured model strings to exact identity, task capability, and promotion state.

Additional evidence gaps include real cancellation races, partial-persistence recovery, production concurrency, broad OCR or summary quality, cross-task model admission, generic-document context comparisons, and physical cache reuse with changing chunks.

## Non-goals and non-claims

This strategy does not:

- implement or migrate any request path;
- modify prompts or define private prompt content;
- select, rank, promote, download, load, or call a model;
- authorize cloud, network, shadow, canary, or benchmark work;
- claim that schema validity proves semantics or product behavior;
- claim audio-grounded cleanup, broad OCR accuracy, summary quality, concurrency safety, cache reuse, or production readiness;
- claim rollback is configuration-only today;
- claim the package core, adapters, validators, state machine, persistence transaction, or catalog already exist;
- authorize external-repository edits, commit, or push.

## Evidence sources

Stage-1 reports:

- `experiments/lmstudio/results_summaries/2026-07-13_host_request_flow_inventory.md`
- `experiments/lmstudio/results_summaries/2026-07-13_labkit_package_reuse_assessment.md`
- `experiments/lmstudio/results_summaries/2026-07-13_task_specific_context_schema_policy.md`
- `experiments/lmstudio/results_summaries/2026-07-13_structured_validation_migration_risks.md`

Stage-2 correction authority:

- `experiments/lmstudio/results_summaries/2026-07-13_local_structured_integration_red_team.md`

Each report has a same-stem JSON companion. This synthesis preserves their static and bounded executed evidence boundaries and does not promote them to host end-to-end proof.
