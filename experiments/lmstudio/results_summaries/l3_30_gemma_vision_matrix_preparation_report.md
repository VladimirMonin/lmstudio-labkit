# L3.30 Gemma Vision Matrix Preparation Report

Status: prepared-only. No live image inference was run.

## Asset coverage

| image_type | coverage_status | image_ids |
|---|---|---|
| `ui_screenshot` | covered | ui_settings_ru_001 |
| `code_screenshot` | covered | code_python_editor_001 |
| `document_table` | covered | document_table_products_ru_001 |
| `chart_graph` | covered | chart_tasks_by_month_ru_001 |
| `people_scene` | covered | people_classroom_selected_001 |
| `mixed_dashboard` | covered | ui_queue_dashboard_ru_001 |
| `slide` | covered | slide_json_schema_ru_001, ui_style_guide_ru_001 |
| `screencast_frame` | missing | - |
| `technical_diagram` | covered | roadmap_timeline_2026_ru_001 |
| `dense_text_screen` | covered | terminal_logs_001 |

## Schema coverage

| schema | status |
|---|---|
| simple_description | prepared |
| medium_objects_text | prepared |
| complex_layout_extraction | prepared-only, not first live run |

## Validator coverage

Validator contracts are prepared in `experiments/lmstudio/structured_matrix/schemas/vision/vision_validator_contracts.yaml`:

- visible_text_recall
- visible_text_precision
- object_label_recall
- table_cell_accuracy
- chart_value_accuracy
- code_identifier_recall
- ui_control_recall
- person_count_accuracy
- forbidden_claims_check
- language_compliance
- json_schema

## Capability gating policy

All Gemma models remain text-only in the committed registry. Image live requires metadata/runtime proof. If no route is proven, classify as `no_image_route_available`, not a quality failure.

## Future canary shape

Eligible Gemma models x 4 assets (`ui_screenshot`, `document_table`, `chart_graph`, `code_screenshot`) x `simple_description` x `ru_ru` output x `max_side_1024`; hard cap 16.

## Future screening shape

Eligible Gemma models x 10 images x compatible task intents x `simple_description`/`medium_objects_text` x RU/EN output x 1024/512, capped/split before live; hard cap 120.

## Blocked conditions

- image live before capability proof;
- model download required;
- cleanup final zero cannot be proven;
- privacy scan fails;
- Qwen/Qwen-VL appears;
- throughput/parallel/session/warmup appears;
- complex schema appears in first live image run;
- raw prompt/response would be committed.

## Experiment readiness

L3.29 text/structured bounded matrix is prepared separately and should run first when inference returns. L3.30 vision capability/canary/screening is now prepared and waits for explicit approval plus capability proof.

## Pre-live correction

- `visible_text_policy`: `preserve_original_visible_text`; visible OCR text must not be translated.
- `description_language`: `output_language`.
- `summary_language`: `output_language`.
- Do not run the prepared image matrix live; it includes broader screening contracts and complex is prepared-only.
- Future tiny image live is represented by `matrix.l3_30c_gemma_vision_tiny_capability_live.yaml`, committed with `live=false` and `allow_image_live=false`; enabling it requires explicit approval and proven eligible image-capable Gemma models.

## Execution policy

1. Run L3.29 Gemma text/structured bounded matrix first when inference returns.
2. Run L3.30 vision route capability probe/preflight next.
3. Run tiny image canary only if capability is proven.
4. Do not run full 480-cell image cartesian, complex image schema live, Qwen VL, throughput/parallel/session/warmup.
