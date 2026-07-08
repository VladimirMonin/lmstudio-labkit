# L3.20 12B Schema Contract Forensics

## Scope

No live rerun was performed. This report uses existing committed sanitized artifacts and decision records only.

## Source status

- `experiments/lmstudio/results_summaries/l3_17_text_quality_12b_decision_record.md`: present

## Findings

1. **Which schema paths failed?** Current committed sanitized decision records identify `json_schema` failures, but do not preserve full path-level schema errors for every failed cell. This is a metadata gap unless older local `/tmp` run artifacts are available outside git.
2. **Which id_exact checks failed?** The committed decision record identifies `id_exact` failures. It does not fully preserve all expected/seen ids in public artifacts.
3. **Did 12B return a different shape?** Available summaries indicate parseable JSON and successful language/business/finish checks, so this was not a total non-JSON collapse. The exact incompatible shape is not fully recoverable from committed metadata.
4. **Did 12B reorder ids?** Current committed metadata is insufficient to prove reorder vs duplicate/missing ids for every cell.
5. **Did retry repeat the same failure or a different failure?** Retry did not recover acceptance. The committed summary is insufficient to classify same-vs-different failure at path level.
6. **Fixable by prompt/schema or blocked?** Treat 12B as blocked until instrumentation captures sanitized schema paths and id metrics. A prompt/schema fix is possible only after path-level evidence is available.

## Metadata gap

The public artifacts need additional sanitized fields for future 12B forensics:

- schema first-error path per failed cell;
- id path checked;
- expected_id_count / seen_id_count;
- missing_count / duplicate_count / unexpected_count;
- first_mismatch_index;
- retry attempt comparison category.

## Decision

Do not rerun 12B in L3.20. Keep 12B blocked for this structured-output family until the instrumentation gap is closed and a single narrow rerun is explicitly authorized.
