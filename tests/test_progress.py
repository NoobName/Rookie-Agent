from pathlib import Path

from fastapi.testclient import TestClient

from services.agent.app import create_app
from services.agent.models import Guardrails
from services.agent.progress import ProgressTracker
from tests.test_core import wait_state
from tests.test_execution import create
from tests.test_tool_errors import SequenceProvider, action


def test_noise_does_not_hide_repeats_and_feedback_precedes_stop():
    tracker = ProgressTracker(3)
    for i in range(6):
        signal = tracker.observe(
            "web.fetch",
            {"url": "https://example.com"},
            {
                "status": "succeeded",
                "output": "same",
                "source": {"url": "https://example.com", "retrieved": i},
            },
        )
        if signal:
            assert not signal["stop"]  # same batch has not given the model a chance to adapt
    tracker.feedback_delivered()
    signal = tracker.observe(
        "web.fetch",
        {"url": "https://example.com"},
        {
            "status": "succeeded",
            "output": "same",
            "source": {"url": "https://example.com", "retrieved": 99},
        },
    )
    assert signal["stop"]


def test_unique_edits_warn_without_stopping_but_version_oscillation_stops():
    tracker = ProgressTracker(3)
    warnings = []
    for i in range(100):
        signal = tracker.observe(
            "files.edit",
            {"path": "render.py", "edits": [{"new": str(i)}]},
            {"status": "succeeded", "sha256": str(i)},
        )
        if signal:
            warnings.append(signal)
            assert not signal["stop"]
        tracker.feedback_delivered()
    assert warnings[0]["kind"] == "edit_churn"
    assert len(tracker.recent) == 64
    tracker = ProgressTracker(3)
    for version in ["a", "b"] * 5:
        signal = tracker.observe(
            "files.edit",
            {"path": "render.py", "expected_sha256": "different"},
            {"status": "succeeded", "sha256": version},
        )
        tracker.feedback_delivered()
    assert signal["kind"] == "edit_cycle" and signal["stop"]


def test_writes_make_followup_reads_legitimate():
    tracker = ProgressTracker()
    for i in range(12):
        tracker.observe(
            "files.write", {"path": "another.py", "content": str(i)}, {"status": "succeeded"}
        )
        assert (
            tracker.observe(
                "files.read", {"path": "render.py"}, {"status": "succeeded", "sha256": "same"}
            )
            is None
        )


def test_loop_warning_goes_to_model_before_typed_pause(tmp_path):
    provider = SequenceProvider([[action("files.read", path="same.txt")] for _ in range(8)])
    app = create_app(tmp_path / "data", "t")
    app.state.engine.provider = lambda _: provider
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(client)
        Path(task["spec"]["workspace"], "same.txt").write_text("unchanged")
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        stopped = wait_state(client, tid, {"waiting_for_user", "failed"})
        assert stopped["stop_reason"] == "no_progress"
        assert len(provider.requests) == 5
        assert "执行器进展提醒" in str(provider.requests[3])
        assert client.post(f"/api/tasks/{tid}/continue", json={}).status_code == 400


def test_round_limit_continue_preserves_plan_and_does_not_replay_write(tmp_path):
    assert Guardrails().max_steps == 160
    app = create_app(tmp_path / "data", "t")
    with TestClient(app, headers={"Authorization": "Bearer t"}) as client:
        task = create(
            client,
            guardrails={"max_steps": 1},
            script=[
                action("files.write", path="result.txt", content="once"),
                action("files.read", path="result.txt"),
            ],
        )
        tid = task["id"]
        client.post(f"/api/tasks/{tid}/start", json={})
        first = wait_state(client, tid, {"waiting_for_user", "failed"})
        assert first["stop_reason"] == "step_limit"
        for _ in range(2):
            assert client.post(f"/api/tasks/{tid}/continue", json={}).status_code == 200
            current = wait_state(client, tid, {"waiting_for_user", "awaiting_feedback", "failed"})
        assert current["state"] == "awaiting_feedback"
        assert current["revision"] == first["revision"]
        calls = client.get(f"/api/tasks/{tid}/calls").json()
        assert [c["tool"] for c in calls] == ["files.write", "files.read"]
        assert Path(task["spec"]["workspace"], "result.txt").read_text() == "once"
