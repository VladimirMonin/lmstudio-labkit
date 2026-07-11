from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import tools.lmstudio_lab.four_model_benchmark_driver as driver
from tools.lmstudio_lab.four_model_benchmark_driver import (
    DEFAULT_MANIFEST,
    DEFAULT_PACK,
    NativeRuntime,
    prepare_bundle,
    run_model,
)
from tools.lmstudio_lab.private_benchmark_overlay import classify_finish_reason


def test_native_generate_disables_reasoning_and_scores_only_final_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({"input": [], "reasoning": "on"}), encoding="utf-8")
    runtime = NativeRuntime("http://unused.invalid", 1)
    captured: dict = {}

    def fake_request(_method, _path, body=None):
        assert isinstance(body, dict)
        captured.update(body)
        return {
            "output": [
                {"type": "reasoning", "content": [{"type": "text", "text": "not-json"}]},
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": '{"ok":true}'}],
                },
            ],
            "finish_reason": "stop",
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }

    monkeypatch.setattr(runtime, "request_json", fake_request)
    text, payload, _, _ = runtime.generate(request_path)
    assert captured["reasoning"] == "off"
    assert text == '{"ok":true}'
    assert json.loads(text) == {"ok": True}
    assert payload["finish_reason"] == "stop"


@pytest.mark.parametrize(
    "payload",
    [
        {"output": [{"type": "reasoning", "content": "unfinished"}]},
        {"output": [{"type": "message", "content": []}], "finish_reason": "length"},
        {},
    ],
)
def test_native_generate_rejects_envelopes_without_final_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict
) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps({"input": []}), encoding="utf-8")
    runtime = NativeRuntime("http://unused.invalid", 1)
    monkeypatch.setattr(runtime, "request_json", lambda *_args, **_kwargs: payload)
    with pytest.raises(RuntimeError, match="no final message content"):
        runtime.generate(request_path)


def test_finish_reason_length_classification() -> None:
    assert classify_finish_reason("length", None, 2048) == "length"
    assert classify_finish_reason(None, {"output_tokens": 2048}, 2048) == "length"
    assert classify_finish_reason("stop", {"output_tokens": 12}, 2048) == "stop"


def test_prepare_bundle_materializes_real_native_requests(tmp_path: Path) -> None:
    plan_path = prepare_bundle(DEFAULT_MANIFEST, DEFAULT_PACK, tmp_path / "bundle")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["planned_cells"] == 64
    assert plan["planned_model_calls"] == 80
    first = plan["requests"][0]
    request = json.loads(
        (tmp_path / "bundle" / "requests" / first["request_path"]).read_text(encoding="utf-8")
    )
    assert request["request_id"] == first["request_id"]
    assert request["call_id"] == first["call_id"]
    assert request["cell_id"] == first["cell_id"]
    assert request["context_length"] == first["context_tier"]
    assert request["max_output_tokens"] == first["max_tokens"]
    assert request["benchmark_binding"]["view_label"] == first["view_label"]
    content = request["input"][0]["content"]
    assert all(field in content for field in ("task_prompt", "sanitized_input", "output_schema"))


def test_run_model_rejects_private_root_inside_repository(tmp_path: Path) -> None:
    plan_path = prepare_bundle(DEFAULT_MANIFEST, DEFAULT_PACK, tmp_path / "bundle")
    with pytest.raises(ValueError, match="outside the repository"):
        run_model(
            model="google/gemma-4-e2b",
            plan_path=plan_path,
            request_root=tmp_path / "bundle" / "requests",
            pack=DEFAULT_PACK,
            private_root=Path(__file__).resolve().parents[2] / "forbidden-private-output",
            ledger=tmp_path / "ledger.jsonl",
            scorecards=tmp_path / "scores",
            base_url="http://127.0.0.1:1234",
            timeout=1,
        )


def test_run_model_executes_closed_e2b_bundle_with_fake_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_path = prepare_bundle(DEFAULT_MANIFEST, DEFAULT_PACK, tmp_path / "bundle")

    class FakeHost:
        def __init__(self, runtime: FakeRuntime) -> None:
            self.runtime = runtime

        def count_all_loaded_instances(self) -> int:
            return int(self.runtime.loaded)

    class FakeRuntime:
        clock = 10.0

        def __init__(self, _base_url: str, _timeout: float) -> None:
            self.loaded = False
            self.host = FakeHost(self)

        def snapshot(self, call_id, stage):
            return {
                "event": "loaded_snapshot",
                "call_id": call_id,
                "stage": stage,
                "loaded_count": int(self.loaded),
                "observed_at": self.clock,
                "response_sha256": "0" * 64,
            }

        def load(self, _model: str, _context: int, _parallel: int):
            assert not self.loaded
            self.loaded = True
            return "fake-instance", {"load_verified": True}

        def unload(self, _model: str) -> None:
            assert self.loaded
            self.loaded = False

        def generate(self, _request_path: Path):
            started = time.time()
            return (
                "{}",
                {
                    "output": [{"type": "message", "content": "{}", "status": "completed"}],
                    "finish_reason": "stop",
                    "usage": {"input_tokens": 12, "output_tokens": 3},
                },
                started,
                started + 1.0,
            )

    monkeypatch.setattr(driver, "NativeRuntime", FakeRuntime)
    private = tmp_path / "private"
    ledger = tmp_path / "ledger.jsonl"
    scores = tmp_path / "scores"
    run_model(
        model="google/gemma-4-e2b",
        plan_path=plan_path,
        request_root=tmp_path / "bundle" / "requests",
        pack=DEFAULT_PACK,
        private_root=private,
        ledger=ledger,
        scorecards=scores,
        base_url="http://unused.invalid",
        timeout=1,
    )
    assert len(list(private.glob("*.raw.txt"))) == 20
    assert len(list(private.glob("*.response.json"))) == 20
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 20
    assert len(list(scores.glob("*.scorecard.json"))) == 20
    first = json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])
    assert first["response_envelope_relative_path"].endswith(".response.json")
    assert len(first["response_envelope_sha256"]) == 64
    assert first["finish_reason"] == "stop"
    assert first["native_usage"] == {"input_tokens": 12, "output_tokens": 3}
    envelope = json.loads((private / first["response_envelope_relative_path"]).read_text())
    assert envelope["output"][0]["content"] == "{}"
