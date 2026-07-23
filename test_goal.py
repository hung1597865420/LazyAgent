import asyncio
import concurrent.futures
import json
import math
import os
import tempfile
from pathlib import Path

import tools.goal as goal
from tools.workspace_context import capture_workspace_context, get_active_workspace_override, workspace_scope


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


def test_goal_state_sanitizes_surrogate_text():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = tmp
        try:
            for key in old_env:
                os.environ.pop(key, None)
            result = goal.init_static_goal("tính năng lớn " + chr(0xDC8B) + " cần BA", source="test")
            assert result["status"] == "initialized_static"
            assert "\udc8b" not in result["goal"]
            loaded = goal.load_goal_state()
            assert loaded is not None
            assert "\udc8b" not in loaded.goal
            assert "?" in loaded.goal
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_workspace_scope_for_claude_gemini_antigravity():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        try:
            for dirname in ("codex", "claude", "gemini", "wins", "claude_wins", "also_loses", "active_wins"):
                (root / dirname).mkdir()
            os.environ.pop("HARNESS_ACTIVE_WORKSPACE", None)
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
            assert goal._state_path().parent == Path(os.path.normcase(str((root / "wins").resolve())))

            os.environ["HARNESS_ACTIVE_WORKSPACE"] = str(root / "active_wins")
            assert goal._state_path().parent == Path(os.path.normcase(str((root / "active_wins").resolve())))

            with workspace_scope(root / "gemini"):
                assert goal._state_path().parent == Path(os.path.normcase(str((root / "gemini").resolve())))
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_workspace_context_explicit_thread_capture_no_global_leak():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_a = root / "repo_a"
        repo_b = root / "repo_b"
        repo_a.mkdir()
        repo_b.mkdir()
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = str(repo_b)
        try:
            os.environ["WORKSPACE_ROOT"] = str(repo_b)
            os.environ.pop("HARNESS_ACTIVE_WORKSPACE", None)
            os.environ.pop("CLAUDE_PROJECT_DIR", None)
            os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)

            with workspace_scope(repo_a):
                runner = capture_workspace_context()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    state_path = pool.submit(runner, goal._state_path).result()

            assert state_path.parent == Path(os.path.normcase(str(repo_a.resolve())))
            assert get_active_workspace_override() == ""
            assert goal._state_path().parent == Path(os.path.normcase(str(repo_b.resolve())))
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_workspace_context_runner_reusable_across_threads():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo = root / "repo"
        repo.mkdir()
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = str(root)
        try:
            with workspace_scope(repo):
                runner = capture_workspace_context()

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: runner(goal._state_path).parent, range(2)))

            assert results == [Path(os.path.normcase(str(repo.resolve())))] * 2
        finally:
            goal.WORKSPACE_ROOT = old_root


