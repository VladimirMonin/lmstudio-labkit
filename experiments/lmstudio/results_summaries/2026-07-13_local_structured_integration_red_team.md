# Local structured integration red-team

Date: 2026-07-13

Status: read-only Stage-2 red-team. No live request, model operation, network request, implementation, prompt change, external-repository change, commit, or push was performed.

Machine-readable companion: `2026-07-13_local_structured_integration_red_team.json`.

## Decision

The four Stage-1 reports are directionally sound, but they mix verified current-state facts, bounded experiment decisions, and unexecuted target architecture. This review classified 37 material claims and recommendations: **19 confirmed, 11 overstated, 5 unsupported, and 2 contradicted**.

Two contradictions must be corrected before synthesis:

1. The package-reuse report recommends direct reuse of a positional `hardened_const` block schema, while stronger executed evidence shows request-specific positional `const` grammar failed before generation on all four tested models. The validated route is compact generic grammar plus exact application-side count, ID, uniqueness, and order checks.
2. The migration-risk report calls rollback configuration-only, but the current system lacks the kill switch, durable request-generation fence, accepted-attempt traceability, and readable schema/validator versions that would make rollback configuration-driven.

A third cross-report correction is material: current LabKit DTO metadata is not automatically privacy-safe for host identifiers. `request_id`, `cell_id`, and `expected_ids` are emitted without hashing, so direct product telemetry reuse requires a sanitizing adapter.

## Verdict vocabulary

- **Confirmed:** current code or retained executed evidence supports the claim within its stated boundary.
- **Overstated:** the claim has a supported core but is broader, more direct, or more production-ready than the evidence permits.
- **Unsupported:** the claim is a plausible proposal or extrapolation without direct current-code or executed-evidence support.
- **Contradicted:** current code or stronger retained evidence conflicts with the claim.

## Evidence boundary

This review re-read the four report pairs, current LabKit request/schema/validation code, the retained structured-output, pipeline-fit, task-context, and vision-closure reports, and the host application's current block, image, queue, and persistence source paths. Source inspection is static evidence. Retained model denominators remain bounded evidence. Neither establishes product admission by itself.

## Host request-flow inventory

| ID | Verdict | Material claim or recommendation | Required correction |
|---|---|---|---|
| HF1 | **confirmed** | Block-preserving text and image analysis are the two current API-bound strict-schema classes. | Static source contract only; no provider or UI execution. |
| HF2 | **confirmed** | Generic, microphone, and media text-mode cleanup accept plain text without structural or semantic acceptance. | Envelope extraction and thinking-tag cleanup are not task validation. |
| HF3 | **confirmed** | Per-chunk and whole-recording summaries are not implemented although summary storage exists. | Reserved storage is not a request, synthesis, update, or read-back owner. |
| HF4 | **confirmed** | Provider builders preserve supplied response format and generation uses compatibility chat completions. | Payload plumbing does not prove runtime provider acceptance. |
| HF5 | **confirmed** | The block parser accepts bare arrays, coerces text, filters extras, and does not reject duplicates or order defects. | `json_schema=true` means API binding, not local full-schema validation. |
| HF6 | **confirmed** | The image parser can recover truncated JSON, default required fields, and normalize unknown scene type. | These are tolerant parser outcomes, not schema or semantic success. |
| HF7 | **confirmed** | IDs/timestamps remain application-owned; aggregate and per-block persistence are separate. | Do not infer atomicity, fallback labeling, accepted-attempt traceability, export, or read-back. |

## LabKit package reuse assessment

| ID | Verdict | Material claim or recommendation | Required correction |
|---|---|---|---|
| PK1 | **confirmed** | Dependency direction must remain host to LabKit with host-owned adapters and no reverse import. | This boundary does not prove that a stable kernel already exists. |
| PK2 | **overstated** | Request DTOs are directly reusable with privacy-safe metadata. | DTO shapes need an adapter: `request_id`, `cell_id`, and `expected_ids` are emitted verbatim. |
| PK3 | **overstated** | `ResponseContract` is directly reusable as the response-contract core. | Extract only the structural subset; the current type mixes identity with lab semantic and review policy. |
| PK4 | **confirmed** | Conservative JSON parsing and exact ID/order validation primitives are reusable. | Keep strict raw parsing as default and report normalization separately. |
| PK5 | **contradicted** | Generic and hardened block schema builders are directly reusable for host requests. | Exclude `hardened_const`; positional request IDs failed pre-generation. Use generic grammar plus exact post-validation. |
| PK6 | **confirmed** | The custom validator is reusable for structural validation. | Only under an explicit tested-keyword allow-list; it is not a full JSON Schema validator. |
| PK7 | **overstated** | Lifecycle policy, context fit, and output-budget policy are direct dependencies today. | Treat as relocate-or-adapt until a stable core and host compatibility test exist. |
| PK8 | **confirmed** | Managed executors/clients/cache/registry/vision concepts require adapters; lab controllers stay out of runtime. | No live compatibility follows; the current image DTO cannot materialize image bytes. |
| PK9 | **unsupported** | The proposed core-and-ports extraction is the smallest safe route. | Call it a candidate minimal architecture; no alternative comparison or host install proof establishes unique minimality or product safety. |
| PK10 | **confirmed** | Lab model identity/capability vocabulary may cross an adapter, but lab candidate and recommendation state must not become runtime authority. | Select one host-owned approved catalog keyed by exact model identity and task capability. Current host configuration selects provider model strings directly; no approved-catalog mapper or promotion gate is implemented. |

