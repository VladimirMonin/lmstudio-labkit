# Sequential long-transcript representation matrix

This phase-1 experiment isolates input representation. It has exactly 54 calls: three full-context representations × three non-overlapping source-ordered chunks × six models. It excludes warmup, cache claims, parallelism, microphone input, translation, retries, and native structured output.

The representations are contiguous plain text, timestamped paragraphs, and a JSON array of original Whisper blocks containing only stable neutral `id`, `start`, `end`, and `text` fields. Every matched request uses the same cleanup instruction and byte-identical authoritative current-chunk text. All outputs are plain cleaned Russian text.

## Private source contract

The source is an owner-verified sanitized long Russian Whisper transcript outside the repository. It must use schema `sanitized-whisper-transcript-v1`, set `owner_verified` and `sanitized` to `true`, provide ordered non-overlapping blocks, and provide exactly three ordered non-overlapping `[start, end)` representative block ranges for early, middle, and late chunks. The preparer rejects missing timestamps, unstable IDs, extra block fields, and overlapping ranges.

Canonical private root:

```text
$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1
```

Expected source path:

```text
$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1/source/sanitized-whisper.json
```

## Offline preparation

```bash
ROOT="$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1"
install -d -m 700 "$ROOT/plan" "$ROOT/review"

uv run python -m tools.lmstudio_lab.source_shaped_rehearsal prepare \
  --manifest experiments/lmstudio/source_shaped_rehearsal/v1/manifest.json \
  --source "$ROOT/source/sanitized-whisper.json" \
  --output "$ROOT/plan/frozen-plan.json"

uv run python -m tools.lmstudio_lab.source_shaped_rehearsal init-private-rubric \
  --template experiments/lmstudio/source_shaped_rehearsal/v1/manual_rubric.template.json \
  --output "$ROOT/review/manual-gold.json"
```

Preparation performs no model operation. The v2 manual rubric scores finish status, complete-current-chunk coverage, chunk-only behavior, outside-chunk spans, exact protected strings, allowlisted semantic canonicalization, uncertain ASR terms, punctuation, topic paragraphs, and beneficial versus harmful corrections as separate fields.

## Frozen 12B confirmation

Materialize the private, source-bound three-call plan offline:

```bash
ROOT="$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1"
uv run python -m tools.lmstudio_lab.source_shaped_rehearsal prepare-confirmation \
  --manifest experiments/lmstudio/source_shaped_rehearsal/v1/manifest.json \
  --source "$ROOT/source/sanitized-whisper.json" \
  --selector experiments/lmstudio/source_shaped_rehearsal/v1/confirmation_selector.json \
  --output "$ROOT/plan/frozen-12b-confirmation.json"
```

The selector is fixed to Gemma 4 12B QAT and, in order, plain/early (`c19`), timestamped-paragraphs/late (`c24`), and JSON-blocks/middle (`c26`). Reasoning is off, retries are zero, timeout is 900 seconds per request, and output remains derived as `ceil(exact current-chunk tokens × 1.5) + 256`.

The exact separately authorized live command is:

```bash
ROOT="$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1"
uv run python -m tools.lmstudio_lab.source_shaped_rehearsal execute --live \
  --plan "$ROOT/plan/frozen-12b-confirmation.json" \
  --load-config experiments/lmstudio/source_shaped_rehearsal/v1/load_config.json \
  --private-root "$ROOT/raw/12b-confirmation" \
  --request-timeout 900
```

## Live execution (not authorized by preparation)

Only after separate owner authorization:

```bash
ROOT="$HOME/.local/share/lmstudio-labkit/long-transcript-representation-v1"
uv run python -m tools.lmstudio_lab.source_shaped_rehearsal execute --live \
  --plan "$ROOT/plan/frozen-plan.json" \
  --load-config experiments/lmstudio/source_shaped_rehearsal/v1/load_config.json \
  --private-root "$ROOT/raw"
```

The driver requires global `loaded_total=0`, processes models in manifest order, performs nine serial calls per model, unloads, and requires `loaded_total=0` before continuing. There are no retries. Each formatted request is tokenized with the loaded model's LM Studio SDK tokenizer. Output budget is `ceil(current_chunk_tokens × 1.5) + 256`, with no fixed 512/2048 cap; context overflow fails closed. Requests set reasoning effort to `none`, and exposed non-zero reasoning tokens abort execution. Raw responses are immutable mode-0600 files outside the repository.

The six exact model keys are:

- `google/gemma-4-e2b`
- `google/gemma-4-e4b`
- `google/gemma-4-12b-qat`
- `google/gemma-4-26b-a4b-qat`
- `qwen/qwen3.5-4b`
- `qwen/qwen3.5-9b`

## Offline gates

```bash
uv run pytest -q tests/tools/test_source_shaped_rehearsal.py
uv run pytest -q tests/libs tests/tools tests/architecture
uv run ruff check .
uv run ruff format --check .
python scripts/audit_publication_safety.py
```

No model generation was performed while preparing this design.