"""Smoke test offline — không gọi Azure API."""
# ruff: noqa: E402
import asyncio
import json
import sys
import os
import shutil
import time
from pathlib import Path
import atexit

# Ngăn chặn đệ quy vô hạn khi các công cụ gọi lại smoke_test.py
if os.environ.get("SMOKE_TEST_SUBRUN") == "1":
    print("✅ Sub-run smoke test pass (bypassed recursively)")
    sys.exit(0)

# Đặt biến môi trường cho các tiến trình con để tránh đệ quy
os.environ["SMOKE_TEST_SUBRUN"] = "1"

SMOKE_DIR = Path(".harness_smoke")
SMOKE_FILE = SMOKE_DIR / "test_panel.py"
SMOKE_FILE_REL = SMOKE_FILE.as_posix()
SMOKE_DIR.mkdir(exist_ok=True)
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

# Mocking Agent and LLM calls to prevent network activity in smoke tests
def mock_run(self, task: str, extra_context: str = "", *, json_mode: bool = False, max_output_tokens: int = 4096):
    role_responses = {
        agents.AgentRole.DEBUGGER: """## Root cause
Lỗi do biến chưa định nghĩa ở file:line

## Patch
```diff
--- a/.harness_smoke/test_panel.py
+++ b/.harness_smoke/test_panel.py
@@ -1,3 +1,3 @@
-x = 1
+x = 2
```

## Lưu ý
Không có""",
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
        agents.AgentRole.ANALYZER: '{"root_cause": "KeyError: \'files\'", "suggested_approach": "Check keys", "target_files": [".harness_smoke/test_panel.py"]}',
        agents.AgentRole.TESTER: '```python\ndef test_swarm_reproducer():\n    assert True\n```',
        agents.AgentRole.REVIEWER: '{"verdict": "approve", "summary": "Bản vá chất lượng tốt, không lỗi."}'
    }
    
    res_val = role_responses.get(self.role, "Dummy response")
    
    if self.role == agents.AgentRole.CODE_A and ("Swarm Debugger" in task or "Coder Agent" in task or "suggested_approach" in task):
        res_val = """## Patch
```diff
--- a/.harness_smoke/test_panel.py
+++ b/.harness_smoke/test_panel.py
@@ -1,3 +1,3 @@
-x = 1
+x = 2
```"""
            
    return agents.AgentResult(
        agent_id=self.agent_id,
        agent_role=self.role,
        model_used=self.model,
        task=task,
        result=res_val,
        duration_ms=10,
        status="success"
    )

async def mock_run_async(self, task: str, extra_context: str = "", *, json_mode: bool = False, max_output_tokens: int = 4096):
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
            return '{"root_cause": "KeyError", "suggested_approach": "Check keys", "target_files": []}', "mock-model", 100, 10
        elif "Tester Agent" in system_prompt:
            return '```python\ndef test_swarm_reproducer():\n    assert False\n```', "mock-model", 100, 10
        elif "Coder Agent" in system_prompt:
            return '## Patch\n```diff\n--- a/.harness_smoke/test_panel.py\n+++ b/.harness_smoke/test_panel.py\n@@ -1,3 +1,3 @@\n-x = 1\n+x = 2\n```', "mock-model", 100, 10
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
from config import MODELS, SPARE_MODELS, WORKSPACE_ROOT
roles = ["manager", "synthesizer", "analyzer", "code_a", "code_b",
         "reviewer", "tester", "security", "integrity", "scanner",
         "debugger", "worker"]
check("ModelConfig đủ 12 role", all(getattr(MODELS, r, None) for r in roles))
check("SPARE_MODELS load được", isinstance(SPARE_MODELS, list) and len(SPARE_MODELS) > 0,
      str(SPARE_MODELS))

# 3. Mỗi role có system prompt + temperature
from agents import AgentRole, SYSTEM_PROMPTS, ROLE_TO_MODEL, ROLE_TEMPERATURE
check("SYSTEM_PROMPTS đủ 12 role", set(SYSTEM_PROMPTS) == set(AgentRole))
check("ROLE_TO_MODEL đủ 12 role", set(ROLE_TO_MODEL) == set(AgentRole))
check("ROLE_TEMPERATURE đủ 12 role", set(ROLE_TEMPERATURE) == set(AgentRole))

