"""Regression contracts for name-resolution bugs inside the traversal engine.

These cover failures that the behavioural suite cannot reach cheaply:

* ``_run_phase_cycle`` reused the name ``recovery`` for a privacy-hub tab
  target, shadowing the ``RuntimeRecoveryCoordinator`` created earlier in the
  same scope.  Every later crash/device-loss recovery then raised
  ``AttributeError: 'NoneType' object has no attribute 'replay_after_reactivation'``.
* ``delete_report_artifacts`` logged an undefined ``task_id`` while handling an
  OSError, which replaced a retryable cleanup warning with a ``NameError``.
"""
from __future__ import annotations

import ast
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.services import artifact_cleanup

ENGINE_PATH = Path(__file__).resolve().parents[2] / "agent" / "ai_explorer" / "explorer_engine.py"
IMPORT_CONTRACT_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_import_contracts.py"


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {ENGINE_PATH.name}")


def _direct_statements(node: ast.AST):
    """Yield nodes in this scope only, never descending into nested defs."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        for child in ast.iter_child_nodes(current):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                continue
            stack.append(child)


def test_run_phase_cycle_binds_recovery_only_to_the_runtime_coordinator() -> None:
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    cycle = _function_node(tree, "_run_phase_cycle")

    assignments = []
    for node in _direct_statements(cycle):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "recovery" for t in node.targets):
                assignments.append(node)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "recovery":
                assignments.append(node)

    assert len(assignments) == 1, (
        "`recovery` must only be assigned once per traversal phase; "
        f"found {len(assignments)} assignments at lines "
        f"{[node.lineno for node in assignments]}"
    )
    assigned_from = assignments[0].value
    assert isinstance(assigned_from, ast.Call), "`recovery` must be built from the coordinator class"
    assert getattr(assigned_from.func, "id", None) == "RuntimeRecoveryCoordinator"


def test_run_phase_cycle_has_no_other_recovery_shadowing_names() -> None:
    """A tab target must never be stored under the coordinator's name."""
    tree = ast.parse(ENGINE_PATH.read_text(encoding="utf-8"))
    cycle = _function_node(tree, "_run_phase_cycle")
    offenders = []
    for node in _direct_statements(cycle):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            fname = getattr(func, "id", None) or getattr(func, "attr", None)
            if fname in {"_privacy_hub_tab_target", "_main_content_tab_target"}:
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "recovery":
                        offenders.append(node.lineno)
    assert offenders == [], f"tab target assigned to `recovery` at lines {offenders}"


def test_all_from_imports_resolve_to_existing_names() -> None:
    """Guard the facade/re-export layer against over-eager unused-import cleanup.

    ruff's F401 cannot see that a name is re-exported for another module, so
    deleting it turns a lint warning into an ImportError at collection time.
    """
    result = subprocess.run(
        [sys.executable, str(IMPORT_CONTRACT_SCRIPT)],
        capture_output=True, text=True, encoding="utf-8", cwd=ENGINE_PATH.parents[2],
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("OK"), result.stdout


def _fail_unlink(monkeypatch) -> None:
    """Force Path.unlink to raise OSError regardless of platform delete shims."""
    def boom(self, *args, **kwargs):
        raise OSError("file is locked by another process")
    monkeypatch.setattr(Path, "unlink", boom)


def _prepare_report(tmp_path, monkeypatch, name: str) -> None:
    """Point the service at tmp_path and create a pending report artifact."""
    export_root = tmp_path / "data" / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / name).write_text("x", encoding="utf-8")
    monkeypatch.setattr(artifact_cleanup, "PROJECT_ROOT", tmp_path)
    # Test runs rewrite the export dir (data/test-runtime/exports); pin it back
    # so the report path resolves inside the configured export root.
    monkeypatch.setitem(artifact_cleanup.config["storage"], "export_dir", "data/exports")
    _fail_unlink(monkeypatch)


def test_report_cleanup_warns_instead_of_raising_nameerror(tmp_path, monkeypatch, caplog) -> None:
    _prepare_report(tmp_path, monkeypatch, "RPT-broken.pdf")

    with caplog.at_level(logging.WARNING):
        artifact_cleanup.delete_report_artifacts(["data/exports/RPT-broken.pdf"])

    assert "report cleanup will need retry" in caplog.text
    assert "unknown" in caplog.text


def test_task_artifacts_cleanup_passes_task_id_into_report_cleanup(tmp_path, monkeypatch, caplog) -> None:
    _prepare_report(tmp_path, monkeypatch, "RPT-task.pdf")

    with caplog.at_level(logging.WARNING):
        artifact_cleanup.delete_task_artifacts(4242, ["data/exports/RPT-task.pdf"])

    assert "Task 4242 report cleanup will need retry" in caplog.text
