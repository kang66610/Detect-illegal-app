from pathlib import Path


TASK_PROGRESS = Path(__file__).parents[2] / "frontend" / "src" / "views" / "TaskProgress.vue"


def test_running_task_stop_control_uses_terminate_contract():
    """The UI must use cooperative termination, not the legacy hard cancel API."""
    source = TASK_PROGRESS.read_text(encoding="utf-8")

    assert "api.post(`/tasks/${task.id}/terminate`)" in source
    assert "api.post(`/tasks/${task.id}/cancel`)" not in source


def test_terminate_control_does_not_wait_for_a_full_list_refresh():
    """The stop button must return immediately; polling can refresh afterward."""
    source = TASK_PROGRESS.read_text(encoding="utf-8")
    block = source.split("async function terminate(task)", 1)[1].split("async function removeTask", 1)[0]

    assert "void load()" in block
    assert "await load()" not in block


def test_operation_history_rows_have_no_horizontal_dividers():
    """History entries should read as a continuous timeline rather than a table."""
    source = TASK_PROGRESS.read_text(encoding="utf-8")
    block = source.split(".process-actions p {", 1)[1].split("}", 1)[0]

    assert "border-bottom" not in block
    history_blocks = [part.split("}", 1)[0] for part in source.split(".process-history {")[1:]]
    assert history_blocks and all("border: 1px" not in block for block in history_blocks)


def test_paused_tasks_are_not_labeled_as_running_in_app_summary():
    """The group summary must distinguish paused work from active work."""
    source = TASK_PROGRESS.read_text(encoding="utf-8")

    assert "pausedCount" in source
    assert "{{ group.pausedCount }} 已暂停" in source
    active_expression = "group.tasks.filter((task) => ACTIVE.includes(task.status)).length"
    assert active_expression in source