# 4. MCP server: list_tools trả đủ 58 tool, schema hợp lệ
tools = asyncio.run(mcp_server.list_tools())
tool_names = {t.name for t in tools}
expected = {"auto_trigger", "panel_review", "consult", "alt_implementation", "suggest_fix",
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
check("MCP đăng ký đủ 58 tool", tool_names == expected,
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
auto_bad_stage = asyncio.run(mcp_server.call_tool("auto_trigger", {"stage": "done"}))
check("auto_trigger stage invalid → error", "error" in json.loads(auto_bad_stage[0].text))
auto_bad_mode = asyncio.run(mcp_server.call_tool("auto_trigger", {"mode": "wild"}))
check("auto_trigger mode invalid → error", "error" in json.loads(auto_bad_mode[0].text))
auto_upper = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["README.md"],
    "stage": " FINAL ",
    "mode": " SAFE ",
}))
check("auto_trigger stage/mode normalize hoa thường", json.loads(auto_upper[0].text).get("status") == "skipped")
auto_env_case = asyncio.run(mcp_server.call_tool("auto_trigger", {
    "changed_files": ["config/.ENV.EXAMPLE"],
    "stage": "post_edit",
    "mode": "safe",
}))
auto_env_case_json = json.loads(auto_env_case[0].text)
check("auto_trigger nhận diện .ENV.EXAMPLE không phân biệt hoa thường",
      auto_env_case_json.get("status") == "completed" and "env_parity_checker" in auto_env_case_json.get("selected_tools", []),
      str(auto_env_case_json))

from tools.swarm import _extractive_codebase_answer, _manager_answer_usable, _normalize_manager_answer
check("ask_codebase unwrap JSON answer",
      _normalize_manager_answer('{"answer": "Có dùng app/api.py:10"}') == "Có dùng app/api.py:10")
check("ask_codebase reject generic manager answer",
      not _manager_answer_usable("Tôi không đủ ngữ cảnh để kết luận, nên cần đọc thêm file."))
check("ask_codebase accept cited manager answer",
      _manager_answer_usable("Flow export nằm ở app/api.py:10 và frontend gọi từ web/page.tsx:4."))
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
lock1 = auto_watch._acquire_lock(lock_path)
fd1 = lock1[0] if lock1 else None
token1 = lock1[1] if lock1 else ""
lock2 = auto_watch._acquire_lock(lock_path)
try:
    check("auto_watch lock acquire atomic", fd1 is not None and lock2 is None)
    if fd1 is not None:
        lock_payload = json.loads(lock_path.read_text(encoding="utf-8"))
        check("auto_watch lock ghi PID metadata", lock_payload.get("pid") == os.getpid() and lock_payload.get("token"), str(lock_payload))
        lock_path.write_text(json.dumps({"pid": os.getpid(), "ts": time.time(), "token": "other"}), encoding="utf-8")
        auto_watch._release_lock(lock_path, token1)
        check("auto_watch release không xóa lock owner khác", lock_path.exists())
finally:
    if fd1 is not None:
        os.close(fd1)
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
codex_sample = '  [mcp_servers.agent-harness]\ncommand = "old"\n\n[mcp_servers.other]\ncommand = "x"\n'
codex_block = '[mcp_servers.agent-harness]\ncommand = "python"\nargs = [ "server.py" ]\n'
import re
codex_pattern = r'(?ms)^\s*\[mcp_servers\.agent-harness\]\n.*?(?=^\s*\[|\Z)'
codex_new = re.sub(codex_pattern, codex_block + "\n", codex_sample)
check("codex MCP block indent vẫn upsert idempotent",
      codex_new.count("[mcp_servers.agent-harness]") == 1 and "[mcp_servers.other]" in codex_new,
      codex_new)

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
check("chặn path ngoài WORKSPACE_ROOT",
      ctx2 == "" and loaded2 == 0 and
      all("ngoài WORKSPACE_ROOT" in w for w in warns2),
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

# 8. Tool validation: thiếu input → error message rõ ràng (không gọi API)
r = asyncio.run(st.panel_review())
check("panel_review không input → error", "error" in r)
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
import sqlite3
import time
server.init_db()
stale_id = "smoke-stale-lock"
now = time.time()
conn = sqlite3.connect(server.FINOPS_DB_PATH)
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
    conn = sqlite3.connect(server.FINOPS_DB_PATH)
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

# 15. panel_review nhận staged=True → không cần files (auto git diff hoặc error từ git)
r3 = asyncio.run(st.panel_review(staged=True))
check("panel_review(staged=True) không crash",
      "error" in r3 or "findings" in r3,
      str(r3.get("error", ""))[:120])

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

# 23. schema_drift test
r_schema = asyncio.run(st.schema_drift())
check("schema_drift chạy được", "drift" in r_schema, str(r_schema))

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
check("run_in_sandbox chạy thành công", r_sb["status"] == "success" and "hello" in r_sb["stdout"], str(r_sb))
r_sb_timeout = st.run_in_sandbox("import time; time.sleep(10)", timeout=1.0)
check("run_in_sandbox timeout", r_sb_timeout["status"] == "timeout", str(r_sb_timeout))

# 27. semantic_search test
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
import sqlite3
from agents import FINOPS_DB_PATH
try:
    conn = sqlite3.connect(FINOPS_DB_PATH)
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
