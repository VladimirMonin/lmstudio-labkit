# Publishable Private Benchmark Pack Contract

## Status and scope

This document freezes the production contract implemented by the publishable v1 benchmark pack for 16 approved private transcript views. It specifies structure, validation, privacy, provenance, deterministic scoring, and review gates. The public asset tree is present under `experiments/lmstudio/private_benchmark_pack/v1/`; this document contains no private source material, source mappings, identifiers, or model output.

The approved view set is identified only by opaque labels:

- short and stress views: `M01`, `M02`, `M03`, `M04`, `M05`, `M07`, `M08`, `M09`, `M10`, `M11`;
- processed-recording views: `V10`, `V20`, `V30`;
- long-recording views: `L02-E`, `L02-M`, `L02-L`.

These labels are benchmark identities, not source identities. Public artifacts must not provide enough information to reverse-map a label to a source record.

## Security model

The pack has two physically separate trees:

1. A private preparation tree contains source mappings, original text, exact ordered units, redaction spans, reviewer evidence, and restricted model outputs.
2. A publishable tree contains only approved redacted fixtures, public-safe metadata, schemas, rubrics, and aggregate results.

The private tree must be outside the repository. No relative or absolute pointer from a committed file may locate it. The publishable tree must be reproducible from a reviewed immutable private manifest, but the repository must not contain the manifest, its source mapping, its redaction map, or a digest that can be used as a public oracle for guessing private content.

Fail closed when a required private field, review, digest, or assertion is absent. A preparation failure must not emit a partial public asset.

## Directory layout

The implemented v1 publishable tree is:

```text
experiments/lmstudio/private_benchmark_pack/v1/
  README.md
  pack.json
  task_bindings.json
  schemas/
    public_pack_v1.schema.json
    public_view_v1.schema.json
    normalization_output_v1.schema.json
    blocks_output_v1.schema.json
    stitch_output_v1.schema.json
    probe_output_v1.schema.json
    scorecard_v1.schema.json
    task_bindings_v1.schema.json
    structural_gold_v1.schema.json
    chunk_map_v1.schema.json
    sanitized_blocks_v1.schema.json
    reference_candidate_v1.schema.json
    rubric_v1.schema.json
    semantic_gold_v1.schema.json
    aggregate_v1.schema.json
    semantic_review_v1.schema.json
    private_replay_evidence_v1.schema.json
  views/
    <opaque-view-label>/
      fixture.json
      structural_gold.json
      semantic_gold.json        # only when manually approved
      rubric.json
  prompts/
    <prompt-version>.txt
  reports/
    aggregate.sanitized.json
    semantic_review.sanitized.json
    private_replay.sanitized.json
```

The private preparation tree must use a separate root with permissions restricted to its owner. Its logical layout is:

```text
<private-root>/
  manifest.json
  manifest.sha256
  source-mapping.json
  redaction-map.json
  reviews/
  source-snapshots/
  model-outputs/
```

The private paths above are logical names only. They must never be copied into public metadata, logs, reports, tests, or documentation.

## Common JSON rules

All JSON documents use UTF-8, JSON Schema draft 2020-12, and `additionalProperties: false` at every object level. Schema versions are immutable strings. A schema change requires a new version and a new pack version; in-place reinterpretation is forbidden.

Canonical JSON for digests uses RFC 8785 JSON Canonicalization Scheme. Text digests use the exact UTF-8 byte sequence of the specified field. Digests are lowercase SHA-256 hexadecimal strings. Public digests may cover only public-safe data.

Ranges use zero-based half-open intervals `[start, end)`. Unit ranges address ordered units, not characters. Character spans address Unicode scalar-value indexes in the exact stored string. Implementations must reject invalid boundaries, overlaps not explicitly allowed by the schema, negative values, and `start >= end`.

## Private manifest schema

The immutable private manifest is the sole authority connecting opaque labels to restricted source material. The normative shape is:

