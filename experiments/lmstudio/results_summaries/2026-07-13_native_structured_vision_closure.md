# Native structured vision closure

Date: 2026-07-13

Status: **full evidence closure after the reviewed continuation**. Compatible-route image transport and API-bound strict JSON Schema are confirmed for the bounded run. Manual semantics are mixed by row and dimension. No comparative ranking or production admission is supported.

## Decision

The cumulative run completed **40/40 authorized host calls** across four Gemma models and four image fixtures. All 40 calls returned without transport error. All **36/36 applicable strict-schema calls** returned raw JSON that passed independent schema validation; the four native-plain baselines were non-JSON by design.

The earlier automated **0/16** strict-simple verdict is explicitly superseded as a semantic-admission result. Its partial supported-text allow-lists were not exhaustive closed-world gold, and the warning-field policy rejected grounded outputs. The immutable 0/16 result—and the controller's eventual 35/35 strict-image rejection count—is retained as a **validator failure record**, not rewritten or discarded.

Direct inspection of all four PNGs and all 40 raw responses is the primary semantic evidence. It found mixed quality, including exact emitted visible text in 25/39 image rows, complete salient text in 31/39, no unsupported claim in 36/39, and no forbidden private claim in 39/39. Because no valid binary semantic threshold was predeclared, this closure does not replace the defective validator with an invented pass/fail gate.

## Exact execution denominators

| Row class | Candidate | Executed | Zero-call | Result |
|---|---:|---:|---:|---|
| Matrix text preflight | 1 | 1 | 0 | Raw JSON and schema pass; route plumbing only |
| Native plain UI baseline | 4 | 4 | 0 | 3/4 exact text, 2/4 salient-text complete, 4/4 grounded objects |
| Strict `simple_description` image | 16 | 16 | 0 | 16/16 raw/schema; 10/16 exact text; 13/16 salient-text complete |
| Strict `medium_objects_text` image | 16 | 16 | 0 | 16/16 raw/schema; 15/16 grounded objects; 11/16 salient-object complete |
| Exact repeat candidate | 4 | 3 | 1 | 3/3 byte-identical UI pairs; 12B repeat not executed |
| **Total** | **41** | **40** | **1** | Final global loaded count zero |

The manifest has four conditional repeat candidates but authorizes at most three repeats. Three reviewed repeats executed and the 12B repeat remained zero-call, so 41 candidate dispositions and the 40-call ceiling are consistent.

## Manual semantic evidence

| Lane | Visible text exact | Salient text complete | Objects grounded | Salient objects complete | Warnings supported/relevant |
|---|---:|---:|---:|---:|---:|
| Native plain UI | 3/4 | 2/4 | 4/4 | 2/4 | n/a |
| Strict simple image | 10/16 | 13/16 | n/a | n/a | 5/16 |
| Strict medium image | 10/16 | 13/16 | 15/16 | 11/16 | 4/16 |

These dimensions must not be collapsed into one quality score. Three image rows contained unsupported non-private claims: one material invented cursor-occlusion warning and two minor inferences or summary errors. No image row made a forbidden private-data or identified-person claim.

## Per-model bounded evidence

| Model | Image calls | Strict image raw/schema | Exact visible text | Salient text complete | Medium objects grounded | Repeat |
|---|---:|---:|---:|---:|---:|---|
| `google/gemma-4-e2b` | 10 | 9/9 | 2/10 | 4/10 | 3/4 | Executed, byte-identical pair |
| `google/gemma-4-e4b` | 10 | 9/9 | 8/10 | 10/10 | 4/4 | Executed, byte-identical pair |
| `google/gemma-4-12b-qat` | 9 | 8/8 | 5/9 | 8/9 | 4/4 | Not executed |
| `google/gemma-4-26b-a4b-qat` | 10 | 9/9 | 10/10 | 9/10 | 4/4 | Executed, byte-identical pair |

The descriptive differences do not establish a family ranking. The fixture set is small and heterogeneous, warning quality is weak, and only one strict-simple UI request was repeated once on three models.

## Validator failure and supersession

The initial controller result rejected 16/16 strict-simple rows and prematurely stop-gated the medium and repeat candidates. A reviewed continuation later executed exactly the missing 16 medium rows and three repeats without rerunning the 21 prior calls.

Across the completed evidence, the controller rejected all 35 strict-image rows. Direct review nevertheless found exact emitted visible text in 22/35 rejected rows and grounded object inventories in 15/16 rejected medium rows. This disagreement demonstrates that the partial-gold validator was not a valid semantic-admission gate for an open-world image contract.

The earlier independent-review and red-team reports remain preserved as records of the 21-call state and the defective gate. Their claims that controller 0/16 was binding, medium/object extraction was not evaluated, and repeatability evidence did not exist are superseded by the completed continuation and 40-call manual reconciliation.

## Admission boundary

- Route and strict-schema contract: **accepted for this bounded four-model, four-fixture run**.
- Binary semantic model admission: **not assessed under a valid gate**; the defective automated rejection is superseded.
- Production admission: **none**.
- Comparative model ranking: **unsupported**.
- Object extraction: demonstrated on 16 medium rows, but not uniformly complete or exact.
- Repeatability: 3/3 byte-identical pairs for one UI request only; broader determinism is unsupported.

This modality-scoped result does not change text cleanup, text structured-output, context, cache, or concurrency decisions.

## Safety and cleanup

The final manual review made no model call, retry, model load, or network request. The cumulative execution remained within the 40-call authorization ceiling, and final global loaded count was zero. Raw requests, responses, and image bytes remain outside the public report.

The owner-only 40-row ledger is bound by SHA-256 `1ffad2666d2208297b5bfe11cc24455a8d4e92d3a0a3629e4184368cf3e6b44e` and is intentionally stored outside the repository.

## Canonical evidence

- `2026-07-13_strict_vision_40_call_manual_reconciliation.md`
- `2026-07-13_native_structured_vision_independent_review.md` (preserved 21-call state; superseded where noted)
- `2026-07-13_native_structured_vision_red_team.md` (preserved 21-call state; superseded where noted)
- `../strict_vision/launch_manifest.json`

Machine-readable companion: `2026-07-13_native_structured_vision_closure.json`.
