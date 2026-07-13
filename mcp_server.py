"""
Agent Harness - MCP Server (Support Toolbox cho Claude Code)
Claude Code gọi các tool này qua MCP protocol.

Đăng ký với Claude Code:
  claude mcp add agent-harness -- python "đường/dẫn/tới/mcp_server.py"
"""
import asyncio
import logging
import json
import os
import subprocess
import sys
import threading
import ctypes
import time
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from agents import Agent, AgentRole, get_finops_stats
from config import MODELS, WORKSPACE_ROOT, get_azure_client
import support_tools as st

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
_log = logging.getLogger("harness.mcp")

app = Server("agent-harness")

# Registry giữ background tasks tránh GC + cho phép harvest khi cancel
_background_tasks: set[asyncio.Task] = set()
# Giới hạn đồng thời để tránh Azure rate-limit khi spam cancel
_TOOL_SEM = asyncio.Semaphore(8)
_LAZY_SETTINGS_MERGE_DONE = False


@app.list_resources()
async def list_resources() -> list[types.Resource]:
    return []


@app.list_resource_templates()
async def list_resource_templates() -> list[types.ResourceTemplate]:
    return []


def _cleanup_orphaned_worktrees() -> None:
    """Xóa git worktrees bị bỏ lại từ lần chạy trước bị crash.
    Dùng 'git worktree list --porcelain' để chỉ remove đúng worktrees do harness tạo.
    """
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = ""
    repo = Path(workspace or (os.getenv("WORKSPACE_ROOT") or "").strip() or WORKSPACE_ROOT)
    if not repo.is_dir():
        return
    try:
        r = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(repo), capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return
        # Parse porcelain: mỗi worktree block bắt đầu bằng "worktree <path>"
        for line in r.stdout.splitlines():
            if not line.startswith("worktree "):
                continue
            wt_path = Path(line[len("worktree "):].strip())
            if (wt_path.name.startswith(".harness_worktree_")
                    and wt_path.is_dir()
                    and not wt_path.is_symlink()):
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt_path)],
                        cwd=str(repo), capture_output=True, timeout=10,
                    )
                    _log.info("Cleaned orphaned worktree: %s", wt_path.name)
                except Exception as e:
                    _log.debug("Worktree cleanup skip %s: %s", wt_path.name, e)
    except Exception as e:
        _log.debug("Worktree list failed: %s", e)


_cleanup_orphaned_worktrees()

STR_TO_ROLE: dict[str, AgentRole] = {r.value: r for r in AgentRole}

_AGENT_METADATA = {
    AgentRole.MANAGER:     {"tool": "ask_codebase",       "specialty": "Q&A trên codebase lớn — 1M token context. Gọi TRƯỚC khi đọc file nếu task >1 file"},
    AgentRole.SYNTHESIZER: {"tool": "panel_review",       "specialty": "Merge/dedupe findings từ review panel"},
    AgentRole.ANALYZER:    {"tool": "consult",            "specialty": "Design questions, trade-offs (deep reasoning)"},
    AgentRole.CODE_A:      {"tool": "alt_implementation", "specialty": "Phương án implementation 1 (Kimi K2.6)"},
    AgentRole.CODE_B:      {"tool": "alt_implementation", "specialty": "Phương án implementation 2 — chủ động khác biệt"},
    AgentRole.REVIEWER:    {"tool": "panel_review",       "specialty": "Bugs, logic errors, anti-patterns, performance"},
    AgentRole.TESTER:      {"tool": "panel_review",       "specialty": "Adversarial devil's advocate — race condition, hidden assumption, edge case mà quality/security bỏ sót"},
    AgentRole.SECURITY:    {"tool": "panel_review",       "specialty": "Injection, XSS, auth flaws, secrets"},
    AgentRole.INTEGRITY:   {"tool": "panel_review",       "specialty": "Data integrity, partial failure gaps, final synthesis guard"},
    AgentRole.SCANNER:     {"tool": "dead_code_scanner",  "specialty": "Static analysis enrichment: dead code, complexity, duplicates, perf hotspots"},
    AgentRole.DEBUGGER:    {"tool": "suggest_fix",        "specialty": "Root cause + patch dạng unified diff"},
    AgentRole.WORKER:      {"tool": "quick_task",         "specialty": "Boilerplate, fixtures, docs, việc vặt"},
}
if set(_AGENT_METADATA) != set(AgentRole):
    missing = set(AgentRole) - set(_AGENT_METADATA)
    extra = set(_AGENT_METADATA) - set(AgentRole)
    raise RuntimeError(f"AGENT_METADATA mismatch: missing={missing}, extra={extra}")

AGENT_INFO = [
    {"role": role.value, **_AGENT_METADATA[role]}
    for role in AgentRole
]

_MODEL_BY_ROLE = {role.value: getattr(MODELS, role.value) for role in AgentRole}