## Task-specific context and schema policy

| ID | Verdict | Material claim or recommendation | Required correction |
|---|---|---|---|
| CP1 | **overstated** | Short microphone cleanup should default to a current-only structured transform. | Scope-consistent proposal only; structured short-microphone and audio-grounded quality were not executed. |
| CP2 | **overstated** | Boundary-neighbor context is the default for long microphone/file cleanup. | Best among three reviewed positions on one recording/model; keep provisional pending full merge and persistence evidence. |
| CP3 | **overstated** | Current-only is the default for per-chunk summaries. | Strong bounded result, but the host summary feature is absent and evidence covers one recording/model. |
| CP4 | **overstated** | Direct full compact summary or hierarchical detailed synthesis should be used. | Bounded candidates only; no blind scoring, production ownership, persistence, or read-back. |
| CP5 | **unsupported** | Generic text should use current-only or boundary neighbors according to chunking. | This extrapolates from speech-derived evidence; no generic-document comparison exists. |
| CP6 | **confirmed** | Image analysis should use the current image and a task-specific strict schema. | Confirmed for bounded single-image transport/schema only, not OCR, semantics, ranking, or production. |
| CP7 | **confirmed** | Default full-transcript-per-chunk should be rejected. | Applies to tested cleanup/chunk-summary defaults, not a single document-level whole task. |
| CP8 | **confirmed** | Request-specific identities stay out of grammar `const` positions and are checked after generation. | This stronger executed result overrides unqualified `hardened_const` reuse. |
| CP9 | **unsupported** | Proposed chunk-summary, whole-summary, and generic-text schemas are ready task contracts. | They are illustrative, with unspecified limits and no host transport-to-read-back execution. |
| CP10 | **confirmed** | IDs/state remain application-owned and acceptance layers remain separate. | Acceptance architecture only; the current host does not persist all layers. |

## Structured validation and migration risks

| ID | Verdict | Material claim or recommendation | Required correction |
|---|---|---|---|
| MR1 | **confirmed** | API-bound schema is a grammar gate only; current post-generation handling is not consistently fail closed. | Preserve transport, parse, local schema, identity, semantics, and product behavior separately. |
| MR2 | **confirmed** | Production acceptance requires full local schema validation. | Mission blocker: neither the current host parser nor LabKit's subset validator provides it. |
| MR3 | **overstated** | One structural retry, separate transport retry, immutable attempts, and one total-call ceiling define safe retry. | Conservative candidate; exact ceiling and complete state machine are unexecuted product decisions. |
| MR4 | **confirmed** | Semantic, protected-value, boundary, length, and grounding failures should skip structural retry and fail closed. | Safety disposition is sound, but detectors and thresholds are still missing. |
| MR5 | **unsupported** | Immutable attempts, request-generation fencing, atomic acceptance, transactional persistence, and read-back define the current safe control path. | Required target mechanisms only; current code lacks them and writes aggregate/block state separately. |
| MR6 | **contradicted** | Rollback is configuration-only. | It can become configuration-driven only after kill switch, generation fence, traceability, and version readability exist. |
| MR7 | **overstated** | Migration can require a binary image semantic-admission gate. | Use separate dimensions plus abstain/review; no valid binary rubric or production threshold exists. |
| MR8 | **unsupported** | Shadow, comparison, canary, and broad rollout are ready migration stages. | Sensible sequence only; shadow needs separate live authorization and instrumentation, canary needs all blockers closed. |
| MR9 | **overstated** | The privacy-safe observability record can be adopted directly. | Identifier/digest retention needs a threat model; current safe metadata leaks some identifiers and no full attempt ledger exists. |
| MR10 | **overstated** | Original-source fallback makes unsafe cleanup migration safe. | Necessary but insufficient without degraded state, fencing, atomic persistence, export, and read-back. Summary/image failures may have no safe substitute. |

## Exact corrections required before synthesis