```json
{
  "schema_version": "private-manifest-v1",
  "pack_version": "v1",
  "created_at": "RFC3339 timestamp",
  "normalization_policy_version": "whitespace-v1",
  "redaction_policy_version": "span-redaction-v1",
  "views": [
    {
      "view_label": "opaque label",
      "source_class": "microphone|processed_recording|long_recording",
      "source_locator": "private value",
      "view_kind": "raw_record|ordered_segments|ordered_blocks|chunk_sequence",
      "source_text": "private value",
      "source_text_sha256": "64 lowercase hex characters",
      "ordered_units": [
        {
          "unit_index": 0,
          "text": "private value",
          "text_sha256": "64 lowercase hex characters"
        }
      ],
      "provenance_class": "RAW_SEGMENT_EXACT|RAW_BLOCK_EXACT|PROCESSED_BLOCK_EXACT|CHUNK_MAP_EXACT|REFERENCE_ONLY|RAW_ONLY",
      "reconstruction_assertions": ["enum"],
      "redaction_spans": [
        {
          "start": 0,
          "end": 1,
          "placeholder": "PERSON_001",
          "placeholder_class": "PERSON",
          "source_sha256": "64 lowercase hex characters"
        }
      ],
      "semantic_gold_status": "absent|reference_candidate|draft|single_reviewed|approved|rejected",
      "review_ids": ["private opaque review identifier"]
    }
  ]
}
```

`source_locator`, source text, units, redaction spans, span digests, review identifiers, and source mapping are private-only. A public manifest must not be made by deleting selected keys from this object; public documents are built independently against their own schemas.

### Immutability procedure

Before any asset generation or model call:

1. Serialize and validate the complete private manifest.
2. Canonicalize it and compute its SHA-256 digest.
3. Write the digest to a separate private checklist.
4. Set the manifest and checklist read-only for the owner and make their parent directories owner-only.
5. Re-read both files, verify permissions and digest, and record the successful preflight privately.
6. Bind every generated private or public candidate to that digest inside private review evidence only.

A writable manifest, digest mismatch, changed label order, changed policy version, or unverifiable permission state invalidates the preparation run. Any change requires a new manifest digest and re-execution of all dependent reviews. Existing approved outputs must not be silently rebound.

## Public pack and view schemas

The public pack index contains no source locator, private digest, exact source duration, timestamp, filename, topic, person, account, or candidate mapping.

```json
{
  "schema_version": "public-pack-v1",
  "pack_version": "v1",
  "view_count": 16,
  "view_labels": ["opaque label"],
  "prompt_versions": ["opaque version"],
  "schema_versions": ["opaque version"],
  "privacy_review": "approved",
  "semantic_review": "complete|partial",
  "media_resolution": "unresolved|partially_resolved|resolved",
  "claims": ["enum"],
  "public_tree_sha256": "64 lowercase hex characters"
}
```

Each `fixture.json` has this shape:

```json
{
  "schema_version": "public-view-v1",
  "pack_version": "v1",
  "view_label": "opaque label",
  "source_class": "microphone|processed_recording|long_recording",
  "duration_tier": "S|M|L|XL|XXL",
  "risk_bucket": "low|medium|high",
  "anomaly_classes": ["enum"],
  "input_view": "raw_record|ordered_segments|ordered_blocks|chunk_sequence",
  "ordered_units": [
    {
      "unit_index": 0,
      "text": "redacted public text"
    }
  ],
  "public_structure_sha256": "64 lowercase hex characters",
  "provenance_claims": ["enum"],
  "semantic_gold_status": "absent|reference_candidate|approved",
  "media_resolution": "unresolved|partially_resolved|resolved"
}
```

`duration_tier` is coarse and fixed before publication review. Exact durations and relative timing buckets are excluded unless a reviewer proves they are non-identifying and necessary. `anomaly_classes`, `provenance_claims`, and `claims` must come from versioned public enums; free-form source descriptions are forbidden.

## Deterministic span-based redaction

Redaction operates on the exact private source string before any normalization, paragraphing, or semantic editing.

1. A declared reviewer marks Unicode scalar-value spans and assigns placeholder classes; reviewer type and method are recorded privately.
2. Spans are sorted by `(start, end, placeholder_class)`.
3. Spans must be non-overlapping. Adjacent spans remain distinct unless the reviewer explicitly replaces them with one reviewed span.
4. Each unique private entity receives one stable placeholder within one view. Placeholder identifiers are view-scoped and must not be reused to express cross-view identity; different entities within a view never share a placeholder.
5. Replacement runs from the highest start index to the lowest so earlier indexes remain stable.
6. The implementation verifies each span against its private source digest before replacement.
7. A second pass rejects residual protected material and unknown placeholder-like tokens.
8. Running the same policy on the same manifest must produce byte-identical public text and canonical JSON.

Redaction must not be implemented with unordered regular-expression substitution, model-generated rewriting, fuzzy matching, or post-hoc search-and-replace. Semantic edits occur only after deterministic redaction and are reviewed separately.

