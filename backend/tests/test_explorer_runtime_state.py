import json
from types import SimpleNamespace

from agent.ai_explorer.page_state import PageState
from agent.ai_explorer.run_checkpoint import RunCheckpointCodec
from agent.ai_explorer.runtime_state import DetectionRunState, ProbePhase, poll_permission_grant
from agent.ai_explorer.explorer_engine import _save_traversal_checkpoint
from agent.detection_engines.base import DetectionContext


def test_allow_phase_reuses_verified_navigation_but_clears_deny_probe():
    storage = {}
    state = DetectionRunState(storage)
    state.navigation.record_verified_route(["我的", "头像"])
    state.permission.begin_denial_probe(permission="相机", trigger_target="头像")

    transition = state.begin_phase(ProbePhase.ALLOW)

    assert transition.previous is ProbePhase.OBSERVE
    assert transition.current is ProbePhase.ALLOW
    assert state.navigation.verified_routes == [("我的", "头像")]
    assert state.permission.active_probe is None
    assert storage["probe_profile"] == "allow"


def test_checkpoint_round_trip_preserves_typed_state():
    source = DetectionRunState({"prior_probe_login_gate_fingerprints": [".LoginActivity:account-password"]})
    source.navigation.record_verified_route(["设置", "隐私"])
    source.permission.begin_denial_probe(permission="存储", trigger_target="上传")
    payload = RunCheckpointCodec.dump(source)

    restored = DetectionRunState({})
    result = RunCheckpointCodec.restore(payload, restored)

    assert result.restored is True
    assert result.schema_version == RunCheckpointCodec.SCHEMA_VERSION
    assert restored.navigation.verified_routes == [("设置", "隐私")]
    assert restored.permission.active_probe.permission == "存储"
    assert restored.login_wait_already_consumed(".LoginActivity:account-password") is True


def test_checkpoint_rejects_future_schema_without_claiming_restore():
    state = DetectionRunState({})

    result = RunCheckpointCodec.restore({"schema_version": 999, "state": {}}, state)

    assert result.restored is False
    assert result.reason == "unsupported_future_schema"
    assert state.checkpoint_restored is False


def test_invalid_phase_is_reported_instead_of_silently_becoming_observe():
    state = DetectionRunState({"probe_profile": "unexpected"})

    assert state.phase is ProbePhase.OBSERVE
    assert state.recovery_gaps == ["invalid_probe_phase:unexpected"]


def test_traversal_checkpoint_embeds_versioned_typed_run_state(tmp_path):
    ctx = DetectionContext(
        task=SimpleNamespace(mode="fast"), apk=SimpleNamespace(package_name="demo"),
        cfg={}, data_dir=tmp_path, runtime={"probe_profile": "deny"},
    )
    DetectionRunState.from_context(ctx).navigation.record_verified_route(["我的", "头像"])

    path = _save_traversal_checkpoint(ctx, PageState(), [], [])
    payload = json.loads(path.read_text("utf-8"))

    assert payload["version"] == 4
    assert payload["run_state"]["schema_version"] == RunCheckpointCodec.SCHEMA_VERSION
    assert payload["run_state"]["state"]["verified_navigation_routes"] == [["我的", "头像"]]


def test_permission_grant_poll_waits_for_android_to_apply_the_allow_response():
    """A post-click read may be stale; terminal evidence must use the fresh state."""
    permission = "android.permission.CAMERA"
    observed = iter([
        {permission: None},
        {permission: False},
        {permission: True},
    ])
    pauses = []

    result = poll_permission_grant(
        lambda package, selected: next(observed),
        package_name="com.example.demo",
        selected_permissions=[permission],
        max_attempts=4,
        interval_seconds=3,
        sleep=pauses.append,
    )

    assert result.verified is True
    assert result.states == {permission: True}
    assert result.attempts == 3
    assert pauses == [3, 3]


def test_login_wait_reuse_requires_the_same_semantic_gate_not_just_a_later_phase():
    state = DetectionRunState({
        "prior_probe_login_gate_fingerprints": [".LoginActivity:account-password"],
    })

    assert state.login_wait_already_consumed(".LoginActivity:phone-code") is False
    assert state.login_wait_already_consumed(".LoginActivity:account-password") is True

    state.mark_login_waiting(gate_fingerprint=".LoginActivity:phone-code")

    assert state.login_wait_already_consumed(".LoginActivity:phone-code") is True
