# Structured route evidence reconciliation

Date: 2026-07-13

Status: offline evidence reconciliation. No model call, model load, network request, or raw private artifact publication was performed.

## Decision

Historical image evidence does not demonstrate API-bound strict JSON Schema.

The old 27-call representation run returned plain text. Its JSON-block axis changed only the input representation. L3.38 and L3.39 native structured-image rows requested JSON in prompts and validated it after generation. Their fence-normalized or schema-valid rows are useful prompt-following and grounding evidence, but they are not schema-bound structured output.

Text-only schema-bound evidence does exist. The focused correction used `/v1/responses` with `text.format.type=json_schema` and `strict=true`. The later 202-call host-application-shaped series used `/v1/chat/completions` with `response_format.type=json_schema` and `strict=true` on every call. Neither text series proves schema-bound vision.

Use these terms separately:

- **Plain text:** no JSON response contract was requested.
- **Prompt-only JSON:** the prompt requested JSON; no API schema field was sent.
- **Fence-normalized JSON:** one complete Markdown JSON fence was removed before parsing. This is recovered serialization, not raw JSON.
- **API-bound strict JSON Schema:** the outbound route-specific payload carried a JSON Schema field with `strict=true`.
- **Local schema validity:** caller-side validation after generation. It does not reveal how the request was constrained.

## Authoritative route and contract inventory

| Evidence | Route and response surface | Outbound contract | Denominator | Classification |
|---|---|---|---:|---|
| L3.34 prepared route probe | No route; no response | Offline image task and schema configuration only | 0 calls / 4 slots | Zero-call preparation |
| L3.34 compatibility image probe | `/v1/chat/completions`; `choices[0].message.content` | PNG data URI object; exact retained `response_format` is missing | 4 calls; 4 payload accepted; 0 schema pass; 4 length | Contract unverified; not schema-bound evidence |
| L3.34.1 compatibility repair | `/v1/chat/completions`; `choices[0].message.content` | PNG data URI; plain text; `max_tokens=256` | 1 call; 0 non-empty extracted text; 1 length | Plain text |
| Native E4B sequential gate | `/api/v1/chat`; `output[]` | Native text+image input; one plain gate, then prompt-requested minimal JSON; no API schema field | 2 calls; 1 plain pass; 0/1 raw JSON | Prompt-only JSON after a plain baseline |
| L3.38 E4B vision | `/api/v1/chat`; native SSE message text | Native message plus optional image data URL; two JSON prompts; caller-side contracts only | 3 calls; 2 JSON rows; 2 raw parse; 1 local schema pass; 0 grounded image pass | Prompt-only JSON |
| L3.38 12B repeated context | `/api/v1/chat`; native SSE message text | JSON requested in prompt; no API schema field | 6 calls; 0 raw parse; 6 fence-normalized and local-contract-valid | Fence-normalized prompt-only JSON |
| L3.38 strict-route investigation | `/v1/chat/completions`; planned compat surface | Documented `response_format=json_schema` shape, generation disabled | 0 calls | Zero-call schema-bound plan |
| L3.39 vision family matrix | `/api/v1/chat`; native SSE message text | Hash-pinned PNG plus JSON prompts; local fence/schema/grounding gates; no API schema field | E2B/E4B: 11/16 executed, 7 structured, 0 raw, 7 normalized, 3 schema. Full family: 17 structured, 0 raw, 17 normalized, 8 schema | Plain perception plus fence-normalized prompt-only JSON |
| 27-call representation slice | `/v1/chat/completions`; `choices[0].message.content` | `messages`, cap, disabled reasoning; no `response_format`; plain output | 27 retained / 54 planned; 27 plain output; 0 structured output | Plain text |
| Native structured correction/repeats | `/v1/responses`; `output[].content[].output_text` | `text.format.type=json_schema`, bound schema, `strict=true` | 12 authoritative + 2 boundary calls; 55/60 repeat outputs raw-or-fence recoverable | API-bound strict JSON Schema, text only |
| 202-call host-application-shaped series | `/v1/chat/completions`; `choices[0].message.content` | `response_format={type:json_schema,json_schema:{name,strict:true,schema}}` on every call; raw parser | 202 HTTP 200; 199 raw parseable; 157 primary, 33 repeat/cache, 12 parallel | API-bound strict JSON Schema, text only |

