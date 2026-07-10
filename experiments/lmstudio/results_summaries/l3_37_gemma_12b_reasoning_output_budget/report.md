# L3.37 Gemma 12B reasoning and output-budget evidence pack

Status: completed bounded evidence publication. The report pack contains sanitized aggregate facts only.

## Scope

This evidence covers one fixed blocks JSON task on the exact `google/gemma-4-12b-qat` model, at context tiers 8192 and 16384. It compares native reasoning `off` and `on` on `/api/v1/chat`, then records two conditional strict JSON confirmation cells on `/v1/chat/completions`.

Executed cells:

- 10 native cells;
- 2 OpenAI-compatible strict JSON cells;
- 12 total cells, sequential, without retries;
- output caps 1024, 2048, 3072, and 4096 where branch escalation was justified.

The canonical machine-readable cell table is [cells.csv](cells.csv). Aggregate facts are in [summary.json](summary.json), and the pack-level privacy result is in [privacy_scan.json](privacy_scan.json).

## Native route results

With native reasoning disabled, both context tiers produced schema-valid blocks JSON at the first 1024-token cap. Each successful cell used 35 total output tokens and 0 reasoning tokens, so both branches stopped at the first sufficient cap.

With native reasoning enabled, both context tiers consumed every tested cap while producing no visible message:

| context | cap sequence | reasoning tokens | visible message chars | final classification |
| --- | --- | --- | --- | --- |
| 8192 | 1024, 2048, 3072, 4096 | 1021, 2045, 3069, 4093 | 0, 0, 0, 0 | reasoning-dominant cap exhaustion; no rescue through 4096 |
| 16384 | 1024, 2048, 3072, 4096 | 1021, 2045, 3069, 4093 | 0, 0, 0, 0 | reasoning-dominant cap exhaustion; no rescue through 4096 |

The paired counters were identical across the two context tiers. This controlled task therefore did not demonstrate a context-size interaction.

## Strict-route confirmation

The strict JSON route was tested once at each context tier with `max_tokens=1024`, after native reasoning-off had succeeded at that cap. Both cells ended with `finish_reason=length`, 1024 completion tokens, empty visible content, and no parseable JSON.

The strict route did not expose a separately proven reasoning-off control or reasoning-token accounting in this experiment. Its result remains underdetermined between default or hidden reasoning, route/template behavior, and constrained structured-output behavior. It is not evidence of constrained-runtime failure alone.

## Conclusion

For this exact model, blocks task, native route, and tested settings, valid visible JSON required native reasoning to be explicitly disabled. Increasing the native output cap did not rescue reasoning-on through 4096 tokens.

This is a route-specific and task-specific conclusion. It does not establish that the 12B model fails all structured tasks, that all reasoning-enabled tasks fail, that larger contexts degrade quality, or that other models require reasoning off.

## Safety and provenance

- Source: the sanitized companion retained under ignored live-run storage for task `t_4b30753d`.
- Source SHA-256: `8d83f83dbabf5ba5a6cb07baaf0fba39fc8bc3044c9299d15c6f707c615ee89e`.
- Prompt and schema identity are represented only by hashes in `summary.json` where needed for evidence identity.
- Raw prompt, response, and reasoning text are absent from this report pack.
- Cleanup was verified for all 12 cells; cleanup failures were zero; final global loaded-model count was zero.
- No live inference, model load, download, or rerun was performed to create this publication pack.

## Future work: 26B MoE canary proposal

Research task `t_465d99eb` proposed, but did not execute, a maximum four-cell native canary for `google/gemma-4-26b-a4b-qat`: reasoning `off/on`, cap 1024, context 8192 first, and the 16384 pair only after a clean 8192 result. The proposal requires sequential cold-load cells, cleanup after every cell, and final zero loaded instances.

This proposal is future work only. It is not part of the L3.37 executed evidence and provides no 26B structured-output result.
