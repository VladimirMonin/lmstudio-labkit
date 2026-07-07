# S6 Managed-backed Lab Runner Live Conformance Summary

## Scope

- Date: 2026-07-04
- Branch: `next/modular-backend-lab`
- S6.1/S6.2 commit: `bc59fdea` (`tools: Добавить S6 managed-backed Lab runner`)
- Purpose: prove the Lab runner bridge can execute the S5 contour through `tools/lmstudio_lab.ManagedLabRunner`, which in turn uses `libs.lmstudio_managed` package clients.
- Live target: local LM Studio loopback.
- Out of scope: Matrix v2, host application runtime integration, `src/**`, QueueManager, UI, SQLite, migrations, vision, embeddings, cache/stateful settings, production defaults.

## Runner path

S6.3 exercised this direction:

```text
tools/lmstudio_lab.ManagedLabRunner
  -> libs.lmstudio_managed.client.ModelListClient
  -> libs.lmstudio_managed.client.DownloadClient
  -> libs.lmstudio_managed.client.LifecycleClient
  -> libs.lmstudio_managed.client.GenerationClient
  -> local LM Studio
```

The live transport was injected into the runner. No host application runtime, QueueManager, UI or SQLite path was involved.

## Fake-first gate before live

S6.1/S6.2 deterministic gate passed before S6.3:

```text
tests/tools/test_lmstudio_lab_managed_runner.py + managed package/boundary subset: 65 passed
ruff check: passed
ruff format --check: passed
```

Covered fake S5 quirks:

- `already_downloaded` terminal success;
- load echo config;
- unload `{}` success;
- unload identifier-only success;
- unload identifier plus error remains failure;
- nested `choices[0].finish_reason="length"`;
- structured/plain safe envelopes.

## S6.3 live results

| Step | Model | Result |
| --- | --- | --- |
| list compat/native models | registry targets | ✅ `compat_count=43`, `native_count=43`, `loaded_instance_count=0` |
| ensure downloaded | `qwen35_4b_q4km` | ✅ `already_downloaded`, `ready_on_disk=True`, terminal success |
| load | `qwen35_4b_q4km` | ✅ `load_reconcile_ok`, echo `context=8192`, `parallel=1`, instance ref present |
| exact unload | `qwen35_4b_q4km` | ✅ `unload_exact`, cleanup verified |
| load | `gemma4_e2b_q4km` | ✅ `load_reconcile_ok`, echo `context=8192`, `parallel=1`, instance ref present |
| structured small | `gemma4_e2b_q4km` | ✅ non-empty safe envelope, `finish_reason=stop`, no error |
| plain small | `gemma4_e2b_q4km` | ✅ non-empty safe envelope, `finish_reason=stop`, no error |
| exact unload | `gemma4_e2b_q4km` | ✅ `unload_exact`, cleanup verified |

Final cleanup proof:

```text
loaded_instance_count=0
```

No LM Studio model deletion was required.

## Safe artifact fields observed

The runner emitted safe summary dictionaries only:

- counts and booleans;
- status and error enum values;
- echo context/parallel;
- response hashes and char counts;
- token counts;
- finish/reasoning flags.

The live runner output did not store raw prompts, raw responses, raw messages, raw provider bodies, raw instance IDs, raw job IDs, local paths, URLs, API keys or host application user data.

## Matrix v2 readiness

S6 confirms that Matrix v2 can start through the managed-backed Lab path rather than the old Lab-only transport path.

Recommended Matrix v2 first set:

```text
gemma4_e2b_q4km
gemma4_e4b_q4km
qwen35_4b_q4km
qwen35_9b_q4km
```

Recommended first modes:

- identity / load echo;
- structured small;
- structured medium chunked sequential;
- true parallel only after sequential green;
- plain normalized app concurrency 1/2;
- system metrics.

Still out of scope until a separate gate: vision, embeddings, cache/stateful settings and host application runtime integration.
