# L3.39 cross-model fenced JSON replay

Status: offline replay complete for every retained eligible fenced JSON response available from the completed model sweeps.

## Evidence set

- Records replayed: 24 across 5 exact model variants.
- Historical L3.38 repeated-context 12B records: 6.
- L3.39 text-structure records: 18.
- Regeneration or model calls: 0.
- Raw response text or private paths published: 0.

## Parser and schema outcomes

- Strict raw JSON parse: 0 pass, 24 fail.
- Normalized JSON parse: 24 pass, 0 fail.
- Exact transformation category: `single_complete_json_fence` for all 24 records.
- Semantic repairs: 0.
- Schema validation after normalization: 15 pass, 9 fail.
- Replayed schema outcomes matched the previously recorded per-row outcomes for all 24 records.

Fence unwrapping changes only syntactic admission. It does not convert a schema-invalid response into a valid one, and the nine schema failures remain failures.

## Cache and session boundary

This replay contains no cache/session timing evidence. No new bounded confirmation was run because the retained evidence already answers the JSON-normalization question, while no explicit telemetry is available to establish physical KV reuse, cache benefit, remote-memory behavior, or timing attribution. Those claims remain false/non-claims.

The required future cache/session shape remains separate from normalization: one stable message 1 plus changing message 2 chunks, evaluated with response validity and timing reported independently.

Machine-readable evidence: `experiments/lmstudio/results_summaries/l3_39_cross_model_fenced_replay.sanitized.json`.
