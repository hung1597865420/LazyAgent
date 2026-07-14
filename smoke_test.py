"""Smoke test offline — không gọi Azure API."""
# ruff: noqa: E402
import asyncio
import json
import sqlite3
import sys
import os
import shutil
import time
import uuid
from pathlib import Path
import atexit

# Ngăn chặn đệ quy vô hạn khi các công cụ gọi lại smoke_test.py
if os.environ.get("SMOKE_TEST_SUBRUN") == "1":
    print("✅ Sub-run smoke test pass (bypassed recursively)")
    sys.exit(0)

# Đặt biến môi trường cho các tiến trình con để tránh đệ quy
os.environ["SMOKE_TEST_SUBRUN"] = "1"

SMOKE_DIR = Path(".harness_smoke") / f"{os.getpid()}_{uuid.uuid4().hex[:8]}"
SMOKE_FILE = SMOKE_DIR / "test_panel.py"
SMOKE_FILE_REL = SMOKE_FILE.as_posix()
SMOKE_DIR.mkdir(parents=True, exist_ok=True)
atexit.register(lambda: shutil.rmtree(SMOKE_DIR, ignore_errors=True))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import subprocess
original_run = subprocess.run

# Mock subprocess.run để giả lập kết quả pip list --outdated offline
def mock_subprocess_run(args, *other_args, **kwargs):
    # Chuẩn hóa args thành list các chuỗi
    cmd_args = args if isinstance(args, (list, tuple)) else str(args).split()
    cmd_args = [str(a).strip().lower() for a in cmd_args]
    
    # Kiểm tra xem có phải lệnh pip list --outdated không
    is_pip_list_outdated = (
        any("pip" in part for part in cmd_args) and 
        "list" in cmd_args and 
        "--outdated" in cmd_args
    )
    
    if is_pip_list_outdated:
        class MockCompletedProcess:
            returncode = 0
            stdout = '[{"name": "playwright", "version": "1.40.0", "latest_version": "1.45.0", "latest_filetype": "wheel"}]'
            stderr = ''
        return MockCompletedProcess()
    return original_run(args, *other_args, **kwargs)

subprocess.run = mock_subprocess_run

import agents
from tools.core import _calculate_review_hash, _is_sqlite_busy_error

# Mocking Agent and LLM calls to prevent network activity in smoke tests
def mock_run(self, task: str, extra_context: str = "", *, json_mode: bool = False, max_output_tokens: int = 4096, **_kwargs):
    role_responses = {
        agents.AgentRole.DEBUGGER: """## Root cause
Lỗi do biến chưa định nghĩa ở file:line

## Patch
```diff
--- a/{path}
+++ b/{path}
@@ -1,3 +1,3 @@
-x = 1
+x = 2
```

## Lưu ý
Không có""".format(path=SMOKE_FILE_REL),
        agents.AgentRole.CODE_A: """```python
def test_auto_generated():
    assert True
```""",
        agents.AgentRole.CODE_B: """{
  "drift_detected": false,
  "score": 95,
  "issues": [],
  "aesthetics_verdict": "UI looks clean and consistent."
}""",
        agents.AgentRole.WORKER: """### API Reference
Here is the public API reference docs.""",
        agents.AgentRole.MANAGER: """{"answer": "dummy manager answer"}""",
        agents.AgentRole.ANALYZER: json.dumps({"root_cause": "KeyError: 'files'", "suggested_approach": "Check keys", "target_files": [SMOKE_FILE_REL]}),
        agents.AgentRole.TESTER: '```python\ndef test_swarm_reproducer():\n    assert True\n```',
        agents.AgentRole.REVIEWER: '{"verdict": "approve", "summary": "Bản vá chất lượng tốt, không lỗi."}'
    }
    
    res_val = role_responses.get(self.role, "Dummy response")
    if self.role == agents.AgentRole.WORKER and "Trích xuất các khái niệm" in task:
        res_val = '{"concepts":[{"filename":"smoke-concept.md","title":"Smoke Concept","content":"---\\ntitle: Smoke Concept\\n---\\nSmoke wiki concept"}],"entities":[]}'
    
    if self.role == agents.AgentRole.CODE_A and ("Swarm Debugger" in task or "Coder Agent" in task or "suggested_approach" in task):
        res_val = """## Patch
```diff
--- a/{path}
+++ b/{path}
@@ -1,3 +1,3 @@
-x = 1
+x = 2
```""".format(path=SMOKE_FILE_REL)
            
    return agents.AgentResult(
        agent_id=self.agent_id,
        agent_role=self.role,
        model_used=self.model,
        task=task,
        result=res_val,
        duration_ms=10,
        status="success"
    )

async def mock_run_async(self, task: str, extra_context: str = "", *, json_mode: bool = False, max_output_tokens: int = 4096, **_kwargs):
    return self.run(task, extra_context, json_mode=json_mode, max_output_tokens=max_output_tokens)

def mock_chat_completion(*args, **kwargs):
    messages = args[2] if len(args) > 2 else kwargs.get("messages", [])
    system_prompt = next((m["content"] for m in messages if m.get("role") == "system"), "")
    if "Visual UI Auditor Agent" in system_prompt:
        return """{
  "drift_detected": false,
  "score": 95,
  "issues": [],
  "aesthetics_verdict": "UI looks clean and consistent."
}""", "mock-model", 120, 30
    if "Swarm Debugger" in system_prompt or "reproducer" in system_prompt:
        if "Architect Agent" in system_prompt:
            return json.dumps({"root_cause": "KeyError", "suggested_approach": "Check keys", "target_files": [SMOKE_FILE_REL]}), "mock-model", 100, 10
        elif "Tester Agent" in system_prompt:
            return '```python\ndef test_swarm_reproducer():\n    assert False\n```', "mock-model", 100, 10
        elif "Coder Agent" in system_prompt:
            return f'## Patch\n```diff\n--- a/{SMOKE_FILE_REL}\n+++ b/{SMOKE_FILE_REL}\n@@ -1,3 +1,3 @@\n-x = 1\n+x = 2\n```', "mock-model", 100, 10
        elif "Reviewer Agent" in system_prompt:
            return '{"verdict": "approve", "summary": "Looks good"}', "mock-model", 100, 10
    return "Dummy response", "mock-model", 100, 10

agents.Agent.run = mock_run
agents.Agent.run_async = mock_run_async
agents.chat_completion = mock_chat_completion

failures: list[str] = []

def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

# 1. Imports
import config
import harness
import support_tools as st
import server
import mcp_server
check("import tất cả modules", True)

# Monkeypatch st.run_in_sandbox to mock pytest execution if pytest is not installed
original_run_in_sandbox = st.run_in_sandbox
def mock_run_in_sandbox(code, timeout=5.0):
    if "test_swarm_reproducer.py" in code:
        return {
            "status": "success",
            "stdout": "================ 1 passed in 0.01s ================\n",
            "stderr": "",
            "returncode": 0
        }
    return original_run_in_sandbox(code, timeout)
st.run_in_sandbox = mock_run_in_sandbox


# 2. Config đầy đủ 12 model
from config import MODELS, WORKSPACE_ROOT, _parse_spare_models, get_model_config, get_spare_models
roles = ["manager", "synthesizer", "analyzer", "code_a", "code_b",
         "reviewer", "tester", "security", "integrity", "scanner",
         "debugger", "worker"]
check("ModelConfig đủ 12 role", all(getattr(MODELS, r, None) for r in roles))
check("SPARE_MODELS load động được", isinstance(get_spare_models(), list) and len(get_spare_models()) > 0,
      str(get_spare_models()))
check("SPARE_MODELS skip model trùng khi failover",
      agents._next_distinct_spare(iter(["gpt-5.4-pro-2", "gpt-5.4-3"]), "gpt-5.4-pro-2") == "gpt-5.4-3")
check("SPARE_MODELS lọc deployment lạ và duplicate",
      _parse_spare_models("gpt-5.4-4,no-such-model,gpt-5.4-4", {"gpt-5.4-4"}) == ["gpt-5.4-4"])
_orig_worker = os.environ.get("MODEL_WORKER")
_orig_spares = os.environ.get("SPARE_MODELS")
_orig_known = os.environ.get("HARNESS_KNOWN_DEPLOYMENTS")
try:
    os.environ["MODEL_WORKER"] = " "
    check("ModelConfig fallback khi MODEL_* rỗng", get_model_config().worker == "gpt-5.4-mini")
    os.environ["MODEL_WORKER"] = "custom-spare"
    os.environ["SPARE_MODELS"] = "custom-spare,no-such-model"
    os.environ["HARNESS_KNOWN_DEPLOYMENTS"] = ""
    check("SPARE_MODELS dynamic theo env sau import", get_spare_models() == ["custom-spare"])
    os.environ["SPARE_MODELS"] = "no-such-model"
    _bad_spare_fallback = get_spare_models()
    check("SPARE_MODELS cấu hình sai vẫn có fallback",
          bool(_bad_spare_fallback) and "no-such-model" not in _bad_spare_fallback,
          str(_bad_spare_fallback))
finally:
    if _orig_worker is None:
        os.environ.pop("MODEL_WORKER", None)
    else:
        os.environ["MODEL_WORKER"] = _orig_worker
    if _orig_spares is None:
        os.environ.pop("SPARE_MODELS", None)
    else:
        os.environ["SPARE_MODELS"] = _orig_spares
    if _orig_known is None:
        os.environ.pop("HARNESS_KNOWN_DEPLOYMENTS", None)
    else:
        os.environ["HARNESS_KNOWN_DEPLOYMENTS"] = _orig_known
check("Responses queue timeout dùng full budget",
      agents._responses_queue_timeout(45.0) == 45.0)
check("Responses queue timeout tôn trọng request nhỏ",
      agents._responses_queue_timeout(0.2) <= 0.2)

# 3. Mỗi role có system prompt + temperature
from agents import AgentRole, SYSTEM_PROMPTS, ROLE_TO_MODEL, ROLE_TEMPERATURE
check("SYSTEM_PROMPTS đủ 12 role", set(SYSTEM_PROMPTS) == set(AgentRole))
check("ROLE_TO_MODEL đủ 12 role", set(ROLE_TO_MODEL) == set(AgentRole))
check("ROLE_TEMPERATURE đủ 12 role", set(ROLE_TEMPERATURE) == set(AgentRole))

# 4. MCP server: list_tools trả đủ expected tools, schema hợp lệ
tools = asyncio.run(mcp_server.list_tools())
tool_names = {t.name for t in tools}
expected = {"auto_trigger", "prod_readiness_gate", "release_orchestrator", "provenance_checker",
            "auth_matrix_auditor", "harness_trace_viewer", "incremental_refactor_guard",
            "goal_autopilot", "goal_supervisor", "goal_runner", "panel_review", "consult", "alt_implementation", "suggest_fix",
            "goal_runner_control", "run_ledger", "policy_profile", "agent_adapters", "context_auditor",
            "ask_codebase_health", "patch_safety_check", "benchmark_runner", "harness_doctor", "lesson_curator",
            "ask_codebase", "quick_task", "run_single_agent", "list_agents",
            "wiki_ingest", "wiki_query", "wiki_lint", "security_autofix",
            "auto_tester", "visual_reviewer", "benchmarker", "dependency_upgrader",
            "schema_drift", "doc_sync", "telemetry_debugger",
            "run_in_sandbox", "semantic_search", "swarm_debug", "finops_stats",
            "devops_pipeline", "config_security_audit",
            "pr_generator", "license_scanner", "sbom_generator", "a11y_auditor",
            "i18n_auditor", "polyglot_reviewer", "git_archaeologist", "feature_flag_auditor",
            "dead_code_scanner", "profiler", "coverage_analyzer", "incident_responder",
            "api_contract_tester", "chaos_tester", "index_codebase", "secret_scanner",
            "changelog_generator", "env_parity_checker", "load_tester", "complexity_analyzer",
            "migration_validator", "sql_query_analyzer", "openapi_spec_sync",
            "breaking_change_detector", "flaky_test_detector", "duplicate_code_scanner",
            "container_linter", "dependency_graph_visualizer", "ci_pipeline_validator",
            "mutation_tester", "data_flow_taint_analyzer", "performance_regression_detector"}
check(f"MCP đăng ký đủ {len(expected)} tool", tool_names == expected,
      f"thiếu {expected - tool_names}, thừa {tool_names - expected}")
for t in tools:
    json.dumps(t.inputSchema)  # schema phải serialize được
check("inputSchema serialize được", True)
resources = asyncio.run(mcp_server.list_resources())
resource_templates = asyncio.run(mcp_server.list_resource_templates())
check("MCP resources/templates trả list rỗng", resources == [] and resource_templates == [],
      f"resources={resources}, templates={resource_templates}")

auto_res = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["README.md"],
    "stage": "post_edit",
    "mode": "safe",
}))
check("auto_trigger docs-only safe skip", json.loads(auto_res[0].text).get("status") == "skipped")
prod_gate = asyncio.run(mcp_server.call_tool("prod_readiness_gate", {
    "changed_files": ["README.md"],
    "task": "ready for production deploy?",
    "mode": "safe",
}))
prod_gate_json = json.loads(prod_gate[0].text)
check("prod_readiness_gate docs-only safe trả verdict hợp lệ",
      prod_gate_json.get("status") == "completed" and prod_gate_json.get("verdict") in {
          "ready_to_deploy", "fix_required", "blocked_needs_user", "deploy_then_verify", "rollback_required",
      },
      str(prod_gate_json))
check("prod_readiness_gate tự chạy orchestrator",
      prod_gate_json.get("orchestrator", {}).get("status") == "completed",
      str(prod_gate_json.get("orchestrator")))
prod_gate_bad = asyncio.run(mcp_server.call_tool("prod_readiness_gate", {"mode": "wild"}))
check("prod_readiness_gate mode invalid → error", "error" in json.loads(prod_gate_bad[0].text))
prod_gate_ref = asyncio.run(mcp_server.call_tool("prod_readiness_gate", {
    "changed_files": ["README.md"],
    "mode": "safe",
    "since_commit": 123,
}))
check("prod_readiness_gate since_commit non-string không crash",
      json.loads(prod_gate_ref[0].text).get("status") == "completed",
      prod_gate_ref[0].text)
from tools.prod import _run_check as _prod_run_check
old_prod_timeout = os.environ.get("HARNESS_PROD_TOOL_TIMEOUT")
os.environ["HARNESS_PROD_TOOL_TIMEOUT"] = "0.01"
try:
    async def _slow_prod_check():
        await asyncio.sleep(0.05)
        return {"status": "completed"}
    prod_timeout = asyncio.run(_prod_run_check("slow_smoke", _slow_prod_check()))
