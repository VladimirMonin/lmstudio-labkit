# D3 Already-downloaded Idempotency — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio Lab acquisition experiment, not WVM runtime integration
- Lab key: `qwen35_4b_q4km`
- Model key: `qwen3.5-4b`
- Run ID: `d3_already_downloaded_qwen35_4b_002`

## Goal

Prove that requesting a download for an already present model is a terminal success, not an error, and does not enter a polling loop.

## API boundary

Allowed and used endpoint kinds:

```text
download
```

Planned but not used because the model was already present:

```text
download_status
```

Explicitly not used in this run:

```text
native_load
native_unload
compat_generation
wildcard_unload
cache/stateful
vision
WVM runtime
```

## Observed behavior

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| Download status | `already_downloaded` |
| Ready on disk | `true` |
| Endpoint kinds planned | `download`, `download_status` |
| Endpoint kinds used | `download` |
| Status polling rows | `0` |
| Load called | `false` |
| Generation called | `false` |
| Registry written | `false` |
| API token present | `false` |

## Privacy scan

Accepted artifacts were checked for raw endpoint paths, raw instance IDs, local/process paths, token values, raw provider bodies, chat/download endpoint paths and credential values.

Result:

```text
0 blocking hits
```

Notes:

- Artifact summaries use `endpoint_kinds_*`, not raw endpoint path fields.
- Source/download model references are stored as hashes.
- The existing environment metadata stores the env-var name `LM_API_TOKEN`, not its value.

## What this proves

- The acquisition path treats `already_downloaded` as terminal success.
- The downloader can report `ready_on_disk=true` without a status polling loop.
- Download state remains distinct from load state; no load/unload/generation calls were made.

## What this does not prove

- It does not verify native load config.
- It does not test generation quality.
- It does not update the registry.
- It does not test partial/resumed downloads.

## Design implication for managed backend

`ModelDownloadManager.ensure_downloaded()` should classify `already_downloaded` as success and return a ready-on-disk state without retrying or polling. Download idempotency is separate from lifecycle idempotency.
