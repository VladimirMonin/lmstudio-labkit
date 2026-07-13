# L3.35 Gemma Vision Screening Decision Record

Status: full bounded simple/medium screening and three repeats executed. The
defective automated verdict is superseded as semantic evidence and preserved as a
validator failure record. No production admission or ranking is assigned.

This record began as a prepared-only capability gate. The later bounded matrix
executed the simple/medium rows and three repeats described below. It did not
download a model, run a full cartesian or complex image schema, test Qwen/VL,
stress the runtime, or track raw prompt/response/image artifacts in Git.

## Superseding full screening update — 2026-07-13

The sole blocker is no longer either the historical native minimal-JSON failure or
the later partial-gold controller 0/16 verdict. The cumulative bounded run executed
all simple and medium rows plus three authorized repeats:

```yaml
strict_simple:
  candidate_rows: 16
  executed_rows: 16
  raw_json: 16
  independent_schema_pass: 16
  per_model_raw_and_schema: 4_of_4
medium_objects_text:
  candidate_rows: 16
  executed_rows: 16
  raw_json: 16
  independent_schema_pass: 16
  grounded_objects_manual: 15_of_16
exact_repeat:
  candidate_rows: 4
  executed_rows: 3
  zero_call_rows: 1
  byte_identical_pairs: 3_of_3
controller_validator:
  initial_simple_verdict: 0_of_16
  full_strict_image_rejections: 35_of_35
  status: preserved_partial_gold_failure_record
  superseded_as_semantic_admission: true
admission:
  route_and_schema: accepted_bounded
  semantic_binary: not_assessed_under_valid_gate
  production: none
  ranking: unsupported
```

The compatible image-plus-strict-schema route is structurally confirmed. Direct
pixel/raw review found mixed text and warning quality, 15/16 grounded medium object
inventories, and three byte-identical UI repeat pairs. The automated 0/16 result is
not a valid semantic denominator because its supported-text lists were incomplete
for an open-world contract. It remains immutable evidence of validator failure.

No replacement binary gate or production threshold is invented from the manual
counts. Production admission and ranking remain unsupported, and repeatability is
limited to the exact three one-request pairs.

The original dependency, decision, and future shape below are historical. Where
they imply that simple screening has not started, this dated update supersedes
that interpretation without altering the old measurements.

## Dependency

L3.35 may run only after L3.34 proves at least one eligible image-capable Gemma route.

Historical L3.34 status:

```yaml
committed_gemma_modalities: text_only
runtime_metadata_vision_capability: true
native_e4b_plain_text: pass
native_e4b_minimal_json: failed_malformed_json_without_truncation
tiny_screening_attempt_count: 0
status: blocked_structured_vision_gate
```

## Historical decision

```yaml
l3_35_status: blocked
quality_failure: not_assessed
image_quality_attempt_count: 0
reason: native plain text passed, but the required minimal JSON gate failed
```

This is not an image-quality failure because screening never started. It is a
structured-output gate failure after native plain-text route capability passed.

## Historical prepared future shape

At that historical point, a future metadata check and tiny route probe would have
opened L3.35 with this canary:

```yaml
models:
  - eligible_gemma_models_only
assets:
  - ui_settings_ru_001
  - document_table_products_ru_001
  - chart_tasks_by_month_ru_001
  - code_python_editor_001
schema:
  - simple_description
resize:
  - max_side_1024
output_language:
  - ru_ru
max_requests: 4_to_8
```

At that historical point, only after the canary could small simple/medium screening
be considered, with compatibility pruning and `max_requests=120`.

## Historical forbidden scope before capability proof

- full image cartesian;
- complex image schema live;
- Qwen/Qwen-VL;
- image live request without metadata-positive route proof;
- raw prompt/response/image artifacts in Git.

## Historical future acceptance criteria

The prepared canary required all of the following:

```yaml
json_parse: pass
schema: pass
forbidden_claims: pass
visible_text_policy: respected
privacy_scan_status: pass
final_loaded_like_count: 0
raw_artifacts_tracked: false
```