_FILES_SCHEMA = {
    "type": "array", "items": {"type": "string"},
    "description": f"Danh sách file paths (tương đối từ WORKSPACE_ROOT: {WORKSPACE_ROOT})",
}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    _ensure_lazy_settings_merge()
    return [
        types.Tool(
            name="auto_trigger",
            description=(
                "Auto-Pilot: sau Edit/Write hoặc trước khi hoàn thành, tự chọn và chạy các harness checks phù hợp "
                "(secret/env/config/devops/complexity/dead-code/duplicate/panel_review). "
                "mode=max để vắt Azure mạnh nhất; tránh gửi .env thật vào panel_review."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại để chọn checks"},
                    "stage": {"type": "string", "enum": ["post_edit", "final", "pre_complete"], "description": "Vị trí gọi auto-pilot"},
                    "mode": {"type": "string", "enum": ["max", "safe"], "description": "max=vắt Azure mạnh nhất; safe=chỉ chạy khi có rủi ro rõ"},
                },
            },
        ),
        types.Tool(
            name="prod_readiness_gate",
            description=(
                "Production readiness gate: gom auto_trigger final + security/env/secret/review/release checks "
                "và trả verdict cứng: ready_to_deploy, fix_required, blocked_needs_user, deploy_then_verify, rollback_required."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff hoặc summary diff nếu có"},
                    "task": {"type": "string", "description": "Task/user request hiện tại"},
                    "context": {"type": "string", "description": "Release/deploy context bổ sung"},
                    "staged": {"type": "boolean", "description": "True → dùng git diff --cached cho panel_review"},
                    "since_commit": {"type": "string", "description": "Base ref/SHA cho breaking change detector và review diff"},
                    "mode": {"type": "string", "enum": ["safe", "max"], "description": "safe=nhẹ/offline hơn; max=full pre-prod gate"},
                },
            },
        ),
        types.Tool(
            name="release_orchestrator",
            description="Release coordinator: checks git/changelog/SBOM evidence and returns ready/manual_steps/blocked before release.",
            inputSchema={"type": "object", "properties": {
                "changed_files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="provenance_checker",
            description="Static build provenance checker: commit, remote, dependency evidence, artifact hashes, suspicious build scripts.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="auth_matrix_auditor",
            description="Build endpoint/auth matrix and flag missing auth or object-level ownership checks.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "context": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="harness_trace_viewer",
            description="View recent harness traces/logs from FinOps DB and .harness logs with secret redaction.",
            inputSchema={"type": "object", "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                "include_logs": {"type": "boolean"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="incremental_refactor_guard",
            description="Detect public symbol removals/signature changes and syntax errors in refactor diffs.",
            inputSchema={"type": "object", "properties": {
                "files": _FILES_SCHEMA,
                "diff": {"type": "string"},
                "since_commit": {"type": "string"},
                "mode": {"type": "string", "enum": ["safe", "max"]},
            }},
        ),
        types.Tool(
            name="goal_autopilot",
            description=(
                "Prompt-only goal autopilot: init/check/complete/block/status. "
                "Stores one active goal and auto_trigger checks alignment after edits."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["init", "check", "complete", "block", "status"], "description": "Operation mode"},
                    "goal": {"type": "string", "description": "User goal; required for init"},
                    "context": {"type": "string", "description": "Progress note or extra context"},
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff or summary diff if available"},
                    "task": {"type": "string", "description": "Current task/user request"},
                },
                "required": ["mode"],
            },
        ),
        types.Tool(
            name="goal_supervisor",
            description=(
                "Goal supervisor: reads active goal state/checks and returns one hard next_action enum: "
                "continue_part, run_check, run_final, blocked_ask_user, complete. Call after each edit/check batch."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "changed_files": _FILES_SCHEMA,
                    "diff": {"type": "string", "description": "Unified diff or summary diff if available"},
                    "context": {"type": "string", "description": "Progress note, user question, or completion summary"},
                    "last_checks": {"description": "Optional last auto_trigger/panel/check result object/list/string"},
                },
            },
        ),
        types.Tool(
            name="goal_runner",
            description=(
                "Direct prompt runner: initializes goal_autopilot from one prompt, delegates to an agent CLI, "
                "runs auto_trigger/goal_supervisor loop, then finalizes through prod_readiness_gate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Prompt/goal to run directly through the harness"},
                    "max_iterations": {"type": "integer", "minimum": 1, "maximum": 30},
                    "mode": {"type": "string", "enum": ["safe", "max"]},
                    "agent_command": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": {"type": "string"}},
                        ],
                        "description": "Optional command template or argv array; use {prompt} placeholder or prompt is appended",
                    },
                    "agent_timeout": {"type": "number", "minimum": 5, "maximum": 7200},
                    "dry_run": {"type": "boolean", "description": "True initializes/supervises but does not call an agent command"},
                    "final_prod_gate": {"type": "boolean", "description": "Run prod_readiness_gate before completing the goal"},
                },
                "required": ["prompt"],
            },
        ),
        types.Tool(
            name="panel_review",
            description=(
                "3 model parallel (reviewer/security/tester adversarial) → findings JSON file/line/severity/fix. "
                "Mỗi finding có `triage`: `auto_fix` (áp ngay) hoặc `ask_user` (cần developer quyết). "
                "`warnings[]` chứa anti-consensus alert khi panel đồng thuận bất thường. "
                "Dùng SAU KHI code xong. Cung cấp ít nhất một trong: files, diff, code, staged, since_commit."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "files":        _FILES_SCHEMA,
                    "diff":         {"type": "string", "description": "Unified diff của thay đổi cần review"},
                    "code":         {"type": "string", "description": "Code snippet inline cần review"},
                    "focus":        {"type": "string", "description": "Trọng tâm review (vd: 'concurrency', 'auth flow')"},
                    "staged":       {"type": "boolean", "description": "True → tự lấy git diff --cached (staged changes). Không cần truyền files."},
                    "since_commit": {"type": "string",  "description": "SHA hoặc ref (vd: 'HEAD~3', 'main') → diff từ commit đó đến HEAD. Không cần truyền files."},
                },
            },
        ),
        types.Tool(
            name="consult",
            description="Hỏi Grok (deep reasoning) trước khi implement: approach, trade-offs, edge cases. Kể cả quyết định nhỏ 'A hay B'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Câu hỏi design cụ thể"},
                    "files":    _FILES_SCHEMA,
                    "context":  {"type": "string", "description": "Context bổ sung (constraints, requirements...)"},
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="alt_implementation",
            description="2 model song song (Kimi K2 + GPT) sinh 2 approach khác nhau để so sánh. Dùng cho function/module độc lập.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec":    {"type": "string", "description": "Spec của thứ cần implement"},
                    "files":   _FILES_SCHEMA,
                    "context": {"type": "string", "description": "Context bổ sung"},
                },
                "required": ["spec"],
            },
        ),
        types.Tool(
            name="suggest_fix",
            description="code + error → root cause + unified diff patch. Dùng khi debug bí sau 1-2 lần thử.",
            inputSchema={
                "type": "object",
                "properties": {
                    "error":   {"type": "string", "description": "Error message / stack trace / mô tả bug"},
                    "files":   _FILES_SCHEMA,
                    "code":    {"type": "string", "description": "Code bị lỗi (inline)"},
                    "context": {"type": "string", "description": "Context bổ sung (đã thử gì, repro steps...)"},
                },
                "required": ["error"],
            },
        ),
        types.Tool(
            name="ask_codebase",
            description="Q&A codebase lớn: đọc rộng, relevance-prune trước Azure, fallback local có file:line nếu model timeout/empty. Gọi TRƯỚC khi Read nếu task >1 file.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Câu hỏi về codebase"},
                    "files":    {**_FILES_SCHEMA, "description": _FILES_SCHEMA["description"] + " — nạp nhiều file thoải mái"},
                    "index_md": {"type": "string", "description": "Nội dung index.md làm navigation"},
                },
                "required": ["question"],
            },
        ),
        types.Tool(
            name="quick_task",
            description="Model mini cho việc vặt: boilerplate, fixtures, mock data, docstring, commit message, cập nhật index.md/decisions.md, tóm tắt diff, giải thích code. Không dùng cho logic phức tạp.",
            inputSchema={
                "type": "object",
                "properties": {
                    "instruction": {"type": "string", "description": "Việc cần làm"},
                    "task": {"type": "string", "description": "Alias tương thích cho instruction"},
                    "context":     {"type": "string", "description": "Input/context nếu cần"},
                },
            },
        ),
        types.Tool(
            name="run_single_agent",
            description="Escape hatch: gọi thẳng 1 trong 12 agent. Roles: " + ", ".join(STR_TO_ROLE.keys()) + ".",
            inputSchema={
                "type": "object",
                "properties": {
                    "role":    {"type": "string", "enum": list(STR_TO_ROLE.keys())},
                    "task":    {"type": "string", "description": "Task cần làm"},
                    "context": {"type": "string", "description": "Context bổ sung"},
                },
                "required": ["role", "task"],
            },
        ),
        types.Tool(
            name="list_agents",
            description="Xem 12 agents: model deployment, tool tương ứng, specialty.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="wiki_ingest",
            description="Ingest llmwiki/raw/ → trích xuất concepts/entities vào wiki. Chạy sau khi thêm file vào raw/.",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["local", "global"], "description": "local=project wiki (default), global=~/.claude/llmwiki/"},
                },
            },
        ),
        types.Tool(
            name="wiki_query",
            description="Tìm kiếm wiki concepts/entities theo từ khóa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Từ khóa tìm kiếm"},
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="wiki_lint",
            description="Kiểm tra wiki: link hỏng, trang trống, raw chưa ingest.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="security_autofix",
            description="Auto-fix Critical/High security findings: panel_review → suggest_fix → worktree test → apply patch → wiki lesson.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": _FILES_SCHEMA,
                },
                "required": ["files"],
            },
        ),
        types.Tool(
            name="auto_tester",
            description="Sinh pytest từ files + panel_review findings. Chạy trong worktree cô lập.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": _FILES_SCHEMA,
                    "findings": {"type": "array", "items": {"type": "object"}, "description": "Findings từ panel_review"}
                },
                "required": ["files", "findings"]
            }
        ),
        types.Tool(
            name="visual_reviewer",
            description="Screenshot URL + Vision LLM audit giao diện. So sánh với baseline nếu có.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL cần kiểm tra"},
                    "baseline_url": {"type": "string", "description": "URL baseline (tùy chọn)"}
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="benchmarker",
            description="So sánh 2 đoạn Python: thời gian + bộ nhớ.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code_a": {"type": "string", "description": "Code thứ nhất"},
                    "code_b": {"type": "string", "description": "Code thứ hai"},
                    "iterations": {"type": "integer", "description": "Số lần chạy (mặc định 5)"}
                },
                "required": ["code_a", "code_b"]
            }
        ),
        types.Tool(
            name="dependency_upgrader",
            description="Quét package lỗi thời trong requirements.txt. dry_run=True chỉ báo cáo, không sửa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "description": "Chỉ quét, không sửa (mặc định True)"}
                }
            }
        ),
        types.Tool(
            name="schema_drift",
            description="So sánh Pydantic models với baseline → phát hiện drift.",
            inputSchema={
                "type": "object",
                "properties": {
                    "baseline_schema": {"type": "string", "description": "Schema baseline JSON (tùy chọn)"}
                }
            }
        ),
        types.Tool(
            name="doc_sync",
            description="Đồng bộ README.md theo public functions mới.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="telemetry_debugger",
            description="stack trace → định vị file + đề xuất patch.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_content": {"type": "string", "description": "Log lỗi hoặc stack trace"}
                },
                "required": ["log_content"]
            }
        ),
        types.Tool(
            name="run_in_sandbox",
            description="Chạy Python code trong sandbox cô lập, giới hạn tài nguyên.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code cần chạy"},
                    "timeout": {"type": "number", "description": "Timeout giây (mặc định 5.0)"}
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="semantic_search",
            description="Tìm file/hàm/class trong codebase — polyglot 158 ngôn ngữ, FTS5+tree-sitter. Index tự build.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Từ khóa tìm kiếm"},
                    "top_k": {"type": "integer", "description": "Số kết quả (mặc định 5)"}
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="swarm_debug",
            description="Multi-Agent Swarm (Architect→Tester→Coder→Reviewer) chẩn đoán và vá lỗi tự động.",
            inputSchema={
                "type": "object",
                "properties": {
                    "error_log": {"type": "string", "description": "Stack trace hoặc log lỗi"},
                    "files": _FILES_SCHEMA
                },
                "required": ["error_log"]
            }
        ),
        types.Tool(
            name="finops_stats",
            description="Thống kê FinOps: chi phí USD, tokens, latency, cache hit rate theo agent/run.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="devops_pipeline",
            description="Quality gate: ruff/flake8 + mypy + black (fallback AST).",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="config_security_audit",
            description="Quét secrets rò rỉ, .env drift, CORS unsafe.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="pr_generator",
            description="Sinh PR title + description từ git diff.",
            inputSchema={
                "type": "object",
                "properties": {
                    "diff": {"type": "string", "description": "Git diff (tùy chọn)"},
                    "branch": {"type": "string", "description": "Branch để diff (tùy chọn)"}
                }
            }
        ),
        types.Tool(
            name="license_scanner",
            description="Phát hiện licenses trong codebase, cảnh báo tương thích.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="sbom_generator",
            description="Sinh SBOM (SPDX JSON) từ dependencies. Dùng trước deploy production.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="a11y_auditor",
            description="Kiểm tra lỗi accessibility WCAG trong HTML/CSS/JSX.",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA}
            }
        ),
        types.Tool(
            name="i18n_auditor",
            description="Tìm hardcoded strings cần i18n trong UI code.",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA}
            }
        ),
        types.Tool(
            name="polyglot_reviewer",
            description="Code review chuyên sâu theo ngôn ngữ đặc thù (polyglot).",
            inputSchema={
                "type": "object",
                "properties": {"files": _FILES_SCHEMA},
                "required": ["files"]
            }
        ),
        types.Tool(
            name="git_archaeologist",
            description="git blame nâng cao: tìm commit cuối thay đổi file/dòng cụ thể.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File cần khảo cổ"},
                    "line_no": {"type": "integer", "description": "Dòng cần blame (tùy chọn)"}
                },
                "required": ["file_path"]
            }
        ),
        types.Tool(
            name="feature_flag_auditor",
            description="Phát hiện feature flags không dùng hoặc quá hạn trong codebase.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="dead_code_scanner",
            description="Phát hiện hàm/class không được gọi — polyglot 158 ngôn ngữ, tree-sitter.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="index_codebase",
            description="Build/rebuild codebase index (FTS5+tree-sitter, 158 ngôn ngữ). force=True rebuild hoàn toàn. Tự chạy khi semantic_search/dead_code_scanner/ask_codebase gọi lần đầu.",
            inputSchema={
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "Rebuild hoàn toàn (mặc định False)"}
                }
            }
        ),
        types.Tool(
            name="profiler",
            description="cProfile + tracemalloc cho Python code. Tìm bottleneck CPU và memory.",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code cần profile"},
                    "iterations": {"type": "integer", "description": "Số vòng lặp (mặc định 1)"}
                },
                "required": ["code"]
            }
        ),
        types.Tool(
            name="coverage_analyzer",
            description="pytest + coverage.py → báo cáo test coverage.",
            inputSchema={"type": "object", "properties": {}}
        ),
        types.Tool(
            name="incident_responder",
            description="log/crash dump → phân loại incident + mitigation ngay + fix lâu dài.",
            inputSchema={
                "type": "object",
                "properties": {
                    "log_content": {"type": "string", "description": "Log hoặc crash dump"}
                },
                "required": ["log_content"]
            }
        ),
        types.Tool(
            name="api_contract_tester",
            description="Sinh pytest kiểm tra API contract (status code, JSON schema).",
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoints": {"type": "array", "items": {"type": "object"}, "description": "Danh sách endpoint {path, method}"}
                },
                "required": ["endpoints"]
            }
        ),
        types.Tool(
            name="chaos_tester",
            description="Fault injection (CPU/memory stress) trong khi monitor ứng dụng.",
            inputSchema={
                "type": "object",
                "properties": {
                    "app_run_command": {"type": "string", "description": "Lệnh chạy app"},
                    "duration": {"type": "integer", "description": "Thời gian inject (mặc định 5s)"}
                },
                "required": ["app_run_command"]
            }
        ),
        types.Tool(
            name="secret_scanner",
            description="Tìm hardcoded secrets bằng regex + Shannon entropy (API key, token, private key).",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths cần quét (mặc định toàn workspace)"}
                }
            }
        ),
        types.Tool(
            name="changelog_generator",
            description="Sinh changelog từ git log, nhóm theo conventional commit type.",
            inputSchema={
                "type": "object",
                "properties": {
                    "since": {"type": "string", "description": "Từ commit nào (mặc định HEAD~10)"},
                    "until": {"type": "string", "description": "Đến commit nào (mặc định HEAD)"},
                    "format": {"type": "string", "description": "'markdown' hoặc 'text' (mặc định markdown)"}
                }
            }
        ),
        types.Tool(
            name="env_parity_checker",
            description="So sánh keys .env vs .env.example — phát hiện thiếu/thừa.",
            inputSchema={
                "type": "object",
                "properties": {
                    "example_file": {"type": "string", "description": "Template (mặc định .env.example)"},
                    "env_file": {"type": "string", "description": "Env thực tế (mặc định .env)"}
                }
            }
        ),
        types.Tool(
            name="load_tester",
            description="HTTP load test concurrent → p50/p95/p99 latency, error rate, RPS.",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL cần test"},
                    "requests_count": {"type": "integer", "description": "Tổng requests (mặc định 100)"},
                    "concurrency": {"type": "integer", "description": "Requests song song (mặc định 10)"},
                    "method": {"type": "string", "description": "HTTP method (mặc định GET)"}
                },
                "required": ["url"]
            }
        ),
        types.Tool(
            name="complexity_analyzer",
            description="Cyclomatic complexity từng function Python (AST). Flag hotspot > threshold.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Paths cần phân tích (mặc định toàn workspace)"},
                    "threshold": {"type": "integer", "description": "Ngưỡng flag (mặc định 10)"}
                }
            }
        ),
        types.Tool(
            name="migration_validator",
            description="Validate SQL/Alembic migration: LOCK_RISK, NON_REVERSIBLE, MISSING_INDEX, DATA_LOSS.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Migration files (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="sql_query_analyzer",
            description="Phát hiện N+1 query, thiếu index, raw SQL không parameterized (SQLAlchemy, Django ORM).",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Files cần phân tích (mặc định toàn .py)"}
                }
            }
        ),
        types.Tool(
            name="openapi_spec_sync",
            description="So sánh OpenAPI spec với route handlers + Pydantic models → UNDOCUMENTED_ENDPOINT, SCHEMA_MISMATCH.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_path": {"type": "string", "description": "OpenAPI spec path (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="breaking_change_detector",
            description="Phát hiện breaking API changes HEAD vs main: renamed param, removed field, status code change. Dùng trước PR.",
            inputSchema={
                "type": "object",
                "properties": {
                    "base_ref": {"type": "string", "description": "Base ref để diff (mặc định tự tìm main/master)"}
                }
            }
        ),
        types.Tool(
            name="flaky_test_detector",
            description="Chạy test N lần, phát hiện flaky tests (pass/fail không nhất quán).",
            inputSchema={
                "type": "object",
                "properties": {
                    "runs": {"type": "integer", "description": "Số lần chạy 2-5 (mặc định 3)"},
                    "test_path": {"type": "string", "description": "Test file/folder (mặc định toàn bộ)"}
                }
            }
        ),
        types.Tool(
            name="duplicate_code_scanner",
            description="Tìm copy-paste code bằng AST normalization — function tương đồng >80% nên extract.",
            inputSchema={
                "type": "object",
                "properties": {
                    "min_lines": {"type": "integer", "description": "Dòng tối thiểu để scan (mặc định 6)"},
                    "threshold": {"type": "number", "description": "Ngưỡng tương đồng 0-1 (mặc định 0.8)"}
                }
            }
        ),
        types.Tool(
            name="container_linter",
            description="Lint Dockerfile/docker-compose: root process, hardcoded secret, unpinned image, missing HEALTHCHECK.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "Dockerfile/compose paths (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="dependency_graph_visualizer",
            description="Python import graph: circular imports, God modules (fan-in ≥10), high coupling.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": ".py files (mặc định toàn workspace)"}
                }
            }
        ),
        types.Tool(
            name="ci_pipeline_validator",
            description="Validate GitHub Actions/GitLab CI: hardcoded secret, injection, no timeout, deprecated actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "CI YAML paths (mặc định tự tìm .github/workflows/)"}
                }
            }
        ),
        types.Tool(
            name="mutation_tester",
            description="Inject mutations (flip bool, đổi operator) → chạy tests → mutation score. Score thấp = test yếu.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Source files cần mutate (mặc định tự tìm non-test .py)"},
                    "max_mutations": {"type": "integer", "description": "Số mutations tối đa (mặc định 20)"}
                }
            }
        ),
        types.Tool(
            name="data_flow_taint_analyzer",
            description="Track user input → dangerous sinks (SQL, subprocess, template) → SQL/COMMAND/TEMPLATE_INJECTION, PATH_TRAVERSAL.",
            inputSchema={
                "type": "object",
                "properties": {
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Files cần phân tích (mặc định tự tìm)"}
                }
            }
        ),
        types.Tool(
            name="performance_regression_detector",
            description="git diff HEAD vs main → phát hiện O(n)→O(n²), unbounded memory, sync IO trong async path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "functions": {"type": "array", "items": {"type": "string"}, "description": "Functions cần kiểm tra (mặc định tự detect từ diff)"},
                    "threshold_pct": {"type": "number", "description": "Ngưỡng regression % (mặc định 20)"}
                }
            }
        ),
    ]