## Exact findings

### L3.34: preparation, compatibility surface, then native surface

The committed L3.34 configuration planned no executable calls because the committed model metadata was text-only. Its `strict_json_schema: true` setting is a preparation contract, not live evidence (`matrix.l3_34_gemma_vision_route_probe.yaml:145-167`).

A later four-model compatibility probe accepted four PNG data-URI payloads but ended in four length results and zero schema passes (`l3_34_gemma_vision_route_capability_decision_record.md:84-114`). The retained public evidence identifies the compatibility envelope and extraction surface, but it does not retain the exact outbound `response_format`. Therefore those calls cannot be safely relabeled either prompt-only or API-bound. They remain **contract unverified**.

The one-call L3.34.1 repair was explicitly plain text. The later native E4B gate corrected the response-surface issue: `/api/v1/chat` with `input:[text(content),image(data_url)]` returned output under `output[]`. Its plain call passed; its minimal-JSON call was malformed and non-truncated (`t_91fd364e_native_e4b_vision_gate_decision_record.md:20-90`). The JSON requirement was in the prompt, not in an API schema field.

### L3.38: local contracts are not wire contracts

The L3.38 runner sends `host.native_chat_diagnostic(...)` with messages, native reasoning control, cap, and optional `image_data_url`. The `ResponseContract` objects are consumed only by `validate_response(...)` after generation (`tools/lmstudio_lab/l3_38_followup.py:314-375,423-498`).

The E4B vision phase produced:

- one plain-text route preflight;
- one raw JSON text marker that passed the local schema;
- one raw JSON image marker that failed the grounded boolean.

These are two prompt-only JSON rows, not API-bound schema rows. The six 12B repeated-context responses were all rejected by the original strict-first validator because they were fenced. Offline removal of exactly one complete fence recovered 6/6 without semantic repair. That supports a narrow normalization policy but does not convert them into raw JSON or wire-bound schema output.

The separately documented OpenAI-compatible strict investigation ran zero requests. A documented request shape is not execution evidence (`strict_json_route_contract_decision.json:1-62`).

### L3.39 vision: structured prompts plus local gates

The L3.39 runner builds a native PNG input and calls `/api/v1/chat`. For structured stages it:

1. requests JSON in the prompt;
2. receives native message text;
3. applies raw-first parsing with optional one-complete-fence normalization;
4. validates a caller-owned schema;
5. applies business and image-grounding checks.

No `response_format`, `text.format`, or other API schema field is sent in this path (`tools/lmstudio_lab/l3_39_family_matrix.py:546-638,641-733,939-979`).

For E2B/E4B, 11 of 16 planned image requests executed; seven were structured. Raw JSON was 0/7, normalized JSON 7/7, and local schema validity 3/7 (`l3_39a_e2b_e4b_vision_results.md:11-47`). Across the five published full-axis model reports, 17 structured vision outputs executed: raw JSON 0/17, fence-normalized JSON 17/17, local schema validity 8/17. These denominators describe prompt-only structured vision.

The final L3.39 synthesis also reports a narrower 24-record fence replay across structured evidence, with 24 normalized parses and 15 schema passes. That replay denominator must not be substituted for the full structured-vision denominator or called native-schema success.

### The 27-call representation run was plain output

The representation runner sets `output_format: plain_text` for every request. Its live payload contains messages, `max_tokens`, temperature zero, and disabled-reasoning controls, but no `response_format` (`tools/lmstudio_lab/source_shaped_rehearsal.py:112-203,393-441`).

The retained phase contains 27 of a frozen 54 calls: nine each for plain, timestamped-paragraph, and JSON-block full-context representations. All 27 returned direct plain text. JSON blocks were an **input representation**, not a model output schema. The run therefore supplies 27 plain-text quality and boundary observations, zero prompt-only JSON outputs, and zero schema-bound outputs.

### The 202-call text series was schema-bound

The exact owner-only runners used one shared call builder. Every call posted to `/v1/chat/completions` with:

- `messages`;
- `response_format.type=json_schema`;
- `response_format.json_schema.name`;
- `response_format.json_schema.strict=true`;
- a bound schema;
- temperature zero and an explicit output cap;
- disabled thinking/reasoning controls.

