# L3.29 Gemma Family Bounded Matrix Decision Record

Status: prepared; live run not started in this slice.

## Admission inputs

- L3.28 transcript cleanup/simple passed for E2B/E4B/12B and tiny 26B.
- L3.28 load-only passed for 12B up to 32768 and 26B up to 16384.
- L3.28d.1 repaired structured JSON and passed E2B/E4B/12B 16/16.

## Prepared scope

| config | models | mode | planned attempts | raw |
|---|---|---|---:|---|
| `matrix.l3_29_gemma_transcript_cleanup_screening.yaml` | E2B/E4B/12B | transcript_cleanup/simple | 120 | local-only |
| `matrix.l3_29_gemma_26b_transcript_cleanup_controlled.yaml` | 26B | transcript_cleanup/simple controlled | 5 | local-only |
| `matrix.l3_29_gemma_structured_json_bounded.yaml` | E2B/E4B/12B | structured_json simple+blocks | 24 | no raw |

Total planned attempts: 149. Hard max: 150.

## Forbidden scope

- Qwen / Qwen VL
- image live
- complex schema
- throughput
- parallel
- session/warmup
- overnight
- context matrix for structured JSON
- 26B structured JSON

## Live execution order

1. Transcript cleanup screening E2B/E4B/12B.
2. 26B controlled transcript cleanup only if operator approves controlled 26B live.
3. Structured JSON bounded E2B/E4B/12B.

Stop on:

- privacy scan failure;
- cleanup final loaded instances not zero;
- model load failure;
- raw artifacts would be committed;
- hard validation failure that invalidates the next phase;
- any Qwen/image/parallel/session scope leak.

## Decision fields to fill after live

- per-model raw quality review;
- latency summary;
- term preservation summary;
- self-correction cleanup summary;
- language drift summary;
- structured JSON simple/blocks pass rates;
- final model admission table.