def _json_response(data: dict) -> list[types.TextContent]:
    return [types.TextContent(
        type="text", text=json.dumps(data, ensure_ascii=False, indent=2),
    )]


def _parse_bool_arg(args: dict, name: str, default: bool = False) -> tuple[bool, str | None]:
    value = args.get(name, default)
    if isinstance(value, bool):
        return value, None
    if value is None:
        return default, None
    if isinstance(value, int) and value in (0, 1):
        return bool(value), None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True, None
        if normalized in {"false", "0", "no", "off"}:
            return False, None
    return default, f"Argument '{name}' must be boolean, got {value!r}"


def _nonempty_str_list(value) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


_wiki_ingest_targets: set[str] = set()
_wiki_ingest_lock = threading.Lock()
_lazy_settings_lock = threading.Lock()
_auto_watch_roots: set[str] = set()
_auto_watch_lock = threading.Lock()


def _ensure_lazy_settings_merge() -> None:
    global _LAZY_SETTINGS_MERGE_DONE
    if _LAZY_SETTINGS_MERGE_DONE:
        return
    with _lazy_settings_lock:
        if _LAZY_SETTINGS_MERGE_DONE:
            return
        try:
            import merge_settings
            if merge_settings.lazy_merge_if_needed():
                _log.info("Auto-merged Agent Harness rules version %s", merge_settings.RULES_VERSION)
        except Exception as e:
            _log.warning("Auto-merge settings skipped (non-fatal): %s", e)
        finally:
            _LAZY_SETTINGS_MERGE_DONE = True


