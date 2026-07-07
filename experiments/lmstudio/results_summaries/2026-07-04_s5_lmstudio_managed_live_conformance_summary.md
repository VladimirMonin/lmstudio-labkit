# S5 lmstudio_managed Live Conformance Summary

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- Purpose: prove the S4 fake-first `lmstudio_managed` package clients against a minimal live LM Studio localhost contour.
- Live target: local LM Studio at loopback.
- Out of scope: Matrix v2, WVM runtime integration, `src/**`, QueueManager, UI, SQLite, migrations, vision, embeddings, cache/stateful settings, production defaults.

## Conformance result

| Step | Package path | Model | Result |
| --- | --- | --- | --- |
| S5.1 model list | `ModelListClient.list_compat_models()` + `list_native_models()` | registry targets | ✅ compat/native parsed; `gemma4_e2b` and `qwen35_4b` visible |
| S5.2 download | `DownloadClient.ensure_downloaded()` | `qwen35_4b_q4km` | ✅ `already_downloaded`, `ready_on_disk=True`, terminal success |
| S5.3 lifecycle | `LifecycleClient.load_model()` + `unload_instance()` | `qwen35_4b_q4km` | ✅ load echo `context=8192`, `parallel=1`; exact unload; cleanup verified |
| S5.4 structured generation | `GenerationClient.complete_structured()` | `gemma4_e2b_q4km` | ✅ safe non-empty envelope, hash present, no error |
| S5.4 plain generation | `GenerationClient.complete_plain_text()` | `gemma4_e2b_q4km` | ✅ safe non-empty envelope, hash present, finish `stop`, no error |

Final cleanup proof:

```text
final_loaded_instances=0
```

No LM Studio model deletion was required.

## Live observations

S5 intentionally used minimal live requests, not a benchmark matrix:

- no repeated benchmark runs;
- no true-parallel matrix;
- no heavy model sweep;
- no vision or embeddings;
- no WVM runtime path.

The live contour proved that the package clients can perform:

```text
list models
already_downloaded
load echo
exact unload
structured small generation
plain small generation
cleanup verification
```

## Contract gaps found and fixed

### 1. Native unload success payload shape

Observed live behavior:

- exact unload may return an empty JSON mapping;
- exact unload may return a mapping containing only an instance identifier field;
- final state can still verify `loaded_instances=0`.

Package fix:

- `LifecycleClient.unload_instance()` now treats HTTP-ok empty mapping and identifier-only mapping as `UNLOAD_EXACT` success;
- identifier-only success is intentionally narrow: mappings with extra non-alias fields such as `error` do not get upgraded to success;
- raw instance identifiers are not returned or stored in public DTOs.

### 2. Nested OpenAI-compatible finish reason

Observed live behavior:

- `finish_reason` may be present at `choices[0].finish_reason` rather than top-level `finish_reason`.

Package fix:

- `generation_envelope_from_fake_payload()` now reads top-level `finish_reason` first;
- if top-level is absent, it falls back to `choices[0].finish_reason`;
- nested `finish_reason="length"` maps to `GenerationFailureKind.FINISH_LENGTH`.

## Privacy and artifact boundary

S5 retained safe public artifacts only:

- response/content hashes;
- char counts;
- token counts;
- finish/error enums;
- status booleans;
- safe model keys and counts.

S5 did not store raw prompts, raw responses, raw messages, raw provider bodies, raw instance IDs, raw job IDs, local paths, URLs, API keys or WVM user data.

## Verification

Deterministic regression gate after S5 fixes:

```text
pytest targeted S4/S5 contract pack: 97 passed
ruff check: passed
ruff format --check: passed
```

Live conformance observations after fixes:

```text
S5.1 model-list: compat/native ok, target models present, loaded_instances=0
S5.2 download: status=already_downloaded, ready_on_disk=True
S5.3 lifecycle: load_reconcile_ok, echo_context=8192, echo_parallel=1, unload_exact, final_loaded_instances=0
S5.4 generation: structured non-empty/no error; plain non-empty/no error; final_loaded_instances=0
```

## Next gate

S5 makes Matrix v2 possible, but Matrix v2 should not start directly from the old Lab-only path.

Next recommended step:

```text
S6 managed-backed Lab runner bridge
```

S6 should make future Lab and Matrix v2 executions flow through `lmstudio_managed` package clients first:

```text
tools/lmstudio_lab -> libs/lmstudio_managed client/contracts -> LM Studio
```

Only after S6 fake-first tests and tiny live conformance should Matrix v2 begin.
