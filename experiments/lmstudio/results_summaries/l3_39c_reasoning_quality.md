# L3.39c bounded reasoning quality review

## Scope

- Five exact installed Gemma-family models; serial execution; one loaded model at a time.
- Tasks: simple structured text and perception-only vision on the same public-safe inputs.
- Google models: reasoning off/on. Exact Unsloth 31B: reasoning control omitted and reported as unknown, not emulated.
- 18/18 private answers were read directly and scored with the fixed private rubric.
- No raw answer, reasoning text, prompt text, or private path is published.

## Findings

- Simple text: all nine outputs were complete and factually correct after deterministic single-fence normalization; all nine violated strict JSON-only syntax by adding a Markdown fence.
- Vision: reasoning-on improved the reviewed answer for E2B and E4B by avoiding minor unsupported details present with reasoning off.
- Vision: 12B misread the visible model identifier in both modes; reasoning did not repair the grounding error.
- Vision: 26B was equivalent and correct in both modes; reasoning off is preferred because latency and token cost were lower.
- Exact Unsloth 31B produced correct text and vision baselines, but its reasoning control remains unknown; no off/on claim is made.

## Pair decisions

| Model | Task | Quality relation | Preferred |
|---|---|---|---|
| google/gemma-4-e2b | text_structure/simple | equivalent | off |
| google/gemma-4-e2b | vision/perception | on_better | on |
| google/gemma-4-e4b | text_structure/simple | equivalent | off |
| google/gemma-4-e4b | vision/perception | on_better | on |
| google/gemma-4-12b-qat | text_structure/simple | equivalent | off |
| google/gemma-4-12b-qat | vision/perception | equivalent | off |
| google/gemma-4-26b-a4b-qat | text_structure/simple | equivalent | off |
| google/gemma-4-26b-a4b-qat | vision/perception | equivalent | off |
| gemma-4-31b-it | both | unsupported/unknown comparison | none |

## Execution and safety

- Calls executed: 18; retries: 0; downloads: 0.
- All responses reached a final answer; no cap-exhausted answer was observed.
- Final global loaded-model count: 0.
- The first E2B batch hit a local post-cleanup forensics-finalization wiring error. Its four HTTP-200 responses were retained and reviewed, no requests were retried, and fresh LM Studio state confirmed cleanup zero.
