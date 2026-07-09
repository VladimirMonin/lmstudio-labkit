# L3.30 Gemma Vision Matrix Preparation Decision Record

Status: prepared-only; no live image inference was run.

## Context

L3.28 Phase F was metadata/config preflight only. Current Gemma registry entries are text-only in this runtime, so image capability remains unproven.

A model with no image route must be classified as `no_image_route_available`, not as a visual quality failure.

## Asset pack

Prepared asset pack: `experiments/lmstudio/structured_matrix/datasets/image/l330_gemma_vision_asset_pack.yaml`.

Selected assets: 10 synthetic public-safe WebP fixtures with grounded expected YAML descriptions.

| image_id | image_type | primary check |
|---|---|---|
| `ui_settings_ru_001` | `ui_settings_ru` | Synthetic Russian model settings dialog with fields for model id, context length, temperature, JSON Schema state, and save/cancel actions. |
| `ui_queue_dashboard_ru_001` | `ui_queue_dashboard_ru` | Synthetic Russian processing queue dashboard with three files, statuses, progress values, total task count, and error count. |
| `code_python_editor_001` | `code_python_editor` | Synthetic dark-theme Python code editor screenshot with a project tree, utils.py tab, line numbers, and simple utility functions. |
| `terminal_logs_001` | `terminal_logs` | Synthetic terminal window with model lifecycle log lines, including load start, load done, retry scheduled, and cleanup done. |
| `slide_json_schema_ru_001` | `slide_json_schema_ru` | Synthetic Russian educational slide explaining JSON Schema with bullet points, process diagram, and schema example. |
| `document_table_products_ru_001` | `document_table_products_ru` | Synthetic Russian document editor window with a product table containing item ids, names, quantities, and prices. |
| `chart_tasks_by_month_ru_001` | `chart_tasks_by_month_ru` | Synthetic Russian bar chart showing completed tasks by month with four bars, labels, legend, and summary metrics. |
| `people_classroom_selected_001` | `people_classroom_selected` | Synthetic classroom scene with an instructor explaining an application architecture diagram to two students; no identity recognition is expected. |
| `roadmap_timeline_2026_ru_001` | `roadmap_timeline_2026_ru` | Synthetic Russian 2026 roadmap timeline slide with phases, months, milestones, progress summary, next milestone, and risk panel. |
| `ui_style_guide_ru_001` | `ui_style_guide_ru` | Synthetic Russian UI style guide slide with palette, typography, spacing, components, principles, and do/don’t examples. |

## Prepared configs

| config | status | expected current planned cells |
|---|---|---:|
| `matrix.l3_30a_gemma_vision_capability_gate.yaml` | prepared-only capability gate | 0 |
| `matrix.l3_30b_gemma_vision_prepared_matrix.yaml` | prepared-only full matrix contract | 0 |

The current planned request count is zero because Gemma model specs are text-only. This is intentional.

## Schema levels

| level | fields | live status |
|---|---|---|
| simple | `description`, `visible_text`, `warnings` | candidate after capability proof |
| medium | `image_type`, `summary`, `visible_text`, `objects`, `warnings` | candidate after simple canary |
| complex | nested `document`, `extracted_data`, `warnings` | prepared-only; not first live run |

## Resize policy

- primary: `max_side_1024`;
- fallback: `max_side_512`;
- crop: false;
- original-size is not the default.

## Future live gating

Before any image inference:

1. model metadata says image/multimodal;
2. runtime accepts image payloads;
3. tiny image canary passes;
4. cleanup final loaded instances can be proven zero;
5. privacy scan passes.

## Blocked scope

- Qwen / Qwen VL;
- throughput / parallel;
- session / warmup;
- complex schema as first live run;
- model downloads;
- raw prompt/response in git.
