# Independent native structured vision artifact review

## Result

All 21 executed artifacts were independently inspected against their raw response, strict schema where applicable, pinned fixture pixels, and frozen truth rubric. The 20 stop-gated rows were reconciled as zero-call rows. No new model calls were made.

Strict transport and structure succeeded: 16/16 strict image responses were raw JSON and independently schema-valid. Semantic admission did not: the controller admitted 0/16. Direct image review found fully exact `visible_text` arrays in 10/16 rows and supported/relevant warning arrays in 7/16 rows. No forbidden private-production, real-customer, or identified-person claim was found.

## Exact denominators

| Surface | Executed | Reviewed | Raw JSON | Schema-valid | Controller grounding |
| --- | ---: | ---: | ---: | ---: | ---: |
| Text preflight | 1 | 1 | 1 | 1 | n/a |
| Native plain UI baseline | 4 | 4 | n/a | n/a | n/a |
| Strict `simple_description` image | 16 | 16 | 16 | 16 | 0 |
| Strict `medium_objects_text` image | 0 | 0 | 0 | 0 | 0 |
| Exact repeat | 0 | 0 | 0 | 0 | 0 |

Candidate rows: 41. Executed host calls: 21. Zero-call stop-gated rows: 20.

## Per-model strict simple verdicts

| Model | Executed | Raw JSON | Schema | Exact visible text | Grounded | Warning quality | Forbidden claims | Admission |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `google/gemma-4-e2b` | 4 | 4 | 4 | 1 | 2 | 1 | 0 | Not admitted |
| `google/gemma-4-e4b` | 4 | 4 | 4 | 3 | 3 | 2 | 0 | Not admitted |
| `google/gemma-4-12b-qat` | 4 | 4 | 4 | 2 | 2 | 2 | 0 | Not admitted |
| `google/gemma-4-26b-a4b-qat` | 4 | 4 | 4 | 4 | 4 | 2 | 0 | Not admitted |

## Findings

- The strict compatible route accepted image data plus API-bound strict JSON Schema for every executed simple row.
- Schema validity is not semantic admission. Material OCR errors include a wrong Gemma model key, wrong code tokens/operators, wrong chart legend text, and one Russian tense error.
- The frozen `supported_visible_text` lists contain only selected salient strings. They omit real sidebar, toolbar, axis, code, and status-bar text that is visibly present. Consequently, the controller's 0/16 precision verdict remains the binding launch gate but must not be restated as 16 hallucination failures.
- The native UI baselines were grounded, but the 12B and 26B responses hit the 1024-token cap and ended incomplete.
- Objects were not evaluated: all 16 medium-schema rows were stop-gated and the simple schema has no `objects` field.
- Repeatability was not evaluated: all four candidate repeat rows were stop-gated, so the exact repeat denominator is 0.
- No forbidden claim about real customer data, a private production system, or an identified person appeared in the strict outputs.

## Limitations

- The review covers only the four pinned synthetic fixtures and 21 executed artifacts.
- Frozen fixture truth is a salient subset rather than a complete OCR transcript; emitted strings were therefore checked directly against fixture pixels.
- Four simple fixtures per model and zero repeats do not support model ranking or repeatability claims.
- No medium/object claim and no model/schema admission is supported by this run.
