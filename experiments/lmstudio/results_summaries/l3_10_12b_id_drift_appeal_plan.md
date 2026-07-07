# L3.10 12B ID Drift Appeal Plan

Status: lab-only appeal workflow for `gemma4_12b_qat` / `google/gemma-4-12b-qat` after the first L3.9 sequential managed-live Blocks JSON run produced one business/ID failure.

## L3.10a — failed-chunk ID forensics

Purpose: add sanitized chunk-level ID diagnostics to `metrics.jsonl` and `structured_errors.jsonl` so the appeal can record expected vs returned block-id sequences without storing raw prompt text or raw response text.

Known L3.9 failed chunk from existing sanitized artifact:

- artifact dir: `experiments/lmstudio/results_summaries/run_l3-9c-gemma-family-blocks-json-12b-qat-20260707_l3_9c_gemma_family_blocks_json_gemma4_12b_qat/`
- request_id: `batch_0001_chunk_0000`
- response_hash: `sha256:aed190389f285e69e5a4c53488f46c54f888d248fbfb79e97d7addb268c21c6b`
- prompt_hash: `sha256:44beb990bb1cf2dcf6ff5e567be489f694a841501c7e66d4f4889ef932e0cba6`
- current L3.9 status: parse/schema `pass`, business `fail`, duplicate/order failure, chunk `0`

Expected L3.10a output:

- `expected_ids`
- `returned_ids`
- `duplicate_ids`
- `missing_ids`
- `extra_ids`
- bounded `reordered_positions`
- `expected_count` / `returned_count`

All of the above must remain synthetic/numeric-only and privacy-safe.

## L3.10b-g — appeal sequence

- **L3.10b deterministic reruns:** repeat the same sequential managed-live config to check whether chunk `0` drift reproduces with the same sanitized request/response hashes and ID diagnostics shape.
- **L3.10c prompt hardening:** tighten the Blocks JSON instruction text only if reruns still drift; keep the same lab-only route and privacy policy.
  - `baseline` = current L3.9/L3.10a-b instruction text.
  - `strict_id_contract` = never change / duplicate / omit / reorder ids; exactly one output per input; keep ids even when text is empty.
  - `ultra_minimal_transform` = no summarization / merging / splitting / reordering; only normalize the text field while preserving ids exactly.
  - Configs: `l3_10c_gemma4_12b_qat_prompt_strict_id_contract.yaml` and `l3_10c_gemma4_12b_qat_prompt_ultra_minimal_transform.yaml`.
- **L3.10d schema hardening:** test whether stricter fixed-ID wording/schema examples reduce duplicate/missing/reordered ids without introducing reasoning leakage.
- **L3.10e chunk-size sensitivity:** evaluate whether smaller chunk sizes remove the chunk-0 failure while keeping the same sequential managed-live lifecycle contract.
- **L3.10f targeted retry policy:** allow a bounded retry experiment only after deterministic and prompt/schema checks, still storing sanitized artifacts only.
- **L3.10g final decision:** close as `pass`, `conditional_pass`, or `exclude_from_live_blocks_json` based on repeated sanitized evidence, not on one boolean-only L3.9 failure row.

## Guardrails

- lab-only
- no host application runtime
- no UI
- no QueueManager
- no `/v1/responses`
- no route matrix
- no 26B generation/live
- sanitized artifacts only
- no raw prompt storage
- no raw response storage
