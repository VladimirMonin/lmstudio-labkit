# Native structured vision red-team

Date: 2026-07-13

Status: offline falsification review. No model call, retry, cap increase, model load, or network action was performed.

## Verdict

The run confirms a narrow but important result: the OpenAI-compatible route accepted real image data together with API-bound strict JSON Schema, and all 16 executed `simple_description` rows returned raw JSON valid against the pinned schema.

It does **not** close structured vision as an admitted capability. The frozen controller admitted 0/16 strict image rows, while direct image review found 11/16 grounded rows, 10/16 exact `visible_text` arrays, and 7/16 supported/relevant warning arrays. The mismatch is explained in part by sparse supported-text allow-lists. Medium/object extraction, repeatability, model ranking, and production admission remain untested or unsupported.

## Exact denominators

| Row class | Candidate | Executed | Zero-call | Key result |
|---|---:|---:|---:|---|
| Matrix text preflight | 1 | 1 | 0 | Raw JSON and schema pass; route plumbing only |
| Native plain UI baseline | 4 | 4 | 0 | 4/4 grounded; 2/4 complete; 2/4 hit the 1024-token cap |
| Strict `simple_description` image | 16 | 16 | 0 | 16/16 HTTP 200, raw JSON, schema-valid, finish `stop`, zero reported reasoning tokens |
| Strict `medium_objects_text` image | 16 | 0 | 16 | Not evaluated |
| Exact repeat candidate | 4 | 0 | 4 | Not evaluated |
| **Total** | **41** | **21** | **20** | Final global loaded count zero |

The manifest has 41 candidate rows but a 40-call ceiling because it contains four conditional repeat candidates while execution may select at most the first three accepted models. All four repeat candidates were stop-gated here, so the 41 candidate dispositions and 40-call ceiling are consistent.

The controller summary's `accepted_rows=1` is the text preflight only. Its 20 rejected executed rows combine four native plain baselines and sixteen strict simple rows; that value is not a model-admission denominator and must not be described as 20 semantic image failures.

## Claim classification

### Confirmed

- **Compatible image plus strict-schema request acceptance:** 16/16 strict simple requests returned HTTP 200. Each retained outbound payload used `/v1/chat/completions`, contained an image data URL, and carried `response_format.type=json_schema` with `strict=true`.
- **Strict simple structure:** 16/16 raw JSON, 16/16 independently schema-valid, 16/16 `finish_reason=stop`, and 16/16 zero reported reasoning tokens.
- **Frozen controller result:** 0/16 strict image rows passed its grounding gate.
- **Independent semantic result:** 11/16 manually grounded, 10/16 exact `visible_text` arrays, 7/16 supported/relevant warning arrays, and 0/16 containing the three pinned forbidden-claim classes.
- **Native baseline:** 4/4 grounded on the single UI fixture, but only 2/4 complete; 12B and 26B reached the output cap.
- **Stop and cleanup:** 21 host calls, no measured-cell retries, 20 zero-call conditional rows, final global loaded count zero.

### Overstated unless corrected

- Schema validity does not prove visual understanding. Transport, API schema binding, raw syntax, schema validity, and semantic grounding are separate gates.
- Controller grounding 0/16 does not mean 16 hallucination failures. The supported-text lists omit genuinely visible sidebar, toolbar, axis, code, and status text. Keep 0/16 as the binding frozen-contract result, but report the manual denominator separately.
- The native baseline did not pass without qualification: it covered one UI fixture, and two larger-model responses were cap-limited and incomplete.
- The image family is not closed. Only compatible-route plus simple-schema structural behavior is closed for this bounded run.

### Unsupported

