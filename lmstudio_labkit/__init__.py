"""Public facade for LM Studio LabKit."""

from .artifacts import ArtifactSet, write_run_artifacts
from .benchmarks import (
    BenchmarkConfig,
    BenchmarkSafetyConfig,
    FakeTransport,
    MatrixCell,
    MatrixPlan,
    MatrixTransport,
    ModelSpec,
    TaskSpec,
    plan_matrix,
    run_live_small_text_screening,
    run_matrix,
)
from .datasets import TaskManifest, load_task_manifest, load_task_manifests, load_task_specs
from .live_bridge import LiveBridgeTransport
from .managed_executor import (
    ManagedExecutionResult,
    ManagedExecutorError,
    ManagedHostRunner,
    ManagedLMStudioExecutor,
    ManagedLMStudioTransport,
)
from .requests import (
    ChatMessage,
    ExecutionOptions,
    ImageInput,
    LanguagePolicy,
    RequestEnvelope,
    RequestPlan,
    RequestResult,
    ResponseContract,
    TextInput,
)
from .schema_builders import build_blocks_schema, build_simple_flat_schema
from .validation import (
    ValidationResult,
    ValidationSummary,
    collect_ids_by_path,
    validate_language,
    validate_response,
)

__all__ = [
    "ArtifactSet",
    "BenchmarkConfig",
    "BenchmarkSafetyConfig",
    "ChatMessage",
    "ExecutionOptions",
    "FakeTransport",
    "ImageInput",
    "LanguagePolicy",
    "LiveBridgeTransport",
    "ManagedExecutionResult",
    "ManagedExecutorError",
    "ManagedHostRunner",
    "ManagedLMStudioExecutor",
    "ManagedLMStudioTransport",
    "MatrixCell",
    "MatrixPlan",
    "MatrixTransport",
    "ModelSpec",
    "RequestEnvelope",
    "RequestPlan",
    "RequestResult",
    "ResponseContract",
    "TaskManifest",
    "TaskSpec",
    "TextInput",
    "ValidationResult",
    "ValidationSummary",
    "build_blocks_schema",
    "build_simple_flat_schema",
    "collect_ids_by_path",
    "load_task_manifest",
    "load_task_manifests",
    "load_task_specs",
    "plan_matrix",
    "run_live_small_text_screening",
    "run_matrix",
    "validate_language",
    "validate_response",
    "write_run_artifacts",
]
