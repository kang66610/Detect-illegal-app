"""Device-free execution of recorded semantic observations."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent.ai_explorer.action_arbitration import ActionProposal
from agent.ai_explorer.action_pipeline import ActionPipeline
from agent.ai_explorer.replay_format import read_replay
from agent.ai_explorer.scenario_controller import ScenarioController
from agent.detection_engines.page_semantics import PageFacts, classify_page


@dataclass(frozen=True)
class ReplayResult:
    scenarios: dict[str, dict]
    final_actions: list[dict]
    checkpoint: int | None = None


def _facts(raw: dict) -> PageFacts:
    allowed = PageFacts.__dataclass_fields__
    return PageFacts(**{key: value for key, value in dict(raw or {}).items() if key in allowed})


def run_replay(path: Path, *, checkpoint: int | None = None) -> ReplayResult:
    rows = read_replay(Path(path))
    if checkpoint is not None and (checkpoint < 0 or checkpoint > len(rows)):
        raise ValueError("checkpoint outside replay")
    controller = ScenarioController.for_items(["3.8", "4.2"])
    pipeline = ActionPipeline()
    final_actions: list[dict] = []
    # Processing the prefix creates the same in-memory checkpoint a live writer
    # would persist; external side effects do not exist in replay mode.
    for row in rows:
        kind = str(row.get("type") or "")
        if kind == "scenario":
            controller.observe(
                str(row.get("event") or ""),
                item=str(row.get("item") or ""),
                target=str(row.get("target") or ""),
                source=str(row.get("source") or "replay"),
                direct_outcome=bool(row.get("direct_outcome")),
            )
        elif kind == "page":
            proposals = [
                ActionProposal(
                    action=str(item.get("action") or "wait"),
                    target=str(item.get("target") or ""),
                    reason=str(item.get("reason") or ""),
                    source=str(item.get("source") or "replay"),
                    priority=int(item.get("priority") or 0),
                    scenario_items=tuple(str(v) for v in item.get("scenario_items") or ()),
                )
                for item in row.get("proposals") or []
            ]
            final = pipeline.choose(
                proposals, semantics=classify_page(_facts(row.get("facts") or {})),
                is_root=bool(row.get("is_root")),
            )
            final_actions.append({
                "action": final.action, "target": final.target, "source": final.source,
            })
    scenarios = {
        item: controller.execution(item).__dict__.copy()
        for item in ("3.8", "4.2")
    }
    for row in scenarios.values():
        row["state"] = row["state"].value
    return ReplayResult(scenarios=scenarios, final_actions=final_actions, checkpoint=checkpoint)
