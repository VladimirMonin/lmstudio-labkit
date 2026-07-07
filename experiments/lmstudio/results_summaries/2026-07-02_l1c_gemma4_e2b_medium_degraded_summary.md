# L1c Medium Structured JSON Evidence — Degraded

## Scope

- Date: 2026-07-02
- Branch: `next/modular-backend-lab`
- Evidence level: controlled live medium probe, degraded result
- Model ID: `google/gemma-4-e2b`
- Dataset ID: `blocks_json_medium`
- Blocks: `100`
- Endpoint: `/v1/chat/completions`
- Base URL class: localhost loopback
- Response format: `json_schema`
- Temperature: `0`
- Requested context length in Lab config: `32768`
- Observed effective total-token ceiling: `8192`
- Load/config echo verification: not performed
- Raw prompt/response/messages/content stored: no

## Probe v1

| Metric | Value |
| --- | ---: |
| Warmup result | timeout at about `30031 ms` |
| Measured runs | `3` |
| Measured `finish_reason=length` | `3/3` |
| Measured `json_parse_pass` | `0/3` |
| Measured `schema_pass` | `0/3` |
| Measured `business_pass` | `0/3` |
| Prompt tokens | `4759` |
| Completion tokens | `3433` |
| Total tokens | `8192` |
| Response chars | `13950` |
| Structured error categories | `json` x3, `timeout` x1 |

## Probe v2 after remediation

Remediation before v2:

- medium prompt requested concise `normalized_text` and no source-paragraph copying;
- `finish_reason=length` was made dominant over truncated-JSON classification.

| Metric | Value |
| --- | ---: |
| Warmup result | timeout at about `30032 ms` |
| Measured runs | `3` |
| Measured `finish_reason=length` | `3/3` |
| Measured `json_parse_pass` | `0/3` |
| Measured `schema_pass` | `0/3` |
| Measured `business_pass` | `0/3` |
| Error category | `finish` |
| Prompt tokens | `4793` |
| Completion tokens | `3399` |
| Total tokens | `8192` |
| Max tokens requested | `7500` |
| Requested context length recorded in metrics | `32768` |
| Measured average latency | `29135 ms` |
| Structured error categories | `finish` x3, `timeout` x1 |

## Interpretation

The medium result is degraded, but it is useful evidence rather than a generic JSON failure.

The stable token pattern indicates a context/load-profile limit:

```text
prompt_tokens + completion_tokens = 8192
finish_reason = length
```

The current loaded runtime behaved like an `8192` total-token context despite the Lab config requesting `32768`. Because no controlled load or config echo was performed, the requested context length is not yet proven as the actually applied runtime context.

## What this proves

- `blocks_json_medium` is too large for the currently observed loaded runtime profile as a single structured-output request.
- The Lab correctly preserved privacy-safe artifacts during degraded live runs.
- The Lab now classifies truncation by `finish_reason=length` as `finish`, not as a generic JSON failure.
- Medium single-request success cannot be evaluated until actual loaded model context is verified.

## What this does not prove

- It does not prove that `google/gemma-4-e2b` cannot handle medium structured output.
- It does not prove that `factual_blocks.v1` is unstable on medium workloads.
- It does not prove that `32768` context failed, because actual loaded context was not verified.
- It does not evaluate parallel, cache, stateful, load/unload, long context, or vision behavior.

## Token-estimate note

The medium manifest records `estimated_input_tokens=6700`, while the live full request reported about `4759` prompt tokens. These values should not be compared as identical scopes without an explicit scope field. Future Lab metrics should distinguish at least:

- `dataset_only` estimate scope;
- `full_request` prompt token measurement.

## Next gate

Do not continue shrinking the medium prompt blindly. The next technical gate should verify the actual loaded model configuration first:

1. **L4a loaded model config visibility probe**
   - `GET /api/v1/models` only;
   - no prompt;
   - no generation;
   - no raw full response storage;
   - safe model/config fields only.
2. **L4b controlled load/config echo probe**
   - same model ID;
   - requested `context_length=32768`;
   - `parallel=1`;
   - record requested vs actual config;
   - no wildcard unload and no lifecycle automation beyond the controlled probe.
3. **Medium retry** only after actual context is verified.
