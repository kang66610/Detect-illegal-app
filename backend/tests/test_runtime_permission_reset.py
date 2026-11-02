from agent.ai_explorer.android_device import AndroidDevice


def test_revoke_runtime_permissions_uses_pm_revoke_only():
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)
    revoked = device.revoke_runtime_permissions(
        "com.example.app",
        ["android.permission.READ_PHONE_STATE", "android.permission.CAMERA", "not.a.permission"],
    )
    assert revoked == ["android.permission.READ_PHONE_STATE", "android.permission.CAMERA"]
    assert all(call[:3] == ["shell", "pm", "revoke"] for call in calls)
    assert any("READ_PHONE_STATE" in " ".join(call) for call in calls)
    assert not any("clear" in " ".join(call) for call in calls)


def test_revoke_clears_phone_and_location_for_first_run_permission_scenes():
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)
    revoked = device.revoke_runtime_permissions(
        "com.example.app",
        [
            "android.permission.READ_PHONE_STATE",
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.ACCESS_COARSE_LOCATION",
            "android.permission.CAMERA",
            "android.permission.RECORD_AUDIO",
        ],
    )
    assert set(revoked) == {
        "android.permission.READ_PHONE_STATE",
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
        "android.permission.CAMERA",
        "android.permission.RECORD_AUDIO",
    }
    revoked_perms = {call[-1] for call in calls}
    assert "android.permission.READ_PHONE_STATE" in revoked_perms
    assert "android.permission.ACCESS_FINE_LOCATION" in revoked_perms


def test_grant_observability_permissions_only_touches_phone_and_location():
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)
    granted = device.grant_runtime_permissions(
        "com.example.app",
        [
            "android.permission.READ_PHONE_STATE",
            "android.permission.CAMERA",
            "android.permission.ACCESS_FINE_LOCATION",
        ],
    )
    assert set(granted) == {
        "android.permission.READ_PHONE_STATE",
        "android.permission.ACCESS_FINE_LOCATION",
    }
    assert all(call[:3] == ["shell", "pm", "grant"] for call in calls)
    assert not any(call[-1] == "android.permission.CAMERA" for call in calls)


def test_grant_observability_permissions_follow_the_apk_manifest_not_one_app():
    calls: list[list[str]] = []

    def runner(args):
        calls.append(list(args))
        return ""

    device = AndroidDevice({"udid": "emulator-5554"}, runner=runner)
    granted = device.grant_runtime_permissions(
        "com.travel.app",
        [
            "android.permission.ACCESS_FINE_LOCATION",
            "android.permission.BLUETOOTH_SCAN",
            "android.permission.CAMERA",
        ],
    )
    assert set(granted) == {
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.BLUETOOTH_SCAN",
    }
    assert "android.permission.READ_PHONE_STATE" not in {call[-1] for call in calls}