def test_goal_state_thread_ignores_mutable_workspace_env():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_a = root / "repo_a"
        repo_b = root / "repo_b"
        stable = root / "stable"
        repo_a.mkdir()
        repo_b.mkdir()
        stable.mkdir()
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = str(stable)
        try:
            def resolve_with_env(path):
                os.environ["HARNESS_ACTIVE_WORKSPACE"] = str(path)
                return goal._state_path().parent

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(resolve_with_env, [repo_a, repo_b]))

            assert results == [Path(os.path.normcase(str(stable.resolve())))] * 2
            assert not (repo_a / goal.GOAL_STATE_FILE).exists()
            assert not (repo_b / goal.GOAL_STATE_FILE).exists()
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_goal_state_async_uses_context_not_mutable_env():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        repo_a = root / "repo_a"
        repo_b = root / "repo_b"
        stable = root / "stable"
        repo_a.mkdir()
        repo_b.mkdir()
        stable.mkdir()
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = str(stable)
        try:
            async def create_in_scope(path, name, marker):
                with workspace_scope(path):
                    os.environ["HARNESS_ACTIVE_WORKSPACE"] = str(repo_b if path == repo_a else repo_a)
                    await marker.wait()
                    return goal.init_static_goal(name, source="async-test")

            async def run_pair():
                marker = asyncio.Event()
                task_a = asyncio.create_task(create_in_scope(repo_a, "ship A", marker))
                task_b = asyncio.create_task(create_in_scope(repo_b, "ship B", marker))
                marker.set()
                return await asyncio.gather(task_a, task_b)

            results = asyncio.run(run_pair())
            assert {item["status"] for item in results} == {"initialized_static"}
            assert (repo_a / goal.GOAL_STATE_FILE).exists()
            assert (repo_b / goal.GOAL_STATE_FILE).exists()
            assert not (stable / goal.GOAL_STATE_FILE).exists()
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_static_goal_reuses_only_same_prompt():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = tmp
        try:
            for key in old_env:
                os.environ.pop(key, None)
            first = goal.init_static_goal("ship lifecycle feature", source="test")
            same = goal.init_static_goal("ship lifecycle feature", source="test")
            different = goal.init_static_goal("write unrelated docs", source="test")
            assert first["status"] == "initialized_static"
            assert same["status"] == "existing_active"
            assert different["status"] == "conflict_active_goal"
            assert goal.load_goal_state().goal == "ship lifecycle feature"
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_static_goal_concurrent_different_prompts_one_wins():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = tmp
        try:
            for key in old_env:
                os.environ.pop(key, None)

            def start(prompt):
                return goal.init_static_goal(prompt, source="thread-test")["status"]

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                statuses = list(pool.map(start, ["ship feature alpha", "ship feature beta"]))

            assert statuses.count("initialized_static") == 1
            assert statuses.count("conflict_active_goal") == 1
            assert goal.get_active_goal() is not None
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_static_goal_fingerprint_preserves_invalid_codepoints():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        goal.WORKSPACE_ROOT = tmp
        try:
            for key in old_env:
                os.environ.pop(key, None)
            first = goal.init_static_goal("fix A" + chr(0xD800) + "B", source="test")
            second = goal.init_static_goal("fix A?B", source="test")
            assert first["status"] == "initialized_static"
            assert second["status"] == "conflict_active_goal"
        finally:
            goal.WORKSPACE_ROOT = old_root
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def test_goal_state_ignores_deleted_workspace_env():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        active = root / "active"
        active.mkdir()
        deleted = root / "deleted"
        old_env = {k: os.environ.get(k) for k in ("HARNESS_ACTIVE_WORKSPACE", "WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = str(active)
        try:
            os.environ.pop("HARNESS_ACTIVE_WORKSPACE", None)
            os.environ.pop("WORKSPACE_ROOT", None)
            os.environ["CLAUDE_PROJECT_DIR"] = str(deleted)
            os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
            assert goal._state_path().parent == Path(os.path.normcase(str(active.resolve())))
        finally:
            goal.WORKSPACE_ROOT = old_root
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


def test_goal_state_rejects_non_finite_integer_fields():
    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        try:
            Path(tmp, goal.GOAL_STATE_FILE).write_text(
                json.dumps({"goal": "ship", "revision": 1e309, "checks_run": 1e309, "current_part_index": 1e309}),
                encoding="utf-8",
            )
            state = goal.load_goal_state()
            assert state is not None
            assert state.revision == 0
            assert state.checks_run == 0
            assert state.current_part_index == 0
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
            assert completed["final_check"]["mode"] == "safe"
            assert calls == [{
                "changed_files": ["app.py"],
                "diff": "+print(1)",
                "task": "Final overall goal acceptance check:\nship\n\ndone",
                "stage": "final",
                "mode": "safe",
            }]
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_runs_fresh_final_check_despite_previous_pass_result():
    calls = []

    async def fake_auto_trigger(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "stage": "final", "blockers_count": 0}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        state = goal.GoalState(goal="ship", parts=["verify"])
        state.last_result = {"verdict": "pass", "part_status": "done", "summary": "old final pass"}
        goal.save_goal_state(state)
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot("complete", changed_files=["app.py"], context="fresh edits"))
            assert completed["status"] == "completed"
            assert len(calls) == 1
            assert calls[0]["task"] == "Final overall goal acceptance check:\nship\n\nfresh edits"
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_rejects_before_final_part_without_running_final_check():
    calls = []

    async def fake_auto_trigger(**kwargs):
        calls.append(kwargs)
        return {"status": "completed", "mode": kwargs["mode"], "stage": kwargs["stage"]}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["design", "verify"], current_part_index=0))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot(
                "complete",
                changed_files=["app.py"],
                diff="+print(1)",
                context="done too early",
            ))
            assert completed["status"] == "blocked"
            assert completed["next_action"] == "continue_part"
            assert completed["final_check"] is None
            assert calls == []
            active = goal.get_active_goal()
            assert active is not None
            assert active.status == "active"
            assert active.current_part_index == 0
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


def test_complete_blocks_when_final_check_raises():
    async def fake_auto_trigger(**kwargs):
        raise TimeoutError("final gate down")

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
            assert completed["final_check"]["status"] == "error"
            assert completed["final_check"]["blockers_count"] == 1
            assert "TimeoutError" in completed["final_check"]["error"]
            saved = goal.load_goal_state()
            assert saved is not None
            assert saved.status == "blocked"
            assert "Final check returned blockers." in saved.completion_note
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_allows_final_check_goal_alignment_mutation():
    async def fake_auto_trigger(**kwargs):
        state = goal.load_goal_state()
        assert state is not None
        state.last_result = {"verdict": "pass", "part_status": "done", "summary": "final alignment"}
        goal.save_goal_state(state)
        return {"status": "completed", "stage": "final", "blockers_count": 0}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            completed = asyncio.run(goal.goal_autopilot("complete", changed_files=["app.py"], context="done"))
            assert completed["status"] == "completed"
            assert completed["final_check"]["status"] == "completed"
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


