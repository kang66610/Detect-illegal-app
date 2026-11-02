from agent.ai_explorer.navigation_state import classify_navigation_surface


def test_external_surfaces_are_never_classified_as_audited_app_pages():
    picker = classify_navigation_surface("com.android.documentsui.picker.PickActivity")
    browser = classify_navigation_surface("org.chromium.chrome.browser.customtabs.CustomTabActivity")
    photo_picker = classify_navigation_surface(
        "com.google.android.photopicker.external.ExternalPickerActivity"
    )

    assert (picker.kind, picker.recoverable, picker.audited_app_surface) == ("file_picker", True, False)
    assert (browser.kind, browser.recoverable, browser.audited_app_surface) == ("custom_tab", True, False)
    assert photo_picker.kind == "file_picker"


def test_permission_and_app_surface_remain_distinct():
    permission = classify_navigation_surface("com.android.permissioncontroller.permission.ui.GrantPermissionsActivity")
    app = classify_navigation_surface("com.example.MainActivity")

    assert permission.kind == "runtime_permission"
    assert app.audited_app_surface is True


def test_full_chrome_privacy_page_is_a_browser_surface_not_an_app_page():
    chrome = classify_navigation_surface("com.google.android.apps.chrome.Main")
    chrome_by_toolbar = classify_navigation_surface(
        ".SomeWebActivity",
        [{"resource_id": "com.android.chrome:id/url_bar", "text": "example.com/privacy.html"}],
    )
    assert chrome.kind == "custom_tab"
    assert chrome.audited_app_surface is False
    assert chrome_by_toolbar.kind == "custom_tab"