### Placeholder taxonomy

Allowed placeholders are uppercase ASCII tokens matching `^[A-Z][A-Z0-9_]*_[0-9]{3}$` and belonging to this closed taxonomy:

- `PERSON_NNN`: personal names, handles, or speaker-identifying aliases;
- `CONTACT_NNN`: email addresses, phone numbers, messaging identifiers, or contact links;
- `ACCOUNT_NNN`: account, customer, tenant, or organization-specific account identifiers;
- `LOCATION_NNN`: private or precise locations;
- `ORG_NNN`: non-public or identifying organization names;
- `PRODUCT_NNN`: private product or project names;
- `ENTITY_NNN`: identifying entities not covered above;
- `DATE_NNN`: identifying exact dates or date-time values;
- `PATH_NNN`: filenames, local paths, URLs, storage keys, or repository-external locators;
- `SECRET_NNN`: credentials or secret-like values; encountering this class also triggers a security review;
- `RARE_NNN`: rare phrases or identifiers that remain identifying in context.

Placeholders are atomic protected tokens. Loss, mutation, translation, case change, splitting, merging, reordering, duplication, or invention is a hard failure. Public files must contain no placeholder-to-source mapping.

## Provenance classes

Provenance claims describe reproducible text transformations, not semantic or audio truth.

- `RAW_SEGMENT_EXACT`: ordered source segments reconstruct the stored raw segment representation exactly under the named whitespace policy and byte digest.
- `RAW_BLOCK_EXACT`: ordered raw blocks reconstruct the stored raw record representation exactly.
- `PROCESSED_BLOCK_EXACT`: ordered processed blocks reconstruct the stored record-level postprocessed representation exactly. This does not make that representation semantic gold.
- `CHUNK_MAP_EXACT`: the chunk map has complete ordered ownership with no missing, duplicate, or foreign unit.
- `REFERENCE_ONLY`: a comparison is relative to a stored textual reference and is not independently adjudicated truth.
- `RAW_ONLY`: no stored postprocessed representation is used as a target.

A view may carry multiple compatible claims in private evidence. Public `provenance_claims` expose only reviewed class names, never source digests or mappings.

## Exact reconstruction assertions

The preparation validator must make each assertion independently and record pass/fail privately:

- `raw_utf8_digest_match`: exact raw bytes match the manifest digest;
- `unit_index_contiguous`: indexes are exactly `0..n-1`;
- `unit_order_exact`: no reordering occurred;
- `unit_coverage_exact`: every required source unit is owned exactly once;
- `unit_text_digest_match`: every unit matches its private digest;
- `raw_segment_reconstruction_exact`: versioned whitespace reconstruction equals the stored raw segment representation;
- `raw_block_reconstruction_exact`: versioned whitespace reconstruction equals the stored raw record representation;
- `processed_block_reconstruction_exact`: when present, processed blocks equal the stored postprocessed representation;
- `chunk_map_exact`: when present, chunk ranges are monotonic, non-overlapping, complete, and foreign-unit free;
- `redaction_deterministic`: repeated redaction produces byte-identical output;
- `placeholder_bijection_exact`: private entities and placeholders have a one-to-one mapping within each class and view, with no public cross-view identity claim;
- `public_schema_exact`: every emitted document validates with no additional properties;
- `public_tree_digest_match`: the canonical public tree matches the reviewed public digest.

Whitespace policy `whitespace-v1` must be specified as executable behavior before assets are created. Until that implementation and its tests exist, reconstruction claims remain inherited analysis requirements rather than executable pack evidence.

## Model-output schemas

All model-output schemas require exact JSON objects and reject extra properties. Raw JSON parsing and schema validation are separate metrics. A transport-only removal of one outer Markdown code fence may be measured separately; no semantic repair is allowed.

### Normalization output

```json
{
  "schema_version": "normalization-v1",
  "normalized_text": "string",
  "preserved_placeholders": ["PERSON_001"],
  "uncertain_spans": [
    {
      "source_unit_start": 0,
      "source_unit_end": 1,
      "category": "unclear|possible_omission|possible_repetition|possible_entity_issue"
    }
  ],
  "input_digest": "public fixture digest"
}
```

### Structured blocks output

```json
{
  "schema_version": "blocks-v1",
  "blocks": [
    {
      "block_index": 0,
      "source_unit_start": 0,
      "source_unit_end": 1,
      "normalized_text": "string",
      "labels": ["enum"]
    }
  ],
  "warnings": ["enum"],
  "input_digest": "public fixture digest",
  "output_digest": "canonical public output digest"
}
```

