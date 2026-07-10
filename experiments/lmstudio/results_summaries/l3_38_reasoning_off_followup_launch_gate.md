# L3.38 reasoning-off follow-up launch gate

Status: prepared and offline-verified; live execution not performed by this task.

## Scope and executable contract

The canonical contract is:

`experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml`

The launcher is:

`tools/lmstudio_lab/l3_38_followup.py`

It reuses `LocalLMStudioHostRunner`, `LocalFailureForensics`, native SSE parsing, and the existing response validator. It does not introduce a second general benchmark runner.

The launcher enforces one request at a time and one loaded model instance globally. Every generating phase refuses a dirty starting state, requires an external private forensic directory, verifies the exact installed model key and requested native reasoning options before loading, verifies exactly one materialized target instance, cleans up its owned model, and requires global `loaded_count=0` before continuing. Any HTTP failure or non-terminal response aborts the remaining requests in that phase after cleanup.

## Offline validation

```bash
uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  validate

uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  plan
```

The plan contains at most 13 generation rows: two 26B 8k rows, two conditional 26B 16k rows, at most three E4B vision-gate rows, and six 12B repeated-context rows. The OpenAI-compatible investigation has zero generation rows.

## Exact serial launch commands

Set one base URL and create a private directory outside the repository. The output directory is gitignored live-run storage and contains sanitized summaries only.

```bash
export LMSTUDIO_BASE_URL="http://127.0.0.1:1234"
export L338_PRIVATE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/lmstudio-l338-private.XXXXXX")"
export L338_OUTPUT_DIR="experiments/lmstudio/live_runs/l3_38_reasoning_off_followup"
```

### Phase 1 — 26B MoE 8k paired canary

```bash
uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  run --phase moe_8k \
  --base-url "$LMSTUDIO_BASE_URL" \
  --private-dir "$L338_PRIVATE_DIR/moe_8k" \
  --output-dir "$L338_OUTPUT_DIR" \
  --live --allow-model-loads
```

Expected rows: 2, ordered `reasoning=off` then `reasoning=on`, both at context 8192 and cap 1024. Each row is a separate cold load/request/unload cell.

The pair is interpretable only when both HTTP requests reached a terminal boundary, both private forensic records exist, every cleanup passed, and the global loaded count returned to zero. Schema failure is still interpretable model/route evidence; transport, capture, or cleanup failure is not.

### Phase 2 — conditional 26B MoE 16k pair

Run only when `moe_8k.sanitized.json` reports `interpretable_pair: true`. The launcher verifies that condition itself.

```bash
uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  run --phase moe_16k \
  --base-url "$LMSTUDIO_BASE_URL" \
  --private-dir "$L338_PRIVATE_DIR/moe_16k" \
  --output-dir "$L338_OUTPUT_DIR" \
  --prior-summary "$L338_OUTPUT_DIR/moe_8k.sanitized.json" \
  --live --allow-model-loads
```

Expected rows: 2 with the same paired order and cap, now at context 16384. Each row remains a separate cold cell.

### Phase 3 — E4B native vision reasoning-off gate

```bash
uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  run --phase e4b_vision \
  --base-url "$LMSTUDIO_BASE_URL" \
  --private-dir "$L338_PRIVATE_DIR/e4b_vision" \
  --output-dir "$L338_OUTPUT_DIR" \
  --live --allow-model-loads
```

Expected rows: at most 3. The first cold cell is a text-only native route preflight with `reasoning=off`. The second cold cell requests minimal text-only JSON and must pass local schema validation. Only then does the third cold cell send the single hash-pinned public-safe WebP fixture and request `{"settings_dialog":true}`. Later gates are skipped if exact model metadata does not advertise vision, if plain text output is empty, or if the minimal text JSON is malformed or schema-invalid without truncation evidence.

### Phase 4 — 12B repeated-context comparison with valid output budget

```bash
uv run python -m tools.lmstudio_lab.l3_38_followup \
  --contract experiments/lmstudio/configs/l3_38_reasoning_off_followup.yaml \
  run --phase repeated_context_12b \
  --base-url "$LMSTUDIO_BASE_URL" \
  --private-dir "$L338_PRIVATE_DIR/repeated_context_12b" \
  --output-dir "$L338_OUTPUT_DIR" \
  --live --allow-model-loads
```

Expected rows: 6. The exact-repeat comparison runs three requests under one loaded instance; cleanup returns global count to zero; then the stable-prefix/dynamic-suffix comparison runs three requests under a fresh loaded instance. Every request uses native `reasoning=off`, cap 1024, `store=false`, and local schema validation. The summary reports timings and response validity only. It must not claim physical KV reuse or remote memory attribution.

## OpenAI-compatible strict JSON investigation

The contract records the documented strict `response_format=json_schema` request shape, but generation is disabled (`probe_enabled: false`, expected rows 0). The route has no separately proven reasoning-off request control in current evidence. A probe would therefore fail the requested reasoning-off comparison contract and is not launched by L3.38 preparation.

Enabling any strict-route generation requires a new reviewed contract that identifies a supported route-specific reasoning control. Do not pass native `reasoning` fields to `/v1/chat/completions` by assumption.

## Global stop conditions

Stop immediately on any of these conditions:

- non-zero or unverifiable global loaded count before a phase;
- requested reasoning mode absent from exact model capability metadata;
- load materialization is not exactly one target/global instance;
- HTTP, runtime, private-capture, or cleanup failure;
- non-zero global loaded count after cleanup;
- 16k requested without an interpretable 8k summary;
- vision metadata or text-route preflight failure;
- any attempt to enable the strict route without a proven reasoning-off contract.

Sanitized summaries contain hashes, lengths, validation categories, numeric native stats, lifecycle evidence, and no private forensic path. Raw response envelopes and reasoning/message text remain only in the external mode-0700 private pack. No prompt, response, reasoning text, image bytes, or private path belongs in Git.

## Non-claims

This preparation performed no live inference, model load, model download, network probe, commit, or push. It does not claim 26B structured quality, E4B structured vision acceptance, 12B KV reuse, remote memory behavior, or OpenAI-compatible reasoning-off support.
