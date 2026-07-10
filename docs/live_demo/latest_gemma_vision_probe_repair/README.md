# Latest Gemma Vision Probe Repair

Source decision record:

```text
experiments/lmstudio/results_summaries/l3_34_1_vision_probe_repair_decision_record.md
```

Status: stopped at Phase 1.

## Summary

```yaml
asset: ui_settings_ru_001
model: google/gemma-4-e4b
phase: plain_text_image_route_sanity
payload: PNG data URI object
max_tokens: 256
http_status: 200
finish_reason: length
prompt_tokens: 298
completion_tokens: 256
response_char_count: 0
final_loaded_count: 0
status: fail
```

## Decision

The LM Studio API route accepted the image request, but Gemma E4B did not produce non-empty plain text before hitting `finish_reason=length`.

Because Phase 1 failed, the repair sequence stopped. Minimal JSON, simple_description, and other Gemma models were not run.

```yaml
l3_35_eligible_models: []
```

## Follow-up investigation summary

No new live image request was run for the follow-up investigation. Current LM Studio docs point to a more specific next repair path than increasing the same `max_tokens` cap:

- first try native `POST /api/v1/chat` with `input` items `{type: text, content: ...}` and `{type: image, data_url: data:image/png;base64,...}`;
- extract text from the native `output[]` response envelope rather than `choices[].message.content`;
- use the native `max_output_tokens` cap for that route;
- keep the next rerun to E4B + `ui_settings_ru_001` + plain text only, with an optional same-route 512-token retry only if the 128-token native probe is still empty/length-limited.

L3.35 stays blocked until a native/plain-text image route returns non-empty output and cleanup final zero.

No raw prompt/response text is stored here.