def _active_workspace() -> str:
    workspace = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not workspace:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                workspace = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                workspace = None
    workspace = workspace or (os.getenv("WORKSPACE_ROOT") or "").strip()
    return os.path.abspath(workspace or WORKSPACE_ROOT)


def _auto_watch_enabled() -> bool:
    return os.getenv("HARNESS_AUTO_WATCH", "1").strip().lower() not in {"0", "false", "no", "off"}


def _project_watcher_alive(root: str) -> bool:
    pid_file = os.path.join(root, ".harness_auto_watch.pid")
    try:
        with open(pid_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        pid = int(data.get("pid", 0))
        script = str(data.get("script", ""))
        if script and Path(script).name != "auto_watch.py":
            return False
        if pid <= 0:
            return False
        if os.name == "nt":
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                if not ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                    return False
                return code.value == 259
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
    except Exception:
        return False


def _watcher_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":
        pythonw = exe.with_name("pythonw.exe")
        if pythonw.exists():
            return str(pythonw)
    return str(exe)


def _claim_startup_lock(root: str) -> int | None:
    lock_path = os.path.join(root, ".harness_auto_watch.start.lock")
    try:
        if os.path.exists(lock_path) and time.time() - os.path.getmtime(lock_path) > 15:
            os.unlink(lock_path)
    except OSError:
        pass
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags)
    except OSError:
        return None
    os.write(fd, json.dumps({"pid": os.getpid(), "ts": time.time()}).encode("utf-8"))
    return fd


