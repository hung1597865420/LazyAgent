import asyncio
import json
import math
import os
import tempfile
from pathlib import Path

import tools.goal as goal


def test_goal_state_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            state = goal.GoalState(goal="ship prompt-only autopilot", plan="check edits")
            state.parts = ["plan", "implement", "verify"]
            state.current_part_index = 1
            goal.save_goal_state(state)
            loaded = goal.get_active_goal()
            assert loaded is not None
            assert loaded.goal == "ship prompt-only autopilot"
            assert loaded.plan == "check edits"
            assert loaded.parts == ["plan", "implement", "verify"]
            assert loaded.current_part_index == 1
            assert Path(tmp, goal.GOAL_STATE_FILE).exists()
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_parse_parts_fallback():
    parsed = goal._parse_parts("Plan: x\nParts:\n1. design\n2. verify\nAcceptance: pass", "fallback")
    assert parsed == ["design", "verify"]
    assert goal._parse_parts("1. design\n2. verify", "fallback") == ["design", "verify"]
    assert goal._parse_parts("no list", "fallback") == ["fallback"]


def test_goal_status_idle_without_file():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            assert asyncio.run(goal.goal_autopilot("status")) == {"status": "idle"}
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_bad_state_does_not_crash():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            Path(tmp, goal.GOAL_STATE_FILE).write_text(
                '{"goal":"x","checks_run":"bad","created_at":"bad","current_part_index":"bad"}',
                encoding="utf-8",
            )
            state = goal.load_goal_state()
            assert state is not None
            assert state.checks_run == 0
            assert state.current_part_index == 0
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_workspace_scope_for_claude_gemini_antigravity():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_env = {k: os.environ.get(k) for k in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        try:
            os.environ["WORKSPACE_ROOT"] = str(root / "codex")
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
            goal.save_goal_state(goal.GoalState(goal="codex"))

            os.environ.pop("WORKSPACE_ROOT", None)
            os.environ["CLAUDE_PROJECT_DIR"] = str(root / "claude")
            goal.save_goal_state(goal.GoalState(goal="claude"))

            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            os.environ["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"workspacePath": str(root / "gemini")}})
            goal.save_goal_state(goal.GoalState(goal="gemini"))

            assert (root / "codex" / goal.GOAL_STATE_FILE).exists()
            assert (root / "claude" / goal.GOAL_STATE_FILE).exists()
            assert (root / "gemini" / goal.GOAL_STATE_FILE).exists()

            os.environ["WORKSPACE_ROOT"] = str(root / "wins")
            os.environ["CLAUDE_PROJECT_DIR"] = str(root / "claude_wins")
            os.environ["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"workspacePath": str(root / "also_loses")}})
            assert goal._state_path().parent == Path(os.path.normcase(str((root / "claude_wins").resolve())))
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_goal_state_rejects_non_finite_timestamps():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            Path(tmp, goal.GOAL_STATE_FILE).write_text(
                json.dumps({"goal": "ship", "created_at": "nan", "updated_at": "inf"}),
                encoding="utf-8",
            )
            state = goal.load_goal_state()
            assert state is not None
            assert math.isfinite(state.created_at)
            assert math.isfinite(state.updated_at)
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_init_and_check_advance_parts_without_router():
    async def fake_worker(instruction, context):
        if "execution plan" in instruction:
            return {"output": "Plan: ship\nParts:\n1. design\n2. implement\nAcceptance: green\nFirst action: design"}
        return {"output": "verdict: pass\npart_status: done\nNext action: implement"}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_worker = goal._worker
        goal.WORKSPACE_ROOT = tmp
        goal._worker = fake_worker
        try:
            started = asyncio.run(goal.goal_autopilot("init", goal="ship goal"))
            assert started["parts"] == ["design", "implement"]
            checked = asyncio.run(goal.goal_autopilot("check", changed_files=["app.py"], diff="+print(1)"))
            assert checked["part_status"] == "done"
            assert checked["current_part_index"] == 1
            assert checked["current_part"] == "implement"
        finally:
            goal._worker = old_worker
            goal.WORKSPACE_ROOT = old_root


def test_complete_runs_final_auto_trigger():
    calls = []

    async def fake_auto_trigger(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "mode": kwargs["mode"], "stage": kwargs["stage"]}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot(
                "complete",
                changed_files=["app.py"],
                diff="+print(1)",
                context="done",
            ))
            assert completed["status"] == "completed"
            assert completed["final_check"]["mode"] == "max"
            assert calls == [{
                "changed_files": ["app.py"],
                "diff": "+print(1)",
                "task": "Final overall goal acceptance check:\nship\n\ndone",
                "stage": "final",
                "mode": "max",
            }]
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_blocks_when_final_check_has_blockers():
    async def fake_auto_trigger(**kwargs):
        return {"status": "completed", "mode": "max", "stage": "final", "blockers_count": 1}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot("complete", changed_files=["app.py"], context="done"))
            assert completed["status"] == "blocked"
            assert "Final check returned blockers." in completed["completion_note"]
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_blocks_when_final_check_skipped():
    async def fake_auto_trigger(**kwargs):
        return {"status": "skipped", "reason": "no matching automatic checks"}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot("complete", context="done"))
            assert completed["status"] == "blocked"
            assert completed["final_check"]["status"] == "skipped"
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_goal_supervisor_next_actions_and_summary():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            assert asyncio.run(goal.goal_supervisor())["next_action"] == "complete"

            state = goal.GoalState(goal="ship supervisor", parts=["build", "verify"])
            goal.save_goal_state(state)
            first = asyncio.run(goal.goal_supervisor())
            assert first["next_action"] == "continue_part"
            assert "Goal: ship supervisor" in first["summary"]
            assert goal.inject_goal_progress_summary("body").startswith("Goal: ship supervisor")
            injected = goal.inject_goal_progress_summary("\ufeff  " + first["summary"] + "\n\nbody")
            assert injected.count("Goal: ship supervisor") == 1

            state.last_result = {"verdict": "unclear", "part_status": "in_progress"}
            goal.save_goal_state(state)
            assert asyncio.run(goal.goal_supervisor(changed_files=["app.py"]))["next_action"] == "run_check"

            state.last_result = {"verdict": "pass", "part_status": "done"}
            state.current_part_index = 1
            goal.save_goal_state(state)
            assert asyncio.run(goal.goal_supervisor())["next_action"] == "run_final"
            assert asyncio.run(goal.goal_supervisor(last_checks={"status": "completed", "stage": "final", "blockers_count": 0}))["next_action"] == "complete"
            assert asyncio.run(goal.goal_supervisor(last_checks={"blockers_count": 1}))["next_action"] == "blocked_ask_user"
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_auto_trigger_drops_stale_goal_alignment():
    async def fake_check_goal(**kwargs):
        return {"status": "idle", "message": "No active goal"}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_check_goal = goal.check_goal
            goal.check_goal = fake_check_goal
            result = asyncio.run(auto.auto_trigger(changed_files=["README.md"], mode="safe", stage="post_edit"))
            assert result["status"] == "completed"
            assert "goal_alignment" not in result["selected_tools"]
            assert any("dropped stale goal_alignment" in w for w in result["warnings"])
        finally:
            goal.check_goal = old_check_goal
            goal.WORKSPACE_ROOT = old_root


