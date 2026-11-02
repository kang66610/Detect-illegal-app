"""页面 XML 的轻量解析与去重，不依赖 Appium，便于单元测试。"""
from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from agent.ai_explorer.document_session import DocumentReadingLedger


@dataclass
class PageSnapshot:
    activity: str
    xml: str
    elements: list[dict]
    fingerprint: str
    surface_fingerprint: str

    def llm_payload(self) -> dict:
        # Preserve every actionable control before adding a small amount of
        # surrounding copy.  Truncating the raw tree at 80 nodes hid controls
        # near the bottom of WebView/Compose pages while ScenarioFrontier still
        # recommended them from the complete tree.
        actionable = [item for item in self.elements if item.get("clickable")]
        context = [item for item in self.elements if not item.get("clickable")][:40]
        return {"activity": self.activity, "elements": [*actionable[:160], *context]}


def page_from_elements(activity: str, xml: str, elements: list[dict]) -> PageSnapshot:
    """Rebuild fingerprints after OCR or other element enrichment."""
    normalized_elements = [dict(item) for item in elements]
    locator_counts: dict[str, int] = {}
    for item in normalized_elements:
        locator = str(
            item.get("locator") or item.get("target") or item.get("resource_id")
            or item.get("text") or item.get("content_desc") or ""
        )
        item["locator"] = locator
        if item.get("clickable") and locator:
            locator_counts[locator] = locator_counts.get(locator, 0) + 1
    locator_instances: dict[str, int] = {}
    for item in normalized_elements:
        locator = str(item.get("locator") or "")
        if not item.get("clickable") or not locator:
            continue
        instance = locator_instances.get(locator, 0)
        locator_instances[locator] = instance + 1
        item["instance"] = instance
        bounds = str(item.get("bounds") or "")
        # RecyclerView rows commonly share one resource-id. Bind the action to
        # the concrete visible instance so the selected row, not the first ID
        # match, is executed. Unique controls keep their readable locator.
        if locator_counts.get(locator, 0) > 1 and bounds:
            item["target"] = f"bounds:{bounds}"
        else:
            item["target"] = str(item.get("target") or locator)
        semantic = "|".join(str(item.get(key) or "") for key in (
            "resource_id", "text", "content_desc", "class_name",
        ))
        item["action_key"] = hashlib.sha256(
            f"{semantic}|{bounds}|{instance}".encode("utf-8")
        ).hexdigest()[:20]
    elements = normalized_elements
    signature = "|".join(sorted(
        f"{e.get('resource_id', '')}:{e.get('text', '')}:{e.get('content_desc', '')}:"
        f"{e.get('target', '')}:{e.get('bounds', '')}" for e in elements
    ))
    fingerprint = hashlib.sha256(f"{activity}|{signature}".encode("utf-8")).hexdigest()

    def semantic_label(value: str) -> str:
        # Keep stable UI meaning while removing volatile counters, clock values,
        # phone numbers and order ids.  Resource-id/class alone collapsed tabs
        # and stateful business screens that shared one layout into one page.
        value = re.sub(r"\d+", "#", (value or "").strip().lower())
        return re.sub(r"\s+", " ", value)[:120]

    def quantized_bounds(value: str) -> str:
        numbers = [int(item) for item in re.findall(r"\d+", str(value or ""))]
        if len(numbers) != 4:
            return ""
        return ",".join(str((number // 24) * 24) for number in numbers)

    surface_signature = "|".join(sorted(
        f"{e.get('resource_id', '')}:{e.get('class_name', '')}:{semantic_label(str(e.get('text') or ''))}:"
        f"{semantic_label(str(e.get('content_desc') or ''))}:{int(bool(e.get('checked')))}:"
        f"{int(bool(e.get('clickable')))}:{int(bool(e.get('enabled', True)))}:"
        f"{int(bool(e.get('selected')))}:"
        f"{quantized_bounds(str(e.get('bounds') or '')) if e.get('clickable') else ''}"
        for e in elements
    ))
    surface_fingerprint = hashlib.sha256(f"{activity}|{surface_signature}".encode("utf-8")).hexdigest()
    return PageSnapshot(
        activity=activity, xml=xml, elements=elements, fingerprint=fingerprint,
        surface_fingerprint=surface_fingerprint,
    )


def parse_page(activity: str, xml: str) -> PageSnapshot:
    elements: list[dict] = []
    try:
        # Appium UiAutomator2 dumps never carry a DTD; entity declarations can
        # only come from hostile content, so refuse them before parsing.
        if "<!DOCTYPE" in (xml or "") or "<!ENTITY" in (xml or ""):
            raise ET.ParseError("DTD declarations are not accepted")
        root = ET.fromstring(xml)
    except ET.ParseError:
        root = None
    if root is not None:
        for node in root.iter():
            attrs = node.attrib
            text = (attrs.get("text") or "").strip()
            resource_id = (attrs.get("resource-id") or "").strip()
            content_desc = (attrs.get("content-desc") or "").strip()
            clickable = attrs.get("clickable") == "true"
            bounds = attrs.get("bounds", "")
            # WebView icon controls (voice/photo/upload) can be exposed as a
            # clickable accessibility node with bounds but no label or id.
            # Retain such nodes so a deterministic, current-page-only probe
            # can address them without arbitrary screen coordinates.
            if not (text or resource_id or content_desc) and not (clickable and bounds):
                continue
            target = resource_id or text or content_desc or (f"bounds:{bounds}" if clickable and bounds else "")
            elements.append({
                "resource_id": resource_id, "text": text, "content_desc": content_desc,
                "target": target, "clickable": clickable, "bounds": bounds,
                "class_name": attrs.get("class", ""), "checked": attrs.get("checked") == "true",
                "checkable": attrs.get("checkable") == "true",
                "scrollable": attrs.get("scrollable") == "true",
                "enabled": attrs.get("enabled", "true") != "false",
                "selected": attrs.get("selected") == "true",
                "displayed": attrs.get("displayed", "true") != "false",
                "password": attrs.get("password") == "true",
                "editable": attrs.get("class", "").lower().endswith("edittext"),
            })
    return page_from_elements(activity, xml, elements)


@dataclass
class NavigationEdge:
    parent: str
    action: str
    status: str = "scheduled"
    child: str | None = None
    attempts: int = 0
    transient_failures: int = 0


@dataclass
class NavigationReplayEdge:
    """One verified, semantic and potentially replayable navigation click."""

    parent_surface: str
    parent_activity: str
    target: str
    target_identity: dict[str, str] = field(default_factory=dict)
    child_surface: str | None = None
    child_activity: str | None = None

    @classmethod
    def from_page(cls, page: PageSnapshot, target: str) -> "NavigationReplayEdge":
        raw = str(target or "")
        target_bounds = raw[len("bounds:"):] if raw.startswith("bounds:") else ""
        matched = None
        for item in page.elements:
            values = {
                str(item.get("target") or ""), str(item.get("resource_id") or ""),
                str(item.get("text") or ""), str(item.get("content_desc") or ""),
            }
            if raw in values or (target_bounds and target_bounds == str(item.get("bounds") or "")):
                matched = item
                break
        identity = {
            key: str((matched or {}).get(key) or "")
            for key in ("resource_id", "text", "content_desc", "class_name")
        }
        return cls(
            parent_surface=page.surface_fingerprint,
            parent_activity=page.activity,
            target=raw,
            target_identity=identity,
        )

    def as_dict(self) -> dict:
        return {
            "parent_surface": self.parent_surface,
            "parent_activity": self.parent_activity,
            "target": self.target,
            "target_identity": dict(self.target_identity),
            "child_surface": self.child_surface,
            "child_activity": self.child_activity,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "NavigationReplayEdge":
        return cls(
            parent_surface=str(value.get("parent_surface") or ""),
            parent_activity=str(value.get("parent_activity") or ""),
            target=str(value.get("target") or ""),
            target_identity={
                str(key): str(item or "")
                for key, item in dict(value.get("target_identity") or {}).items()
            },
            child_surface=str(value.get("child_surface") or "") or None,
            child_activity=str(value.get("child_activity") or "") or None,
        )


@dataclass
class NavigationReplayLedger:
    """Current safe breadcrumb route, independent of transient Appium sessions."""

    root_surface: str | None = None
    root_activity: str | None = None
    route: list[NavigationReplayEdge] = field(default_factory=list)
    pending_click: NavigationReplayEdge | None = None
    pending_back: bool = False
    revision: int = 0

    @staticmethod
    def _is_runtime_permission(activity: str) -> bool:
        lowered = str(activity or "").lower()
        return any(term in lowered for term in (
            "permissioncontroller", "grantpermissionsactivity", "permission.ui",
        ))

    def observe(self, page: PageSnapshot) -> None:
        if self.root_surface is None and not self._is_runtime_permission(page.activity):
            self.root_surface = page.surface_fingerprint
            self.root_activity = page.activity
            self.revision += 1
        if self.pending_click is not None:
            edge = self.pending_click
            self.pending_click = None
            if page.surface_fingerprint != edge.parent_surface:
                # A system permission dialog is ephemeral.  Keep the last
                # audited-App ancestor as the replay destination; replaying
                # its trigger lets the normal permission policy recreate it.
                if not self._is_runtime_permission(page.activity):
                    edge.child_surface = page.surface_fingerprint
                    edge.child_activity = page.activity
                    parent_index = next((
                        index for index, item in enumerate(self.route)
                        if item.child_surface == edge.parent_surface
                    ), None)
                    if edge.parent_surface == self.root_surface:
                        self.route = []
                    elif parent_index is not None:
                        self.route = self.route[:parent_index + 1]
                    self.route.append(edge)
                    self.revision += 1
        elif self.pending_back:
            self.pending_back = False
            if page.surface_fingerprint == self.root_surface:
                if self.route:
                    self.route = []
                    self.revision += 1
            else:
                match = next((
                    index for index, item in enumerate(self.route)
                    if item.child_surface == page.surface_fingerprint
                ), None)
                if match is not None and match + 1 < len(self.route):
                    self.route = self.route[:match + 1]
                    self.revision += 1
                elif self.route:
                    self.route.pop()
                    self.revision += 1

    def action_succeeded(self, page: PageSnapshot, target: str) -> None:
        if not target:
            return
        self.pending_click = NavigationReplayEdge.from_page(page, target)
        self.pending_back = False
        self.revision += 1

    def action_failed(self, page: PageSnapshot, target: str) -> None:
        if (
            self.pending_click is not None
            and self.pending_click.parent_surface == page.surface_fingerprint
            and self.pending_click.target == str(target or "")
        ):
            self.pending_click = None
            self.revision += 1

    def back_succeeded(self) -> None:
        self.pending_click = None
        self.pending_back = True
        self.revision += 1

    def replay_edges(self) -> list[NavigationReplayEdge]:
        edges = list(self.route)
        if self.pending_click is not None:
            edges.append(self.pending_click)
        return edges

    def semantic_route(self, limit: int = 6) -> str:
        """Stable route identity based on control meaning rather than bounds."""
        labels: list[str] = []
        for edge in self.route[-max(1, int(limit)):]:
            identity = edge.target_identity or {}
            label = next((
                str(identity.get(key) or "").strip()
                for key in ("resource_id", "text", "content_desc", "class_name")
                if str(identity.get(key) or "").strip()
            ), str(edge.target or ""))
            labels.append(re.sub(r"\d+", "#", label.lower()))
        return ">".join(labels)

    def as_dict(self) -> dict:
        return {
            "root_surface": self.root_surface,
            "root_activity": self.root_activity,
            "route": [item.as_dict() for item in self.route],
            "pending_click": self.pending_click.as_dict() if self.pending_click else None,
        }

    def restore(self, value: dict) -> None:
        self.root_surface = str(value.get("root_surface") or "") or None
        self.root_activity = str(value.get("root_activity") or "") or None
        self.route = [
            NavigationReplayEdge.from_dict(item)
            for item in value.get("route") or [] if isinstance(item, dict)
        ]
        pending = value.get("pending_click")
        self.pending_click = NavigationReplayEdge.from_dict(pending) if isinstance(pending, dict) else None
        self.pending_back = False
        self.revision += 1


@dataclass
class NavigationGraph:
    """Observed page graph with verified click/back transitions.

    The graph never assumes that a click descends. It waits for the next
    observation and records ``no_effect`` when the surface did not change.
    This is the state needed for real sibling-aware DFS on single-Activity
    Android applications.
    """

    nodes: set[str] = field(default_factory=set)
    roots: set[str] = field(default_factory=set)
    edges: dict[tuple[str, str], NavigationEdge] = field(default_factory=dict)
    stack: list[str] = field(default_factory=list)
    current_node: str | None = None
    pending_click: tuple[str, str] | None = None
    pending_back_from: str | None = None
    semantic_context: str = ""

    def node_for(self, page: PageSnapshot) -> str:
        if not self.semantic_context:
            return page.surface_fingerprint
        digest = hashlib.sha256(
            f"{page.surface_fingerprint}|{self.semantic_context}".encode("utf-8")
        ).hexdigest()[:20]
        return f"{page.surface_fingerprint}:{digest}"

    def set_semantic_context(self, *, role: str, phase: str, route: str = "") -> None:
        self.semantic_context = "|".join((str(role or "app_page"), str(phase or "observe"), str(route or "")))

    @property
    def depth(self) -> int:
        return max(0, len(self.stack) - 1)

    def observe(self, page: PageSnapshot) -> None:
        node = self.node_for(page)
        self.nodes.add(node)
        if not self.stack:
            self.stack.append(node)
        had_pending_transition = bool(self.pending_click or self.pending_back_from)
        if self.pending_click:
            parent, action = self.pending_click
            edge = self.edges[(parent, action)]
            if node == parent:
                edge.status = "no_effect"
            else:
                edge.status = "descended"
                edge.child = node
                if node in self.stack:
                    self.stack = self.stack[:self.stack.index(node) + 1]
                else:
                    self.stack.append(node)
            self.pending_click = None
        if self.pending_back_from:
            origin = self.pending_back_from
            if node != origin:
                if node in self.stack:
                    self.stack = self.stack[:self.stack.index(node) + 1]
                elif len(self.stack) > 1:
                    self.stack.pop()
                    self.stack[-1] = node
                else:
                    self.stack = [node]
            self.pending_back_from = None
        if not had_pending_transition and self.current_node and node != self.current_node:
            # Passive redraws, tab state updates and verified scroll viewports
            # stay at the same navigation depth. Replace the active stack node
            # rather than inventing a child edge.
            if self.stack:
                self.stack[-1] = node
        self.current_node = node

    def anchor_root(self, page: PageSnapshot) -> None:
        node = self.node_for(page)
        self.nodes.add(node)
        self.roots.add(node)
        self.current_node = node
        self.stack = [node]

    def is_root(self, page: PageSnapshot) -> bool:
        return self.node_for(page) in self.roots

    def schedule(self, page: PageSnapshot, action: str) -> NavigationEdge:
        key = (self.node_for(page), str(action))
        edge = self.edges.setdefault(key, NavigationEdge(parent=key[0], action=key[1]))
        edge.status = "scheduled"
        return edge

    def action_succeeded(self, page: PageSnapshot, action: str) -> None:
        edge = self.schedule(page, action)
        edge.attempts += 1
        edge.status = "attempted"
        self.pending_click = (edge.parent, edge.action)

    def action_failed(self, page: PageSnapshot, action: str, *, transient: bool) -> None:
        edge = self.schedule(page, action)
        edge.attempts += 1
        edge.status = "transient_failed" if transient else "blocked"
        edge.transient_failures += int(transient)
        if self.pending_click == (edge.parent, edge.action):
            self.pending_click = None

    def back_succeeded(self, page: PageSnapshot) -> None:
        self.pending_back_from = self.node_for(page)

    def edge_status(self, page: PageSnapshot, action: str) -> str | None:
        edge = self.edges.get((self.node_for(page), str(action)))
        return edge.status if edge else None


@dataclass
class PageState:
    seen: set[str] = field(default_factory=set)
    covered_pages: set[str] = field(default_factory=set)
    visited_targets: set[str] = field(default_factory=set)
    visited_page_targets: set[str] = field(default_factory=set)
    captured_views: set[str] = field(default_factory=set)
    page_visits: dict[str, int] = field(default_factory=dict)
    document_scrolls: dict[str, int] = field(default_factory=dict)
    document_entry_clicks: dict[str, int] = field(default_factory=dict)
    completed_documents: set[str] = field(default_factory=set)
    root_fingerprint: str | None = None
    root_surfaces: set[str] = field(default_factory=set)
    last_action: str | None = None
    last_action_page: str | None = None
    active_document: str | None = None
    navigation_depth: int = 0
    navigation_graph: NavigationGraph = field(default_factory=NavigationGraph)
    navigation_replay: NavigationReplayLedger = field(default_factory=NavigationReplayLedger)
    scheduled_page_targets: set[str] = field(default_factory=set)
    documents: DocumentReadingLedger = field(default_factory=DocumentReadingLedger)

    def set_semantic_context(self, *, role: str, phase: str) -> None:
        """Bind subsequent graph operations to role and Probe phase."""
        self.navigation_graph.set_semantic_context(
            role=role, phase=phase, route=self.navigation_replay.semantic_route(),
        )

    def is_new(self, page: PageSnapshot) -> bool:
        self.navigation_graph.observe(page)
        self.navigation_replay.observe(page)
        self.navigation_depth = self.navigation_graph.depth
        self.page_visits[page.fingerprint] = self.page_visits.get(page.fingerprint, 0) + 1
        # A long-document viewport is evidence content, not a new App page.
        # Semantic tab/business-state changes still count independently.
        if not (self.last_action == "scroll" and self.active_document):
            self.covered_pages.add(page.surface_fingerprint)
        if self.root_fingerprint is None:
            self.root_fingerprint = page.fingerprint
        if page.fingerprint in self.seen:
            return False
        self.seen.add(page.fingerprint)
        return True

    def anchor_root(self, page: PageSnapshot) -> None:
        """Anchor every observed main-tab state as a legitimate root surface."""
        self.root_fingerprint = page.fingerprint
        self.root_surfaces.add(page.surface_fingerprint)
        self.navigation_depth = 0
        self.navigation_graph.anchor_root(page)

    @staticmethod
    def _page_target_key(page: PageSnapshot, target: str) -> str:
        return f"{page.surface_fingerprint}:{target}"

    def mark_target(self, page: PageSnapshot, target: str) -> None:
        if target:
            self.visited_targets.add(target)
            self.visited_page_targets.add(self._page_target_key(page, target))

    def schedule_target(self, page: PageSnapshot, target: str) -> None:
        if target:
            self.scheduled_page_targets.add(self._page_target_key(page, target))
            self.navigation_graph.schedule(page, target)

    def commit_target(self, page: PageSnapshot, target: str) -> None:
        if target:
            self.scheduled_page_targets.discard(self._page_target_key(page, target))
            self.mark_target(page, target)
            self.navigation_graph.action_succeeded(page, target)
            self.navigation_replay.action_succeeded(page, target)

    def fail_target(self, page: PageSnapshot, target: str, *, transient: bool = True) -> None:
        if target:
            self.scheduled_page_targets.discard(self._page_target_key(page, target))
            self.navigation_graph.action_failed(page, target, transient=transient)
            self.navigation_replay.action_failed(page, target)

    def target_visited(self, page: PageSnapshot, target: str) -> bool:
        return self._page_target_key(page, target) in self.visited_page_targets

    def forget_target(self, page: PageSnapshot, target: str) -> None:
        """Allow one more tap after a consent gate (checkbox) changes the page."""
        if target:
            self.visited_page_targets.discard(self._page_target_key(page, target))

    def forget_target_everywhere(self, target: str) -> None:
        """Drop a click mark on every surface so an unread clause can be reopened."""
        if not target:
            return
        self.visited_targets.discard(target)
        suffix = f":{target}"
        self.visited_page_targets = {
            key for key in self.visited_page_targets if not key.endswith(suffix)
        }

    def targets_visited_on(self, page: PageSnapshot) -> set[str]:
        prefix = f"{page.surface_fingerprint}:"
        return {item[len(prefix):] for item in self.visited_page_targets if item.startswith(prefix)}

    def should_capture(self, page: PageSnapshot) -> bool:
        """Capture each distinct page or successful document viewport once."""
        document_key = self.active_document or ""
        scroll_index = self.document_scrolls.get(document_key, 0)
        key = f"{page.fingerprint}:{document_key}:{scroll_index}"
        if key in self.captured_views:
            return False
        self.captured_views.add(key)
        return True

    def start_document(
        self,
        key: str,
        entry_clicks: int = 0,
        *,
        kind: str = "",
        title: str = "",
        source_activity: str = "",
        source_target: str = "",
    ) -> None:
        self.active_document = key
        self.document_scrolls.setdefault(key, 0)
        self.document_entry_clicks.setdefault(key, entry_clicks)
        session = self.documents.start(
            key,
            kind=kind,
            title=title,
            source_activity=source_activity,
            source_target=source_target,
            entry_clicks=entry_clicks,
        )
        session.scrolls = max(session.scrolls, self.document_scrolls.get(key, 0))
        self.sync_document_projections()

    def sync_document_projections(self) -> None:
        """Maintain legacy document fields as one-way ledger projections."""
        self.active_document = self.documents.active_key
        self.completed_documents.update(self.documents.completed_keys())
        for key, session in self.documents.sessions.items():
            self.document_scrolls[key] = session.scrolls
            self.document_entry_clicks[key] = session.entry_clicks

    def document_is_complete(self, key: str) -> bool:
        return str(key or "") in self.documents.completed_keys() or str(key or "") in self.completed_documents

    def document_scroll_count(self, key: str) -> int:
        session = self.documents.sessions.get(str(key or ""))
        if session is not None:
            return int(session.scrolls)
        return int(self.document_scrolls.get(str(key or ""), 0))

    def document_entry_click_count(self, key: str) -> int:
        session = self.documents.sessions.get(str(key or ""))
        if session is not None:
            return int(session.entry_clicks)
        return int(self.document_entry_clicks.get(str(key or ""), 0))

    def document_active(self, key: str = "") -> bool:
        active = str(self.documents.active_key or self.active_document or "")
        return bool(active) if not key else active == str(key)

    def interrupt_document(self, key: str = "") -> None:
        if not key or self.document_active(key):
            self.documents.interrupt()
            self.sync_document_projections()

    def can_scroll_document(self, key: str, limit: int) -> bool:
        return key not in self.completed_documents and self.document_scrolls.get(key, 0) < limit

    def mark_document_scrolled(self, key: str) -> int:
        self.active_document = key
        self.document_scrolls[key] = self.documents.mark_scrolled(key)
        self.sync_document_projections()
        return self.document_scrolls[key]

    def finish_document(self, key: str) -> None:
        self.completed_documents.add(key)
        self.documents.finish(key, bottom_confirmed=True)
        self.sync_document_projections()

    def record_action(self, page: PageSnapshot, action: str, target: str = "") -> None:
        self.last_action = action
        self.last_action_page = page.fingerprint
        if action == "click" and target:
            self.navigation_graph.action_succeeded(page, target)
            self.navigation_replay.action_succeeded(page, target)
        elif action == "back":
            self.navigation_graph.back_succeeded(page)
            self.navigation_replay.back_succeeded()
        self.navigation_depth = self.navigation_graph.depth
        if action in {"click", "back", "stop"}:
            self.documents.interrupt()
            self.sync_document_projections()

    def back_made_no_progress(self, page: PageSnapshot) -> bool:
        return self.last_action == "back" and self.last_action_page == page.fingerprint

    def is_root_page(self, page: PageSnapshot) -> bool:
        return (
            self.navigation_graph.is_root(page)
            or page.fingerprint == self.root_fingerprint
            or page.surface_fingerprint in self.root_surfaces
        )

    def route_context(self, page: PageSnapshot) -> str:
        """Stable context for budgets that must not leak across sibling routes."""
        node = page.surface_fingerprint
        path = list(self.navigation_graph.stack)
        if not path or path[-1] != node:
            path.append(node)
        return ">".join(path[-4:])