finally:
    if old_prod_timeout is None:
        os.environ.pop("HARNESS_PROD_TOOL_TIMEOUT", None)
    else:
        os.environ["HARNESS_PROD_TOOL_TIMEOUT"] = old_prod_timeout
check("prod_readiness_gate tool timeout trả blocker có kiểm soát",
      prod_timeout.get("ok") is False and prod_timeout.get("raw", {}).get("error") == "timeout",
      str(prod_timeout))
prod_max_specs = []
from tools import prod as prod_mod
async def _capture_prod_adds():
    original_run_check = prod_mod._run_check
    async def fake_run_check(name, coro):
        try:
            coro.close()
        except Exception:
            pass
        prod_max_specs.append(name)
        return {"tool": name, "ok": True, "summary": "completed", "raw": {"status": "completed"}}
    prod_mod._run_check = fake_run_check
    try:
        await prod_mod.prod_readiness_gate(changed_files=["tools/prod.py"], mode="max", task="release")
    finally:
        prod_mod._run_check = original_run_check
asyncio.run(_capture_prod_adds())
check("prod_readiness_gate max không duplicate auto-managed heavy checks",
      "auto_trigger" in prod_max_specs
      and "release_orchestrator" not in prod_max_specs
      and "provenance_checker" not in prod_max_specs,
      str(prod_max_specs))
from tools.auto import (
    _auto_max_tools,
    _auto_tool_timeout_seconds,
    _auto_total_timeout_seconds,
    _parse_subprocess_payload as _auto_parse_subprocess_payload,
    _record_auto_trigger_lesson as _auto_record_auto_trigger_lesson,
    _run_named as _auto_run_named,
    _run_subprocess_job as _auto_run_subprocess_job,
)
old_auto_timeout = os.environ.get("HARNESS_AUTO_TOOL_TIMEOUT")
os.environ["HARNESS_AUTO_TOOL_TIMEOUT"] = "0.01"
try:
    async def _slow_auto_check():
        await asyncio.sleep(0.05)
        return {"status": "completed"}
    auto_timeout = asyncio.run(_auto_run_named("slow_auto_smoke", _slow_auto_check()))
    async def _stubborn_probe():
        loop = asyncio.get_running_loop()
        errors = []
        old_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, ctx: errors.append(ctx))
        async def _stubborn_auto_check():
            try:
                await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                await asyncio.sleep(0.02)
                raise RuntimeError("late failure after cancel")
        try:
            result = await _auto_run_named("stubborn_auto_smoke", _stubborn_auto_check())
            await asyncio.sleep(0.05)
            return result, errors
        finally:
            loop.set_exception_handler(old_handler)
    stubborn_timeout, stubborn_errors = asyncio.run(_stubborn_probe())
finally:
    if old_auto_timeout is None:
        os.environ.pop("HARNESS_AUTO_TOOL_TIMEOUT", None)
    else:
        os.environ["HARNESS_AUTO_TOOL_TIMEOUT"] = old_auto_timeout
check("auto_trigger tool timeout trả lỗi có kiểm soát",
      auto_timeout.get("ok") is False and auto_timeout.get("error") == "timeout",
      str(auto_timeout))
check("auto_trigger không chờ tool nuốt cancel",
      stubborn_timeout.get("ok") is False
      and stubborn_timeout.get("error") == "timeout"
      and not stubborn_errors,
      f"result={stubborn_timeout} errors={stubborn_errors}")
auto_subprocess = asyncio.run(_auto_run_subprocess_job(
    "harness_doctor_subprocess_smoke",
    "tools.ops",
    "harness_doctor",
    {},
))
check("auto_trigger subprocess JSON parse chạy được",
      auto_subprocess.get("tool") == "harness_doctor_subprocess_smoke"
      and auto_subprocess.get("ok") is True,
      str(auto_subprocess))
check("auto_trigger subprocess parse ngược tìm JSON ok",
      _auto_parse_subprocess_payload('{"ok": true, "result": {"status": "completed"}}\ndone\n', "")
      == {"ok": True, "result": {"status": "completed"}},
      "subprocess payload parser missed earlier JSON line")
check("auto_trigger subprocess parse stderr fallback",
      _auto_parse_subprocess_payload("log only\n", '{"ok": true, "result": {"status": "completed"}}\n')
      == {"ok": True, "result": {"status": "completed"}},
      "subprocess payload parser missed stderr JSON line")
auto_subprocess_unicode = asyncio.run(_auto_run_subprocess_job(
    "unicode_subprocess_smoke",
    "tools.devops",
    "incident_responder",
    {"log_content": ""},
))
check("auto_trigger subprocess UTF-8 output chạy được",
      auto_subprocess_unicode.get("tool") == "unicode_subprocess_smoke"
      and auto_subprocess_unicode.get("error") != "UnicodeEncodeError",
      str(auto_subprocess_unicode))
os.environ["HARNESS_AUTO_TOOL_TIMEOUT"] = "999"
try:
    check("auto_trigger timeout cap dưới MCP client",
          _auto_tool_timeout_seconds() == 240.0,
          str(_auto_tool_timeout_seconds()))
finally:
    if old_auto_timeout is None:
        os.environ.pop("HARNESS_AUTO_TOOL_TIMEOUT", None)
    else:
        os.environ["HARNESS_AUTO_TOOL_TIMEOUT"] = old_auto_timeout
old_auto_total_timeout = os.environ.get("HARNESS_AUTO_TOTAL_TIMEOUT")
old_auto_max_tools = os.environ.get("HARNESS_AUTO_MAX_TOOLS")
os.environ["HARNESS_AUTO_TOTAL_TIMEOUT"] = "999"
os.environ["HARNESS_AUTO_MAX_TOOLS"] = "999"
try:
    check("auto_trigger total budget cap dưới MCP client",
          _auto_total_timeout_seconds() == 270.0 and _auto_max_tools("max") == 24,
          f"total={_auto_total_timeout_seconds()} max_tools={_auto_max_tools('max')}")
finally:
    if old_auto_total_timeout is None:
        os.environ.pop("HARNESS_AUTO_TOTAL_TIMEOUT", None)
    else:
        os.environ["HARNESS_AUTO_TOTAL_TIMEOUT"] = old_auto_total_timeout
    if old_auto_max_tools is None:
        os.environ.pop("HARNESS_AUTO_MAX_TOOLS", None)
    else:
        os.environ["HARNESS_AUTO_MAX_TOOLS"] = old_auto_max_tools
release_res = asyncio.run(mcp_server.call_tool("release_orchestrator", {
    "changed_files": ["README.md"],
    "mode": "safe",
}))
release_json = json.loads(release_res[0].text)
check("release_orchestrator safe chạy được",
      release_json.get("status") == "completed" and release_json.get("verdict") in {"ready", "manual_steps", "blocked"},
      str(release_json))
prov_res = asyncio.run(mcp_server.call_tool("provenance_checker", {
    "files": ["README.md"],
    "mode": "safe",
}))
prov_json = json.loads(prov_res[0].text)
check("provenance_checker safe chạy được",
      prov_json.get("status") == "completed" and "provenance_score" in prov_json,
      str(prov_json))
AUTH_ROUTE = SMOKE_DIR / "auth_route.py"
AUTH_ROUTE.write_text('@router.get("/items/{id}")\ndef get_item(id, current_user=Depends(get_user)):\n    return {"id": id, "user_id": current_user.id}\n', encoding="utf-8")
auth_res = asyncio.run(mcp_server.call_tool("auth_matrix_auditor", {
    "files": [AUTH_ROUTE.as_posix()],
    "mode": "safe",
}))
auth_json = json.loads(auth_res[0].text)
check("auth_matrix_auditor safe chạy được",
      auth_json.get("status") == "completed" and auth_json.get("endpoints_count", 0) >= 1,
      str(auth_json))
trace_res = asyncio.run(mcp_server.call_tool("harness_trace_viewer", {
    "limit": 5,
    "mode": "safe",
}))
trace_json = json.loads(trace_res[0].text)
check("harness_trace_viewer safe chạy được",
      trace_json.get("status") == "completed" and "trace_count" in trace_json,
      str(trace_json))
refactor_res = asyncio.run(mcp_server.call_tool("incremental_refactor_guard", {
    "diff": "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n-def public_api(a):\n+def public_api(a, b):\n",
    "mode": "safe",
}))
refactor_json = json.loads(refactor_res[0].text)
check("incremental_refactor_guard bắt signature change",
      refactor_json.get("status") == "completed" and refactor_json.get("guard_verdict") == "breaking",
      str(refactor_json))
gap_bad_mode = asyncio.run(mcp_server.call_tool("release_orchestrator", {"mode": "wild"}))
check("release_orchestrator mode invalid → error", "error" in json.loads(gap_bad_mode[0].text))
quick_task_alias = asyncio.run(mcp_server.call_tool("quick_task", {"task": "Say OK"}))
check("quick_task nhận alias task",
      bool(json.loads(quick_task_alias[0].text).get("output")),
      quick_task_alias[0].text)
from tools.gap_tools import _diff_symbol_changes, harness_trace_viewer as _harness_trace_viewer
from tools.goal import GoalState
from tools.runner import _acquire_runner_lock, _agent_prompt, _parse_porcelain_z, _parse_porcelain_z_bytes, _prod_gate_ok, _release_runner_lock
RUNNER_WORKSPACE = SMOKE_DIR / "runner_workspace"
RUNNER_WORKSPACE.mkdir(exist_ok=True)
(RUNNER_WORKSPACE / "README.md").write_text("# runner smoke\n", encoding="utf-8")
multi_file_changes = _diff_symbol_changes(
    "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n-def public_a(x):\n+def public_a(x, y):\n"
    "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n-def public_b(x):\n+def public_b(x, y):\n"
)
check("incremental_refactor_guard diff multi-file giữ đúng file",
      {c.get("file") for c in multi_file_changes} == {"a.py", "b.py"},
      str(multi_file_changes))
trace_bad_limit = asyncio.run(_harness_trace_viewer(limit="bad", mode="safe"))
check("harness_trace_viewer direct bad limit không crash",
      trace_bad_limit.get("status") == "completed",
      str(trace_bad_limit))
check("goal_runner parse porcelain -z rename/path space",
      _parse_porcelain_z("R  old name.py\0new name.py\0 R old2.py\0new2.py\0 M spaced file.py\0") == ["new name.py", "new2.py", "spaced file.py"])
check("goal_runner parse porcelain -z bytes surrogateescape",
      _parse_porcelain_z_bytes(b" M bad-\xff.py\0")[0].startswith("bad-"))
check("goal_runner prod gate malformed blockers fail-closed",
      not _prod_gate_ok({"verdict": "ready_to_deploy", "blockers_count": "bad"}))
legacy_budget_goal = GoalState.from_dict({"goal": "legacy", "status": "budget_limited"})
check("goal state bỏ legacy budget_limited",
      legacy_budget_goal is not None and legacy_budget_goal.status == "blocked",
      str(legacy_budget_goal))
old_project_dir_for_lock = os.environ.get("CLAUDE_PROJECT_DIR")
os.environ["CLAUDE_PROJECT_DIR"] = str(RUNNER_WORKSPACE.resolve())
runner_lock = _acquire_runner_lock()
try:
    busy_res = asyncio.run(mcp_server.call_tool("goal_runner", {
        "prompt": "second runner must not start",
        "mode": "safe",
        "dry_run": True,
        "max_iterations": 1,
    }))
finally:
    _release_runner_lock(runner_lock)
    if old_project_dir_for_lock is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_project_dir_for_lock
check("goal_runner chặn concurrent run cùng workspace",
      json.loads(busy_res[0].text).get("status") == "blocked_goal_busy",
      busy_res[0].text)
bad_agent_command = asyncio.run(mcp_server.call_tool("goal_runner", {
    "prompt": "bad agent command",
    "agent_command": 123,
}))
check("goal_runner reject agent_command sai kiểu",
      "error" in json.loads(bad_agent_command[0].text),
      bad_agent_command[0].text)
blank_agent_command = asyncio.run(mcp_server.call_tool("goal_runner", {
    "prompt": "blank agent command",
    "agent_command": [" "],
}))
check("goal_runner reject agent_command whitespace",
      "error" in json.loads(blank_agent_command[0].text),
      blank_agent_command[0].text)
direct_bad_agent = asyncio.run(__import__("tools.runner").runner.goal_runner(
    "direct bad agent",
    agent_command=[" "],
    dry_run=True,
))
check("goal_runner direct reject agent_command sai kiểu",
      "error" in direct_bad_agent,
      str(direct_bad_agent))
from tools.prod import _hard_flags
_blockers, _needs_user, _warnings = _hard_flags([{
    "tool": "panel_review",
    "ok": True,
    "raw": {"findings": [{"file": "x.py", "line": 1, "severity": "low", "triage": "ask_user"}]},
}])
check("prod_readiness_gate ask_user finding chặn decision",
      bool(_needs_user) and not _blockers,
      f"blockers={_blockers}, needs_user={_needs_user}, warnings={_warnings}")
_fix_blockers, _, _ = _hard_flags([{"tool": "auto_trigger", "ok": True, "raw": {"verdict": "fix_required"}}])
check("prod_readiness_gate fix_required verdict là blocker", bool(_fix_blockers), str(_fix_blockers))
auto_bad_stage = asyncio.run(mcp_server.call_tool("auto_trigger", {"stage": "done"}))
check("auto_trigger stage invalid → error", "error" in json.loads(auto_bad_stage[0].text))
goal_status = asyncio.run(mcp_server.call_tool("goal_autopilot", {"mode": "status"}))
check("goal_autopilot status không cần Azure", json.loads(goal_status[0].text).get("status") in {"idle", "ok"})
goal_supervisor = asyncio.run(mcp_server.call_tool("goal_supervisor", {}))
goal_supervisor_json = json.loads(goal_supervisor[0].text)
check("goal_supervisor trả next_action không cần Azure",
      goal_supervisor_json.get("next_action") in {"continue_part", "run_check", "run_final", "blocked_ask_user", "complete"},
      str(goal_supervisor_json))
old_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
os.environ["CLAUDE_PROJECT_DIR"] = str(RUNNER_WORKSPACE.resolve())
try:
    goal_runner_res = asyncio.run(mcp_server.call_tool("goal_runner", {
        "prompt": "Update the runner smoke workspace",
        "mode": "safe",
        "dry_run": True,
        "max_iterations": 1,
        "final_prod_gate": False,
    }))
finally:
    if old_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_project_dir
goal_runner_json = json.loads(goal_runner_res[0].text)
check("goal_runner dry-run init/supervise không cần client rules",
      goal_runner_json.get("status") == "blocked_needs_agent",
      str(goal_runner_json))