### Stitching output

```json
{
  "schema_version": "stitch-v1",
  "stitched_text": "string",
  "duplicate_ranges": [{"start": 0, "end": 1}],
  "missing_ranges": [{"start": 0, "end": 1}],
  "order_errors": [{"left": 1, "right": 0}],
  "structure_digest": "public structure digest"
}
```

### Retention and contamination probe output

```json
{
  "schema_version": "probe-v1",
  "probe_id": "opaque public identifier",
  "answer": "enum or keyed public marker",
  "cited_unit_ranges": [{"start": 0, "end": 1}],
  "unknown": false
}
```

## Semantic-gold policy

Structural gold and semantic gold are separate assets.

Structural gold may be generated only from exact provenance assertions: unit order, coverage, ownership, reconstruction, public digests, placeholder inventory, and schema identity. A stored postprocessed transcript is never promoted automatically to semantic gold.

Semantic gold requires all of the following:

1. Deterministic redaction and privacy review have passed.
2. A declared reviewer authors or corrects the target without seeing model outputs for the evaluated run; reviewer type and method are recorded privately.
3. A second reviewer independently checks fidelity, placeholder preservation, and policy compliance. When a task requires human adjudication and no human reviewer has participated, the status remains `draft` or `reference_candidate`, never `approved`.
4. Disagreements are adjudicated and documented privately.
5. The final redacted target and rubric are frozen before model execution.
6. The public asset exposes only status `approved`; reviewer identities and private evidence remain private.

Priority for initial manual semantic review is `M03`, then `M01`, then `M04`. Views `M05`, `M07`, `M08`, `M09`, and `M11` require separately authored or corrected human gold before semantic scoring. All other views require span-level review before semantic admission. `M11` remains raw-only and must not inherit a historical postprocessed target.

Without approved semantic gold, only structural and explicitly `REFERENCE_ONLY` metrics may be reported. Such a result must not be described as semantic accuracy. In v1, eleven reference-only normalization tasks consume the available, non-null `reference_candidate.json` named in `task_bindings.json`; their acceptance scope is `reference_relative_normalization`. `M11`, whose reference target is absent/null, and the three long views are bound only to structural, context, and retention capabilities and cannot receive normalization acceptance. An absent or null reference must never be promoted into an executable reference-relative task.

## Scorecard schema and rubric

The public scorecard shape is:

```json
{
  "schema_version": "scorecard-v1",
  "view_label": "opaque label",
  "task_family": "normalization|blocks|stitch|probe",
  "raw_json_valid": true,
  "transport_normalized_json_valid": true,
  "exact_schema_valid": true,
  "hard_failures": ["enum"],
  "metrics": {
    "placeholder_preservation": 1.0,
    "source_unit_coverage": 1.0,
    "omission_span_rate": 0.0,
    "addition_span_rate": 0.0,
    "boundary_f1": 1.0,
    "repetition_precision": 1.0,
    "repetition_recall": 1.0,
    "repetition_f1": 1.0,
    "retention_early": 1.0,
    "retention_middle": 1.0,
    "retention_late": 1.0,
    "citation_range_validity": 1.0,
    "unknown_calibration": 1.0
  },
  "ordinal_scores": {
    "punctuation_casing": 2,
    "disfluency_handling": 2
  },
  "gold_basis": "structural|semantic|reference_only",
  "accepted": true
}
```

Metrics that are inapplicable or lack the required gold basis must be omitted, not filled with zero. Thresholds must be frozen in `rubric.json` before execution.

### Hard failures

Any of the following sets `accepted=false` regardless of aggregate score:

- invalid raw JSON when raw JSON is required for admission;
- exact-schema failure, unknown field, invalid enum, or missing required field;
- unsupported addition against approved semantic gold;
- severe omission or required late-section loss;
- placeholder loss, mutation, duplication, invention, or order corruption;
- protected-entity corruption;
- segment, block, or chunk order/coverage violation;
- foreign marker or cross-view contamination;
- silent truncation or token-accounting mismatch;
- private mapping, source identifier, or unredacted protected content exposure.

### Quantitative rules

