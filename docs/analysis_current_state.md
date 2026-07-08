# Current State Analysis

## Done in code

- Managed LM Studio backend contracts and clients live in `libs/lmstudio_managed/`.
- Lab runners, probes, lifecycle helpers, cache/context planning, structured-output validation, metrics and reporting live in `tools/lmstudio_lab/`.
- The standalone benchmark entry tool is `tools/lmstudio_benchmark.py` and the packaged CLI entry point is `lmstudio_labkit.cli:main`.
- The public facade package `lmstudio_labkit` exposes request core, benchmark planning/execution, validation, artifacts, schema builders, dataset manifests, reports, and host/live adapter boundaries.
- Offline matrix planning and fake execution are implemented for text/image-shaped tasks without starting LM Studio.
- Validators cover the hardened structured subset needed for Blocks JSON: schema keywords, exact IDs including integer IDs, order, duplicates, missing/extra IDs, placeholders, Markdown fence leakage, language compliance, length ratios, image labels, and finish-length failures.
- Fake transport can deterministically exercise failure and retry paths.
- Artifact writing performs a privacy scan and stores hashes/counts/statuses/metrics rather than raw prompt/response content.
- Report helpers produce pass/fail totals plus per-axis, per-model, retry-impact, and failure-taxonomy summaries.
- A guarded live bridge interface exists, but live execution is not invoked by default and requires an injected host/managed executor.
- Experiment configs, schemas, candidate metadata, and curated result summaries live in `experiments/lmstudio/`.
- Regression coverage exists in `tests/libs/`, `tests/tools/`, `tests/architecture/`, and `tests/lmstudio_labkit/`.

## Mocked/offline only

- Matrix harness execution defaults to offline/fake.
- Live bridge tests use injected mocks only; they do not call a local server and do not load models.
- Image lane has manifest/schema/validator skeletons and fake-run coverage, not real image-model execution.

## Planned / future

- Host applications should provide their own executor/adapters for real managed live runs.
- Overnight runs need a separate operator profile, resumability policy, and explicit runtime/resource budget controls before use.
- Larger private datasets should remain outside public artifacts and enter only through safe manifests or private adapters.

## Real next work

1. Wire a host-owned managed executor into `lmstudio_labkit.live_bridge` behind explicit live approval.
2. Add resumable run state for long guarded profiles before attempting any overnight run.
3. Expand synthetic image fixtures and image-specific business validators before promoting image screening beyond skeleton status.
4. Continue keeping live LM Studio checks opt-in and guarded by explicit user permission.
