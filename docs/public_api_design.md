# Public API Design

## Purpose

This document proposes the public API direction for LM Studio LabKit. The target package should expose a reusable request core and benchmark harness while preserving compatibility with the extracted `libs/` and `tools/` layout during migration.

This is a design document. It should not be read as an implementation guarantee until matching code and tests land.

## Proposed facade package

The proposed public facade package is:

```python
import lmstudio_labkit
```

Planned subpackages:

```text
lmstudio_labkit.requests
lmstudio_labkit.benchmarks
lmstudio_labkit.validation
lmstudio_labkit.artifacts
lmstudio_labkit.adapters
lmstudio_labkit.cli
```

The facade should expose stable types and functions while keeping implementation details inside existing or future internal modules.

## Compatibility wrappers

The current extracted layout uses:

- `libs.lmstudio_managed`
- `tools.lmstudio_lab`
- `tools.lmstudio_benchmark`

During migration:

- Existing imports should keep working.
- New public code should prefer `lmstudio_labkit` imports.
- Compatibility wrappers should be thin and tested.
- Deprecation, if any, should be explicit and delayed until the facade is stable.

Example compatibility direction:

```python
from lmstudio_labkit.requests import RequestEnvelope
from lmstudio_labkit.benchmarks import MatrixPlan
```

Existing code may continue to import lower-level modules until the migration is complete.

## Core request API

The request core should describe requests independently from execution.

Planned concepts:

- `RequestEnvelope` — common request metadata and inputs.
- `TextInput` — text prompt or chat content reference.
- `ImageInput` — image metadata reference with hash, dimensions, and declared source type.
- `ChatMessage` — role/content message unit.
- `ResponseContract` — structured or non-structured expectation.
- `ExecutionOptions` — model, endpoint family, timeout, context tier, temperature, and retry policy.
- `RequestPlan` — executable plan produced from config and datasets.
- `RequestResult` — privacy-safe execution result envelope.

The API should support:

- text requests
- image requests
- mixed text/image requests
- chat-style requests
- structured JSON outputs
- non-structured text outputs
- fake/offline transports for tests
- live LM Studio transports only when explicitly enabled

Default result envelopes should store hashes, counts, statuses, timings, token/resource metrics, and validation summaries rather than raw prompt/response content.

## Benchmark API

The benchmark API should build on the request core.

Planned concepts:

- `BenchmarkConfig` — loaded from YAML/JSON config.
- `BenchmarkAxis` — one configurable matrix axis.
- `MatrixPlan` — expanded cell plan.
- `MatrixCell` — one model/task/modality/language/schema/retry/repeat combination.
- `BenchmarkRunner` — executes cells through a selected transport.
- `ValidationPipeline` — ordered validators for result checking.
- `ArtifactWriter` — writes privacy-safe run artifacts.
- `ReportBuilder` — builds Markdown/CSV/JSON summaries from artifacts.

The API should support both:

- no-live planning and fake-transport execution for tests;
- guarded live execution for explicit operator runs.

## CLI surface

The existing command is:

```bash
lmstudio-benchmark
```

Planned CLI surface:

```bash
lmstudio-benchmark plan-matrix --config path/to/config.yaml --output-root runs/
lmstudio-benchmark run-matrix --config path/to/config.yaml --profile offline-fake
lmstudio-benchmark run-matrix --config path/to/config.yaml --profile live-small --live
lmstudio-benchmark summarize --run-dir runs/<run-id>
lmstudio-benchmark compare --run-dir runs/<run-a> --run-dir runs/<run-b>
```

Safety expectations:

- Default profile is offline/no-live.
- Live LM Studio requires an explicit flag.
- Model downloads require a separate explicit command or flag.
- Long/overnight profiles require explicit profile names.
- CLI output should make privacy mode and artifact paths clear.

These commands are roadmap targets unless and until implemented and covered by tests.

## Host-application integration strategy

Host applications should integrate through adapters rather than importing benchmark internals.

Planned adapter boundaries:

- model-selection adapter
- request-scheduling adapter
- artifact-storage adapter
- report-consumption adapter
- UI/status adapter
- host-owned privacy policy adapter

The public LabKit package should own reusable abstractions and validators. Host applications should own private workflow details, credentials, release policy, UI integration, and product-specific behavior.

Expected integration shape:

```python
from lmstudio_labkit.adapters import HostApplicationAdapter
from lmstudio_labkit.requests import RequestEnvelope
from lmstudio_labkit.benchmarks import BenchmarkRunner
```

Private adapters can live outside this repository and depend only on stable public interfaces.

## L3.12 implementation status

Implemented public modules now include:

```text
lmstudio_labkit.requests
lmstudio_labkit.benchmarks
lmstudio_labkit.validation
lmstudio_labkit.schema_builders
lmstudio_labkit.datasets
lmstudio_labkit.artifacts
lmstudio_labkit.privacy
lmstudio_labkit.reports
lmstudio_labkit.live_bridge
lmstudio_labkit.adapters
lmstudio_labkit.cli
```

The compatibility layer remains in place: existing `libs.*` and `tools.*` imports are not removed.

Live-run procedure status: guarded interface implemented, real execution host-managed and explicit opt-in only. The default CLI still performs offline/fake execution and rejects live profiles unless live intent and config safety flags agree.

## Documentation contract

Public docs should distinguish clearly between:

- implemented public API;
- compatibility layer;
- planned API;
- private host integration examples;
- live-run procedures that require explicit operator permission.

No public API document should include private host-application names, local private paths, credentials, private support workflows, or raw private prompts/responses.
