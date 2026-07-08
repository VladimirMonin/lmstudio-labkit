from __future__ import annotations

import json

import pytest
from lmstudio_labkit.managed_executor import LocalLMStudioHostRunner

from lmstudio_labkit import (
    ChatMessage,
    ExecutionOptions,
    ManagedExecutorError,
    ManagedLMStudioExecutor,
    RequestEnvelope,
    RequestPlan,
    ResponseContract,
    build_simple_flat_schema,
)


class DirtyStateHostRunner:
    def __init__(self, *, pre_load_instances: int | None) -> None:
        self.pre_load_instances = pre_load_instances
        self.calls: list[str] = []

    def load_model(self, *, model_id: str, context_length: int, parallel: int) -> object:
        self.calls.append("load_model")
        return {
            "load_verified": True,
            "applied_load_config": {"context_length": context_length, "parallel": parallel},
        }

    def chat_completion(self, **kwargs: object) -> object:
        self.calls.append("chat_completion")
        return {
            "choices": [
                {"message": {"content": json.dumps({"id": "ok", "text": "Synthetic response"})}}
            ]
        }

    def cleanup_model(self, *, model_id: str) -> object:
        self.calls.append("cleanup_model")
        return {"cleanup_verified": True}

    def count_loaded_instances(self, *, model_id: str) -> int | None:
        self.calls.append("count_loaded_instances")
        return self.pre_load_instances


class FakeLocalRunner(LocalLMStudioHostRunner):
    unload_payloads: list[dict[str, object]]
    models_payload: dict[str, object]

    def __init__(self) -> None:
        super().__init__()
        object.__setattr__(self, "unload_payloads", [])
        object.__setattr__(
            self,
            "models_payload",
            {
                "models": [
                    {
                        "key": "google/gemma-4-e2b",
                        "loaded_instances": [
                            {"id": "google/gemma-4-e2b"},
                            {"id": "google/gemma-4-e2b:2"},
                        ],
                    }
                ]
            },
        )

    def _request_json(
        self, path: str, payload: dict[str, object] | None, timeout_s: float
    ) -> dict[str, object]:  # type: ignore[override]
        if path == "/api/v1/models" and payload is None:
            return self.models_payload
        if path == "/api/v1/models/unload" and payload is not None:
            self.unload_payloads.append(dict(payload))
            instance_id = payload.get("instance_id")
            models = self.models_payload["models"]
            assert isinstance(models, list)
            loaded = models[0]["loaded_instances"]
            assert isinstance(loaded, list)
            models[0]["loaded_instances"] = [
                item for item in loaded if isinstance(item, dict) and item.get("id") != instance_id
            ]
            return {"instance_id": instance_id}
        raise AssertionError(f"unexpected request {path} {payload}")


def structured_plan() -> RequestPlan:
    return RequestPlan(
        cell_id="dirty-state-cell",
        envelope=RequestEnvelope(
            request_id="dirty-state-cell",
            modality="text",
            chat_messages=(ChatMessage(role="user", content="Return structured JSON"),),
            response_contract=ResponseContract(
                mode="json",
                schema=build_simple_flat_schema(),
                expected_output={"id": "ok", "text": "Synthetic response"},
            ),
        ),
        options=ExecutionOptions(
            model_id="mock/text",
            endpoint_family="openai_compat",
            context_tier="8192",
            temperature=0.0,
            timeout_s=30.0,
            live=True,
        ),
    )


@pytest.mark.parametrize(
    ("pre_load_instances", "match"),
    [
        (1, "dirty loaded state"),
        (None, "pre-load state was not verified"),
    ],
)
def test_managed_executor_refuses_dirty_or_ambiguous_preload_state(
    pre_load_instances: int | None, match: str
) -> None:
    host = DirtyStateHostRunner(pre_load_instances=pre_load_instances)
    executor = ManagedLMStudioExecutor(host_runner=host, allow_model_loads=True)

    with pytest.raises(ManagedExecutorError, match=match):
        executor.execute(structured_plan())

    assert "load_model" not in host.calls
    assert "chat_completion" not in host.calls


def test_local_lmstudio_cleanup_unloads_each_loaded_instance_by_instance_id() -> None:
    runner = FakeLocalRunner()

    result = runner.cleanup_model(model_id="google/gemma-4-e2b")

    assert result == {"cleanup_verified": True}
    assert runner.unload_payloads == [
        {"instance_id": "google/gemma-4-e2b"},
        {"instance_id": "google/gemma-4-e2b:2"},
    ]
    assert runner.count_loaded_instances(model_id="google/gemma-4-e2b") == 0
