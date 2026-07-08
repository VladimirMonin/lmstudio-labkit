# Structured Matrix Benchmark Design

## Purpose

The structured matrix benchmark harness is a planned LabKit component for evaluating LM Studio models across configurable structured-output scenarios. It should support text, image, chat, structured, and non-structured request modes through the reusable request core while keeping artifacts publication-safe.

This document describes the target design. It does not claim that every lane is already implemented.

## Matrix axes

A benchmark matrix cell is the cartesian product of selected axis values. Config files should be able to reduce or expand any axis.

### Models

Models come from config, not hard-coded source lists.

Example fields:

- `model_key`
- `model_id`
- `display_name`
- `endpoint_family`
- `supported_modalities`
- `context_tiers`
- `notes`

### Modality

Allowed values:

- `text`
- `image`

The `image` modality includes image-only and mixed text/image requests. Mixed requests should declare text and image inputs explicitly in the request manifest.

### Language

Allowed values:

- `ru_ru` — Russian input, Russian output.
- `ru_en_mixed` — Russian input with English technical terms, mixed output allowed by task contract.
- `en_en` — English input, English output.
- `en_ru` — English input, Russian output.

Language validation should be task-specific rather than a naive character-count rule only.

### Structure complexity

Allowed values:

- `simple` — flat object or short list.
- `medium` — blocks, grouped records, moderate nesting.
- `complex` — nested entities, cross-references, per-item IDs, constraints, and optional fields.

### Volume

Allowed values:

- `single` — one compact request.
- `many` — multiple items or chunks in a normal batch.
- `stress` — high item count, larger context, or high concurrency. Stress runs must be explicit opt-in.

### Context tier

Allowed values:

- `8192`
- `16384`
- `32768`
- `model-specific`

The `model-specific` tier lets config map a model to its known safe context window. The planner should reject unsupported tiers unless config explicitly marks them experimental.

### Schema variant

Allowed values:

- `baseline_loose` — normal schema with enough flexibility to observe model behavior.
- `hardened_const` — stricter schema with constants, exact IDs, tighter enums, and stronger structural constraints.

### Retry policy

Allowed values:

- `off` — one attempt only.
- `retry1` — one retry after a validation failure, using a privacy-safe retry prompt template and no raw previous response in artifacts.

### Repeats

`repeats` is an integer repeat count per cell. Repeats should use stable run IDs and emit per-repeat and aggregate summaries.

## Text task families

### Simple flat

A compact extraction task with a flat JSON object or short flat list.

Typical checks:

- JSON parse
- JSON Schema
- required fields
- no placeholder text
- language compliance

### Medium blocks

A block reconstruction or grouped extraction task with stable item IDs.

Typical checks:

- exact ID coverage
- duplicate ID detection
- per-block field validation
- length ratio by field or block
- language compliance

### Complex nested

A nested document or multi-entity task with references between entities.

Typical checks:

- nested schema validation
- cross-reference integrity
- exact ID checks
- missing/duplicate entity checks
- field-level business validation
- length and completeness ratios

## Image task families

Image tasks should use public-safe or synthetic fixtures by default. Raw private screenshots must not enter public artifacts.

### `ui_screenshot`

Evaluate UI understanding from a screenshot.

Expected outputs may include visible controls, state, labels, layout facts, and requested action summaries.

### `code_screenshot`

Evaluate code understanding from a screenshot of source code or terminal output.

Expected outputs may include language, visible symbols, diagnostics, error class, and safe remediation categories.

### `document_table`

Evaluate extraction from a table in a document screenshot.

Expected outputs may include rows, columns, headers, totals, and normalized values.

### `chart_graph`

Evaluate chart or graph interpretation.

Expected outputs may include chart type, axes, series labels, trend direction, extrema, and caveats.

### `people_scene`

Evaluate non-identifying scene description.

Expected outputs should avoid identity claims. Allowed outputs may include count ranges, broad activity labels, visible objects, and safety-relevant scene facts.

### `mixed_text_image`

Evaluate combined text instruction plus image evidence.

Expected outputs may combine OCR-like extraction, visual facts, and task-specific structured fields.

## Validators

Validators should operate on stored result metadata and parsed outputs. They should not require raw prompts or raw responses in default artifacts.

### JSON parse

Checks whether the model output can be parsed as JSON after the allowed extraction policy. Records parse status and sanitized error category.

### JSON Schema

Checks the parsed value against the selected schema variant. Records pass/fail, schema version, and sanitized error counts.

### Pydantic/business validation

Checks task-specific constraints that are awkward to express in JSON Schema, such as cross-field consistency, value ranges, and normalized domain rules.

### ID exact checks

Checks exact expected IDs, missing IDs, duplicate IDs, ordering where relevant, and unexpected IDs.

### Length ratio

Checks output completeness using ratios against source or ground-truth expectations. Records numeric ratios, not raw source text.

### No placeholder text

Flags generic filler such as `TODO`, `N/A` where not allowed, `unknown` overuse, template remnants, or copied schema labels masquerading as answers.

### Language compliance

Checks whether output language matches the task contract: `ru_ru`, `ru_en_mixed`, `en_en`, or `en_ru`.

### Image ground truth

Checks image task outputs against public-safe ground-truth metadata: expected labels, counts, table cells, chart facts, UI controls, or scene facts.

## Artifacts

Every run should write deterministic, privacy-safe artifacts. Defaults must avoid raw prompts, raw responses, local paths, credentials, private screenshots, and private host-application context.

### `planner_summary.json`

Run plan metadata:

- run ID
- config hash
- selected axes
- cell count
- planned repeats
- live/offline mode
- privacy mode
- schema versions

### `cell_results.jsonl`

One JSON object per cell attempt:

- run ID
- cell ID
- repeat index
- model key and model ID
- axis values
- request metadata hashes
- response metadata hashes
- timing and token/resource metrics when available
- validation statuses
- sanitized error categories

### `cell_summary.csv`

Flat per-cell summary for spreadsheet review:

- cell ID
- axis values
- pass/fail status
- parse/schema/business/ID/language/image statuses
- retry outcome
- latency/resource fields

### `model_summary.csv`

Aggregated model-level summary:

- model key
- modality
- task family
- pass rates
- retry recovery rates
- failure categories
- resource/timing aggregates

### `failure_summary.csv`

Aggregated failure taxonomy:

- failure category
- axis values
- affected models
- count
- first/last run IDs
- retry recovery status

### `retry_summary.csv`

Retry-specific summary:

- retry policy
- initial failure type
- retry outcome
- recovery rate
- secondary failure category

### `resource_summary.csv`

Resource and performance summary:

- model key
- context tier
- token counts when available
- latency metrics
- throughput metrics
- memory or runtime metrics when safely available

### `privacy_scan.json`

Publication-safety scan summary:

- scanned artifact files
- policy version
- violations count
- sanitized violation categories
- pass/fail status

### `report.md`

Human-readable report generated from the safe artifacts. It should include:

- run configuration summary
- top-level pass/fail status
- key findings
- model and task comparisons
- failure taxonomy
- retry impact
- resource notes
- explicit limitations and non-claims

## Privacy requirements

Default artifacts must not contain:

- raw prompts
- raw responses
- local file paths
- private screenshots or private image paths
- credentials or tokens
- host-application names or private workflow names
- raw private transcripts

Default artifacts may contain:

- hashes
- counts
- statuses
- sanitized error categories
- model IDs
- axis values
- schema versions
- timing metrics
- token/resource metrics
- validation summaries

A separate private debug mode may be designed later, but it must be opt-in and must not be used for publishable artifacts.
