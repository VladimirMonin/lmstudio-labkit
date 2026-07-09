# L3.29 Gemma Family Bounded Matrix Decision Record

Status: prepared; live inference not run in this slice.

## Context

L3.28d.1 repaired the structured JSON contract. The previous L3.28 structured JSON `0/12` result was a contract/prompt/validator failure, not evidence that Gemma cannot do structured JSON.

Admitted into L3.29:

- `transcript_cleanup/simple`: E2B, E4B, 12B, plus controlled 26B.
- `structured_json/simple`: E2B, E4B, 12B.
- `structured_json/blocks`: E2B, E4B, 12B with `hardened_const` only.

Still blocked:

- 26B structured JSON.
- complex schema.
- image live.
- Qwen.
- throughput/parallel.
- session/warmup.

## Prepared configs

| lane | config | models | planned attempts | raw policy |
|---|---|---|---:|---|
| A | `matrix.l3_29a_gemma_transcript_cleanup_screening.yaml` | E2B/E4B/12B | 72 | local-only raw prose review |
| B | `matrix.l3_29b_gemma_structured_json_screening.yaml` | E2B/E4B/12B | 72 | sanitized metrics only |
| C | `matrix.l3_29c_gemma_26b_transcript_cleanup_controlled.yaml` | 26B | 5 | local-only raw prose review |

Total target: 149 requests. Hard cap: 160 requests.

## Suite order

1. transcript cleanup screening;
2. structured JSON screening;
3. 26B transcript cleanup controlled.

Do not run 26B automatically if earlier phases fail infrastructure.

## Reports to fill after live

- per-model pass/fail;
- per-lane pass/fail;
- per-language degradation;
- per-context degradation;
- structured JSON simple vs blocks;
- retry impact;
- raw prose review summary for transcript cleanup;
- 26B controlled result;
- latency summary;
- model admission table for L3.30.

## Model admission table for L3.30

| model | transcript cleanup | structured simple | structured blocks | context 16k | 26B control | next status |
|---|---|---|---|---|---|---|
| google/gemma-4-e2b | pending | pending | pending | pending | n/a | pending L3.29 |
| google/gemma-4-e4b | pending | pending | pending | pending | n/a | pending L3.29 |
| google/gemma-4-12b-qat | pending | pending | pending | pending | n/a | pending L3.29 |
| google/gemma-4-26b-a4b-qat | pending controlled only | blocked | blocked | blocked in L3.29 | pending controlled | pending L3.29 |

## Stop conditions

Stop if:

1. cleanup final zero cannot be proven;
2. privacy scan fails;
3. model download required;
4. 26B tries structured JSON;
5. complex schema appears;
6. image live appears;
7. Qwen appears;
8. run exceeds 160 requests;
9. raw prompt/response would be committed.