1. Change blocks `json_schema=true` wording to “API-bound schema present”; no full local post-response schema validation currently runs.
2. Reclassify request DTOs and `ResponseContract` from unconditional direct reuse to extraction/adaptation because identifiers are emitted verbatim and structural fields are mixed with lab semantic policy.
3. Exclude `hardened_const` from the host path; use compact generic grammar plus exact application-side count, ID, uniqueness, and order checks.
4. Reclassify lifecycle, context-fit, and output-budget utilities as relocate-or-adapt pending a stable core and host compatibility test.
5. Call the core-and-ports layout a candidate minimal architecture, not the proven smallest safe route.
6. Mark short-microphone, long-cleanup, per-chunk, whole-summary, and generic-text context defaults as provisional at their actual denominators.
7. Label proposed summary and generic-text schemas illustrative and unexecuted.
8. State that rollback is not configuration-only in the current system.
9. Replace binary image admission language with multidimensional semantic review plus abstain or review-required state.
10. Treat shadow/canary rollout and observability as implementation proposals requiring separate authorization and verification.
11. Make the host-owned approved model catalog the only runtime selection authority. Lab registry and benchmark recommendation records are evidence inputs only; exact identity/capability intersection is required and no automatic promotion is allowed.

## Mission blockers

These blockers do not authorize implementation or live work. They define later gates.

| ID | Blocker | Required gate |
|---|---|---|
| B1 | No stable dependency-light package core; pure contracts are split across broad repository-layout namespaces. | Extracted-core install/import compatibility and boundary tests. |
| B2 | Safe metadata emits request, cell, and expected IDs verbatim. | Approved identifier policy and telemetry proof using categorical values, counts, or keyed digests. |
| B3 | Positional-const grammar conflicts with stronger model evidence. | Generic grammar and exact post-generation identity checks. |
| B4 | No full production JSON Schema validation. | Complete validator or fail-closed keyword allow-list tested against every accepted schema. |
| B5 | Block duplicate/extra/reorder/wrong-type/empty/bare-array defects do not all fail closed. | Offline adversarial contract tests. |
| B6 | No immutable attempts, generation fence, or total logical-call ceiling. | Retry/cancellation/stale-completion tests at every pre-commit boundary. |
| B7 | Separate aggregate/block writes have no transaction, recovery, export, or read-back proof. | Failure injection and deterministic recovery with exact accepted-attempt read-back. |
| B8 | Protected-value, boundary, omission, and unsupported-addition gates lack thresholds and fixtures. | Task-specific deterministic fixtures and explicit review/fallback disposition. |
| B9 | Image parsing tolerates schema defects and no valid semantic rubric exists. | Reject repaired/defaulted structure; establish reviewed multidimensional OCR/grounding outcomes with abstention. |
| B10 | Summary ownership, exact schemas, synthesis provenance, persistence, and read-back are absent. | Fake-client end-to-end tests before any live canary. |
| B11 | Text context evidence is one recording/model with representative cleanup positions and no audio-grounded short-microphone truth. | Keep defaults provisional and require task/source-specific canary evidence under separate authorization. |
| B12 | Kill switches, validator-version state, and rollback traceability do not exist. | Offline state-machine and rollback tests before shadow or canary. |
| B13 | No host-owned approved model catalog currently maps configured provider model strings to exact verified identity, task capability, and explicit promotion state. | Define one catalog authority and prove exact-identity lookup, task-capability rejection, unknown-model fail-closed behavior, and evidence-only LabKit import without automatic promotion. |

## Layered acceptance boundary

The final strategy must preserve six independent outcomes:

1. **Transport:** route, envelope, cancellation, finish, and usage.
2. **Raw parse:** untouched JSON versus separately reported bounded normalization.
3. **Schema:** full closed-schema validation, not merely server-side schema binding.
4. **Business identity:** exact target count, unique IDs, sequence, target/reference separation, and strict non-empty strings.
5. **Semantic quality:** completeness, grounding, protected values, boundary ownership, and unsupported additions.
6. **Product behavior:** retry, fallback, cancellation fencing, persistence, export, read-back, rollback, and user-visible state.

No Stage-1 report proves all six layers end to end. The strongest evidence proves bounded transport/schema capability and selected semantic observations; the missing product-control path remains the migration boundary.

## Constraints for Stage 3

- Preserve confirmed current-state inventory facts but apply every correction above.
- Do not select hardened positional-const grammar for host block requests.
- Distinguish candidate architecture from the current reusable package surface.
- Select a host-owned approved catalog as runtime authority; LabKit registry and benchmark recommendations remain non-promoting evidence inputs.
- Attach exact denominators and product non-admission boundaries to every context default.
- Shadow, canary, live inference, implementation, commit, and push remain outside this analysis stage.

## Non-claims

- This review does not select or admit a model.
- It does not claim audio-grounded cleanup quality, broad OCR accuracy, summary quality, concurrency safety, cache reuse, or production readiness.
- It does not prove package extraction, adapters, validators, state machine, persistence transaction, rollout, or rollback behavior.
