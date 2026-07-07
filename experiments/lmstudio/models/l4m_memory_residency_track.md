# L4m Memory Residency Track

Future track only. Do not implement or execute this now.

## Gate

- Run only after M1 and M2 finish and a top-2 candidate set is selected.
- Keep this track separate from candidate discovery and identity-resolution work.

## Comparison matrix

For each of the top-2 candidates, compare only these residency/load options:

| Variant | keepModelInMemory | tryMmap |
| --- | --- | --- |
| A | `false` | `false` |
| B | `false` | `true` |
| C | `true` | `false` |
| D | `true` | `true` |

## Measure

Capture the same metrics for every variant:

- load time
- first request latency
- repeated request latency
- RAM before / peak / after
- process RSS before / peak / after
- VRAM before / peak / after

## REST caution

`keepModelInMemory` exists in SDK `LLMLoadModelConfig`, but REST `/api/v1/models/load` docs do not list it explicitly. Do not assume the REST path accepts it until a feature probe is run and the echoed/applied config confirms it.

## Isolation rules

- Do not mix this track with thinking toggles.
- Do not mix this track with temperature changes.
- Do not mix this track with cache experiments.
- Do not mix this track with vision experiments.

## Output expectation

Record only the residency comparison evidence and the measured deltas for the top-2 finalists.
