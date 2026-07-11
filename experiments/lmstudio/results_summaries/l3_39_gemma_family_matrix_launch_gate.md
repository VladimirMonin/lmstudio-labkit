# L3.39 Gemma family matrix launch gate

Status: prepared offline; live execution is not authorized by this artifact.

## Scope

The L3.39 launcher defines one comparable native `/api/v1/chat` matrix for five exact model variants. It contains 108 maximum live rows and six offline L3.38 replay rows, for 114 matrix records total.

The model order is fixed: E2B, E4B, 12B QAT, 26B-A4B QAT, then exact Unsloth 31B IQ3_XXS. The Google 31B QAT model is not an allowed substitute. E2B, E4B, 12B, and 26B use explicit reasoning off/on rows only after exact capability preflight. Unsloth 31B uses `reasoning_omitted_unknown`; it is never included in off/on deltas.

## Matrix

- 27 text structure rows: simple, blocks, complex.
- 36 vision rows: unbiased perception plus simple, medium, complex structured extraction.
- 15 one-shot context rows: nominal 4k, 12k, and 28k inputs under 8k, 16k, and 32k load tiers.
- 30 session rows: three cold full-prefix requests and three requests under one loaded instance with stable message 1 and changing message 2.
- 6 offline replay records from the L3.38 12B private pack.

Context and session phases require an external exact per-model token-count map before any request. All live phases are serial, require private external capture, verify applied context and parallelism, unload owned instances, and require global loaded count zero before and after each batch.

## Offline commands

```bash
uv run python -m tools.lmstudio_lab.l3_39_family_matrix validate
uv run python -m tools.lmstudio_lab.l3_39_family_matrix plan
uv run python -m tools.lmstudio_lab.l3_39_family_matrix replay \
  --private-dir <external-l3.38-private-phase-dir> \
  --output <new-sanitized-json>
```

A live phase additionally requires both `--live` and `--allow-model-loads`, an external `--private-dir`, one exact `--model`, and one `--phase`. Completion of this offline implementation does not grant those flags.

## Parsing and review gates

Raw message bytes are parsed first. Only after strict failure may the opt-in parser unwrap one complete triple-backtick block with an optional `json` tag and whitespace-only exterior. It performs no semantic repair. Validation and output-budget observation use the same parser policy.

Every quality verdict requires a reviewer to read the private answer and fill the sanitized rubric. Token use, latency, parse validity, and schema validity are not qualitative vision/reasoning verdicts.

## Non-claims

No live inference, model load/download, network request, KV-reuse proof, cache-benefit claim, remote memory attribution, quality comparison, commit, or push was performed by this preparation.