The caller read `choices[0].message.content` and parsed the unmodified text with `json.loads`; no fence-normalization path was used. The three exact runner basenames were:

- `run_wvm_shaped_structured_v1.py`;
- `run_wvm_shaped_repeat_cache_v1.py`;
- `run_wvm_shaped_parallel_v1.py`.

The public summary reconciles 202/202 HTTP 200 and 199/202 raw parseable structured outputs: 155/157 primary, 32/33 repeat/cache, and 12/12 parallel (`2026-07-13_host_application_shaped_structured_context_summary.md:19-41`). These calls are API-bound strict JSON Schema evidence, but they are heterogeneous and are not 202 independent quality observations. They are also text-only.

### Native text schema evidence is separate

The focused structured correction used `/v1/responses` with `text.format.type=json_schema`, a bound schema, and `strict=true`; it extracted final text from `output[].content[].type=output_text` (`tools/lmstudio_lab/structured_output_correction.py:114-182`). This is also API-bound text evidence. Its raw/fenced/schema/semantic outcomes remain separate, as required by the structured-output audit.

## Claims that must be corrected

| Historical or possible claim | Verdict | Required correction |
|---|---|---|
| The 27-call representation matrix tested structured JSON output. | Contradicted | It tested three input representations and requested plain text in every retained call. |
| L3.39 schema-valid vision rows prove native or API-bound structured vision. | Contradicted | They prove prompt-following plus fence normalization, local schema checks, and bounded grounding only. |
| Fence-normalized JSON is raw JSON compliance. | Contradicted | Report raw parse, deterministic fence recovery, and schema validity separately. |
| Caller-side schema validation proves strict schema was bound on the wire. | Contradicted | Require the retained outbound route-specific schema field with `strict=true`. |
| The 80-call prompt-embedded overlay proves no JSON/schema capability. | Superseded | Its `accepted=0` is the combined strict verdict for that prompt contract; later `/v1/responses` evidence proves bounded text schema capability. |
| The 202-call text series proves schema-bound image output. | Unsupported | It proves text-only schema-bound output over `/v1/chat/completions`. |
| HTTP image acceptance, JSON syntax, schema validity, and grounding are interchangeable. | Contradicted | Keep transport, response surface, raw syntax, recovered syntax, schema, and grounding as independent gates. |

## Missing evidence and closure boundary

- No retained historical image request combines image input with a route-level strict JSON Schema field.
- The exact outbound `response_format` of the four-call L3.34 compatibility probe is absent from retained public evidence.
- No historical image row can be reclassified as API-bound from local schema results alone.
- Schema-bound image evidence therefore requires the separately reviewed closure runner and new live calls.

## Evidence sources

Primary repository sources inspected:

- `experiments/lmstudio/structured_matrix/configs/matrix.l3_34_gemma_vision_route_probe.yaml`
- `experiments/lmstudio/results_summaries/l3_34_gemma_vision_route_capability_decision_record.md`
- `experiments/lmstudio/results_summaries/l3_34_1_vision_probe_repair_decision_record.md`
- `experiments/lmstudio/results_summaries/t_91fd364e_native_e4b_vision_gate_decision_record.md`
- `tools/lmstudio_lab/l3_38_followup.py`
- `experiments/lmstudio/live_runs/l3_38_reasoning_off_followup/*.json`
- `tools/lmstudio_lab/l3_39_family_matrix.py`
- `experiments/lmstudio/results_summaries/l3_39*.md`
- `experiments/lmstudio/results_summaries/l3_39*.sanitized.json`
- `tools/lmstudio_lab/source_shaped_rehearsal.py`
- `experiments/lmstudio/results_summaries/2026-07-12_long_context_representation_analysis.md`
- `tools/lmstudio_lab/structured_output_correction.py`
- `experiments/lmstudio/results_summaries/2026-07-12_structured_output_and_scorer_audit.md`
- `experiments/lmstudio/results_summaries/2026-07-13_host_application_shaped_structured_context_summary.{md,json}`

The exact 202-call runner payloads were additionally checked in owner-only runner source without publishing private prompts, source text, responses, artifact paths, or image bytes.

Machine-readable companion: `2026-07-13_structured_route_evidence_reconciliation.json`.
