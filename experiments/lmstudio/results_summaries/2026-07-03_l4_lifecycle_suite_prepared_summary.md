# L4 Lifecycle Suite Prepared — LM Studio Lab

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: code readiness + fake/offline QA + dry-run CLI plans
- Live load/unload executed: no
- GPU/VRAM touched by this suite: no
- host application runtime integration: no

## Goal

Prepare LM Studio lifecycle experiments before running any real VRAM-affecting load/unload operations.

The suite targets the lifecycle invariants needed for a future managed backend:

```text
ReadyOnDisk -> Load -> Echo config -> Reconcile native state -> Unload -> Reconcile
```

It also prepares diagnostics for externally changed LM Studio state, duplicate loaded instances, already-unloaded targets, and load-timeout reconciliation.

## Implemented CLI

```text
tools/lmstudio_benchmark.py probe-lifecycle
```

Default behavior:

```text
dry-run only
no network
no load
no unload
no generation
```

Real lifecycle actions require the explicit flag:

```text
--execute-lifecycle
```

This flag was **not** used during preparation because the GPU was occupied by another process.

## Prepared scenarios

| Scenario | Purpose | Live execution during prep |
| --- | --- | --- |
| `controlled_load_echo` | load with `echo_load_config`, then list-state verification | no |
| `unload_happy_path` | unload exact `instance_id`, then verify zero loaded instances | no |
| `external_unload_reconcile` | detect user/manual unload by polling native list state | no |
| `duplicate_load_guard` | detect duplicate loaded instances via native list only | no |
| `two_model_swap_plan` | plan `single_model_safe + wvm_owned_only` swap | no |
| `unload_already_gone` | treat already-missing instance as successful reconciliation | no |
| `load_timeout_reconcile` | recover from lost load response by reconciling native list state | no |

## API boundary

Execute mode is limited to native lifecycle endpoints:

```text
GET  /api/v1/models
POST /api/v1/models/load
POST /api/v1/models/unload
```

Explicitly excluded:

```text
/v1/chat/completions
/api/v1/models/download
wildcard unload
unload all
registry writes
```

Unload uses exact loaded `instance_id` in memory only. Persisted artifacts, reports and logs store `instance_id_hash`, never raw instance IDs.

## Verification

QA ran fake/offline checks only:

```text
tests/tools/test_lmstudio_lab_model_lifecycle.py: 9 passed
tests/tools/test_lmstudio_lab_load_probe.py: 10 passed
tests/tools/test_lmstudio_lab_model_acquisition.py: 11 passed
ruff check: passed
ruff format --check: passed
```

Dry-run CLI plans were generated for all seven scenarios with:

```text
execute_lifecycle: false
endpoint_paths_used: []
lifecycle_events.jsonl: empty
status: planned
```

Dry-run artifact privacy scan found no raw instance IDs, local/process paths, credential values, chat endpoints or download endpoints.

## Status categories prepared

The suite can classify:

```text
planned
ok
already_unloaded
externally_unloaded
duplicate_instances
not_loaded
still_loaded
load_succeeded_response_lost
load_unknown_after_timeout
reconcile_timeout
load_not_verified
transport_error
decode_error
invalid_shape
```

## What this proves

- Lifecycle probe code is ready for controlled live experiments when GPU is free.
- Dry-run plan generation is safe and does not touch LM Studio or VRAM.
- The future stuck-status bug class has explicit reconciliation scenarios prepared.
- Duplicate detection and exact-instance unload are modeled before product integration.

## What this does not prove yet

- No real model was loaded into RAM/VRAM by this suite.
- No real unload was performed.
- No memory deltas were measured.
- No production host application runtime/status fix was applied.

## Next gated live order

Run only when GPU is available:

```text
L4b controlled_load_echo
L4c unload_happy_path
L4d external_unload_reconcile
L4e duplicate_load_guard
L4f two_model_swap_plan
L4g unload_already_gone
L4h load_timeout_reconcile
```

After live lifecycle evidence exists, apply the minimal host application product fix: transitional UI/model states must reconcile against observed `/api/v1/models` state rather than trusting only desired command state.
