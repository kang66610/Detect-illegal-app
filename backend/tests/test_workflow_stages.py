from agent.agent_core.workflow_stages import run_reporting_stage, run_static_analysis_stage


def test_static_stage_decrypts_once_and_accumulates_results():
    calls = []
    state = {"decrypted_apk": None, "results": []}

    run_static_analysis_stage(
        state,
        decrypt=lambda: calls.append("decrypt") or "apk.tmp",
        run_static=lambda: calls.append("static") or ["flowdroid"],
    )
    run_static_analysis_stage(
        state,
        decrypt=lambda: calls.append("decrypt") or "apk.tmp",
        run_static=lambda: calls.append("static") or ["flowdroid"],
    )

    assert calls == ["decrypt", "static", "static"]
    assert state == {"decrypted_apk": "apk.tmp", "results": ["flowdroid", "flowdroid"]}


def test_reporting_stage_passes_the_shared_pipeline_state_to_generator():
    state = {"session": "db", "task": "task", "apk": "apk", "matched": ["r"],
             "score": 90, "breakdown": {"total": 10}, "evidence": ["e"], "ctx": "ctx"}
    received = []

    run_reporting_stage(state, generate=lambda *args: received.append(args))

    assert received == [("db", "task", "apk", ["r"], 90, {"total": 10}, ["e"], "ctx")]
