# L3.38 Reasoning-Off Follow-up Evidence

Status: independently reconciled; narrow native-route gains, no family-wide green admission.

This report summarizes sanitized aggregates only. Raw prompts, responses, reasoning text, image bytes, endpoint details, and private artifact locations are excluded.

## Executed scope

| Lane | Route | Model/task | Attempted cells | Result |
|---|---|---|---:|---|
| 26B paired canary | native `/api/v1/chat` | blocks JSON at 8192 and 16384, reasoning off/on | 4 | 4/4 schema-valid |
| E4B vision gate | native `/api/v1/chat` | plain text, text JSON, then one image JSON | 3 | transport and text JSON passed; image grounding failed |
| 12B repeated context | native `/api/v1/chat` | exact repeat and stable-prefix, reasoning off | 6 | 0/6 strict local JSON-valid; research only |
| 12B strict JSON investigation | OpenAI-compatible `/v1/chat/completions` | route-contract review | 0 | blocked before generation |

Total generation cells: 13. Every cell reached HTTP 200 and a terminal native boundary, created a non-empty private record, completed cleanup, and ended with global loaded count zero. The strict lane made zero generation requests because no documented route-specific reasoning-disable control was established.

## Independent findings

### 26B-A4B MoE

The exact native model variant advertised reasoning `off` and `on`, defaulting to `on`. At both 8192 and 16384, the off/on pair returned the same schema-valid visible payload. Reasoning-on added 262 reasoning tokens and about 20 seconds of latency in each pair; reasoning-off used zero reasoning tokens. No context interaction appeared in this task.

Decision: accept only the native blocks-JSON canary scope at 8192 and 16384. Reasoning-off is recommended for this exact bounded transformation because it preserves the validated answer while avoiding measured reasoning overhead. This does not admit strict structured output, complex JSON, cache/session, vision, or broad 26B use.

### E4B vision

With native reasoning off, the plain route marker passed and minimal text-only JSON was schema-valid. The image request reached the route and returned valid, non-truncated JSON, but its grounded boolean contradicted the verified fixture truth.

Decision: image transport is accepted, image understanding is not. Keep structured vision blocked. Reasoning-off removed reasoning overhead but did not repair grounding quality; it is a route/task setting, not a global model recommendation.

### 12B repeated context

Both three-request comparisons ran at 16384 with native reasoning off. First-to-warm latency ratios were 4.985 for exact repeat and 4.392 for stable-prefix/dynamic-suffix. However, all six outputs leaked Markdown fences and were not parseable under the strict local JSON contract.

Decision: research-only timing evidence. Do not admit the session/cache lane and do not claim physical KV reuse, cache benefit, or remote memory attribution. Reasoning-off prevents the previously observed reasoning-dominant output exhaustion, but it does not guarantee contract-valid output for this prompt/route/task shape.

### 12B OpenAI-compatible strict JSON

Current documentation and the installed read-only API surface expose reasoning control for native chat, not a supported reasoning-disable parameter for OpenAI-compatible chat completions. Native `reasoning=off` was therefore not transferred by assumption.

Decision: blocked with zero generation requests. A future confirmation requires an official route-specific contract or installed schema that explicitly defines reasoning disablement, followed by review.

## Admission changes

- `google/gemma-4-26b-a4b-qat`: native blocks-JSON canary accepted narrowly at 8192 and 16384 for both reasoning modes; prefer off for this exact task on latency/overhead grounds.
- `google/gemma-4-e4b`: native text and text-only minimal JSON remain accepted narrowly; image transport is accepted, but structured image grounding remains blocked.
- `google/gemma-4-12b-qat`: native repeated-context timing remains research-only because strict response validity is 0/6; OpenAI-compatible strict JSON remains blocked and untested in L3.38.
- `google/gemma-4-e2b`: unchanged by L3.38.

Gemma family closure remains `partial_not_green`.

## Safety and privacy review

- 13/13 attempted generation cells have non-empty external private records.
- Private directories were mode `0700`; record files were mode `0600`.
- 13/13 cells report cleanup verified and final global loaded count zero.
- Sanitized evidence exposes no private path and contains no raw prompt, response, reasoning text, or image bytes.
- The live-run directory is ignored, and no L3.38 live-run file is tracked.
- No model download, commit, or push occurred in this synthesis.

Machine-readable decisions and per-model cards are in `admission_matrix.json`; privacy invariants are in `privacy_manifest.json`.
