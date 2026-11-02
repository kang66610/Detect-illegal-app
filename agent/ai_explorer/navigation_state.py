"""Classify Android navigation surfaces before the explorer acts on them.

Appium decisions are valid only on the audited App's own UI.  Android system
screens, file pickers and browser Custom Tabs can reuse a stale accessibility
tree for a frame; treating them as ordinary App pages is the source of many
mis-clicks and premature Frida shutdowns.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavigationSurface:
    kind: str
    recoverable: bool
    audited_app_surface: bool


def classify_navigation_surface(activity: str, elements: list[dict] | None = None) -> NavigationSurface:
    normalized_activity = str(activity or "").lower()
    identity = " ".join(
        str(item.get(key) or "").lower()
        for item in (elements or []) for key in ("resource_id", "text", "content_desc", "class_name")
    )
    if any(term in normalized_activity for term in (
        "documentsui", ".picker.pickactivity", "filepicker", "photopicker",
        "picker.external", "externalpickeractivity",
    )):
        return NavigationSurface("file_picker", True, False)
    if any(term in normalized_activity for term in (
        "customtabactivity", "customtabs", "chrome.browser",
        "apps.chrome", "android.chrome", "com.android.chrome",
        "org.chromium.chrome", "org.mozilla.firefox",
    )):
        return NavigationSurface("custom_tab", True, False)
    chrome_ids = " ".join(str(item.get("resource_id") or "").lower() for item in (elements or []))
    if any(term in chrome_ids for term in (
        "com.android.chrome:", "org.chromium.chrome:", "com.google.android.apps.chrome:",
    )):
        return NavigationSurface("custom_tab", True, False)
    if any(term in normalized_activity for term in ("permissioncontroller", "grantpermissionsactivity", "permission.ui")):
        return NavigationSurface("runtime_permission", False, False)
    if any(term in identity for term in ("display over other apps", "appear on top", "所有文件访问", "manage all files")):
        return NavigationSurface("special_permission_settings", True, False)
    if any(term in normalized_activity for term in ("settings", "launcheractivity", "nexuslauncher")):
        return NavigationSurface("system_surface", True, False)
    return NavigationSurface("app", False, True)