- Placeholder preservation and source-unit coverage must both equal `1.0`.
- Punctuation/casing and policy-defined disfluency handling use `0` (violates policy), `1` (partially meets policy), or `2` (meets policy).
- Repetition precision, recall, and F1 are reported only against approved semantic gold whose reviewer requirements are satisfied.
- Boundary F1 permits a tolerance of plus or minus one source unit and must publish the matching rule.
- Retention is reported separately for early, middle, and late views; no single average may conceal late loss.
- Latency and throughput are reported only for quality-admitted outputs.
- Acceptance requires no hard failure, exact schema validity, complete placeholder and source coverage, and every task-specific threshold met.

Thresholds may not be tuned after model outputs are inspected. Changing a threshold creates a new rubric version and invalidates comparisons with the previous version unless both are reported separately. The v1 normalization policy is `exact-target-v1`: exact target text and placeholder inventory are required. Any corruption, omission, addition, or placeholder damage adds a hard failure. The scorer rejects target-schema, view-label, and scoring-tier confusion before parsing model output.

## Media-resolved and media-unresolved claims

`media_resolution` governs claim language:

- `unresolved`: no source-media review supports the view;
- `partially_resolved`: media review covers named spans or dimensions only;
- `resolved`: the entire view and all claimed audio dimensions received independent media review.

When media is unresolved, allowed claims are limited to text/structure facts: exact reconstruction, schema behavior, placeholder preservation, raw-to-reference differences, structural omission/addition ranges, and reference-relative risk classes.

Media-unresolved results must not claim WER/CER, true speech omission, hallucination relative to audio, acoustic robustness, VAD correctness, diarization, speaker attribution, timestamp-to-audio alignment, spoken-entity correctness, or speech-grounded disfluency correctness. Terms such as `omission-like`, `hallucination-like`, and `entity mismatch` must be qualified as reference-relative.

A partially resolved pack must identify the exact reviewed dimension without implying full audio validation. Summary quality and physical KV-cache reuse are outside this pack's gold contract and require separate evidence.

## Review gates

The gates are sequential and fail closed.

### Gate 0: specification review

- Confirm this contract, the 16 opaque labels, and the no-assets boundary.
- Confirm public enums and schema versions before implementation.

### Gate 1: private-boundary preflight

- Confirm the private root is outside the repository and owner-only.
- Validate the manifest, canonical digest, read-only state, and label order.
- Confirm no source mapping or private locator appears in Git status or public logs.

### Gate 2: deterministic redaction review

- Validate every span and placeholder class against the private source.
- Verify deterministic replay, placeholder bijection, and residual-protected-content scan.
- Stop immediately on secret-like material or ambiguous identifying context.

### Gate 3: structural provenance review

- Run every applicable exact reconstruction assertion.
- Independently verify class assignment and public-safe claim wording.
- Reject missing or mismatched units; do not repair them silently.

### Gate 4: semantic-gold review

- Complete independent authoring, second review, and adjudication.
- Freeze targets and rubrics before any evaluated model call.
- Mark non-approved views `absent`; do not substitute historical postprocessing.

### Gate 5: public-tree privacy review

- Validate every public document against its exact schema.
- Run publication-safety audit and a dedicated residual identifier scan.
- Review diffs manually for source clues, rare phrases, exact timings, paths, mappings, and digest oracles.

### Gate 6: execution admission

- Require approved private-manifest preflight, public-tree digest, semantic status, exact tokenizer fit, output reserve, and model-state plan.
- Keep live execution, model loads, network calls, parallelism escalation, and retries behind separate explicit authorization.

### Gate 7: result publication review

- Separate planned, executed, reviewed, accepted, and zero-call rows.
- Preserve raw failed outputs privately; publish only categories and bucketed statistics.
- Verify claim language against `media_resolution` and `gold_basis`.
- Re-run publication-safety and repository gates before commit or push.

No later gate can waive an earlier failure. A changed source, manifest, redaction map, schema, prompt, gold target, or rubric returns the affected views to the earliest applicable gate.

## v1 status and non-claims

The v1 public tree, one frozen normalization prompt, tier-aware view-to-task bindings, closed public document schemas, structural assets, one two-reviewer-approved semantic gold asset (`M01`), twelve executable reference-relative targets, three structural-only long views, task-specific rubrics, and deterministic offline scoring are implemented. The current immutable private preparation root is shared locally through an owner-only handoff file and is never named or digested publicly. Independent replay fails closed when that handoff and the explicit environment override are both unavailable.

The pack contains no model output and establishes no model-call, audio-grounded accuracy, physical cache-reuse, production suitability, or runtime recommendation evidence. Live execution remains a separate explicitly authorized gate.