def test_complete_concurrent_runs_final_once():
    calls = []

    async def fake_auto_trigger(**kwargs):
        calls.append(kwargs)
        await asyncio.sleep(0.05)
        return {"status": "completed", "stage": "final", "blockers_count": 0}

    async def run_complete_pair():
        return await asyncio.gather(
            goal.goal_autopilot("complete", changed_files=["app.py"], context="done"),
            goal.goal_autopilot("complete", changed_files=[], context="done"),
        )

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        goal.WORKSPACE_ROOT = tmp
        goal.save_goal_state(goal.GoalState(goal="ship", parts=["verify"]))
        try:
            import tools.auto as auto

            old_auto_trigger = auto.auto_trigger
            auto.auto_trigger = fake_auto_trigger
            results = asyncio.run(run_complete_pair())
            assert len(calls) == 1
            assert any(result["status"] == "completed" for result in results), results
            assert any(result["status"] in {"blocked", "idle"} for result in results), results
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


def test_goal_check_revision_guard_with_frozen_time():
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
        old_now = goal._now
        goal.WORKSPACE_ROOT = tmp
        goal._worker = fake_worker
        goal._now = lambda: 123.0
        try:
            goal.save_goal_state(goal.GoalState(goal="ship", parts=["build", "verify"]))
            results = asyncio.run(run_checks())
            state = goal.get_active_goal()
            assert all(r["status"] == "checked" for r in results), results
            assert state is not None
            assert state.current_part_index == 1
            assert state.checks_run == 2
            assert state.revision >= 3
        finally:
            goal._now = old_now
            goal._worker = old_worker
            goal.WORKSPACE_ROOT = old_root


def test_goal_check_sanitizes_changed_files():
    async def fake_worker(*_args, **_kwargs):
        return {"output": "verdict: unclear\npart_status: in_progress\nok"}

    with tempfile.TemporaryDirectory() as tmp:
        old_root = goal.WORKSPACE_ROOT
        old_worker = goal._worker
        goal.WORKSPACE_ROOT = tmp
        goal._worker = fake_worker
        try:
            goal.save_goal_state(goal.GoalState(goal="ship", parts=["build"]))
            result = asyncio.run(goal.check_goal(changed_files=[None, 123, "app.py"]))
            assert result["status"] == "checked"
            saved = goal.get_active_goal()
            assert saved is not None
            assert saved.last_result["changed_files"] == ["123", "app.py"]
        finally:
            goal._worker = old_worker
            goal.WORKSPACE_ROOT = old_root


def test_complete_blocks_on_malformed_blockers_count():
    async def fake_auto_trigger(**kwargs):
        return {"status": "completed", "stage": "final", "blockers_count": "unknown"}

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
            assert completed["final_check"]["blockers_count"] == "unknown"
        finally:
            auto.auto_trigger = old_auto_trigger
            goal.WORKSPACE_ROOT = old_root


if __name__ == "__main__":
    test_goal_state_roundtrip()
    test_parse_parts_fallback()
    test_goal_status_idle_without_file()
    test_bad_state_does_not_crash()
    test_workspace_scope_for_claude_gemini_antigravity()
    test_workspace_context_explicit_thread_capture_no_global_leak()
    test_workspace_context_runner_reusable_across_threads()
    test_goal_state_thread_ignores_mutable_workspace_env()
    test_goal_state_async_uses_context_not_mutable_env()
    test_static_goal_fingerprint_preserves_invalid_codepoints()
    test_goal_state_rejects_non_finite_timestamps()
    test_goal_state_rejects_non_finite_integer_fields()
    test_init_and_check_advance_parts_without_router()
    test_complete_runs_final_auto_trigger()
    test_complete_blocks_when_final_check_has_blockers()
    test_complete_blocks_when_final_check_skipped()
    test_complete_allows_final_check_goal_alignment_mutation()
    test_complete_concurrent_runs_final_once()
    test_goal_supervisor_next_actions_and_summary()
    test_auto_trigger_drops_stale_goal_alignment()
    test_goal_check_revision_guard_with_frozen_time()
    test_goal_check_sanitizes_changed_files()
    test_complete_blocks_on_malformed_blockers_count()
    test_goal_check_retries_when_part_advances_concurrently()
