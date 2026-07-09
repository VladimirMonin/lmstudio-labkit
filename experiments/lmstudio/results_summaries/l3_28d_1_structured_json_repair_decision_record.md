# L3.28d.1 Structured JSON Repair Decision Record

Status: completed.

## Inputs

- L3.28 structured JSON canary failed 0/12.
- Failure categories were `language_mismatch`, `schema_error`, and `finish_length`.
- 26B did not participate in L3.28 structured JSON and remains out of scope for this repair.

## Repair

Changes:

- Exact-shape prompts now include the concrete JSON payload to return.
- Structured language validation is scoped to payload fields:
  - simple: `items[*]`
  - blocks: `blocks[*].text`
- RU fixtures use Russian payload text.
- mixed fixtures use genuinely mixed RU/EN technical text.
- blocks use supported hardened schema variant `hardened_const`.

## Results

| run | models | attempts | pass | fail | privacy |
|---|---|---:|---:|---:|---|
| E2B/E4B repair canary | E2B, E4B | 8 | 8 | 0 | pass |
| 12B repair rerun | 12B | 8 | 8 | 0 | pass |

Per-model result:

| model | attempts | pass | fail | json parse | schema | id exact | language | finish length |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| google/gemma-4-e2b | 4 | 4 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 |
| google/gemma-4-e4b | 4 | 4 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 |
| google/gemma-4-12b-qat | 8 | 8 | 0 | 1.0 | 1.0 | 1.0 | 1.0 | 0 |

## Answers

1. Was L3.28 structured failure caused by test/prompt/validator design?
   - Yes. The repair passed 16/16 after making the payload explicit and scoping language validation correctly.
2. Do E2B/E4B pass repaired structured canary?
   - Yes, 8/8 combined.
3. Does 12B pass after repair?
   - Yes, 8/8.
4. Is `structured_json/simple` admitted to L3.29?
   - Yes, for E2B/E4B/12B in bounded screening.
5. Is `structured_json/blocks` admitted to L3.29?
   - Yes, for E2B/E4B/12B with `hardened_const` only.
6. Is 26B still structured-blocked?
   - Yes. 26B structured JSON was not run in L3.28d.1 and needs separate approval/tiny canary.

## L3.29 policy update

Admit into bounded L3.29 structured screening:

- E2B structured_json/simple and structured_json/blocks.
- E4B structured_json/simple and structured_json/blocks.
- 12B structured_json/simple and structured_json/blocks, with hardened blocks only.

Keep blocked:

- 26B structured JSON.
- complex schema.
- context matrix for structured JSON until bounded screening remains green.
