# L3.27 Raw-Prose Quality Decision Record

## Decision

Accept E4B for the next hidden/dev host-app prototype. Accept E2B only as a lightweight fallback/minimal cleanup mode.

Do not move to a user-facing/default release claim from this result alone.

## Evidence

- 60/60 live attempts passed JSON/schema/privacy/lifecycle validation.
- 60 local-only raw cases were reviewed outside the repository.
- E4B had better overall acceptability and term handling than E2B.
- E2B had critical term/fact failures on mixed technical and model-name cases.
- E4B had a smaller but real term issue (`Qwen` -> `Kwen`) and shares weak self-correction cleanup on one case.

## Model policy

- Quality default: `google/gemma-4-e4b`
- Lightweight fallback: `google/gemma-4-e2b`
- Product mode: `transcript_cleanup/simple` only
- Prompt: `strict_no_new_facts_v2`

## Next step

Proceed to hidden/dev host-app prototype with guarded model policy and add term-preservation regression cases before expanding to 12B/Gemma family matrix.