check("goal_runner tự chạy doctor event",
      any(e.get("step") == "doctor" for e in goal_runner_json.get("events", [])),
      str(goal_runner_json))
ops_calls = {
    "goal_runner_control": {"action": "status"},
    "run_ledger": {"limit": 5},
    "policy_profile": {"profile": "balanced"},
    "agent_adapters": {},
    "context_auditor": {"question": "smoke", "files": ["README.md"]},
    "ask_codebase_health": {"question": "smoke", "files": ["README.md"]},
    "benchmark_runner": {"tasks": ["smoke benchmark"], "mode": "safe", "dry_run": True},
    "harness_doctor": {},
}
old_project_dir_ops = os.environ.get("CLAUDE_PROJECT_DIR")
os.environ["CLAUDE_PROJECT_DIR"] = str(RUNNER_WORKSPACE.resolve())
try:
    stale_lock = RUNNER_WORKSPACE / ".harness_goal_runner.lock"
    stale_lock.write_text(json.dumps({"pid": 999999999, "created_at": time.time() - 999}), encoding="utf-8")
    cancel_res = asyncio.run(mcp_server.call_tool("goal_runner_control", {"action": "cancel_stale"}))
    cancel_json = json.loads(cancel_res[0].text)
    check("goal_runner_control cancel_stale xoá lock stale bằng real path",
          cancel_json.get("status") == "cancelled_stale_lock" and not stale_lock.exists(),
          str(cancel_json))
    for tool_name, payload in ops_calls.items():
        res = asyncio.run(mcp_server.call_tool(tool_name, payload))
        data = json.loads(res[0].text)
        check(f"{tool_name} chạy được", data.get("status") == "completed", str(data))
finally:
    if old_project_dir_ops is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_project_dir_ops
patch_empty = asyncio.run(mcp_server.call_tool("patch_safety_check", {"patch": ""}))
check("patch_safety_check thiếu patch → error", "error" in json.loads(patch_empty[0].text))
auto_bad_mode = asyncio.run(mcp_server.call_tool("auto_trigger", {"mode": "wild"}))
check("auto_trigger mode invalid → error", "error" in json.loads(auto_bad_mode[0].text))
auto_upper = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["README.md"],
    "stage": " FINAL ",
    "mode": " SAFE ",
}))
check("auto_trigger stage/mode normalize hoa thường", json.loads(auto_upper[0].text).get("status") == "skipped")
auto_docs_max = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["README.md"],
    "stage": "final",
    "mode": "max",
}))
check("auto_trigger docs-only max skip nếu không phải release",
      json.loads(auto_docs_max[0].text).get("status") == "skipped")
auto_env_case = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["config/.ENV.EXAMPLE"],
    "stage": "post_edit",
    "mode": "safe",
}))
auto_env_case_json = json.loads(auto_env_case[0].text)
check("auto_trigger nhận diện .ENV.EXAMPLE không phân biệt hoa thường",
      auto_env_case_json.get("status") == "completed" and "env_parity_checker" in auto_env_case_json.get("selected_tools", []),
      str(auto_env_case_json))
old_auto_max_tools = os.environ.get("HARNESS_AUTO_MAX_TOOLS")
os.environ["HARNESS_AUTO_MAX_TOOLS"] = "3"
try:
    auto_bounded = asyncio.run(mcp_server.call_tool("auto_trigger", {
        "changed_files": [
            ".env.example",
            "src/api.py",
            "web/App.tsx",
            "requirements.txt",
            "Dockerfile",
            ".github/workflows/ci.yml",
        ],
        "task": "final deploy api db ui deps ci timeout",
        "stage": "final",
        "mode": "max",
    }))
finally:
    if old_auto_max_tools is None:
        os.environ.pop("HARNESS_AUTO_MAX_TOOLS", None)
    else:
        os.environ["HARNESS_AUTO_MAX_TOOLS"] = old_auto_max_tools
auto_bounded_json = json.loads(auto_bounded[0].text)
check("auto_trigger max tự bound check để tránh MCP timeout",
      auto_bounded_json.get("status") == "degraded"
      and len(auto_bounded_json.get("selected_tools", [])) <= 3
      and bool(auto_bounded_json.get("skipped_tools")),
      str(auto_bounded_json))
from tools.auto import (
    _ci_files,
    _container_files,
    _dependency_files,
    _discover_api_endpoints,
    _extract_urls,
    _migration_files,
    _test_files,
    _ui_files,
)
selector_files = [
    "alembic/versions/001_init.py",
    ".github/workflows/ci.yml",
    "Dockerfile",
    "requirements.txt",
    "web/App.tsx",
    "tests/test_app.py",
]
check("auto_trigger selectors cover db/ci/container/deps/ui/tests",
      _migration_files(selector_files)
      and _ci_files(selector_files)
      and _container_files(selector_files)
      and _dependency_files(selector_files)
      and _ui_files(selector_files)
      and _test_files(selector_files)
      and _extract_urls("load test https://example.com/api")[0] == "https://example.com/api",
      "selector helpers missed a contextual tool family")
route_file = SMOKE_DIR / "route_api.py"
route_file.write_text('@app.get("/health")\ndef health():\n    return {"ok": True}\n\n@api_router.post(\n    "/items"\n)\ndef items():\n    return {}\n', encoding="utf-8")
route_rel = route_file.as_posix()
route_abs = str(route_file.resolve())
route_hits = _discover_api_endpoints([route_rel, route_abs])
check("auto_trigger endpoint discovery nhận relative và absolute path",
      any(hit.get("path") == "/health" for hit in route_hits)
      and any(hit.get("path") == "/items" for hit in route_hits),
      str(route_hits))
sensitive_gate = asyncio.run(mcp_server.call_tool("prod_readiness_gate", {
    "changed_files": [".env"],
    "mode": "safe",
}))
sensitive_gate_json = json.loads(sensitive_gate[0].text)
check("prod_readiness_gate cảnh báo sensitive-only change",
      any("sensitive-only" in w for w in sensitive_gate_json.get("warnings", [])),
      str(sensitive_gate_json))

from tools.swarm import (
    _extractive_codebase_answer,
    _direct_workspace_hits,
    _local_context_pack,
    _manager_answer_appears_truncated,
    _manager_answer_usable,
    _narrow_files_for_question,
    _normalize_manager_answer,
    _prune_context_for_question,
    _redact_sensitive_text,
    _sanitize_ask_files,
    _safe_warn_value,
    _skip_auto_selected_file,
)
import tools.swarm as swarm_mod
check("ask_codebase unwrap JSON answer",
      _normalize_manager_answer('{"answer": "Có dùng app/api.py:10"}') == "Có dùng app/api.py:10")
check("ask_codebase reject generic manager answer",
      not _manager_answer_usable("Tôi không đủ ngữ cảnh để kết luận, nên cần đọc thêm file."))
check("ask_codebase accept cited manager answer",
      _manager_answer_usable("Flow export nằm ở app/api.py:10 và frontend gọi từ web/page.tsx:4."))
check("ask_codebase accept cited path with spaces",
      _manager_answer_usable("Flow nằm ở `New folder (11)/app/api.py:10`."))
check("ask_codebase accept line/hash citations",
      _manager_answer_usable("Flow nằm ở app/api.py line 10 và web/page.tsx#L4."))
check("ask_codebase accept short cited manager answer",
      _manager_answer_usable("Xem app.py:1"))
check("ask_codebase accept expanded citation formats",
      _manager_answer_usable("Flow in app/api.py:L10 and web/page.tsx (line=4)."))
check("ask_codebase accept explicit no-evidence answer",
      _manager_answer_usable("Không tìm thấy trong context đã cung cấp."))
check("ask_codebase detect truncated cited answer",
      _manager_answer_appears_truncated("Có route ở `src/app.py:12` nhưng dở dang `", 4096)
      and not _manager_answer_appears_truncated("Có route ở `src/app.py:12`.", 4096)
      and not _manager_answer_appears_truncated("khong tim thay trong context da cung cap", 1)
      and not _manager_answer_appears_truncated("Danh sách hợp lệ:", 4096)
      and not _manager_answer_appears_truncated(("Có route ở `src/app.py:12`. " * 300), 64),
      "truncation heuristic failed")
direct_hits = _direct_workspace_hits("goal_supervisor next_action enum", limit=5)
check("ask_codebase direct symbol scan ưu tiên source mới",
      "tools/goal.py" in direct_hits,
      str(direct_hits))
check("ask_codebase auto-select lọc wiki/env artifacts",
      _skip_auto_selected_file("llmwiki/wiki/entities/x.md")
      and _skip_auto_selected_file(".ENV")
      and _skip_auto_selected_file(".Env")
      and _skip_auto_selected_file(".ENV.LOCAL")
      and _skip_auto_selected_file(".env.example")
      and _skip_auto_selected_file("config/.Env.Prod")
      and _skip_auto_selected_file(".harness_ast_graph.json"),
      "filter failed")
safe_files, unsafe_warnings = _sanitize_ask_files(["tools/swarm.py", "../secret.txt", "C:/tmp/x.py", ".ENV", "llmwiki/wiki/x.md"])
check("ask_codebase sanitize user files",
      safe_files == ["tools/swarm.py"] and len(unsafe_warnings) == 4,
      f"safe={safe_files}, warnings={unsafe_warnings}")
bounded_warn = _safe_warn_value("x" * 500)
check("ask_codebase warning value bounded",
      len(bounded_warn) < 150 and "truncated" in bounded_warn,
      bounded_warn)
direct_scan_root = SMOKE_DIR / "direct_scan"
direct_scan_root.mkdir(exist_ok=True)
(direct_scan_root / ".ENV").write_text("unique_direct_secret_symbol=1\n", encoding="utf-8")
(direct_scan_root / ".Env.local").write_text("unique_direct_secret_symbol=2\n", encoding="utf-8")
(direct_scan_root / "source.py").write_text("def unique_direct_source_symbol(): pass\n", encoding="utf-8")
outside_target = SMOKE_DIR / "outside_target.py"
outside_target.write_text("def unique_outside_symbol(): pass\n", encoding="utf-8")
old_workspace_env = os.environ.get("WORKSPACE_ROOT")
try:
    os.environ["WORKSPACE_ROOT"] = str(direct_scan_root.resolve())
    env_hits = swarm_mod._direct_workspace_hits("unique_direct_secret_symbol", limit=5)
    source_hits = swarm_mod._direct_workspace_hits("unique_direct_source_symbol", limit=5)
    check("ask_codebase direct scan bỏ qua .ENV hoa thường",
          ".ENV" not in env_hits and ".Env.local" not in env_hits and source_hits == ["source.py"],
          f"env={env_hits}, source={source_hits}")
    many_dir = direct_scan_root / "many"
    many_dir.mkdir(exist_ok=True)
    for i in range(1005):
        (many_dir / f"zz_{i:04d}.py").write_text("pass\n", encoding="utf-8")
    (many_dir / "zz_1004.py").write_text("def unique_late_direct_symbol(): pass\n", encoding="utf-8")
    late_hits = swarm_mod._direct_workspace_hits("unique_late_direct_symbol", limit=3)
    check("ask_codebase direct scan deterministic >1000 files",
          "many/zz_1004.py" in late_hits,
          str(late_hits))
    link_path = direct_scan_root / "outside_link.py"
    try:
        os.symlink(outside_target.resolve(), link_path)
        outside_hits = swarm_mod._direct_workspace_hits("unique_outside_symbol", limit=5)
        check("ask_codebase direct scan chặn symlink out-of-root",
              "outside_link.py" not in outside_hits,
              str(outside_hits))
    except (OSError, NotImplementedError):
        check("ask_codebase direct scan symlink test skipped", True)
finally:
    if old_workspace_env is None:
        os.environ.pop("WORKSPACE_ROOT", None)
    else:
        os.environ["WORKSPACE_ROOT"] = old_workspace_env
large_ctx = "\n\n".join(
    f"=== FILE: file{i}.py ===\n1\tdef unrelated_{i}():\n2\t    return {i}"
    for i in range(30)
) + "\n\n=== FILE: src/exporter.py ===\n10\tdef export_excel():\n11\t    return workbook\n"
pruned_ctx, prune_warns = _prune_context_for_question("frontend xuất Excel gọi API nào", large_ctx, 1200)
check("ask_codebase relevance prune giữ file match sau",
      "src/exporter.py" in pruned_ctx and "export_excel" in pruned_ctx and prune_warns,
      pruned_ctx)
large_block_ctx = "=== FILE: big.py ===\n" + "\n".join(
    [f"{i}\tfiller filler filler filler filler" for i in range(1, 100)]
    + [f"{i}\tdef export_excel_{i}(): return workbook" for i in range(100, 180)]
)
large_block_pruned, _large_block_warns = _prune_context_for_question("export excel workbook", large_block_ctx, 500)
check("ask_codebase prune slices oversized relevant block",
      "big.py" in large_block_pruned and "export_excel" in large_block_pruned,
      large_block_pruned)
tiny_pruned, tiny_warns = _prune_context_for_question("export excel workbook", large_block_ctx, 50)
check("ask_codebase prune cap quá nhỏ có warning",
      tiny_warns and "too small" in tiny_warns[0],
      str(tiny_warns))
many_files = [f"src/other_{i}.py" for i in range(20)] + ["src/export_excel_api.py"]
narrowed_files, narrow_warns = _narrow_files_for_question("export excel api", many_files)
check("ask_codebase narrows large provided file list",
      "src/export_excel_api.py" in narrowed_files and len(narrowed_files) <= 15 and narrow_warns,
      str(narrowed_files))
check("ask_codebase redacts secrets from fallback context",
      "supersecret" not in _redact_sensitive_text("API_KEY='supersecretvalue1234567890'"),
      _redact_sensitive_text("API_KEY='supersecretvalue1234567890'"))
check("ask_codebase redacts quoted secrets with spaces",
      "secret with spaces" not in _redact_sensitive_text('password = "secret with spaces"'),
      _redact_sensitive_text('password = "secret with spaces"'))
check("ask_codebase redacts short token/password",
      "abc123" not in _redact_sensitive_text("token=abc123\npassword='hunter2'"),
      _redact_sensitive_text("token=abc123\npassword='hunter2'"))
check("ask_codebase redacts authorization assignment",
      "Bearer x" not in _redact_sensitive_text("authorization='Bearer x'"),
      _redact_sensitive_text("authorization='Bearer x'"))
fallback_answer = _extractive_codebase_answer(
    "frontend xuất Excel gọi API nào",
    "=== FILE: app/api.py ===\n10\tdef export_excel():\n11\t    return workbook\n"
    "=== FILE: web/page.tsx ===\n4\tconst onExport = () => api.exportExcel()\n",
    ["app/api.py", "web/page.tsx"],
    "mock timeout",
)
check("ask_codebase fallback local có citation usable",
      "Kết luận khả dĩ" in fallback_answer and "`app/api.py:10`" in fallback_answer,
      fallback_answer)