- Admission of any model for structured vision.
- Ranking 26B, or any other model, as best. The per-model sample is four simple fixtures, with no repeats and no admitted lane.
- Medium-schema or object-extraction quality: 0/16 medium rows executed.
- Repeatability or determinism: 0/4 repeat candidates executed; temperature zero is only a request setting.
- A universal “no hallucinations” claim. The review checked three forbidden-claim classes and found OCR/warning errors elsewhere.
- A causal claim that strict schema was necessary for conformance. The contract was sent and accepted and outputs conformed, but this run has no matched no-schema compatible-image counterfactual.

### Contradicted

- Historical L3.39 or fence-normalized image JSON already proved API-bound strict structured vision. Those rows were prompt-only with caller-side normalization and validation.
- All four models failed image transport or strict schema. All four completed four strict simple rows with HTTP 200, raw JSON, and schema validity; the blocker was semantic admission.
- Manifest presence means medium or repeat evidence exists. All 20 such rows made zero calls.

## Mandatory corrections by target file

### `2026-07-13_native_structured_vision_closure.md`

- Use 41 candidate / 21 executed / 20 zero-call and explain the 41-candidate versus 40-call distinction.
- Split 1 text preflight, 4 native baselines, 16 strict simple rows, 0 medium rows, and 0 repeats.
- Report strict results as 16/16 HTTP 200, raw JSON, schema-valid, finish `stop`, and zero reported reasoning tokens.
- Keep controller 0/16 separate from manual 11/16 grounded, 10/16 exact text, and 7/16 warning-quality results.
- State no model admission, no ranking, no medium/object result, and no repeatability result.
- Qualify native baseline as one fixture, 4/4 grounded, 2/4 complete, 2/4 cap-limited.
- Record final global loaded count zero and that review/red-team made no new calls.

### `2026-07-13_native_structured_vision_closure.json`

- Pair every numerator with its denominator.
- Use `null` or `not_evaluated` for medium, objects, repeats, ranking, and admission rather than zero-valued quality scores.
- Do not use aggregate controller accepted/rejected rows as a model-admission denominator.
- Encode route/schema, controller semantics, manual semantics, and cleanup as distinct objects.

### `l3_34_gemma_vision_route_capability_decision_record.md`

- Append a dated superseding update: compatible image plus strict-schema transport is now confirmed for 16/16 simple rows across all four models.
- Preserve historical four-call length and native E4B evidence as historical; do not relabel them schema-bound.
- Do not convert route capability into semantic or model-quality admission.

### `l3_35_gemma_vision_screening_decision_record.md`

- Replace the stale sole blocker “native minimal JSON failed” with the current state: strict simple screening executed structurally, but no model passed the frozen semantic gate.
- Record 16 strict simple calls and zero medium/object/repeat calls; keep model admission blocked.

### `l3_31_l3_36_gemma_admission_matrix.md`

- Add a dated vision addendum without rewriting text-task admissions.
- Record 4/4 strict simple raw/schema success and `not_admitted` vision semantics for each model.
- Do not rank 26B or generalize the vision result to text structured-output policy.

### `experiments/lmstudio/models/candidates.yaml`

- Do not change the general `structured_output_policy` fields from this vision run.
- If a vision annotation is added, make it route/schema-scoped and `not_admitted`; add no family ranking.

## Remaining minimal gaps

1. Correct the incomplete fixture truth or replace exact allow-list precision with an exhaustive, pixel-reviewed semantic rubric before using it as an admission gate.
2. After an approved plan change, rerun the bounded simple gate under that corrected rubric. Only admitted models may enter medium/object and repeat lanes.
3. Execute at least one exact repeat for any admitted model before claiming repeatability.
4. Execute medium rows before claiming object extraction.
5. Add fixtures and repeats before comparative model ranking or production recommendations.

## Non-claims

- No model is admitted for structured vision.
- No model ranking is supported.
- No medium/object or repeatability result exists.
- No production, source-application integration, latency superiority, or unattended-use claim is supported.
- No historical prompt-only or fence-normalized row is relabeled as API-bound evidence.

Machine-readable companion: `2026-07-13_native_structured_vision_red_team.json`.
