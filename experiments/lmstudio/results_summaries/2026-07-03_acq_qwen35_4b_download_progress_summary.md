# ACQ Live Download Progress — qwen35_4b_q4km

## Scope

- Date: 2026-07-03
- Branch: `next/modular-backend-lab`
- Evidence level: live LM Studio acquisition experiment, not host application runtime integration
- Lab key: `qwen35_4b_q4km`
- Command kind: `acquire-candidate`
- Execute download: yes
- Poll download status: yes
- Native load/unload: not called
- Generation/chat: not called
- Registry write: no
- Raw source URL, source ID, filename, job ID, token, local path stored: no

## Goal

Verify that a fresh/missing LM Studio model can be requested through the native download API and that host application Lab can observe progress safely.

This experiment was run after the user removed `qwen3.5-4b` from LM Studio.

## API boundary

Only these LM Studio endpoints were used:

```text
POST /api/v1/models/download
GET /api/v1/models/download/status/:job_id
```

Explicitly not used:

```text
/api/v1/models/load
/api/v1/models/unload
/v1/chat/completions
```

## Live result

Run ID: `acq_live_qwen35_4b_q4km_001`

| Metric | Value |
| --- | ---: |
| Status | `ok` |
| Download status | `completed` |
| Ready on disk | `true` |
| Progress | `100%` |
| Downloaded bytes | `3383082464` |
| Total size bytes | `3383082464` |
| Status records | `280` |
| Poll records | `279` |
| Average positive speed | `61.68 Mbps` |
| Max observed speed | `191.539 Mbps` |
| API token present | `false` |
| Quantization requested from registry source | `Q4_K_M` |
| Quantization verified by acquisition artifact | `false` |
| Native key verified by acquisition artifact | `false` |

The acquisition artifact deliberately keeps `quantization_verified=false` and `native_key_verified=false`, because the download endpoint itself confirms download status, not full model identity.

## Post-download visibility check

After the download completed, safe GET-only visibility checks were run without storing raw provider responses.

OpenAI-compatible `/v1/models`:

```text
qwen3.5-4b visible: true
```

Native `/api/v1/models` filtered result:

| Field | Value |
| --- | --- |
| key | `qwen3.5-4b` |
| type | `llm` |
| format | `gguf` |
| quantization | `Q4_K_M` |
| bits per weight | `4` |
| params | `4B` |
| size bytes | `3383082464` |
| loaded instances | `0` |

This confirms the downloaded model is visible for inference and that native list reports the expected GGUF quantization. It still does not load the model into RAM/VRAM.

## Logging/progress behavior

Console logging emitted privacy-safe progress events with:

```text
lab_key
download_status
progress_percent
speed_mbps
poll_index
terminal ready_on_disk state
```

Example terminal state:

```text
status=ok download_status=completed ready_on_disk=True
```

The logs intentionally did not include raw source URL, raw job ID, token value, local path, or provider body.

## Privacy check

Accepted acquisition artifacts were scanned for:

```text
raw source id / raw HF URL / GGUF basename / local path / process fields / credential values / raw job id values
```

Result:

```text
0 hits
```

Committed acquisition tooling records status JSONL endpoint labels as `endpoint_kind` (`download`, `download_status`) rather than private-looking path fields. This keeps progress artifacts informative without weakening privacy. The live run evidence below remains the source for the download/progress result; the endpoint-kind cleanup is covered by the acquisition test suite and was not re-run as a second live download.

## What this proves

- LM Studio can download a missing candidate model through the native REST API.
- The Lab can poll progress until completion and preserve safe progress records.
- Download is separate from load: the model is ready on disk and has `loaded_instances=0` after the experiment.
- Post-download native model list can confirm key/format/quantization without generation.

## What this does not prove yet

- It does not prove generation quality.
- It does not prove structured JSON or plain-text benchmark behavior.
- It does not prove load config, context length, parallel, memory residency, unload behavior, or VRAM cost.
- It does not update `candidates.yaml`.

## Next gated steps

1. Commit acquisition diagnostic and this evidence summary after approval.
2. Update model registry only with explicitly confirmed compat/native/variant facts.
3. Start lifecycle load/unload/reconciliation probes before M1/M2 screening.
