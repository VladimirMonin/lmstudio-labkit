# L3.28 Gemma Family Expansion Decision Record

Status: live phased run completed. See `experiments/lmstudio/results_summaries/l3_28_gemma_family_live_decision_update.md` for the sanitized live update.

## Questions to close

1. Which Gemma models are load-capable?
2. Which Gemma models are generation-capable?
3. Which Gemma models pass `transcript_cleanup/simple`?
4. Which Gemma models pass `structured_json/simple`?
5. Which Gemma models pass `structured_json/blocks`?
6. Which models degrade by language?
7. Which models degrade by context?
8. Which models support images in the current LM Studio route?
9. Which models are allowed into L3.29 full Gemma matrix?
10. Which remain blocked?

## Current status

- E2B/E4B have accepted L3.27 raw-prose evidence for `transcript_cleanup/simple`; E4B is the quality candidate and E2B is the lightweight fallback.
- 12B is conditionally viable for structured JSON only under hardened schema and/or sanitized retry according to L3.10.
- 26B has historical load-only evidence but no current generation proof in this branch of work.
- Vision/image support is not assumed for any Gemma model until current route capability is proven.
- L3.28 prepared configs must be run phase-by-phase; do not run the full suite automatically.
- Do not run the full suite automatically.

## Prepared L3.28 phase gates

| phase | purpose | status | next action |
|---|---|---|---|
| A | readiness metadata | prepared | read-only metadata check only |
| B | 12B/26B load-only | prepared manifest | implement/use dedicated load-only command; do not use ordinary matrix run |
| C1 | E2B/E4B/12B transcript cleanup canary | prepared | run after B proves 12B load-only and owner approves |
| C2 | 26B tiny transcript cleanup canary | prepared optional | run only after 26B load-only passes and owner explicitly approves 26B generation |
| D | Gemma structured JSON canary | prepared | run after B and C gating |
| E | context screening example | prepared | do not run until C/D choose accepted combinations |
| F | vision capability | prepared | metadata/capability preflight before any image canary |

## Model admission summary fields

The final L3.28 decision record must keep these columns:

- `model_admission_status`
- `load_only_status`
- `generation_status`
- `structured_simple_status`
- `structured_blocks_status`
- `transcript_cleanup_status`
- `vision_route_status`
- `allowed_next_phase`
- `blocked_reason`

## Prepared admission table

| model | model_admission_status | load_only_status | generation_status | transcript_cleanup_status | structured_simple_status | structured_blocks_status | vision_route_status | allowed_next_phase | blocked_reason |
|---|---|---|---|---|---|---|---|---|---|
| google/gemma-4-e2b | known L3.27 text baseline | known/skip for L3.28b | prepared C1 | L3.27 pass; C1 pending | D pending | D pending | gated; no image route proof | pending L3.28 evidence | prepared-only slice |
| google/gemma-4-e4b | known L3.27 quality candidate | known/skip for L3.28b | prepared C1 | L3.27 pass; C1 pending | D pending | D pending | gated; no image route proof | pending L3.28 evidence | prepared-only slice |
| google/gemma-4-12b-qat | pending L3.28 load-only | B pending | prepared C1 if B passes | C1 pending | D pending | D pending hardened only | gated; no image route proof | pending load-only and canaries | no current load-only evidence in this slice |
| google/gemma-4-26b-a4b-qat | pending L3.28 load-only | B pending | C2 optional tiny only | C2 blocked until load-only + owner approval | not planned | not planned | gated; no image route proof | blocked by default | heavy model; no generation before clean load-only |

## Ready-to-run requirements

L3.28 is ready for live phases only after:

1. Phase C transcript cleanup is split so 26B is not automatic.
2. Phase B has a dedicated executable load-only command or reviewed exact operator path.
3. Structured RU fixtures no longer use English-only payloads.
4. Raw prose Phase C commands use platform temp output roots outside the repository.
5. This decision record keeps the model admission summary fields.
6. Full checks pass.

## Interim L3.29 policy

No model/mode is newly admitted into L3.29 by this prepared-only slice. L3.29 admission requires completed L3.28 live/load evidence and privacy-safe artifacts.
