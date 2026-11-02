from agent.agent_core.workflow import run_task
def test_run_task_returns_when_task_does_not_exist():
    run_task(999999)
    # 不存在的任务：workflow 静默返回，不抛异常（日志记录）