def _release_startup_lock(root: str, fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(os.path.join(root, ".harness_auto_watch.start.lock"))
    except OSError:
        pass


def _rotate_bootstrap_log(log_path: Path) -> None:
    try:
        if log_path.exists() and log_path.stat().st_size > 1_000_000:
            rotated = log_path.with_suffix(log_path.suffix + ".1")
            try:
                rotated.unlink()
            except OSError:
                pass
            log_path.replace(rotated)
    except OSError:
        pass


def _kick_project_auto_watch() -> None:
    if not _auto_watch_enabled():
        return
    root = _active_workspace()
    if not os.path.isdir(root):
        return
    with _auto_watch_lock:
        if root in _auto_watch_roots and _project_watcher_alive(root):
            return
        _auto_watch_roots.discard(root)
        startup_fd = _claim_startup_lock(root)
        if startup_fd is None:
            return

        env = os.environ.copy()
        env["HARNESS_WATCH_ROOT"] = root
        script = Path(__file__).with_name("auto_watch.py")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        log_path = Path(root) / ".harness_auto_watch.bootstrap.log"
        try:
            _rotate_bootstrap_log(log_path)
            with open(log_path, "ab") as log:
                subprocess.Popen(
                    [_watcher_python(), str(script)],
                    cwd=str(Path(__file__).resolve().parent),
                    env=env,
                    stdout=log,
                    stderr=log,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags,
                    close_fds=True,
                )
            _auto_watch_roots.add(root)
            _log.info("Started Auto-Watch for %s", root)
        except Exception as e:
            _log.debug("Auto-Watch start skipped for %s: %s", root, e)
        finally:
            _release_startup_lock(root, startup_fd)


def _kick_auto_wiki_ingest() -> None:
    try:
        import llmwiki_tool
        targets = llmwiki_tool.wiki_pending_targets()
    except Exception as e:
        _log.debug("wiki pending check failed: %s", e)
        return

    workspace = _active_workspace()
    for target in targets:
        target_key = f"{target}:{workspace if target == 'local' else 'global'}"
        with _wiki_ingest_lock:
            if target_key in _wiki_ingest_targets:
                continue
            _wiki_ingest_targets.add(target_key)

        async def _run(target_name: str = target, key: str = target_key) -> None:
            try:
                await llmwiki_tool.wiki_ingest(target=target_name)
                _log.info("Auto-ingested %s llmwiki raw docs", target_name)
            except Exception as e:
                _log.warning("Auto wiki ingest failed for %s: %s", target_name, e)
            finally:
                with _wiki_ingest_lock:
                    _wiki_ingest_targets.discard(key)

        task = asyncio.create_task(_run(), name=f"wiki-ingest-{target}")
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    import uuid
    import time
    from agents import current_run_id, log_run_to_db

    run_id = f"mcp-{uuid.uuid4().hex[:8]}"
    run_token = current_run_id.set(run_id)
    start_time = time.perf_counter()
    _ensure_lazy_settings_merge()
    _kick_project_auto_watch()
    _kick_auto_wiki_ingest()

    async def _run():
        async with _TOOL_SEM:
            return await _execute_tool(name, arguments)

    task = asyncio.create_task(_run(), name=f"tool-{run_id}")
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    try:
        res = await asyncio.shield(task)
        return res
    except asyncio.CancelledError:
        # Yield once then check — catches tasks that finished microseconds before cancel
        await asyncio.sleep(0)
        if task.done() and not task.cancelled():
            exc = task.exception()
            if exc is None:
                return task.result()
        # Try brief harvest window for near-complete tasks
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        _log.info("tool %s cancelled by client, running in background", name)
        return _json_response({"error": "cancelled", "detail": "Cancelled by client; tool running in background"})
    finally:
        current_run_id.reset(run_token)
        if name not in ("list_agents", "finops_stats"):
            def _log_task(t: asyncio.Task, _rid=run_id, _n=name, _s=start_time) -> None:
                suffix = "_cancelled" if t.cancelled() else ("_error" if t.exception() else "")
                log_run_to_db(_rid, f"mcp_{_n}{suffix}", int((time.perf_counter() - _s) * 1000))

            if task.done():
                _log_task(task)
            else:
                task.add_done_callback(_log_task)


async def _execute_tool(name: str, arguments: dict) -> list[types.TextContent]:
    # Gemini IDE gửi "agent-harness/panel_review", Claude Code gửi "panel_review"
    if "/" in name:
        name = name.split("/", 1)[-1]

    if arguments is None:
        args = {}
    elif not isinstance(arguments, dict):
        return _json_response({"error": "invalid_arguments_type", "detail": f"arguments must be object, got {type(arguments).__name__}"})
    else:
        args = arguments

    try:
        if name == "auto_trigger":
            stage = str(args.get("stage", "post_edit")).strip().lower()
            if stage not in {"post_edit", "final", "pre_complete"}:
                return _json_response({"error": "invalid_argument", "detail": "stage must be one of: post_edit, final, pre_complete"})
            mode = args.get("mode")
            mode = str(mode).strip().lower() if mode is not None else None
            if mode is not None and mode not in {"max", "safe"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: max, safe"})
            return _json_response(await st.auto_trigger(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
                stage=stage,
                mode=mode,
            ))

        if name == "prod_readiness_gate":
            staged, staged_error = _parse_bool_arg(args, "staged")
            if staged_error:
                return _json_response({"error": "invalid_argument", "detail": staged_error})
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            since_commit = args.get("since_commit", "")
            since_commit = "" if since_commit is None else str(since_commit).strip()
            return _json_response(await st.prod_readiness_gate(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
                context=args.get("context"),
                staged=staged,
                since_commit=since_commit,
                mode=mode,
            ))

        if name == "goal_autopilot":
            mode = str(args.get("mode", "")).strip().lower()
            if mode not in {"init", "check", "complete", "block", "status"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: init, check, complete, block, status"})
            return _json_response(await st.goal_autopilot(
                mode=mode,
                goal=args.get("goal"),
                context=args.get("context"),
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                task=args.get("task"),
            ))

        if name == "release_orchestrator":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.release_orchestrator(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "provenance_checker":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.provenance_checker(
                files=args.get("files"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "auth_matrix_auditor":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.auth_matrix_auditor(
                files=args.get("files"),
                diff=args.get("diff"),
                context=args.get("context"),
                mode=mode,
            ))

        if name == "harness_trace_viewer":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            limit = args.get("limit", 20)
            try:
                limit = max(1, min(200, int(limit)))
            except (TypeError, ValueError):
                return _json_response({"error": "invalid_argument", "detail": "limit must be an integer"})
            include_logs, include_logs_error = _parse_bool_arg(args, "include_logs")
            if include_logs_error:
                return _json_response({"error": "invalid_argument", "detail": include_logs_error})
            return _json_response(await st.harness_trace_viewer(limit=limit, include_logs=include_logs, mode=mode))

        if name == "incremental_refactor_guard":
            mode = str(args.get("mode", "safe")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            return _json_response(await st.incremental_refactor_guard(
                files=args.get("files"),
                diff=args.get("diff"),
                since_commit=args.get("since_commit", ""),
                mode=mode,
            ))

        if name == "goal_supervisor":
            return _json_response(await st.goal_supervisor(
                changed_files=args.get("changed_files"),
                diff=args.get("diff"),
                context=args.get("context"),
                last_checks=args.get("last_checks"),
            ))

        if name == "goal_runner":
            mode = str(args.get("mode", "max")).strip().lower()
            if mode not in {"safe", "max"}:
                return _json_response({"error": "invalid_argument", "detail": "mode must be one of: safe, max"})
            agent_command = args.get("agent_command")
            if agent_command is not None and not (
                isinstance(agent_command, str)
                or (isinstance(agent_command, list) and all(isinstance(item, str) and item.strip() for item in agent_command))
            ):
                return _json_response({"error": "invalid_argument", "detail": "agent_command must be a string or list of strings"})
            dry_run, dry_run_error = _parse_bool_arg(args, "dry_run")
            if dry_run_error:
                return _json_response({"error": "invalid_argument", "detail": dry_run_error})
            final_prod_gate, final_prod_gate_error = _parse_bool_arg(args, "final_prod_gate", True)
            if final_prod_gate_error:
                return _json_response({"error": "invalid_argument", "detail": final_prod_gate_error})
            return _json_response(await st.goal_runner(
                prompt=args.get("prompt", ""),
                max_iterations=args.get("max_iterations", 8),
                mode=mode,
                agent_command=agent_command,
                agent_timeout=args.get("agent_timeout", 900.0),
                dry_run=dry_run,
                final_prod_gate=final_prod_gate,
            ))

        if name == "panel_review":
            staged, staged_error = _parse_bool_arg(args, "staged")
            if staged_error:
                return _json_response({"error": "invalid_argument", "detail": staged_error})
            return _json_response(await st.panel_review(
                files=args.get("files"), diff=args.get("diff"),
                code=args.get("code"), focus=args.get("focus"),
                staged=staged,
                since_commit=args.get("since_commit", ""),
            ))

        if name == "consult":
            return _json_response(await st.consult(
                question=args["question"],
                files=args.get("files"), context=args.get("context"),
            ))

        if name == "alt_implementation":
            return _json_response(await st.alt_implementation(
                spec=args["spec"],
                files=args.get("files"), context=args.get("context"),
            ))

        if name == "suggest_fix":
            return _json_response(await st.suggest_fix(
                error=args["error"], files=args.get("files"),
                code=args.get("code"), context=args.get("context"),
            ))

        if name == "ask_codebase":
            return _json_response(await st.ask_codebase(
                question=args["question"], 
                files=args.get("files"),
                index_md=args.get("index_md"),
            ))

        if name == "quick_task":
            instruction = args.get("instruction") or args.get("task")
            if not isinstance(instruction, str) or not instruction.strip():
                return _json_response({"error": "invalid_argument", "detail": "quick_task requires instruction or task"})
            return _json_response(await st.quick_task(
                instruction=instruction, context=args.get("context"),
            ))

        if name == "run_single_agent":
            role_str = args.get("role", "")
            if role_str not in STR_TO_ROLE:
                return _json_response({"error": f"Invalid role: {role_str}. Lựa chọn hợp lệ: {list(STR_TO_ROLE.keys())}"})
            role = STR_TO_ROLE[role_str]
            client = get_azure_client()
            result = await Agent(role, client).run_async(
                args.get("task", ""), args.get("context", ""),
            )
            return _json_response({
                "agent_id": result.agent_id, "role": result.agent_role.value,
                "model": result.model_used, "status": result.status,
                "duration_ms": result.duration_ms,
                "result": result.result, "error": result.error,
            })

        if name == "list_agents":
            return _json_response({
                "toolbox": "12-Agent Support Team cho Claude Code",
                "workspace_root": _active_workspace(),
                "agents": [
                    {**a, "model": _MODEL_BY_ROLE[a["role"]]} for a in AGENT_INFO
                ],
            })

        if name == "wiki_ingest":
            import llmwiki_tool
            return _json_response(await llmwiki_tool.wiki_ingest(target=args.get("target", "local")))

        if name == "wiki_query":
            import llmwiki_tool
            return _json_response(llmwiki_tool.wiki_query(args["query"]))

        if name == "wiki_lint":
            import llmwiki_tool
            return _json_response(llmwiki_tool.wiki_lint())

        if name == "security_autofix":
            files = args.get("files")
            if not files:
                return _json_response({"error": "Thiếu argument bắt buộc: files"})
            return _json_response(await st.security_autofix(files=files))

        if name == "auto_tester":
            files = args.get("files")
            findings = args.get("findings")
            if not files or not isinstance(findings, list) or not findings or not all(isinstance(f, dict) for f in findings):
                return _json_response({"error": "Thiếu argument bắt buộc: files và findings"})
            return _json_response(await st.auto_tester(files=files, findings=findings))

        if name == "visual_reviewer":
            url = args.get("url")
            if not url:
                return _json_response({"error": "Thiếu argument bắt buộc: url"})
            return _json_response(await st.visual_reviewer(url=url, baseline_url=args.get("baseline_url")))

        if name == "benchmarker":
            code_a = args.get("code_a")
            code_b = args.get("code_b")
            if not code_a or not code_b:
                return _json_response({"error": "Thiếu argument bắt buộc: code_a và code_b"})
            return _json_response(await st.benchmarker(code_a=code_a, code_b=code_b, iterations=args.get("iterations", 5)))

        if name == "dependency_upgrader":
            return _json_response(await st.dependency_upgrader(dry_run=args.get("dry_run", True)))

        if name == "schema_drift":
            return _json_response(await st.schema_drift(baseline_schema=args.get("baseline_schema")))

        if name == "doc_sync":
            return _json_response(await st.doc_sync())

        if name == "telemetry_debugger":
            log_content = args.get("log_content")
            if not log_content:
                return _json_response({"error": "Thiếu argument bắt buộc: log_content"})
            return _json_response(await st.telemetry_debugger(log_content=log_content))

        if name == "run_in_sandbox":
            code = args.get("code")
            if not code:
                return _json_response({"error": "Thiếu argument bắt buộc: code"})
            return _json_response(st.run_in_sandbox(code=code, timeout=args.get("timeout", 5.0)))

        if name == "semantic_search":
            query = args.get("query")
            if not query:
                return _json_response({"error": "Thiếu argument bắt buộc: query"})
            return _json_response(await st.semantic_search(query=query, top_k=args.get("top_k", 5)))

        if name == "swarm_debug":
            error_log = args.get("error_log")
            if not error_log:
                return _json_response({"error": "Thiếu argument bắt buộc: error_log"})
            return _json_response(await st.swarm_debug(error_log=error_log, files=args.get("files")))

        if name == "finops_stats":
            return _json_response(get_finops_stats())

        if name == "devops_pipeline":
            return _json_response(await st.devops_pipeline())

        if name == "config_security_audit":
            return _json_response(await st.config_security_audit())

        if name == "pr_generator":
            return _json_response(await st.pr_generator(diff=args.get("diff"), branch=args.get("branch")))

        if name == "license_scanner":
            return _json_response(await st.license_scanner())

        if name == "sbom_generator":
            return _json_response(await st.sbom_generator())

        if name == "a11y_auditor":
            return _json_response(await st.a11y_auditor(files=args.get("files")))

        if name == "i18n_auditor":
            return _json_response(await st.i18n_auditor(files=args.get("files")))

        if name == "polyglot_reviewer":
            files = args.get("files")
            if not _nonempty_str_list(files):
                return _json_response({"error": "Thiếu hoặc sai kiểu argument: files phải là mảng string không rỗng"})
            return _json_response(await st.polyglot_reviewer(files=files))

        if name == "git_archaeologist":
            file_path = args.get("file_path")
            if not file_path:
                return _json_response({"error": "Thiếu argument bắt buộc: file_path"})
            return _json_response(await st.git_archaeologist(file_path=file_path, line_no=args.get("line_no")))

        if name == "feature_flag_auditor":
            return _json_response(await st.feature_flag_auditor())

        if name == "dead_code_scanner":
            return _json_response(await st.dead_code_scanner())

        if name == "index_codebase":
            return _json_response(await st.index_codebase(force=args.get("force", False)))

        if name == "profiler":
            code = args.get("code")
            if not code:
                return _json_response({"error": "Thiếu argument bắt buộc: code"})
            return _json_response(st.profiler(code=code, iterations=args.get("iterations", 1)))

        if name == "coverage_analyzer":
            return _json_response(await st.coverage_analyzer())

        if name == "incident_responder":
            log_content = args.get("log_content")
            if not log_content:
                return _json_response({"error": "Thiếu argument bắt buộc: log_content"})
            return _json_response(await st.incident_responder(log_content=log_content))

        if name == "api_contract_tester":
            endpoints = args.get("endpoints")
            if not isinstance(endpoints, list) or not endpoints or not all(isinstance(e, dict) for e in endpoints):
                return _json_response({"error": "Thiếu hoặc sai kiểu argument: endpoints phải là mảng object không rỗng"})
            return _json_response(await st.api_contract_tester(endpoints=endpoints))

        if name == "chaos_tester":
            app_run_command = args.get("app_run_command")
            if not app_run_command:
                return _json_response({"error": "Thiếu argument bắt buộc: app_run_command"})
            return _json_response(st.chaos_tester(app_run_command=app_run_command, duration=args.get("duration", 5)))

        if name == "secret_scanner":
            return _json_response(await st.secret_scanner(paths=args.get("paths")))

        if name == "changelog_generator":
            return _json_response(await st.changelog_generator(
                since=args.get("since", "HEAD~10"),
                until=args.get("until", "HEAD"),
                format=args.get("format", "markdown"),
            ))

        if name == "env_parity_checker":
            return _json_response(await st.env_parity_checker(
                example_file=args.get("example_file", ".env.example"),
                env_file=args.get("env_file", ".env"),
            ))

        if name == "load_tester":
            url = args.get("url")
            if not url:
                return _json_response({"error": "Thiếu argument bắt buộc: url"})
            return _json_response(await st.load_tester(
                url=url,
                requests_count=args.get("requests_count", 100),
                concurrency=args.get("concurrency", 10),
                method=args.get("method", "GET"),
            ))

        if name == "complexity_analyzer":
            return _json_response(await st.complexity_analyzer(
                paths=args.get("paths"),
                threshold=args.get("threshold", 10),
            ))

        if name == "migration_validator":
            return _json_response(await st.migration_validator(paths=args.get("paths")))

        if name == "sql_query_analyzer":
            return _json_response(await st.sql_query_analyzer(files=args.get("files")))

        if name == "openapi_spec_sync":
            return _json_response(await st.openapi_spec_sync(spec_path=args.get("spec_path")))

        if name == "breaking_change_detector":
            return _json_response(await st.breaking_change_detector(base_ref=args.get("base_ref", "")))

        if name == "flaky_test_detector":
            return _json_response(await st.flaky_test_detector(
                runs=args.get("runs", 3),
                test_path=args.get("test_path", ""),
            ))

        if name == "duplicate_code_scanner":
            return _json_response(await st.duplicate_code_scanner(
                min_lines=args.get("min_lines", 6),
                threshold=args.get("threshold", 0.8),
            ))

        if name == "container_linter":
            return _json_response(await st.container_linter(paths=args.get("paths")))

        if name == "dependency_graph_visualizer":
            return _json_response(await st.dependency_graph_visualizer(paths=args.get("paths")))

        if name == "ci_pipeline_validator":
            return _json_response(await st.ci_pipeline_validator(paths=args.get("paths")))

        if name == "mutation_tester":
            return _json_response(await st.mutation_tester(
                files=args.get("files"),
                max_mutations=args.get("max_mutations", 20),
            ))

        if name == "data_flow_taint_analyzer":
            return _json_response(await st.data_flow_taint_analyzer(files=args.get("files")))

        if name == "performance_regression_detector":
            return _json_response(await st.performance_regression_detector(
                functions=args.get("functions"),
                threshold_pct=args.get("threshold_pct", 20.0),
            ))

        return _json_response({"error": f"Unknown tool: {name}"})

    except KeyError as e:
        return _json_response({"error": f"Thiếu argument bắt buộc: {e}"})
    except Exception as e:
        return _json_response({"error": f"{type(e).__name__}: {e}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())

if __name__ == "__main__":
    asyncio.run(main())