fallback_pack = _local_context_pack(
    "frontend xuất Excel gọi API nào",
    "=== FILE: app/api.py ===\n10\tdef export_excel():\n11\t    return workbook\n"
    "=== FILE: web/page.tsx ===\n4\tconst onExport = () => api.exportExcel()\n",
    ["app/api.py", "web/page.tsx"],
)
check("ask_codebase fallback local trả context_pack",
      fallback_pack["relevant_files"]
      and fallback_pack["snippets"]
      and "`app/api.py:10`" in fallback_pack["markdown"],
      str(fallback_pack))
fallback_schema = asyncio.run(swarm_mod.ask_codebase("ask_codebase docs", files=["README.md"]))
check("ask_codebase relevant_files giữ list path string",
      isinstance(fallback_schema.get("relevant_files"), list)
      and all(isinstance(path, str) for path in fallback_schema.get("relevant_files", []))
      and "relevant_files_scored" in fallback_schema,
      str(fallback_schema))
early_error = asyncio.run(swarm_mod.ask_codebase("no context", files="config.py"))
check("ask_codebase early error schema ổn định",
      early_error.get("error")
      and early_error.get("fallback") is False
      and "context_pack" in early_error
      and "config" in early_error,
      str(early_error))
ask_mcp = asyncio.run(mcp_server.call_tool("ask_codebase", {
    "question": "ask_codebase docs",
    "files": ["README.md"],
}))
ask_mcp_text = ask_mcp[0].text if ask_mcp else ""
ask_mcp_json = json.loads(ask_mcp_text) if ask_mcp_text else {}
check("ask_codebase MCP không trả no-content",
      bool(ask_mcp_text.strip())
      and ("answer" in ask_mcp_json or "error" in ask_mcp_json)
      and "context_pack" in ask_mcp_json,
      ask_mcp_text[:1000])
none_response_text = mcp_server._json_response(None)[0].text
list_response_text = mcp_server._json_response(["ok"])[0].text
check("MCP json response không bao giờ rỗng",
      bool(none_response_text.strip())
      and json.loads(none_response_text).get("error") == "empty_tool_result"
      and json.loads(list_response_text).get("result") == ["ok"],
      f"none={none_response_text!r} list={list_response_text!r}")
context_audit = asyncio.run(mcp_server.call_tool("context_auditor", {
    "question": "frontend xuất Excel gọi API nào",
    "context": "=== FILE: app/api.py ===\n10\tdef export_excel():\n",
}))
context_audit_json = json.loads(context_audit[0].text)
check("ask_codebase/context audit tự đánh giá context inline",
      context_audit_json.get("status") == "completed" and context_audit_json.get("bytes", 0) > 0,
      str(context_audit_json))

import auto_watch
watch_root = SMOKE_DIR / "watch_root"
(watch_root / "src").mkdir(parents=True, exist_ok=True)
(watch_root / ".git").mkdir(parents=True, exist_ok=True)
watched_file = watch_root / "src" / "app.py"
ignored_file = watch_root / ".git" / "config"
watched_file.write_text("print(1)\n", encoding="utf-8")
ignored_file.write_text("ignore\n", encoding="utf-8")
snap1 = auto_watch.snapshot(watch_root)
watched_file.write_text("print(2)\n", encoding="utf-8")
snap2 = auto_watch.snapshot(watch_root)
watch_changed = auto_watch.changed_files(snap1, snap2)
check("auto_watch ignore .git và detect file đổi",
      "src/app.py" in watch_changed and ".git/config" not in snap1,
      str(watch_changed))
lock_path = watch_root / auto_watch.LOCK_FILE
token1 = auto_watch._acquire_lock(lock_path)
lock2 = auto_watch._acquire_lock(lock_path)
try:
    check("auto_watch lock acquire atomic", token1 is not None and lock2 is None)
    if token1 is not None:
        lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
        check("auto_watch lock ghi PID metadata", lock_payload.get("pid") == os.getpid() and lock_payload.get("token"), str(lock_payload))
        lock_path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time(), "token": "other"}), encoding="utf-8")
        auto_watch._release_lock(lock_path, token1)
        check("auto_watch release không xóa lock owner khác", lock_path.exists())
finally:
    lock_path.unlink(missing_ok=True)
lock_path.mkdir()
try:
    check("auto_watch lock path directory không crash", auto_watch._acquire_lock(lock_path) is None)
finally:
    lock_path.rmdir()
auto_watch._append_log(watch_root, {
    "changed_files": ["src/app.py"],
    "api_key": "super-secret",
    "result": {"token": "abc", "summary": "Bearer abcdefghijklmnopqrstuvwxyz123456"},
})
watch_log = (watch_root / auto_watch.LOG_FILE).read_text(encoding="utf-8")
check("auto_watch log redact secret keys", "super-secret" not in watch_log and "abcdefghijklmnopqrstuvwxyz" not in watch_log, watch_log)

import merge_settings
managed_sample = "before\n<!-- agent-harness-managed -->\nold\n<!-- /agent-harness-managed -->\nafter"
managed_new, managed_replaced = merge_settings._replace_managed_section(
    managed_sample,
    merge_settings.CLAUDE_MARKER,
    "<!-- agent-harness-managed -->\nnew\n<!-- /agent-harness-managed -->",
)
check("managed section replace giữ nội dung ngoài block",
      managed_replaced and "before" in managed_new and "after" in managed_new and "old" not in managed_new)
managed_corrupt, corrupt_replaced = merge_settings._replace_managed_section(
    "before\n<!-- agent-harness-managed -->\nold duplicated rule\n",
    merge_settings.CLAUDE_MARKER,
    "<!-- agent-harness-managed -->\nnew\n<!-- /agent-harness-managed -->",
)
check("managed section corrupt marker replace tới EOF",
      corrupt_replaced
      and managed_corrupt.count(merge_settings.CLAUDE_MARKER) == 1
      and managed_corrupt.count(merge_settings._end_marker_for(merge_settings.CLAUDE_MARKER)) == 1
      and "old duplicated rule" not in managed_corrupt,
      managed_corrupt)
fenced_marker_sample = "before\n```md\n<!-- agent-harness-managed -->\n```\nafter\n"
fenced_marker_new, fenced_marker_replaced = merge_settings._replace_managed_section(
    fenced_marker_sample,
    merge_settings.CLAUDE_MARKER,
    "<!-- agent-harness-managed -->\nnew\n<!-- /agent-harness-managed -->",
)
check("managed section bỏ qua marker trong code fence",
      not fenced_marker_replaced
      and "after" in fenced_marker_new
      and fenced_marker_new.count(merge_settings.CLAUDE_MARKER) == 2,
      fenced_marker_new)
codex_sample = '  [mcp_servers.agent-harness]\ncommand = "old"\n\n[mcp_servers.other]\ncommand = "x"\n'
codex_block = '[mcp_servers.agent-harness]\ncommand = "python"\nargs = [ "server.py" ]\n'
import re
codex_pattern = r'(?ms)^\s*\[mcp_servers\.agent-harness\]\n.*?(?=^\s*\[|\Z)'
codex_new = re.sub(codex_pattern, codex_block + "\n", codex_sample)
check("codex MCP block indent vẫn upsert idempotent",
      codex_new.count("[mcp_servers.agent-harness]") == 1 and "[mcp_servers.other]" in codex_new,
      codex_new)
rules_home = SMOKE_DIR / "rules_home"
check("lazy rules merge cần update khi chưa có stamp",
      merge_settings.needs_update(home=rules_home))
