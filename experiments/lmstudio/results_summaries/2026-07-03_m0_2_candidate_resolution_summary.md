# M0.2 Candidate Resolution — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: safe candidate identity diagnostic, not model screening
- Registry: `experiments/lmstudio/models/candidates.yaml`
- Endpoint: `/v1/models`
- Endpoint class: OpenAI-compatible, localhost loopback
- Request method: `GET`
- Native load/unload/download endpoints: not called
- Generation endpoints: not called
- Cache/stateful/vision: not tested
- Registry written: no
- Raw provider response stored: no
- Raw source IDs stored: no

## Goal

M0.2 adds a safe diagnostic layer above M0.1 exact matching. It can suggest candidate compatible model IDs from `/v1/models`, but fuzzy suggestions remain unconfirmed until the user approves them.

The resolver records only safe counts, hashes, candidate lab keys, safe visible model IDs, match types, confidence labels, scores and safe matched tokens. It does not write `candidates.yaml`.

## Live run

Run ID: `m0_2_candidate_resolution_001`

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| Candidate count | `4` |
| Visible model count | `41` |
| Exact confirmed count | `1` |
| Unresolved-or-suggested count | `3` |
| Suggestion count | `8` |
| Requires user confirmation count | `8` |
| Response chars | `5055` |

## Candidate results

| Candidate | Status | Suggestions | Confirmation |
| --- | --- | --- | --- |
| `gemma4_e2b_q4km` | confirmed | `google/gemma-4-e2b` exact existing compat ID | not needed |
| `qwen35_4b_q4km` | suggested | `qwen/qwen3-4b-2507`, `qwen/qwen3-vl-4b`, `qwen3.5-4b` | required |
| `gemma4_e4b_q4km` | suggested | `google/gemma-3n-e4b`, `google/gemma-4-e4b` | required |
| `qwen35_9b_q4km` | suggested | `qwen/qwen3.5-9b`, `qwen.qwen3-reranker-0.6b`, `qwen/qwen3-14b` | required |

## Interpretation

M0.2 found likely compatible IDs for the unresolved registry candidates, but no registry update was made.

Best-looking suggestions by name intent are:

```text
qwen35_4b_q4km   -> qwen3.5-4b
gemma4_e4b_q4km  -> google/gemma-4-e4b
qwen35_9b_q4km   -> qwen/qwen3.5-9b
```

These still require explicit user confirmation before writing `compat_model_id` into the registry.

## Privacy check

Artifacts from `m0_2_candidate_resolution_001` were scanned for local paths, command lines, cwd, usernames, raw source IDs, GGUF source basenames, API keys, secrets and prompt/message/content sentinels. The scan found `0` hits.

## What this proves

- Safe `/v1/models` candidate resolution works without generation, native load, unload or download.
- The baseline `gemma4_e2b_q4km` remains exactly confirmed.
- The other three candidates have safe suggestion records, but they are not confirmed yet.
- Fuzzy resolution can support user confirmation without guessing registry IDs.

## What this does not prove yet

- It does not prove the suggested IDs are the intended GGUF files.
- It does not prove model quality, structured JSON behavior, plain text behavior, VRAM/RAM cost or throughput for the suggestions.
- It does not update `candidates.yaml`.

## Next gated steps

1. User confirms or rejects suggested compatible IDs.
2. Update `candidates.yaml` only for confirmed IDs.
3. Repeat safe `/v1/models` exact confirmation.
4. Start M1/M2 screening only for confirmed visible models.