def test_goal_check_retries_when_part_advances_concurrently():
    async def fake_worker(*_args, **_kwargs):
        await asyncio.sleep(0.01)
        return {"output": "verdict: pass\npart_status: done\nok"}

    async def run_checks():
        return await asyncio.gather(
            goal.check_goal(changed_files=["app.py"]),
            goal.check_goal(changed_files=["app.py"]),
        )

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_worker = goal._worker
        goal.WORKSPACE_ROOT = tmp
        goal._worker = fake_worker
        try:
            goal.save_goal_state(goal.GoalState(goal="ship", parts=["build", "verify"]))
            results = asyncio.run(run_checks())
            state = goal.get_active_goal()
            assert all(r["status"] == "checked" for r in results), results
            assert state is not None
            assert state.current_part_index == 1
            assert state.checks_run == 2
            assert state.last_result["part_status"] == "done"
        finally:
            goal._worker = old_worker
            goal.WORKSPACE_ROOT = old_root


if __name__ == "__main__":
    test_goal_state_roundtrip()
    test_parse_parts_fallback()
    test_goal_status_idle_without_file()
    test_bad_state_does_not_crash()
    test_workspace_scope_for_claude_gemini_antigravity()
    test_goal_state_rejects_non_finite_timestamps()
    test_init_and_check_advance_parts_without_router()
    test_complete_runs_final_auto_trigger()
    test_complete_blocks_when_final_check_has_blockers()
    test_complete_blocks_when_final_check_skipped()
    test_goal_supervisor_next_actions_and_summary()
    test_auto_trigger_drops_stale_goal_alignment()
    test_goal_check_retries_when_part_advances_concurrently()