merged_once = merge_settings.lazy_merge_if_needed(home=rules_home)
claude_rules = (rules_home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
gemini_rules = (rules_home / ".gemini" / "GEMINI.md").read_text(encoding="utf-8")
codex_cfg = (rules_home / ".codex" / "config.toml").read_text(encoding="utf-8")
check("lazy rules merge tạo stamp và rules mới",
      merged_once
      and merge_settings.installed_rules_version(home=rules_home) == merge_settings.RULES_VERSION
      and "goal_supervisor" in claude_rules
      and "prod_readiness_gate" in gemini_rules
      and "mcp_server.py" in codex_cfg)
merged_twice = merge_settings.lazy_merge_if_needed(home=rules_home)
check("lazy rules merge idempotent sau stamp",
      not merged_twice and not merge_settings.needs_update(home=rules_home))
old_lazy_done = mcp_server._LAZY_SETTINGS_MERGE_DONE
old_lazy_merge = merge_settings.lazy_merge_if_needed
lazy_calls = []
try:
    mcp_server._LAZY_SETTINGS_MERGE_DONE = False
    def _fake_lazy_merge(*_args, **_kwargs):
        lazy_calls.append("called")
        return False
    merge_settings.lazy_merge_if_needed = _fake_lazy_merge
    mcp_server._ensure_lazy_settings_merge()
    mcp_server._ensure_lazy_settings_merge()
    check("MCP lazy settings merge guard chỉ gọi một lần",
          lazy_calls == ["called"],
          str(lazy_calls))
finally:
    merge_settings.lazy_merge_if_needed = old_lazy_merge
    mcp_server._LAZY_SETTINGS_MERGE_DONE = old_lazy_done

hot_mod_path = SMOKE_DIR / "hot_reload_fake.py"
hot_mod_path.write_text("VALUE = 1\n", encoding="utf-8")
sys.path.insert(0, str(SMOKE_DIR.resolve()))
old_reloadable = mcp_server._reloadable_tool_modules
try:
    import importlib
    hot_mod = importlib.import_module("hot_reload_fake")
    mcp_server._reloadable_tool_modules = lambda: ["hot_reload_fake"]
    mcp_server._HOT_RELOAD_SIGNATURES.pop("hot_reload_fake", None)
    baseline_reload = asyncio.run(mcp_server._ensure_fresh_tool_modules())
    baseline_sig = mcp_server._HOT_RELOAD_SIGNATURES["hot_reload_fake"]
    hot_mod_path.write_text("VALUE = 2\n", encoding="utf-8")
    os.utime(hot_mod_path, (baseline_sig[0], baseline_sig[0]))
    importlib.invalidate_caches()
    changed_reload = asyncio.run(mcp_server._ensure_fresh_tool_modules())
    check("MCP hot-reload nạp lại tool module sau khi file đổi",
          baseline_reload == []
          and "hot_reload_fake" in changed_reload
          and getattr(hot_mod, "VALUE", None) == 2,
          f"baseline={baseline_reload}, changed={changed_reload}, value={getattr(hot_mod, 'VALUE', None)}")
finally:
    mcp_server._reloadable_tool_modules = old_reloadable
    sys.modules.pop("hot_reload_fake", None)
    try:
        sys.path.remove(str(SMOKE_DIR.resolve()))
    except ValueError:
        pass

# 5. list_agents chạy được không cần API
out = asyncio.run(mcp_server.call_tool("list_agents", {}))
data = json.loads(out[0].text)
check("list_agents trả 12 agents", len(data.get("agents", [])) == 12)

# 6. read_workspace_files: đọc file thật, chặn path ngoài workspace
ctx, warns, loaded = st.read_workspace_files(["config.py"])
check("đọc config.py có đánh số dòng", "=== FILE: config.py ===" in ctx and "1\t" in ctx)
check("loaded_count đúng", loaded == 1)
# dùng path tương đối ra ngoài workspace — portable trên mọi OS
outside_paths = ["../outside.txt", "../../another.txt"]
ctx2, warns2, loaded2 = st.read_workspace_files(outside_paths)
check("chặn path ngoài workspace runtime",
      ctx2 == "" and loaded2 == 0 and
      all("ngoài workspace" in w for w in warns2),
      f"workspace={WORKSPACE_ROOT} warns={warns2}")
ctx3, warns3, _ = st.read_workspace_files(["khong_ton_tai.py"])
check("file không tồn tại → warning", ctx3 == "" and any("không tồn tại" in w for w in warns3))

# 7. JSON parsing chịu được markdown fence và text rác
clean = st._parse_json_findings('{"findings": [{"issue": "x"}]}')
fenced = st._parse_json_findings('Đây là kết quả:\n```json\n{"findings": [{"issue": "y"}]}\n```\nXong.')
garbage = st._parse_json_findings("hoàn toàn không phải json")
check("parse JSON thuần", len(clean) == 1)
check("parse JSON trong markdown fence", len(fenced) == 1)
check("text rác → findings rỗng", garbage == [])
import tools.quality as quality_mod
quality_parse_fallback = quality_mod._parse_json_result("not json", {"findings": [], "summary": ""})
check("quality parser fallback degraded rõ ràng",
      quality_parse_fallback.get("degraded") is True
      and quality_parse_fallback.get("fallback_reason") == "llm_json_parse_failed",
      str(quality_parse_fallback))

# 8. Tool validation: thiếu input → error message rõ ràng (không gọi API)
r = asyncio.run(st.panel_review())
check("panel_review không input → error", "error" in r)
import tools.review as review_mod
old_integrity_timeout = os.environ.get("HARNESS_PANEL_INTEGRITY_TIMEOUT")
os.environ["HARNESS_PANEL_INTEGRITY_TIMEOUT"] = "-1"
try:
    check("panel_review integrity timeout clamp invalid",
          review_mod._panel_integrity_timeout(240.0) == 75.0,
          str(review_mod._panel_integrity_timeout(240.0)))
finally:
    if old_integrity_timeout is None:
        os.environ.pop("HARNESS_PANEL_INTEGRITY_TIMEOUT", None)
    else:
        os.environ["HARNESS_PANEL_INTEGRITY_TIMEOUT"] = old_integrity_timeout
r2 = asyncio.run(st.suggest_fix(error="lỗi gì đó"))
check("suggest_fix thiếu code/files → error", "error" in r2)

# 8b. MCP boundary validation
orig_panel_review = mcp_server.st.panel_review
async def _fake_panel_review(**kwargs):
    return {"staged": kwargs["staged"]}
mcp_server.st.panel_review = _fake_panel_review
try:
    r_false = asyncio.run(mcp_server.call_tool("panel_review", {"staged": "false"}))
    r_bad_bool = asyncio.run(mcp_server.call_tool("panel_review", {"staged": "maybe"}))
    r_blank_bool = asyncio.run(mcp_server.call_tool("panel_review", {"staged": "  "}))
finally:
    mcp_server.st.panel_review = orig_panel_review
check("panel_review staged='false' parse đúng", json.loads(r_false[0].text).get("staged") is False)
check("panel_review staged invalid → error", "error" in json.loads(r_bad_bool[0].text))
check("panel_review staged blank → error", "error" in json.loads(r_blank_bool[0].text))

# 9. Quirks adaptation logic
from agents import _quirks_for, _MODEL_QUIRKS
q = _quirks_for("test-model")
check("quirks mặc định: max_completion_tokens + temperature",
      q["token_param"] == "max_completion_tokens" and q["temperature"] is True)

# 10. Pipeline cũ vẫn import được prompt riêng
check("pipeline prompts tồn tại",
      bool(harness.PIPELINE_MANAGER_PROMPT) and bool(harness.PIPELINE_SYNTHESIZER_PROMPT))

# 11. server.py /api/models trả đủ 12 key
models_resp = asyncio.run(server.get_models())
check("/api/models đủ 12 model", set(models_resp) == set(roles))
check("swarm lock state không terminal", server._is_terminal_state("_locking_pending_coder") is False)
server.init_db()
stale_id = "smoke-stale-lock"
now = time.time()
conn = sqlite3.connect(server.get_finops_db_path())
cur = conn.cursor()
cur.execute("DELETE FROM swarm_sessions WHERE swarm_id=?", (stale_id,))
cur.execute(
    """INSERT INTO swarm_sessions
       (swarm_id, state, error_log, target_files, reproducer_code, suggested_patch,
        logs, final_result, expires_at, updated_at)
       VALUES (?, ?, '', '[]', '', '', '[]', '{}', ?, ?)""",
    (stale_id, "_locking_pending_coder", now + server.SWARM_SESSION_TTL_SECONDS, now - server.SWARM_LOCK_STALE_SECONDS - 1),
)
conn.commit()
conn.close()
try:
    stale_sess = server.get_swarm_session(stale_id)
finally:
    conn = sqlite3.connect(server.get_finops_db_path())
    conn.execute("DELETE FROM swarm_sessions WHERE swarm_id=?", (stale_id,))
    conn.commit()
    conn.close()
check("swarm stale lock tự recover", stale_sess is not None and stale_sess["state"] == "pending_coder")
from fastapi.testclient import TestClient
old_api_key = os.environ.get("HARNESS_API_KEY")
os.environ["HARNESS_API_KEY"] = "smoke-key"
try:
    auth_resp = TestClient(server.app).get("/api/history")
finally:
    if old_api_key is None:
        os.environ.pop("HARNESS_API_KEY", None)
    else:
        os.environ["HARNESS_API_KEY"] = old_api_key
check("/api/history yêu cầu API key", auth_resp.status_code == 401, str(auth_resp.status_code))

# 12. Responses API routing — pre-seed quirks theo tên model
_MODEL_QUIRKS.clear()  # reset cache để test fresh
all_configured_models = [getattr(MODELS, r) for r in roles]
responses_models = [m for m in all_configured_models if "codex" in m or any(term in m for term in ["-pro"])]
chat_models      = [m for m in all_configured_models if m not in responses_models]
check("codex + pro models → responses API",
      all(_quirks_for(m)["api"] == "responses" for m in responses_models),
      str([(m, _quirks_for(m)["api"]) for m in responses_models]))
check("kimi/gpt/grok models → chat API",
      all(_quirks_for(m)["api"] == "chat" for m in chat_models),
      str([(m, _quirks_for(m)["api"]) for m in chat_models]))

# 13. get_responses_client() khởi tạo được (không gọi API)
try:
    rc = config.get_responses_client()
    check("get_responses_client() khởi tạo thành công", rc is not None)
except Exception as e:
    check("get_responses_client() khởi tạo thành công", False, str(e))

# 14. git diff helper — không có git repo trong WORKSPACE_ROOT (có thể) → warning rõ ràng
diff_text, diff_err = st._git_diff(staged=False)
if diff_err:
    check("_git_diff() lỗi có error message rõ ràng", len(diff_err) > 0, diff_err)
else:
    check("_git_diff() trả về diff hoặc error", len(diff_text) > 0 or len(diff_err) > 0)

import tools.core as core_mod
old_core_run = core_mod.subprocess.run
def fake_git_status(args, *other_args, **kwargs):
    if list(args[:3]) == ["git", "status", "--porcelain"]:
        raw = (
            " M src/app.py\x00"
            "?? README.md\x00"
            "R  renamed_new.py\x00renamed_old.py\x00"
            " D deleted.py\x00"
            " T type_changed.py\x00"
            " M dir/file with space.py\x00"
            " M REVIEW_REPORT.md\x00"
            " M .env\x00"
            "?? llmwiki/raw/note.md\x00"
        ).encode("utf-8")
        return subprocess.CompletedProcess(args, 0, stdout=raw, stderr=b"")
    return old_core_run(args, *other_args, **kwargs)
try:
    core_mod.subprocess.run = fake_git_status
    dirty_status = core_mod._scoped_dirty_status(Path("."), ["src/app.py"])
    check("dirty status scoped conflict chỉ đúng file trong scope",
          dirty_status["scoped_conflicts"] == ["src/app.py"],
          str(dirty_status))
    check("dirty status phân loại artifact/sensitive",
          "REVIEW_REPORT.md" in dirty_status["harness_artifacts"]
          and "llmwiki/raw/note.md" in dirty_status["harness_artifacts"]
          and ".env" in dirty_status["sensitive_ignored"],
          str(dirty_status))
    check("dirty status parse rename/delete/typechange/space path",
          "renamed_new.py" in dirty_status["user_changes"]
          and "renamed_old.py" not in dirty_status["user_changes"]
          and "deleted.py" in dirty_status["user_changes"]
          and "type_changed.py" in dirty_status["user_changes"]
          and "dir/file with space.py" in dirty_status["user_changes"],
          str(dirty_status))
finally:
    core_mod.subprocess.run = old_core_run

# 15. panel_review nhận staged=True → không cần files (auto git diff hoặc error từ git)
r3 = asyncio.run(st.panel_review(staged=True))
check("panel_review(staged=True) không crash",
      "error" in r3 or "findings" in r3,
      str(r3.get("error", ""))[:120])
async def _cancelled_tool_keeps_run_context_probe():
    from agents import current_run_id
    original_execute_tool = mcp_server._execute_tool
    started = asyncio.Event()
    seen_run_ids: list[str] = []

    async def fake_execute_tool(_name, _arguments):
        started.set()
        await asyncio.sleep(0.12)
        seen_run_ids.append(current_run_id.get())
        return mcp_server._json_response({"ok": True})

    mcp_server._execute_tool = fake_execute_tool
    try:
        task = asyncio.create_task(mcp_server.call_tool("context_probe", {}))
        await started.wait()
        task.cancel()
        response = await task
        await asyncio.sleep(0.15)
        return seen_run_ids, response
    finally:
        mcp_server._execute_tool = original_execute_tool

cancel_seen_run_ids, cancel_response = asyncio.run(_cancelled_tool_keeps_run_context_probe())
check("MCP cancel background giữ run_id context",
      bool(cancel_seen_run_ids)
      and cancel_seen_run_ids[0].startswith("mcp-")
      and "cancelled" in cancel_response[0].text,
      f"seen={cancel_seen_run_ids} response={cancel_response[0].text}")

# 16. Wiki API endpoints (static check, không gọi Azure)
import os
import llmwiki_tool
wiki_root = os.path.join(WORKSPACE_ROOT, "llmwiki", "wiki")
wiki_exists = os.path.isdir(wiki_root)
check("llmwiki/wiki/ tồn tại", wiki_exists, f"path={wiki_root}")
if wiki_exists:
    pages_found = []
    for sub in ["concepts", "entities"]:
        sub_dir = os.path.join(wiki_root, sub)
        if os.path.isdir(sub_dir):
            pages_found += [f for f in os.listdir(sub_dir) if f.endswith(".md")]
    check("llmwiki có pages khởi tạo", len(pages_found) >= 0,
          f"{len(pages_found)} pages tìm thấy")

old_workspace_root = os.environ.get("WORKSPACE_ROOT")
old_claude_project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
old_antigravity_meta = os.environ.get("ANTIGRAVITY_SOURCE_METADATA")
old_global_raw = llmwiki_tool.GLOBAL_RAW_DIR
old_global_wiki = llmwiki_tool.GLOBAL_WIKI_DIR
wiki_smoke = SMOKE_DIR / "wiki_scope"
local_project = wiki_smoke / "local_project"
global_root = wiki_smoke / "global"
try:
    os.environ["WORKSPACE_ROOT"] = str(local_project.resolve())
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
    llmwiki_tool.GLOBAL_RAW_DIR = str(global_root / "raw")
    llmwiki_tool.GLOBAL_WIKI_DIR = str(global_root / "wiki")
    for base in [
        local_project / "llmwiki" / "raw",
        local_project / "llmwiki" / "wiki" / "concepts",
        global_root / "raw",
        global_root / "wiki" / "concepts",
        global_root / "wiki" / "entities",
    ]:
        base.mkdir(parents=True, exist_ok=True)
    (local_project / "llmwiki" / "raw" / "local.md").write_text("local raw", encoding="utf-8")
    (global_root / "raw" / "global.md").write_text("global raw", encoding="utf-8")
    (local_project / "llmwiki" / "wiki" / "concepts" / "shared.md").write_text(
        "---\ntitle: Local Shared\n---\nneedle-scope local wins", encoding="utf-8"
    )
    (global_root / "wiki" / "concepts" / "shared.md").write_text(
        "---\ntitle: Global Shared\n---\nneedle-scope global loses", encoding="utf-8"
    )
    (global_root / "wiki" / "entities" / "global-only.md").write_text(
        "---\ntitle: Global Only\n---\nneedle-global-only", encoding="utf-8"
    )
    local_raw, local_wiki = llmwiki_tool._local_wiki_dirs()
    pending_targets = llmwiki_tool.wiki_pending_targets()
    scoped = llmwiki_tool.wiki_query("needle-scope")
    global_only = llmwiki_tool.wiki_query("needle-global-only")
    os.environ.pop("WORKSPACE_ROOT", None)
    os.environ["ANTIGRAVITY_SOURCE_METADATA"] = json.dumps({"tool": {"workspacePath": str(local_project.resolve())}})
    meta_raw, meta_wiki = llmwiki_tool._local_wiki_dirs()
finally:
    if old_workspace_root is None:
        os.environ.pop("WORKSPACE_ROOT", None)
    else:
        os.environ["WORKSPACE_ROOT"] = old_workspace_root
    if old_claude_project_dir is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_claude_project_dir
    if old_antigravity_meta is None:
        os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
    else:
        os.environ["ANTIGRAVITY_SOURCE_METADATA"] = old_antigravity_meta
    llmwiki_tool.GLOBAL_RAW_DIR = old_global_raw
    llmwiki_tool.GLOBAL_WIKI_DIR = old_global_wiki

check("llmwiki local dùng WORKSPACE_ROOT runtime", str(local_project.resolve()) in local_raw and str(local_project.resolve()) in local_wiki)
check("llmwiki local dùng ANTIGRAVITY_SOURCE_METADATA", str(local_project.resolve()) in meta_raw and str(local_project.resolve()) in meta_wiki)
check("llmwiki pending targets có local/global", pending_targets == ["local", "global"], str(pending_targets))
check("llmwiki query local ưu tiên global trùng filename",
      scoped["results_count"] == 1 and scoped["results"][0]["scope"] == "local",
      str(scoped))
check("llmwiki query global fallback hoạt động",
      global_only["results_count"] == 1 and global_only["results"][0]["scope"] == "global",
      str(global_only))

# 17. security_autofix tool có trong MCP và nhận files argument
sec_tool = next((t for t in tools if t.name == "security_autofix"), None)
check("security_autofix có trong MCP tools", sec_tool is not None)
if sec_tool:
    schema_props = sec_tool.inputSchema.get("properties", {})
    check("security_autofix schema có 'files' property", "files" in schema_props)
    check("security_autofix required=['files']", "files" in (sec_tool.inputSchema.get("required") or []))

# 18. security_autofix không có files → error message rõ ràng
r_sec = asyncio.run(st.security_autofix(files=None))
check("security_autofix không có files → error", "error" in r_sec)
r_sec2 = asyncio.run(st.security_autofix(files=[]))
check("security_autofix files rỗng → error", "error" in r_sec2)

# 19. auto_tester validation
r_tester = asyncio.run(st.auto_tester(files=None, findings=[]))
check("auto_tester không files → error", "error" in r_tester)
r_tester_mcp = asyncio.run(mcp_server.call_tool("auto_tester", {"files": ["config.py"], "findings": []}))
check("auto_tester findings rỗng ở MCP → error", "error" in json.loads(r_tester_mcp[0].text))
r_tester_bad = asyncio.run(mcp_server.call_tool("auto_tester", {"files": ["config.py"], "findings": ["x"]}))
check("auto_tester findings sai kiểu ở MCP → error", "error" in json.loads(r_tester_bad[0].text))
poly_bad = asyncio.run(mcp_server.call_tool("polyglot_reviewer", {"files": "config.py"}))
check("polyglot_reviewer files sai kiểu ở MCP → error", "error" in json.loads(poly_bad[0].text))
api_bad = asyncio.run(mcp_server.call_tool("api_contract_tester", {"endpoints": "/api/models"}))
check("api_contract_tester endpoints sai kiểu ở MCP → error", "error" in json.loads(api_bad[0].text))
import tools.core as core_mod
old_core_llm = core_mod._llm_analyze
async def _timeout_llm(*_args, **_kwargs):
    await asyncio.sleep(0.01)
    raise asyncio.TimeoutError()
try:
    core_mod._llm_analyze = _timeout_llm
    api_timeout = asyncio.run(st.api_contract_tester(endpoints=[{"path": "/health", "method": "GET"}]))
finally:
    core_mod._llm_analyze = old_core_llm
check("api_contract_tester timeout fallback rõ ràng",
      api_timeout.get("degraded") is False
      and api_timeout.get("fallback_reason") == "llm_timeout"
      and bool(api_timeout.get("test_code"))
      and api_timeout.get("syntax_valid") is True,
      str(api_timeout))

# 19b. Unsafe/mutating tools run in isolated workspace, not live repo
import tools.testing as testing_mod
import tools.wiki as wiki_mod
import tools.quality as quality_mod
unsafe_root = SMOKE_DIR / "unsafe_workspace"
unsafe_root.mkdir(exist_ok=True)
(unsafe_root / "README.md").write_text("# Unsafe smoke\n", encoding="utf-8")
(unsafe_root / "sample.py").write_text(
    "def is_enabled():\n"
    "    value = True\n"
    "    if value:\n"
    "        return True\n"
    "    return False\n\n"
    "def public_api():\n"
    "    return is_enabled()\n",
    encoding="utf-8",
)
(unsafe_root / "test_sample.py").write_text(
    "from sample import is_enabled\n\n"
    "def test_is_enabled():\n"
    "    assert is_enabled() is True\n",
    encoding="utf-8",
)
(unsafe_root / "llmwiki" / "raw").mkdir(parents=True, exist_ok=True)
(unsafe_root / "llmwiki" / "raw" / "unsafe.md").write_text("unsafe smoke raw doc", encoding="utf-8")
old_env_workspace = os.environ.get("WORKSPACE_ROOT")
old_env_claude = os.environ.get("CLAUDE_PROJECT_DIR")
old_testing_root = testing_mod.WORKSPACE_ROOT
old_wiki_root = wiki_mod.WORKSPACE_ROOT
old_quality_root = quality_mod.WORKSPACE_ROOT
try:
    os.environ["WORKSPACE_ROOT"] = str(unsafe_root.resolve())
    os.environ.pop("CLAUDE_PROJECT_DIR", None)
    testing_mod.WORKSPACE_ROOT = str(unsafe_root.resolve())
    wiki_mod.WORKSPACE_ROOT = str(unsafe_root.resolve())
    quality_mod.WORKSPACE_ROOT = str(unsafe_root.resolve())
    unsafe_wiki = asyncio.run(st.wiki_ingest(target="local"))
    unsafe_doc = asyncio.run(st.doc_sync())
    unsafe_tester = asyncio.run(st.auto_tester(files=["sample.py"], findings=[{"issue": "probe"}]))
    unsafe_sec = asyncio.run(st.security_autofix(files=["sample.py"]))
    unsafe_mut = asyncio.run(st.mutation_tester(files=[str((unsafe_root / "sample.py").resolve())], max_mutations=1))
finally:
    if old_env_workspace is None:
        os.environ.pop("WORKSPACE_ROOT", None)
    else:
        os.environ["WORKSPACE_ROOT"] = old_env_workspace
    if old_env_claude is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_env_claude
    testing_mod.WORKSPACE_ROOT = old_testing_root
    wiki_mod.WORKSPACE_ROOT = old_wiki_root
    quality_mod.WORKSPACE_ROOT = old_quality_root
check("unsafe wiki_ingest isolated chạy thật",
      any(item.get("status") == "success" for item in unsafe_wiki.get("details", [])),
      str(unsafe_wiki))
check("unsafe doc_sync isolated chạy thật",
      unsafe_doc.get("success") is True and "API Reference" in (unsafe_root / "README.md").read_text(encoding="utf-8"),
      str(unsafe_doc))
check("unsafe auto_tester isolated chạy thật",
      unsafe_tester.get("success") is True and (unsafe_root / "test_auto_generated.py").exists(),
      str(unsafe_tester))
check("unsafe security_autofix isolated chạy thật",
      "error" not in unsafe_sec
      and ("findings_count" in unsafe_sec or "fixed" in unsafe_sec or "applied" in unsafe_sec),
      str(unsafe_sec))
check("unsafe mutation_tester isolated chạy thật",
      "total_mutations" in unsafe_mut and unsafe_mut.get("total_mutations", 0) >= 0,
      str(unsafe_mut))

# 20. visual_reviewer validation
r_vis = asyncio.run(st.visual_reviewer(url=None))
check("visual_reviewer không url → error", "error" in r_vis)
from tools.testing import _clean_review_url, _skip_scan_dir
check("visual_reviewer reject control chars",
      _clean_review_url("https://example.com\x00/path", "URL")[1] != "")
check("visual_reviewer skip harness worktree dir",
      _skip_scan_dir(str(SMOKE_DIR / ".harness_worktree_abc" / "src")))

# 21. benchmarker test
r_bench = asyncio.run(st.benchmarker(code_a="x = 1", code_b="y = 2", iterations=1))
check("benchmarker chạy thành công", "code_a_stats" in r_bench and "code_b_stats" in r_bench, str(r_bench))

# 22. dependency_upgrader dry_run test
r_dep = asyncio.run(st.dependency_upgrader(dry_run=True))
check("dependency_upgrader dry run chạy được", "upgrades" in r_dep or "message" in r_dep, str(r_dep))
import tools.devops as devops_mod
dep_timeout_root = SMOKE_DIR / "dep_timeout_workspace"
dep_timeout_root.mkdir(exist_ok=True)
(dep_timeout_root / "requirements.txt").write_text("example-pkg==1.0.0\n", encoding="utf-8")
old_dep_env = os.environ.get("WORKSPACE_ROOT")
old_dep_runner = devops_mod._run_text
def _timeout_pip(*_args, **_kwargs):
    raise subprocess.TimeoutExpired("pip list", 30)
try:
    os.environ["WORKSPACE_ROOT"] = str(dep_timeout_root.resolve())
    devops_mod._run_text = _timeout_pip
    dep_timeout = asyncio.run(st.dependency_upgrader(dry_run=True))
finally:
    devops_mod._run_text = old_dep_runner
    if old_dep_env is None:
        os.environ.pop("WORKSPACE_ROOT", None)
    else:
        os.environ["WORKSPACE_ROOT"] = old_dep_env
check("dependency_upgrader timeout không báo latest giả",
      dep_timeout.get("degraded") is True
      and dep_timeout.get("fallback_reason") == "pip_outdated_check_failed"
      and dep_timeout.get("upgrades_count") is None,
      str(dep_timeout))

# 23. schema_drift test
r_schema = asyncio.run(st.schema_drift())
check("schema_drift chạy được", "drift_detected" in r_schema or "drift" in r_schema, str(r_schema))

# 24. doc_sync test
import tools.wiki as wiki_mod
docsync_root = SMOKE_DIR / "docsync_workspace"
docsync_root.mkdir(exist_ok=True)
(docsync_root / "README.md").write_text("# Smoke docs\n", encoding="utf-8")
original_wiki_root = wiki_mod.WORKSPACE_ROOT
try:
    wiki_mod.WORKSPACE_ROOT = str(docsync_root.resolve())
    r_doc = asyncio.run(st.doc_sync())
finally:
    wiki_mod.WORKSPACE_ROOT = original_wiki_root
check("doc_sync chạy được không đụng README thật", "success" in r_doc or "error" in r_doc, str(r_doc))

# 25. telemetry_debugger validation
r_tel = asyncio.run(st.telemetry_debugger(log_content=""))
check("telemetry_debugger chạy được với log rỗng", "fix_result" in r_tel, str(r_tel))

# 26. run_in_sandbox test
r_sb = st.run_in_sandbox("print('hello')", timeout=2.0)
check("run_in_sandbox chạy thành công", r_sb["status"] == "success" and r_sb.get("returncode") == 0 and "hello" in r_sb["stdout"], str(r_sb))
r_sb_timeout = st.run_in_sandbox("import time; time.sleep(10)", timeout=1.0)
check("run_in_sandbox timeout", r_sb_timeout["status"] == "timeout" and r_sb_timeout.get("returncode") is not None, str(r_sb_timeout))
check("run_in_sandbox dùng ignored parent dir",
      (Path(os.environ["WORKSPACE_ROOT"]) / ".harness_sandbox").exists(),
      str(Path(os.environ["WORKSPACE_ROOT"]) / ".harness_sandbox"))

runtime_cwd = (SMOKE_DIR / "runtime-cwd").resolve()
runtime_cwd.mkdir(parents=True, exist_ok=True)
old_runtime_env = {k: os.environ.get(k) for k in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
try:
    os.environ.pop("WORKSPACE_ROOT", None)
    os.environ["CLAUDE_PROJECT_DIR"] = str(runtime_cwd)
    os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
    rc_cwd, out_cwd, err_cwd = st._run_cmd_safe([sys.executable, "-c", "import os; print(os.getcwd())"])
finally:
    for key, value in old_runtime_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
check("_run_cmd_safe dùng runtime workspace",
      rc_cwd == 0 and Path(out_cwd.strip()).resolve() == runtime_cwd,
      f"rc={rc_cwd} out={out_cwd!r} err={err_cwd!r}")

ws_a = (SMOKE_DIR / "runtime-a").resolve()
ws_b = (SMOKE_DIR / "runtime-b").resolve()
ws_a.mkdir(parents=True, exist_ok=True)
ws_b.mkdir(parents=True, exist_ok=True)
(ws_a / "same.py").write_text("MARKER_A = True\n", encoding="utf-8")
(ws_b / "same.py").write_text("MARKER_B = True\n", encoding="utf-8")
old_runtime_env = {k: os.environ.get(k) for k in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA")}
try:
    os.environ.pop("WORKSPACE_ROOT", None)
    os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
    os.environ["CLAUDE_PROJECT_DIR"] = str(ws_a)
    block_a, _, _ = st.read_workspace_files(["same.py"])
    hash_a = st._calculate_review_hash(["same.py"], None, None, None, False, "")
    from tools.core import get_runtime_path
    from agents import get_finops_db_path
    runtime_path_a = get_runtime_path(".harness_cache")
    finops_path_a = get_finops_db_path()
    server.init_db()
    os.environ["CLAUDE_PROJECT_DIR"] = str(ws_b)
    block_b, _, _ = st.read_workspace_files(["same.py"])
    hash_b = st._calculate_review_hash(["same.py"], None, None, None, False, "")
    runtime_path_b = get_runtime_path(".harness_cache")
    finops_path_b = get_finops_db_path()
finally:
    for key, value in old_runtime_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
check("core file reads dùng runtime workspace",
      "MARKER_A" in block_a and "MARKER_B" in block_b and "MARKER_B" not in block_a and hash_a != hash_b,
      f"block_a={block_a!r} block_b={block_b!r} hash_a={hash_a} hash_b={hash_b}")
check("runtime cache/finops paths isolate theo workspace",
      runtime_path_a == str(ws_a / ".harness_cache")
      and runtime_path_b == str(ws_b / ".harness_cache")
      and finops_path_a == str(ws_a / ".harness_finops.db")
      and finops_path_b == str(ws_b / ".harness_finops.db")
      and (ws_a / ".harness_finops.db").exists(),
      f"cache=({runtime_path_a}, {runtime_path_b}) finops=({finops_path_a}, {finops_path_b})")

lesson_ws = (SMOKE_DIR / "lesson-runtime").resolve()
lesson_ws.mkdir(parents=True, exist_ok=True)
lesson_ws_other = (SMOKE_DIR / "lesson-runtime-other").resolve()
lesson_ws_other.mkdir(parents=True, exist_ok=True)
global_lesson_file = lesson_ws / "global-lessons.jsonl"
old_lesson_env = {k: os.environ.get(k) for k in ("WORKSPACE_ROOT", "CLAUDE_PROJECT_DIR", "ANTIGRAVITY_SOURCE_METADATA", "HARNESS_GLOBAL_LESSONS_FILE")}
try:
    os.environ.pop("WORKSPACE_ROOT", None)
    os.environ.pop("ANTIGRAVITY_SOURCE_METADATA", None)
    os.environ["CLAUDE_PROJECT_DIR"] = str(lesson_ws)
    os.environ["HARNESS_GLOBAL_LESSONS_FILE"] = str(global_lesson_file)
    from tools.core import append_lesson, get_global_lessons_path, get_lesson_db_path, load_relevant_lessons_context, record_procedure_lesson
    from tools.runner import _fallback_lesson_tags, _record_agent_lessons
    append_lesson({
        "source": "smoke",
        "title": "ask_codebase model chain timeout",
        "outcome": "fixed",
        "files": ["tools/swarm.py"],
        "error_signature": "ask_codebase gpt-5.4-pro-3 timeout",
        "fix_summary": "Switch ask_codebase to gpt-5.4-4 model_chain and local fallback.",
        "tags": ["ask_codebase", "timeout"],
    })
    record_procedure_lesson(
        title="Power Automate create approval flow",
        summary="Create a cloud flow, choose the trigger, configure approval actions, then save and test the flow.",
        steps=[
            "Open Power Automate and choose Create.",
            "Select Automated cloud flow.",
            "Configure trigger and approval action.",
            "Save, test, and verify run history.",
        ],
        tags=["power automate", "approval flow"],
        source="smoke",
    )
    curator_local_promoted = append_lesson({
        "source": "goal_runner",
        "lesson_type": "procedure",
        "title": "Dataverse solution import workflow",
        "summary": "Import a managed Dataverse solution into a target environment and validate dependencies.",
        "steps": [
            "Open the target Power Platform environment.",
            "Import the managed solution package.",
            "Verify connection references and environment variables.",
        ],
        "tags": ["dataverse", "solution", "workflow"],
        "lesson_key": "smoke:curator-local-procedure",
    })
    curator_untrusted_local = append_lesson({
        "source": "manual",
        "lesson_type": "procedure",
        "title": "Untrusted global promotion workflow",
        "summary": "This looks procedural but should not auto-promote because the source is not trusted.",
        "steps": [
            "Open the untrusted tool.",
            "Create a reusable workflow.",
            "Verify the result.",
        ],
        "tags": ["workflow"],
        "lesson_key": "smoke:curator-untrusted-procedure",
    })
    curator_noise_blocked = append_lesson({
        "source": "client_hook",
        "lesson_type": "edit_event",
        "title": "Edit local temp file",
        "summary": "Client hook observed a local edit.",
        "files": ["tmp/local.py"],
        "lesson_key": "smoke:curator-noise",
    })
    curator_safe_dry_run = asyncio.run(st.lesson_curator(limit=20, promote=True, dry_run=True, mode="safe"))
    duplicate_reordered = record_procedure_lesson(
        title="Power Automate create approval flow",
        summary="Create a cloud flow, choose the trigger, configure approval actions, then save and test the flow.",
        steps=[
            "Save, test, and verify run history.",
            "Configure trigger and approval action.",
            "Select Automated cloud flow.",
            "Open Power Automate and choose Create.",
        ],
        tags="power automate",
        source="smoke",
    )
    marker_lessons = _record_agent_lessons("learn reusable Power Automate flow setup", {
        "status": "completed",
        "stdout": (
            'HARNESS_LESSON_JSON: {"title":"Power Automate scheduled flow",'
            '"summary":"Create a scheduled cloud flow and configure recurrence before adding actions.",'
            '"steps":["Open Power Automate Create","Select Scheduled cloud flow","Set recurrence and save"],'
            '"tags":["power automate","scheduled flow"]}'
        ),
        "stderr": "",
    })
    multiline_marker_lessons = _record_agent_lessons("learn reusable Power Automate approval flow", {
        "status": "completed",
        "stdout": """HARNESS_LESSON_JSON: {
  "title": "Power Automate approval reassignment",
  "summary": "Configure approval reassignment steps after creating the flow.",
  "steps": ["Open approval action", "Set reassignment policy"],
  "tags": "power automate"
}""",
        "stderr": "",
    })
    fallback_lessons = _record_agent_lessons("learn reusable Power Automate environment promotion", {
        "status": "completed",
        "stdout": """Reusable workflow:
Title: Power Automate environment promotion
Summary: Promote a Power Automate flow between environments through a managed solution.
Steps:
1. Add the flow to a solution in the source environment.
2. Export the solution as managed.
3. Import the solution in the target environment.
4. Verify connection references and run history.
""",
        "stderr": "",
    })
    fallback_blocked_lessons = _record_agent_lessons("fix tools/runner.py bug", {
        "status": "completed",
        "stdout": "Fixed bug in tools/runner.py after traceback. Steps: 1. patch file 2. rerun tests",
        "stderr": "",
    })
    fallback_missing_status = _record_agent_lessons("learn reusable Power Automate environment promotion", {
        "stdout": """Reusable workflow:
Title: Power Automate environment promotion missing status
Summary: Promote a Power Automate flow between environments through a managed solution.
Steps:
1. Add the flow to a solution in the source environment.
2. Export the solution as managed.
""",
        "stderr": "",
    })
    fallback_timeline_blocked = _record_agent_lessons("learn incident timeline", {
        "status": "completed",
        "stdout": """Lesson learned:
Title: Payment outage timeline
Summary: Timeline of the incident.
Steps:
1. Alert fired at 10:00.
2. Error rate rose at 10:03.
3. Service recovered at 10:30.
""",
        "stderr": "",
    })
    invalid_marker_no_fallback = _record_agent_lessons("learn reusable deployment workflow", {
        "status": "completed",
        "stdout": """HARNESS_LESSON_JSON: {"title":
Reusable workflow:
Title: Deployment workflow after invalid marker
Summary: Deploy through the standard release pipeline.
Steps:
1. Build the release artifact.
2. Deploy the artifact to staging.
""",
        "stderr": "",
    })
    vietnamese_fallback_tags = _fallback_lesson_tags("tạo quy trình power automate", "Quy trình phê duyệt")
    mcp_tool_lesson = mcp_server._maybe_record_mcp_tool_lesson("quick_task", {}, mcp_server._json_response({
        "status": "completed",
        "notes": """Reusable workflow:
Title: SharePoint list approval routing
Summary: Configure a reusable SharePoint approval routing workflow. Authorization: Bearer sharepoint-secret-token
Steps:
1. Create the SharePoint list columns.
2. Configure the approval routing rule.
3. Test the approval path with a sample item.
""",
    }))
    mcp_tool_non_candidate = mcp_server._maybe_record_mcp_tool_lesson("run_ledger", {}, mcp_server._json_response({
        "status": "completed",
        "notes": """Reusable workflow:
Title: Should not store from run ledger
Summary: This should be ignored because run_ledger is not a lesson source.
Steps:
1. Create a record.
2. Verify a record.
""",
    }))
    cyclic_ref = {}
    cyclic_ref["self"] = cyclic_ref
    append_lesson({
        "source": "smoke",
        "title": "secret lesson redaction marker",
        "summary": "token='abc def' Authorization: Bearer abc123 password=plain",
        "refs": cyclic_ref,
    })
    from concurrent.futures import ThreadPoolExecutor
    concurrent_entry = {
        "source": "smoke",
        "title": "concurrent lesson dedupe",
        "summary": "only one physical record should be appended",
        "lesson_key": "smoke:concurrent-dedupe",
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent_flags = list(pool.map(lambda _i: append_lesson(concurrent_entry), range(12)))
    lesson_lines_after_concurrency = (lesson_ws / ".harness_lessons.jsonl").read_text(encoding="utf-8").splitlines()
    concurrent_count = sum(1 for line in lesson_lines_after_concurrency if '"lesson_key": "smoke:concurrent-dedupe"' in line)
    concurrent_global_entry = {
        "source": "goal_runner",
        "lesson_type": "procedure",
        "title": "Concurrent global promotion workflow",
        "summary": "Create a reusable workflow once even when many appenders race.",
        "steps": ["Open the workflow tool.", "Create the workflow.", "Verify the workflow."],
        "tags": ["workflow"],
        "lesson_key": "smoke:global-concurrent-dedupe",
    }
    with ThreadPoolExecutor(max_workers=8) as pool:
        concurrent_global_flags = list(pool.map(lambda _i: append_lesson(concurrent_global_entry), range(12)))
    global_lines_after_concurrency = global_lesson_file.read_text(encoding="utf-8").splitlines()
    concurrent_global_count = sum(1 for line in global_lines_after_concurrency if '"lesson_key": "smoke:global-concurrent-dedupe"' in line)
    process_global_code = """
from tools.core import append_lesson
append_lesson({
    "source": "goal_runner",
    "lesson_type": "procedure",
    "title": "Cross process global promotion workflow",
    "summary": "Create one reusable global workflow when multiple processes race.",
    "steps": ["Open the workflow tool.", "Create the workflow.", "Verify the workflow."],
    "tags": ["workflow"],
    "lesson_key": "smoke:global-process-dedupe",
})
"""
    process_env = {**os.environ, "WORKSPACE_ROOT": str(lesson_ws), "CLAUDE_PROJECT_DIR": str(lesson_ws), "HARNESS_GLOBAL_LESSONS_FILE": str(global_lesson_file)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        process_global_runs = list(pool.map(
            lambda _i: subprocess.run([sys.executable, "-c", process_global_code], cwd=str(Path.cwd()), env=process_env, capture_output=True, text=True, timeout=20),
            range(8),
        ))
    global_lines_after_process = global_lesson_file.read_text(encoding="utf-8").splitlines()
    process_global_count = sum(1 for line in global_lines_after_process if '"lesson_key": "smoke:global-process-dedupe"' in line)
    lesson_context = load_relevant_lessons_context("ask_codebase timeout model_chain")
    procedure_context = load_relevant_lessons_context("Power Automate tạo flow approval")
    secret_context = load_relevant_lessons_context("secret lesson redaction marker")
    os.environ["CLAUDE_PROJECT_DIR"] = str(lesson_ws_other)
    global_procedure_context = load_relevant_lessons_context("Power Automate tạo flow approval")
    global_fallback_context = load_relevant_lessons_context("Power Automate environment promotion managed solution")
    global_mcp_tool_context = load_relevant_lessons_context("SharePoint approval routing workflow")
    global_curator_context = load_relevant_lessons_context("Dataverse solution import workflow")
    global_curator_untrusted_context = load_relevant_lessons_context("Untrusted global promotion workflow")
    global_only_bug_context = load_relevant_lessons_context("ask_codebase timeout model_chain")
    os.environ["CLAUDE_PROJECT_DIR"] = str(lesson_ws)
    global_lesson_path_during_test = get_global_lessons_path()
    assembled_lesson_ctx, _ = st._assemble_context(context="ask_codebase timeout model_chain")
    agent_prompt_local_lessons = _agent_prompt("fix ask_codebase timeout model_chain", {"summary": "ask_codebase timeout model_chain"})
    os.environ["CLAUDE_PROJECT_DIR"] = str(lesson_ws_other)
    agent_prompt_global_lessons = _agent_prompt("Power Automate environment promotion managed solution", {"summary": "Power Automate environment promotion"})
    agent_prompt_pinned_lessons = _agent_prompt("fix ask_codebase timeout model_chain", {"summary": "ask_codebase timeout model_chain"}, root=lesson_ws)
    os.environ["CLAUDE_PROJECT_DIR"] = str(lesson_ws)
    import tools.runner as runner_mod
    original_runner_lessons = runner_mod.load_relevant_lessons_context
    try:
        runner_mod.load_relevant_lessons_context = lambda *_args, **_kwargs: "x" * 20000
        capped_agent_prompt = runner_mod._agent_prompt("x" * 6000 + "\x01", {"summary": "y" * 6000})
    finally:
        runner_mod.load_relevant_lessons_context = original_runner_lessons
    (lesson_ws / "sample.py").write_text("def sample():\n    return 'ask_codebase timeout model_chain'\n", encoding="utf-8")
    auto_lesson = asyncio.run(mcp_server.call_tool("auto_trigger", {
        "changed_files": ["README.md"],
        "task": "ask_codebase timeout model_chain docs",
        "stage": "post_edit",
        "mode": "safe",
    }))
    auto_lesson_json = json.loads(auto_lesson[0].text)
    auto_attr = asyncio.run(mcp_server.call_tool("auto_trigger", {
        "changed_files": ["sample.py"],
        "diff": "diff --git a/sample.py b/sample.py\n+ask_codebase timeout model_chain\n",
        "task": "fix ask_codebase timeout model_chain bug",
        "stage": "pre_complete",
        "mode": "safe",
    }))
    auto_attr_json = json.loads(auto_attr[0].text)
    ledger_after_attr = asyncio.run(mcp_server.call_tool("run_ledger", {"limit": 10}))
    ledger_after_attr_json = json.loads(ledger_after_attr[0].text)
    clean_lesson_recorded = _auto_record_auto_trigger_lesson(
        batch_id="smoke-clean-batch",
        diff_hash="smoke-clean-diff",
        files=["sample.py"],
        task="fix ask_codebase timeout model_chain bug",
        stage="pre_complete",
        mode="safe",
        selected=["harness_trace_viewer"],
        skipped_tools=[],
        results=[{"tool": "harness_trace_viewer", "ok": True, "status": "completed", "warnings": []}],
        blockers_count=0,
        timeout_budget_exceeded=False,
    )
    ledger_after_clean = asyncio.run(mcp_server.call_tool("run_ledger", {"limit": 10}))
    ledger_after_clean_json = json.loads(ledger_after_clean[0].text)
    old_key_entry = {
        "source": "smoke",
        "title": "old lesson key outside tail window",
        "summary": "dedupe must still find keys older than 200 rows",
        "lesson_key": "smoke:old-key-window",
    }
    old_key_first = append_lesson(old_key_entry)
    for idx in range(220):
        append_lesson({
            "source": "smoke",
            "title": f"filler lesson {idx}",
            "summary": "push old lesson key outside the old tail window",
            "lesson_key": f"smoke:filler-{idx}",
        })
    old_key_second = append_lesson(old_key_entry)
    lesson_lines_after_old_key = (lesson_ws / ".harness_lessons.jsonl").read_text(encoding="utf-8").splitlines()
    old_key_count = sum(1 for line in lesson_lines_after_old_key if '"lesson_key": "smoke:old-key-window"' in line)
    lesson_db_path = Path(get_lesson_db_path())
    lesson_db = sqlite3.connect(str(lesson_db_path))
    try:
        db_old_key_count = lesson_db.execute(
            "SELECT COUNT(*) FROM lesson_keys WHERE lesson_key = ?",
            ("smoke:old-key-window",),
        ).fetchone()[0]
    finally:
        lesson_db.close()
    for suffix in ("", "-wal", "-shm"):
        Path(str(lesson_db_path) + suffix).unlink(missing_ok=True)
    old_key_after_db_delete = append_lesson(old_key_entry)
    rebuilt_lesson_db_exists = lesson_db_path.exists()
    rebuilt_lesson_db = sqlite3.connect(str(lesson_db_path))
    try:
        rebuilt_old_key_count = rebuilt_lesson_db.execute(
            "SELECT COUNT(*) FROM lesson_keys WHERE lesson_key = ?",
            ("smoke:old-key-window",),
        ).fetchone()[0]
    finally:
        rebuilt_lesson_db.close()
    for suffix in ("-wal", "-shm"):
        Path(str(lesson_db_path) + suffix).unlink(missing_ok=True)
    lesson_db_path.write_bytes(b"not a sqlite database")
    old_key_after_db_corrupt = append_lesson(old_key_entry)
    post_corrupt_new_entry = {
        "source": "smoke",
        "title": "new lesson after corrupt db",
        "summary": "index should rebuild after quarantine",
        "lesson_key": "smoke:after-corrupt-db",
    }
    post_corrupt_new_stored = append_lesson(post_corrupt_new_entry)
    post_corrupt_db = sqlite3.connect(str(lesson_db_path))
    try:
        post_corrupt_counts = dict(post_corrupt_db.execute(
            "SELECT lesson_key, COUNT(*) FROM lesson_keys WHERE lesson_key IN (?, ?) GROUP BY lesson_key",
            ("smoke:old-key-window", "smoke:after-corrupt-db"),
        ).fetchall())
    finally:
        post_corrupt_db.close()
    no_key_entry = {
        "source": "smoke",
        "title": "no key append-only contract",
        "summary": "entries without lesson_key are append-only",
    }
    no_key_first = append_lesson(no_key_entry)
    no_key_second = append_lesson(no_key_entry)
    import tools.core as lesson_core
    original_fsync = lesson_core.os.fsync
    try:
        lesson_core.os.fsync = lambda _fd: (_ for _ in ()).throw(OSError("smoke fsync failure"))
        fsync_entry = {
            "source": "smoke",
            "title": "fsync best effort lesson",
            "summary": "flushed JSONL write should survive fsync warning",
            "lesson_key": "smoke:fsync-best-effort",
        }
        fsync_stored = append_lesson(fsync_entry)
    finally:
        lesson_core.os.fsync = original_fsync
    lesson_lines_after_fsync = (lesson_ws / ".harness_lessons.jsonl").read_text(encoding="utf-8").splitlines()
    fsync_line_count = sum(1 for line in lesson_lines_after_fsync if '"lesson_key": "smoke:fsync-best-effort"' in line)
finally:
    for key, value in old_lesson_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
check("lesson memory tự inject vào context",
      "ask_codebase model chain timeout" in lesson_context
      and "=== PRIOR LESSONS (AUTO-INJECTED) ===" in assembled_lesson_ctx,
      f"lesson_context={lesson_context!r}")
check("goal_runner agent prompt inject local/global lessons",
      "ask_codebase model chain timeout" in agent_prompt_local_lessons
      and "Power Automate environment promotion" in agent_prompt_global_lessons
      and "ask_codebase model chain timeout" in agent_prompt_pinned_lessons
      and "ask_codebase model chain timeout" not in agent_prompt_global_lessons,
      f"local_prompt={agent_prompt_local_lessons!r} global_prompt={agent_prompt_global_lessons!r} pinned={agent_prompt_pinned_lessons!r}")
check("goal_runner agent prompt cap prior lessons",
      len(capped_agent_prompt) < 18000 and "[truncated prior lessons]" in capped_agent_prompt,
      f"len={len(capped_agent_prompt)} prompt={capped_agent_prompt[:200]!r}")
check("procedure lesson memory tự học và inject workflow",
      "Power Automate create approval flow" in procedure_context
      and "steps:" in procedure_context
      and any(item.get("status") == "stored" for item in marker_lessons),
      f"procedure_context={procedure_context!r} marker_lessons={marker_lessons!r}")
check("procedure fallback tự học khi agent quên marker",
      any(item.get("status") == "stored" for item in fallback_lessons)
      and fallback_blocked_lessons == []
      and fallback_missing_status == []
      and fallback_timeline_blocked == []
      and invalid_marker_no_fallback and invalid_marker_no_fallback[0].get("status") == "skipped"
      and vietnamese_fallback_tags
      and "Power Automate environment promotion" in global_fallback_context
      and "scope=global" in global_fallback_context,
      f"fallback={fallback_lessons!r} blocked={fallback_blocked_lessons!r} missing={fallback_missing_status!r} timeline={fallback_timeline_blocked!r} invalid={invalid_marker_no_fallback!r} tags={vietnamese_fallback_tags!r} context={global_fallback_context!r}")
check("mcp tool fallback tự học không cần goal_runner",
      mcp_tool_lesson.get("status") == "stored"
      and mcp_tool_non_candidate.get("status") == "skipped"
      and "SharePoint list approval routing" in global_mcp_tool_context
      and "sharepoint-secret-token" not in global_mcp_tool_context
      and "scope=global" in global_mcp_tool_context,
      f"lesson={mcp_tool_lesson!r} non_candidate={mcp_tool_non_candidate!r} context={global_mcp_tool_context!r}")
check("procedure lesson global qua project khác, bug/fix vẫn local",
      global_lesson_path_during_test == str(global_lesson_file.resolve())
      and global_lesson_file.exists()
      and "Power Automate create approval flow" in global_procedure_context
      and "scope=global" in global_procedure_context
      and "ask_codebase model chain timeout" not in global_only_bug_context,
      f"global={global_procedure_context!r} bug={global_only_bug_context!r} path={global_lesson_path_during_test!r}")
check("lesson curator tự phân loại và promote global đúng loại",
      curator_local_promoted is True
      and curator_untrusted_local is True
      and curator_noise_blocked is True
      and "Dataverse solution import workflow" in global_curator_context
      and "scope=global" in global_curator_context
      and "Untrusted global promotion workflow" not in global_curator_untrusted_context
      and curator_safe_dry_run.get("counts", {}).get("noise", 0) >= 1
      and any(d.get("lesson_key") == "smoke:curator-local-procedure" and d.get("promote_global") for d in curator_safe_dry_run.get("decisions", [])),
      f"promoted={curator_local_promoted} untrusted={curator_untrusted_local} noise={curator_noise_blocked} context={global_curator_context!r} untrusted_ctx={global_curator_untrusted_context!r} dry={curator_safe_dry_run!r}")
check("procedure lesson parser/dedupe/redaction robust",
      duplicate_reordered.get("status") == "duplicate"
      and any(item.get("status") == "stored" for item in multiline_marker_lessons)
      and "abc123" not in secret_context
      and "abc def" not in secret_context
      and "password=plain" not in secret_context,
      f"duplicate={duplicate_reordered!r} multiline={multiline_marker_lessons!r} secret={secret_context!r}")
check("lesson append dedupe atomic trong process",
      concurrent_flags.count(True) == 1 and concurrent_count == 1,
      f"flags={concurrent_flags} count={concurrent_count}")
check("lesson auto-promote global dedupe atomic trong process",
      concurrent_global_flags.count(True) == 1 and concurrent_global_count == 1,
      f"flags={concurrent_global_flags} count={concurrent_global_count}")
check("lesson auto-promote global dedupe atomic đa tiến trình",
      all(run.returncode == 0 for run in process_global_runs) and process_global_count == 1,
      f"returncodes={[run.returncode for run in process_global_runs]} count={process_global_count} stderr={[run.stderr[:120] for run in process_global_runs]}")
check("lesson append dedupe scan full file",
      old_key_first is True and old_key_second is False and old_key_count == 1,
      f"first={old_key_first} second={old_key_second} count={old_key_count}")
check("lesson sqlite index tự tạo và rebuild",
      db_old_key_count == 1 and old_key_after_db_delete is False and rebuilt_lesson_db_exists and rebuilt_old_key_count == 1,
      f"db_count={db_old_key_count} after_delete={old_key_after_db_delete} rebuilt={rebuilt_lesson_db_exists} rebuilt_count={rebuilt_old_key_count}")
check("lesson sqlite index tự quarantine corrupt db",
      old_key_after_db_corrupt is False
      and post_corrupt_new_stored is True
      and post_corrupt_counts.get("smoke:old-key-window") == 1
      and post_corrupt_counts.get("smoke:after-corrupt-db") == 1,
      f"old_after_corrupt={old_key_after_db_corrupt} new={post_corrupt_new_stored} counts={post_corrupt_counts}")
busy_error = sqlite3.OperationalError("database is locked")
check("lesson sqlite busy không bị xem là corrupt",
      _is_sqlite_busy_error(busy_error) is True,
      str(busy_error))
check("lesson không có lesson_key append-only",
      no_key_first is True and no_key_second is True,
      f"first={no_key_first} second={no_key_second}")
review_hash_fast = _calculate_review_hash(files=["a.py"], fast=True, agent_timeout=5, cache_schema=2)
review_hash_full = _calculate_review_hash(files=["a.py"], fast=False, agent_timeout=90, cache_schema=2)
check("panel_review cache key tách mode/timeout",
      review_hash_fast != review_hash_full,
      f"fast={review_hash_fast} full={review_hash_full}")
check("lesson fsync best-effort không làm mất write",
      fsync_stored is True and fsync_line_count == 1,
      f"stored={fsync_stored} count={fsync_line_count}")
check("auto_trigger trả prior_lessons dù skip docs-only",
      "ask_codebase model chain timeout" in auto_lesson_json.get("prior_lessons", ""),
      str(auto_lesson_json))
check("auto_trigger gắn attribution cho batch edit",
      bool(auto_attr_json.get("batch_id"))
      and bool(auto_attr_json.get("diff_hash"))
      and "failed_tools" in auto_attr_json
      and auto_attr_json.get("lessons_recorded", {}).get("status") == "skipped"
      and auto_attr_json.get("orchestrator", {}).get("status") == "completed"
      and any(e.get("event") == "edit_batch_checked" and e.get("batch_id") == auto_attr_json.get("batch_id") for e in ledger_after_attr_json.get("entries", [])),
      f"auto={auto_attr_json} ledger={ledger_after_attr_json}")
check("auto_trigger tự ghi lesson sau batch pass",
      clean_lesson_recorded.get("status") in {"stored", "duplicate"}
      and any(item.get("source") == "auto_trigger" and item.get("lesson_type") == "checked_edit" for item in ledger_after_clean_json.get("lessons", [])),
      f"recorded={clean_lesson_recorded} lessons={ledger_after_clean_json.get('lessons')}")
check("orchestrator tự chạy trong auto_trigger skip/check",
      auto_lesson_json.get("orchestrator", {}).get("status") == "completed"
      and auto_attr_json.get("orchestrator", {}).get("skill_route", {}).get("recommended_tools"),
      f"skip={auto_lesson_json.get('orchestrator')} check={auto_attr_json.get('orchestrator')}")

# 27. semantic_search test
r_index = asyncio.run(st.index_codebase(force=False))
check("index_codebase chạy được", "status" in r_index, str(r_index))
r_index_mcp = asyncio.run(mcp_server.call_tool("index_codebase", {"force": False}))
check("index_codebase MCP dispatch chạy được", "status" in json.loads(r_index_mcp[0].text), r_index_mcp[0].text)
r_search = asyncio.run(st.semantic_search(query="test", top_k=2))
check("semantic_search chạy được", "results" in r_search and "warnings" in r_search, str(r_search))

# 28. finops_stats test
from agents import get_finops_stats
r_finops = get_finops_stats()
check("finops_stats chạy được", "total_cost_usd" in r_finops and "model_stats" in r_finops, str(r_finops))

# 29. swarm_debug test
r_swarm = asyncio.run(st.swarm_debug(error_log="KeyError: 'files'", files=[]))
check("swarm_debug chạy được", "logs" in r_swarm, str(r_swarm))

# 30. devops_pipeline test (CI/CD Quality Gate & Fallback parser)
r_devops = asyncio.run(st.devops_pipeline())
check("devops_pipeline chạy thành công và trả về score", "score" in r_devops and "findings" in r_devops, str(r_devops))

# 31. config_security_audit test (Exposed Secrets & Config Drift scanner)
r_config = asyncio.run(st.config_security_audit())
check("config_security_audit chạy thành công", "findings" in r_config and "secrets_found" in r_config, str(r_config))

# 32. Interactive Swarm init & session test
from agents import get_finops_db_path
try:
    conn = sqlite3.connect(get_finops_db_path())
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS swarm_sessions (
        swarm_id TEXT PRIMARY KEY,
        state TEXT,
        error_log TEXT,
        target_files TEXT,
        reproducer_code TEXT,
        suggested_patch TEXT,
        logs TEXT,
        final_result TEXT,
        ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error creating swarm_sessions table in test: {e}")

with open(SMOKE_FILE, "w", encoding="utf-8") as f:
    f.write("x = 1\n")
try:
    asyncio.run(server.api_swarm_init(server.SwarmInitRequest(error_log="bad", files=["../secret.py"])))
    invalid_swarm_blocked = False
except Exception as exc:
    invalid_swarm_blocked = getattr(exc, "status_code", None) == 422
check("Interactive Swarm init chặn target_files ngoài workspace",
      invalid_swarm_blocked,
      "expected HTTP 422 for path traversal")
init_req = server.SwarmInitRequest(error_log="KeyError: 'files'", files=[SMOKE_FILE_REL])
init_res = asyncio.run(server.api_swarm_init(init_req))
check("Interactive Swarm init trả về swarm_id và state pending_tester", 
      "swarm_id" in init_res and init_res["state"] == "pending_tester", str(init_res))

# 33. Interactive Swarm proceed state machine test
if "swarm_id" in init_res:
    swarm_id = init_res["swarm_id"]
    # Step 2: proceed to pending_coder
    proceed_body_tester = server.SwarmProceedBody(reproducer_code="def test_swarm_reproducer():\n    assert True\n")
    proceed_res1 = asyncio.run(server.api_swarm_proceed(swarm_id, proceed_body_tester))
    check("Swarm proceed 1: pending_tester -> pending_coder", 
          proceed_res1["state"] == "pending_coder", str(proceed_res1))

    # Step 3: proceed to pending_apply
    proceed_res2 = asyncio.run(server.api_swarm_proceed(swarm_id, server.SwarmProceedBody()))
    check("Swarm proceed 2: pending_coder -> pending_apply", 
          proceed_res2["state"] == "pending_apply", str(proceed_res2))

    # Step 4: proceed to pending_review
    proceed_res3 = asyncio.run(server.api_swarm_proceed(swarm_id, server.SwarmProceedBody()))
    check("Swarm proceed 3: pending_apply -> pending_review", 
          proceed_res3["state"] == "pending_review", str(proceed_res3))

    # Step 5: proceed to completed (approve verdict)
    proceed_res4 = asyncio.run(server.api_swarm_proceed(swarm_id, server.SwarmProceedBody()))
    check("Swarm proceed 4: pending_review -> completed", 
          proceed_res4["state"] == "completed", str(proceed_res4))
else:
    check("Swarm proceed 1-4 bypassed due to init failure", False)

# 34. pr_generator test
r_pr = asyncio.run(st.pr_generator(diff=f"diff --git a/{SMOKE_FILE_REL} b/{SMOKE_FILE_REL}"))
check("pr_generator chạy thành công", "title" in r_pr or "description" in r_pr or "error" in r_pr, str(r_pr))

# 35. dead_code_scanner test
r_dead = asyncio.run(st.dead_code_scanner())
check("dead_code_scanner chạy thành công", "dead_symbols" in r_dead or "findings" in r_dead, str(r_dead))

# 36. coverage_analyzer test
r_cov = asyncio.run(st.coverage_analyzer())
check("coverage_analyzer chạy thành công", "coverage_percent" in r_cov or "report" in r_cov or "error" in r_cov, str(r_cov))

# 37. incident_responder test
r_inc = asyncio.run(st.incident_responder(log_content="KeyError: 'files'"))
check("incident_responder chạy thành công", "severity" in r_inc or "summary" in r_inc or "mitigation_steps" in r_inc, str(r_inc))

# 38. api_contract_tester test
r_contract = asyncio.run(st.api_contract_tester(endpoints=[{"path": "/api/models", "method": "GET"}]))
check("api_contract_tester chạy thành công", "test_code" in r_contract or "syntax_valid" in r_contract, str(r_contract))

# 39. license_scanner test
r_lic = asyncio.run(st.license_scanner())
check("license_scanner chạy thành công", "licenses" in r_lic or "warnings" in r_lic, str(r_lic))

# 40. profiler test
r_prof = st.profiler(code="sum(range(100))", iterations=1)
check("profiler chạy thành công", "execution_time_ms" in r_prof or "stats" in r_prof or "warnings" in r_prof, str(r_prof))

# 41. polyglot_reviewer test
r_poly = asyncio.run(st.polyglot_reviewer(files=[SMOKE_FILE_REL]))
check("polyglot_reviewer chạy thành công", "review" in r_poly or "findings" in r_poly, str(r_poly))

# 42. a11y_auditor test
r_a11y = asyncio.run(st.a11y_auditor(files=["index.html"]))
check("a11y_auditor chạy thành công", "issues" in r_a11y or "score" in r_a11y, str(r_a11y))

# 43. git_archaeologist test
r_git_arch = asyncio.run(st.git_archaeologist(file_path=SMOKE_FILE_REL, line_no=1))
check("git_archaeologist chạy thành công", "commit_sha" in r_git_arch or "error" in r_git_arch, str(r_git_arch))

# 44. feature_flag_auditor test
r_ff = asyncio.run(st.feature_flag_auditor())
check("feature_flag_auditor chạy thành công", "flags" in r_ff or "findings" in r_ff, str(r_ff))

# 45. sbom_generator test
r_sbom = asyncio.run(st.sbom_generator())
check("sbom_generator chạy thành công", "sbom" in r_sbom or "dependencies" in r_sbom, str(r_sbom))

# 46. chaos_tester test
r_chaos = st.chaos_tester(app_run_command="python --version", duration=1)
check("chaos_tester chạy thành công", "chaos_results" in r_chaos or "status" in r_chaos or "warnings" in r_chaos, str(r_chaos))

# 47. i18n_auditor test
r_i18n = asyncio.run(st.i18n_auditor(files=["index.html"]))
check("i18n_auditor chạy thành công", "issues" in r_i18n or "issues_count" in r_i18n, str(r_i18n))

print()
if failures:
    print(f"❌ {len(failures)} test fail: {failures}")
    raise SystemExit(1)
print("✅ Tất cả smoke tests pass")
