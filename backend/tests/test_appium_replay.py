import json
from pathlib import Path

from agent.ai_explorer.replay_format import ReplayWriter, replay_semantics_for_resolved
from agent.ai_explorer.replay_runner import run_replay
from agent.detection_engines.page_semantics import PageFacts, classify_page


FIXTURES = Path(__file__).parent / "fixtures/appium_replays"


def test_replay_writer_redacts_credentials_and_device_identifiers(tmp_path):
    path = tmp_path / "trace.jsonl"
    writer = ReplayWriter(path)
    writer.write({
        "type": "page", "device_id": "emulator-5554",
        "password": "secret", "screen_text": "密码 secret 13800138000 a@example.com",
        "elements": [{"password": True, "text": "secret"}],
    })

    body = path.read_text("utf-8")

    assert "secret" not in body
    assert "emulator-5554" not in body
    assert "13800138000" not in body
    assert "a@example.com" not in body
    assert "[REDACTED]" in body


def test_replay_resumes_from_checkpoint_and_reaches_same_state():
    path = FIXTURES / "generic_permission_denial.jsonl"

    whole = run_replay(path)
    resumed = run_replay(path, checkpoint=3)

    assert resumed.scenarios == whole.scenarios
    assert resumed.final_actions == whole.final_actions
    assert whole.scenarios["4.2"]["state"] == "evidence_observed"


def test_replay_uses_real_safety_arbitration_without_device():
    result = run_replay(FIXTURES / "generic_camera_exit.jsonl")

    assert result.final_actions == [{
        "action": "back", "target": "", "source": "safety_scope_exit",
    }]


def test_replay_schema_rejects_future_versions(tmp_path):
    path = tmp_path / "future.jsonl"
    path.write_text(json.dumps({"schema_version": 999, "type": "header"}) + "\n", "utf-8")

    try:
        run_replay(path)
    except ValueError as exc:
        assert str(exc) == "unsupported replay schema: 999"
    else:
        raise AssertionError("future replay schema must be rejected")


def test_replay_persists_resolved_role_evidence_without_page_text():
    resolved = classify_page(PageFacts(consent_dialog=True, document_body=True))
    snapshot = replay_semantics_for_resolved(resolved)

    assert snapshot["role"] == "consent_dialog"
    assert snapshot["blocked_roles"] == ["document_body"]
    assert snapshot["evidence"][0]["source"] == "ui_tree"
    assert "text" not in json.dumps(snapshot, ensure_ascii=False)
