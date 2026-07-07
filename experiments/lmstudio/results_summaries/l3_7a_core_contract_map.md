# L3.7a — Core contract map

Date: 2026-07-06

## Contract map

- `ExperimentIdentity` — `experiment_id`, `run_id`, `schema_version`, `lab_only`, `production_default`, `wvm_runtime_integration`.
- `SafetyFlags` — generation/live authorization flags plus privacy-storage guards and `is_privacy_safe`.
- `ModelProfile` — public `model_key` / `model_id`, backend/profile metadata, allowed/blocked routes, recommended context lengths.
- `HardwareProfile` — reusable OS / CPU / RAM / GPU / VRAM and backend capability notes.
- `LoadProfile` — context length, parallel, flash-attention, KV offload, applied load config, ownership, cleanup policy.
- `RouteMode`, `RouteObservation`, `ResultClassification`, `ExperimentStatus` — stable route/result vocabulary. `ResultClassification` now exposes the full requested status-like set: `passed`, `blocked`, `blocked_internal_error`, `primary_candidate`, `research_latency_candidate`, `baseline`, `cache_accounting_candidate`, `production_blocked`.
- `ArtifactBundleSummary` — reusable summary for sanitized L3.6 artifact bundles.
- `LabEvidenceRef` — place for summary-only evidence such as L3.5 markdown closure notes.
- `ManagedCoreContract` — conservative aggregate contract with promotion gate property.

## Artifact schema

`LAB_ARTIFACT_SCHEMA` captures the shared filename set:

- `environment.json`
- `run_config.json`
- `load_response_sanitized.json`
- `requests.jsonl`
- `metrics.jsonl`
- `system_samples.jsonl`
- `system_summary.json`
- `comparison_summary.json`
- `privacy_scan.json`
- `report.md`

Notes:

- `comparison_summary.json` stays in the schema map but remains optional for single-route bundles like L3.6c r2.
- Privacy defaults remain strict: no raw prompt/response text, no raw state ids, no raw local URLs.
- Exact public-marker exemption is limited to `model_id` and `model_key` only, and only when the value exactly matches the bundle's public `model_id` / `model_key`.

## L3.5 / L3.6 evidence mapping

- L3.5 markdown-only summaries map to `LabEvidenceRef`.
- L3.6c sanitized bundle maps to `ArtifactBundleSummary` without a comparison payload.
- L3.6d sanitized bundle maps to `ArtifactBundleSummary` with preserved route classifications:
  - `compact_memory -> primary_candidate`
  - `native_chat_stateful -> research_latency_candidate`
  - `stateless_full_prefix -> baseline`

## Promotion guardrail

- Lab evidence still does **not** imply `production_default=true`.
- Lab evidence still does **not** imply `wvm_runtime_integration=true`.
- Lab evidence still does **not** imply `kv_reuse_proven=true`.
- `ManagedCoreContract.is_production_promotable` therefore stays blocked for current L3.5/L3.6 evidence.

## Internal draft recommendation baseline

- `compact_memory` — primary internal default.
- `native_chat_stateful` — research accelerator only.
- `stateless_full_prefix` — baseline / fallback.
- `openai_responses` — blocked for long-context use.
- No final user-facing recommendation is emitted in L3.7a.

## Next slice

- L3.7b: model registry / profile layer on top of these contracts.
