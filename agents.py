"""
Agent Harness - 12-Agent Support Team cho Claude Code
Roles, models, system prompts + core LLM call (adaptive params, retry, fallback)
"""
import asyncio
import concurrent.futures
import contextlib
import json
import logging
import math
import os
import random
import re
import sqlite3
import contextvars
import threading
import time
import uuid
from enum import Enum
from typing import Any, Optional

from openai import (
    OpenAI,
    APIConnectionError,
    APITimeoutError,
    BadRequestError,
    InternalServerError,
    NotFoundError,
    RateLimitError,
)
from config import (
    MODELS, MAX_OUTPUT_TOKENS, MAX_RETRIES, REQUEST_TIMEOUT,
    ROLE_TIMEOUTS, get_llm_client, get_router_responses_client,
    WORKSPACE_ROOT, get_spare_models,
)
from runtime_flags import bool_flag
from pydantic import BaseModel

_log = logging.getLogger("harness.agents")

try:
    _RESPONSES_MAX_WORKERS = min(16, max(1, int(os.getenv("HARNESS_RESPONSES_MAX_WORKERS", "4"))))
except (TypeError, ValueError):
    _RESPONSES_MAX_WORKERS = 4
_RESPONSES_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
    max_workers=_RESPONSES_MAX_WORKERS,
    thread_name_prefix="harness-resp",
)
_RESPONSES_SEM = threading.BoundedSemaphore(_RESPONSES_MAX_WORKERS)

_FINOPS_LOCK = threading.RLock()

def _finops_workspace_root() -> str:
    root = (os.getenv("CLAUDE_PROJECT_DIR") or "").strip()
    if not root:
        meta = os.getenv("ANTIGRAVITY_SOURCE_METADATA")
        if meta:
            try:
                root = str(json.loads(meta).get("tool", {}).get("workspacePath") or "").strip()
            except Exception:
                root = ""
    root = root or (os.getenv("WORKSPACE_ROOT") or "").strip() or WORKSPACE_ROOT
    root = os.path.abspath(root)
    if os.path.isdir(root) and os.access(root, os.W_OK):
        return root
    fallback = os.path.join(os.path.expanduser("~"), ".agent-harness")
    os.makedirs(fallback, exist_ok=True)
    _log.warning("FinOps workspace root invalid/unwritable: %s; using %s", root, fallback)
    return fallback


def _finops_db_path() -> str:
    return os.path.join(_finops_workspace_root(), ".harness_finops.db")

def get_finops_db_path() -> str:
    return _finops_db_path()

FINOPS_DB_PATH = _finops_db_path()
current_run_id = contextvars.ContextVar("current_run_id", default="")

def _connect_finops_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_finops_db_path(), timeout=30.0, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextlib.contextmanager
def _finops_file_lock():
    lock_path = _finops_db_path() + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        if os.name == "nt":
            import msvcrt
            for attempt in range(50):
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if attempt == 49:
                        raise
                    time.sleep(0.05 + random.uniform(0, 0.05))
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

def _with_finops_write(action):
    for attempt in range(5):
        with _FINOPS_LOCK:
            with _finops_file_lock():
                conn = _connect_finops_db()
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    result = action(conn)
                    conn.commit()
                    return result
                except sqlite3.OperationalError as e:
                    conn.rollback()
                    if "locked" in str(e).lower() and attempt < 4:
                        time.sleep((0.1 * (attempt + 1)) + random.uniform(0, 0.05))
                        continue
                    raise
                finally:
                    conn.close()

def init_finops_db():
    def _init(conn: sqlite3.Connection):
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            workflow_type TEXT,
            duration_ms INTEGER,
            total_cost REAL
        )
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS steps (
            step_id TEXT PRIMARY KEY,
            run_id TEXT,
            agent_role TEXT,
            model TEXT,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            latency_ms INTEGER,
            cache_hit INTEGER,
            cost_usd REAL,
            FOREIGN KEY(run_id) REFERENCES runs(run_id)
        )
        """)
    _with_finops_write(_init)

try:
    init_finops_db()
except Exception as e:
    logging.getLogger("harness.agents").warning("FinOps DB init failed: %s", e)

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    m = model.lower()
    input_rate = 2.0
    output_rate = 6.0
    if "sonnet" in m:
        input_rate = 3.0
        output_rate = 15.0
    elif "gemini" in m and ("extra-low" in m or "-low" in m):
        input_rate = 0.15
        output_rate = 0.60
    elif "gemini" in m:
        input_rate = 1.0
        output_rate = 4.0
    cost = (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000
    return round(cost, 6)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _runtime_bool(name: str, default: bool = False) -> bool:
    try:
        return bool_flag(name, default, root=_finops_workspace_root())
    except Exception:
        return _env_bool(name, default)


def enforce_llm_budget(model: str, messages: list[dict], max_output_tokens: int) -> None:
    """Keep the hard LLM kill-switch; FinOps cost guard no longer blocks calls."""
    if not _runtime_bool("HARNESS_LLM_ENABLED", True):
        raise RuntimeError("HARNESS_LLM_ENABLED=0: 9Router LLM calls are disabled")
    return

def log_step_to_db(run_id: str, agent_role: str, model: str, prompt_tokens: int, completion_tokens: int, latency_ms: int, cache_hit: bool):
    if not run_id or not _runtime_bool("HARNESS_FINOPS_ENABLED", True):
        return
    step_id = f"step-{uuid.uuid4().hex[:8]}"
    cost_usd = calculate_cost(model, prompt_tokens, completion_tokens)
    try:
        def _insert(conn: sqlite3.Connection):
            conn.execute("""
                INSERT OR IGNORE INTO runs (run_id, workflow_type, duration_ms, total_cost)
                VALUES (?, ?, ?, ?)
            """, (run_id, "in_progress", 0, 0.0))
            conn.execute("""
                INSERT INTO steps (step_id, run_id, agent_role, model, prompt_tokens, completion_tokens, latency_ms, cache_hit, cost_usd)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (step_id, run_id, agent_role, model, prompt_tokens, completion_tokens, latency_ms, int(cache_hit), cost_usd))
        _with_finops_write(_insert)
    except Exception as e:
        _log.warning("FinOps ghi log step thất bại: %s", e)

def log_run_to_db(run_id: str, workflow_type: str, duration_ms: int):
    if not run_id or not _runtime_bool("HARNESS_FINOPS_ENABLED", True):
        return
    try:
        def _insert(conn: sqlite3.Connection):
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(cost_usd) FROM steps WHERE run_id = ?", (run_id,))
            row = cursor.fetchone()
            total_cost = row[0] if row and row[0] is not None else 0.0
            cursor.execute("""
                INSERT OR REPLACE INTO runs (run_id, workflow_type, duration_ms, total_cost)
                VALUES (?, ?, ?, ?)
            """, (run_id, workflow_type, duration_ms, total_cost))
        _with_finops_write(_insert)
    except Exception as e:
        _log.warning("FinOps ghi log run thất bại: %s", e)


class AgentRole(str, Enum):
    MANAGER     = "manager"
    SYNTHESIZER = "synthesizer"
    ANALYZER    = "analyzer"
    CODE_A      = "code_a"
    CODE_B      = "code_b"
    REVIEWER    = "reviewer"
    TESTER      = "tester"
    SECURITY    = "security"
    INTEGRITY   = "integrity"   # data integrity + synthesis guard
    SCANNER     = "scanner"     # static analysis: dead_code/complexity/duplicate/perf
    DEBUGGER    = "debugger"
    WORKER      = "worker"


class AgentMessage(BaseModel):
    role: str
    content: str


class AgentResult(BaseModel):
    agent_id:    str
    agent_role:  AgentRole
    model_used:  str
    task:        str
    result:      str
    duration_ms: int
    status:      str    # "success" | "error"
    error:       str = ""


# ── System prompts ────────────────────────────────────────────────────────────
# Vai trò mới: hỗ trợ một AI coding agent chính (Claude Code) — không thay nó code.


SYSTEM_PROMPTS: dict[AgentRole, str] = {

    AgentRole.MANAGER: """Bạn là Codebase Q&A Agent với context window 1M tokens.
Bạn nhận một lượng lớn source code (nhiều file, đánh số dòng) và một câu hỏi
từ một AI coding agent đang làm việc trên codebase đó.

Nhiệm vụ:
1. Trả lời chính xác dựa trên code được cung cấp — KHÔNG đoán mò
2. Luôn trích dẫn vị trí cụ thể dạng `file:line` cho mọi claim
3. Nếu câu hỏi liên quan đến flow xuyên nhiều file, vẽ lại flow đó từng bước
4. Nếu code được cung cấp KHÔNG đủ để trả lời, nói rõ thiếu file nào

Output ngắn gọn, có cấu trúc, ưu tiên độ chính xác hơn độ dài.""",

    AgentRole.SYNTHESIZER: """Bạn là Findings Merge Agent.
Bạn nhận findings (JSON) từ 3 reviewer độc lập (code quality / security / adversarial testing)
về cùng một đoạn code.

Nhiệm vụ:
1. Dedupe: các finding trùng nhau (cùng file + line + cùng bản chất issue) → giữ 1, lấy severity cao nhất
2. Loại finding rõ ràng là noise/đệm cho có (style nitpick không hậu quả, suy đoán không căn cứ)
3. Sắp xếp theo severity: critical → high → medium → low
4. Giữ nguyên field "triage" từ finding gốc (auto_fix / ask_user); nếu conflict → ask_user

Trả về JSON object thuần (không markdown fence):
{
  "verdict": "approve" | "fix_first",
  "summary": "1-2 câu tổng kết",
  "findings": [
    {"file": "...", "line": <int|null>, "severity": "critical|high|medium|low",
     "category": "...", "issue": "...", "suggested_fix": "...", "found_by": ["reviewer","security"],
     "triage": "auto_fix|ask_user"}
  ]
}
verdict = "fix_first" nếu có bất kỳ finding critical/high nào.""",

    AgentRole.ANALYZER: """Bạn là Design Consultant Agent (deep reasoning).
Một AI coding agent hỏi ý kiến bạn TRƯỚC khi nó implement phần khó.

Nhiệm vụ:
1. Hiểu đúng câu hỏi và constraints từ context được cung cấp
2. Đề xuất approach tốt nhất, kèm 1-2 alternative đáng cân nhắc
3. Nêu trade-offs cụ thể (performance, complexity, maintainability)
4. Liệt kê edge cases và pitfalls mà người implement dễ bỏ qua

Output ngắn gọn, có cấu trúc. Kết luận rõ ràng: "Khuyến nghị: X, vì Y".""",

    AgentRole.CODE_A: """Bạn là Code Agent A — sinh phương án implementation thứ nhất.
Output của bạn là MỘT PHƯƠNG ÁN THAM KHẢO cho một AI coding agent so sánh,
nó sẽ tự quyết định dùng gì — nên hãy chọn approach bạn tin là tối ưu nhất.

Quy tắc BẮT BUỘC:
- Code HOÀN CHỈNH, không placeholder, không "..."
- Type hints đầy đủ (Python) / TypeScript types
- Error handling proper
- Cuối output: 2-3 dòng giải thích vì sao chọn approach này""",

    AgentRole.CODE_B: """Bạn là Code Agent B — sinh phương án implementation thứ hai.
Output của bạn là PHƯƠNG ÁN THAY THẾ cho một AI coding agent so sánh với phương án A.

Quy tắc BẮT BUỘC:
- Chủ động chọn approach KHÁC với cách hiển nhiên nhất (pattern khác, cấu trúc dữ liệu khác,
  library khác, hoặc đơn giản hơn) — giá trị của bạn nằm ở sự KHÁC BIỆT
- Code HOÀN CHỈNH, không placeholder
- Cuối output: 2-3 dòng giải thích approach này khác gì và khi nào nên chọn nó""",

    AgentRole.REVIEWER: """Bạn là Code Review Agent trong panel 3 người (quality / security / testing).
Bạn phụ trách CODE QUALITY: bugs, logic errors, anti-patterns, performance.
Code được cung cấp có đánh số dòng — luôn ghi đúng line number.

Chỉ báo issue THẬT, có hậu quả cụ thể. KHÔNG đệm finding cho có.
Nếu code sạch, trả về danh sách rỗng.

Trả về JSON object thuần (không markdown fence):
{"findings": [{"file": "path hoặc 'inline'", "line": <int|null>,
  "severity": "critical|high|medium|low", "category": "bug|logic|performance|design",
  "issue": "mô tả ngắn, cụ thể", "suggested_fix": "fix cụ thể, kèm code nếu được",
  "triage": "auto_fix|ask_user"}]}

triage = "auto_fix" khi fix là mechanical/deterministic (đổi tên, thêm null check, sửa typo).
triage = "ask_user" khi fix đòi hỏi judgment của developer (refactor architecture, thay đổi behavior).""",

    AgentRole.TESTER: """Bạn là Adversarial Test Agent trong panel 3 người (quality / security / testing).
Vai trò của bạn là DEVIL'S ADVOCATE — tìm những gì hai reviewer kia (code quality + security) sẽ BỎ SÓT:
- Input edge cases khiến code fail theo cách không hiển nhiên
- Race conditions chỉ xuất hiện dưới concurrent load
- Behavioral surprises khi state ngoài tầm kiểm soát (empty list, None, 0, negative, max int, unicode, empty string)
- Assumptions ẩn trong code mà developer quên document

Mỗi finding PHẢI có INPUT CỤ THỂ hoặc SCENARIO CỤ THỂ làm code fail.
Nếu không tìm thấy lỗi thật, trả về danh sách rỗng — đừng đệm finding.

Trả về JSON object thuần (không markdown fence):
{"findings": [{"file": "path hoặc 'inline'", "line": <int|null>,
  "severity": "critical|high|medium|low", "category": "edge_case|race_condition|assumption|error_handling",
  "issue": "input/scenario cụ thể làm code fail", "suggested_fix": "cách handle + test case mẫu",
  "triage": "auto_fix|ask_user"}]}

triage = "auto_fix" khi fix là mechanical. triage = "ask_user" khi cần developer quyết.""",

    AgentRole.SECURITY: """Bạn là Security Audit Agent trong panel 3 người (quality / security / testing).
Bạn phụ trách SECURITY: injection (SQL/command/path), XSS/CSRF, auth flaws,
secrets exposure, insecure deserialization, race conditions, input validation.

Chỉ báo vuln THẬT có attack vector cụ thể — nêu rõ cách khai thác.
KHÔNG báo lý thuyết suông. Nếu không tìm thấy, trả về danh sách rỗng.

Trả về JSON object thuần (không markdown fence):
{"findings": [{"file": "path hoặc 'inline'", "line": <int|null>,
  "severity": "critical|high|medium|low", "category": "injection|xss|auth|secrets|validation|other",
  "issue": "vuln + attack vector cụ thể", "suggested_fix": "fix cụ thể kèm code",
  "triage": "auto_fix|ask_user"}]}

triage = "auto_fix" khi fix là parameterized query, encode output, thêm header — mechanical.
triage = "ask_user" khi cần thay đổi auth flow hoặc redesign.""",

    AgentRole.DEBUGGER: """Bạn là Fix Suggestion Agent.
Bạn nhận: code (đánh số dòng) + error message / test failure / mô tả bug.
Một AI coding agent sẽ đọc đề xuất của bạn và TỰ áp dụng — bạn không sửa file trực tiếp.

Output format:
## Root cause
[1-3 câu: vì sao lỗi xảy ra, trỏ đúng file:line]

## Patch
```diff
[unified diff để fix — chỉ sửa chỗ cần sửa, không refactor lan man]
```

## Lưu ý
[side effects hoặc chỗ khác cũng cần sửa tương tự, nếu có]""",

    AgentRole.INTEGRITY: """Bạn là Data Integrity & Synthesis Guard — reviewer thứ 4 trong panel.
Bạn nhận: (1) code diff/source, (2) findings từ 3 reviewer trước (quality/security/testing).

NHIỆM VỤ KÉP:

### Phần 1 — Data Integrity Review (tìm trong code)
Chuyên tìm các lỗi mà 3 reviewer kia hay bỏ sót:
- Race conditions: TOCTOU, shared mutable state không lock, concurrent write conflict
- Missing transaction boundary: nhiều DB ops không atomic, partial failure không rollback
- Non-idempotent operation: retry gây duplicate, side effect kép
- Partial failure gap: step N thành công nhưng step N+1 fail → state không nhất quán
- Saga/compensation gap: distributed operation thiếu rollback path

### Phần 2 — Synthesis (tổng hợp findings từ cả panel)
Sau khi thêm findings riêng, merge toàn bộ 4 reviewer:
- Dedupe: cùng file + line + bản chất → giữ 1, lấy severity cao nhất, gộp found_by
- Loại noise: style nitpick không hậu quả, suy đoán không căn cứ
- Sắp xếp: critical → high → medium → low
- Giữ triage từ finding gốc; conflict → ask_user

Trả về JSON object thuần (không markdown fence):
{
  "verdict": "approve" | "fix_first",
  "summary": "1-2 câu tổng kết toàn panel",
  "findings": [
    {"file": "...", "line": <int|null>, "severity": "critical|high|medium|low",
     "category": "...", "issue": "...", "suggested_fix": "...",
     "found_by": ["reviewer","security","integrity",...],
     "triage": "auto_fix|ask_user"}
  ]
}
verdict = "fix_first" nếu có bất kỳ finding critical/high nào.""",

    AgentRole.SCANNER: """Bạn là Static Analysis Scanner — engine phân tích code thuần tĩnh, không suy diễn.

Chỉ báo findings dựa trên pattern cụ thể, metrics, data-flow literal, hoặc structural duplication.
KHÔNG đề xuất thay đổi kiến trúc. KHÔNG suy đoán runtime behavior.

Mỗi finding BẮT BUỘC có:
- file:line chính xác
- confidence: HIGH (pattern rõ ràng) | MEDIUM (heuristic) | LOW (nghi ngờ)
- metric cụ thể nếu có (cyclomatic complexity N, similarity 87%, N+1 tại line X)

Nếu không tìm thấy issue thật → trả danh sách rỗng. Không đệm finding.""",

    AgentRole.WORKER: """Bạn là Quick Task Agent — xử lý việc vặt nhanh gọn cho một AI coding agent:
boilerplate, test fixtures, mock data, docstrings, config files, format chuyển đổi.

Trả đúng thứ được yêu cầu, không giải thích dài, không hỏi lại.""",
}


ROLE_TO_MODEL: dict[AgentRole, str] = {
    AgentRole.MANAGER:     MODELS.manager,
    AgentRole.SYNTHESIZER: MODELS.synthesizer,
    AgentRole.ANALYZER:    MODELS.analyzer,
    AgentRole.CODE_A:      MODELS.code_a,
    AgentRole.CODE_B:      MODELS.code_b,
    AgentRole.REVIEWER:    MODELS.reviewer,
    AgentRole.TESTER:      MODELS.tester,
    AgentRole.INTEGRITY:   MODELS.integrity,
    AgentRole.SCANNER:     MODELS.scanner,
    AgentRole.SECURITY:    MODELS.security,
    AgentRole.DEBUGGER:    MODELS.debugger,
    AgentRole.WORKER:      MODELS.worker,
}

# Review/fix cần ổn định (temp thấp), code_b cần đa dạng (temp cao hơn)
ROLE_TEMPERATURE: dict[AgentRole, float] = {
    AgentRole.MANAGER:     0.2,
    AgentRole.SYNTHESIZER: 0.1,
    AgentRole.ANALYZER:    0.3,
    AgentRole.CODE_A:      0.4,
    AgentRole.CODE_B:      0.8,
    AgentRole.REVIEWER:    0.1,
    AgentRole.TESTER:      0.2,
    AgentRole.SECURITY:    0.1,
    AgentRole.INTEGRITY:   0.1,
    AgentRole.SCANNER:     0.0,  # deterministic — no creativity needed
    AgentRole.DEBUGGER:    0.1,
    AgentRole.WORKER:      0.3,
}


# ── Core LLM call: adaptive params, retry, spare fallback ────────────────────
# 9Router local proxy exposes OpenAI-compatible Chat Completions for all
# configured models. Param quirks are learned from BadRequestError and cached
# per model instead of hardcoding.

_MODEL_QUIRKS: dict[str, dict[str, Any]] = {}
_model_quirks_lock = threading.Lock()

_responses_client: Optional[OpenAI] = None
_responses_client_lock = threading.Lock()

class _ResponsesTimeoutError(Exception):
    """Raised khi _responses_call vượt Python-level timeout. Map sang spare-model fallback trong chat_completion."""


def _responses_queue_timeout(timeout: float) -> float:
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.01, value)


def _get_router_responses_client() -> OpenAI:
    global _responses_client
    if _responses_client is None:
        with _responses_client_lock:
            if _responses_client is None:
                _responses_client = get_router_responses_client()
    return _responses_client


def _quirks_for(model: str) -> dict[str, Any]:
    if not isinstance(model, str) or not model:
        raise ValueError(f"model phải là non-empty string, nhận: {model!r}")
    with _model_quirks_lock:
        if model not in _MODEL_QUIRKS:
            from config import IS_OPENAI_COMPAT
            responses_only = False
            _MODEL_QUIRKS[model] = {
                "api":         "responses" if responses_only else "chat",
                "api_locked":  False,  # chỉ cho flip api 1 lần, tránh ping-pong
                "token_param": "max_completion_tokens",
                "temperature": True,
                "json_mode":   True,
            }
        return _MODEL_QUIRKS[model]


def _chat_call(
    client: OpenAI, model: str, messages: list[dict], quirks: dict,
    json_mode: bool, max_output_tokens: int, temperature: float,
    timeout: float,
) -> tuple[str, int, int]:
    params: dict[str, Any] = {
        "model": model,
        "messages": messages,
        quirks["token_param"]: max_output_tokens,
        "timeout": timeout,
    }
    if quirks["temperature"]:
        params["temperature"] = temperature
    if json_mode and quirks["json_mode"]:
        params["response_format"] = {"type": "json_object"}
    response = client.chat.completions.create(**params)
    usage = getattr(response, "usage", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None) or getattr(usage, "input_token_count", 0)
        completion_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None) or getattr(usage, "output_token_count", 0)
    return (response.choices[0].message.content or ""), prompt_tokens, completion_tokens


def _responses_call(model: str, messages: list[dict], max_output_tokens: int, timeout: float) -> tuple[str, int, int]:
    # Reasoning models: không temperature; JSON ép qua prompt (parser có fallback)
    client = _get_router_responses_client()
    instructions = "\n\n".join(
        m["content"] for m in messages if m["role"] == "system"
    ) or None
    input_msgs = [m for m in messages if m["role"] != "system"]

    def _do_call():
        return client.responses.create(
            model=model,
            instructions=instructions,
            input=input_msgs,
            max_output_tokens=max_output_tokens,
            timeout=timeout,
        )

    # 9Router Responses endpoint có thể ignore SDK timeout — enforce ở Python level.
    # Shared bounded pool prevents unbounded thread growth when requests time out.
    queue_timeout = _responses_queue_timeout(timeout)
    acquired = _RESPONSES_SEM.acquire(timeout=queue_timeout)
    if not acquired:
        raise _ResponsesTimeoutError(f"responses_call queue saturated after {queue_timeout}s on {model}")

    released = threading.Event()

    def _release_once(_f=None):
        if not released.is_set():
            released.set()
            _RESPONSES_SEM.release()

    future = _RESPONSES_EXECUTOR.submit(_do_call)
    future.add_done_callback(_release_once)
    try:
        response = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        _release_once()
        raise _ResponsesTimeoutError(f"responses_call timeout after {timeout}s on {model}")

    usage = getattr(response, "usage", None)
    prompt_tokens = 0
    completion_tokens = 0
    if usage:
        prompt_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None) or getattr(usage, "input_token_count", 0)
        completion_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None) or getattr(usage, "output_token_count", 0)
    return (response.output_text or ""), prompt_tokens, completion_tokens


def chat_completion(
    client: OpenAI,
    model: str,
    messages: list[dict],
    *,
    json_mode: bool = False,
    max_output_tokens: int = MAX_OUTPUT_TOKENS,
    temperature: float = 0.2,
    timeout: float = REQUEST_TIMEOUT,
    timeout_retries: int = 1,
    use_spares: bool = True,
) -> tuple[str, str, int, int]:
    """Gọi LLM qua API phù hợp với deployment. Trả về (text, model_đã_dùng_thật_sự, prompt_tokens, completion_tokens).

    - "operation is unsupported" trên chat → flip sang Responses API và thử lại
    - NotFound trên responses → flip về chat (model không có trên route đó)
    - BadRequest về param → flip quirk tương ứng và thử lại ngay
    - 429 → exponential backoff; hết MAX_RETRIES → chuyển sang SPARE_MODELS
    - Timeout/5xx → backoff retry
    """
    current_model  = model
    spares         = iter(get_spare_models())
    attempt        = 0
    timeout_attempt = 0  # retry tối đa 1 lần trước khi chuyển spare

    while True:
        quirks = _quirks_for(current_model)
        try:
            enforce_llm_budget(current_model, messages, max_output_tokens)
            if quirks["api"] == "responses":
                text, p_tok, c_tok = _responses_call(current_model, messages, max_output_tokens, timeout)
            else:
                text, p_tok, c_tok = _chat_call(
                    client, current_model, messages, quirks,
                    json_mode, max_output_tokens, temperature, timeout,
                )
            return text, current_model, p_tok, c_tok

        except BadRequestError as e:
            msg = str(e).lower()
            _retry = False
            with _model_quirks_lock:
                if quirks["api"] == "chat" and "unsupported" in msg and not quirks["api_locked"]:
                    quirks["api"], quirks["api_locked"] = "responses", True
                    _retry = True
                elif quirks["api"] == "chat":
                    if quirks["token_param"] == "max_completion_tokens" and "max_completion_tokens" in msg:
                        quirks["token_param"] = "max_tokens"
                        _retry = True
                    elif quirks["token_param"] == "max_tokens" and "max_tokens" in msg:
                        quirks["token_param"] = "max_completion_tokens"
                        _retry = True
                    elif quirks["temperature"] and "temperature" in msg:
                        quirks["temperature"] = False
                        _retry = True
                    elif json_mode and quirks["json_mode"] and "response_format" in msg:
                        quirks["json_mode"] = False
                        _retry = True
            if _retry:
                continue
            raise

        except NotFoundError:
            _retry = False
            with _model_quirks_lock:
                if quirks["api"] == "responses" and not quirks["api_locked"]:
                    quirks["api"], quirks["api_locked"] = "chat", True
                    _retry = True
            if _retry:
                continue
            raise

        except RateLimitError:
            timeout_attempt = 0  # reset streak vì đây là lỗi khác loại
            attempt += 1
            if attempt <= MAX_RETRIES:
                time.sleep(min(2 ** attempt, 30) + random.uniform(0, 1))
                continue
            spare = _next_distinct_spare(spares, current_model)
            if spare is not None:
                current_model = spare
                attempt = 0
                continue
            raise

        except (APITimeoutError, _ResponsesTimeoutError):
            timeout_attempt += 1
            if timeout_attempt <= timeout_retries:
                # Cho 1 lần retry ngắn trước khi failover spare
                _log.warning("Timeout lần %d trên %s — thử lại", timeout_attempt, current_model)
                time.sleep(1.0)
                continue
            spare = _next_distinct_spare(spares, current_model) if use_spares else None
            if spare is not None:
                _log.warning("Timeout lần %d trên %s → spare %s", timeout_attempt, current_model, spare)
                current_model = spare
                attempt = 0
                timeout_attempt = 0
                continue
            raise

        except (APIConnectionError, InternalServerError):
            timeout_attempt = 0  # reset streak
            attempt += 1
            if attempt <= MAX_RETRIES:
                time.sleep(min(2 ** attempt, 15))
                continue
            spare = _next_distinct_spare(spares, current_model)
            if spare is not None:
                _log.warning("Connection/server error trên %s → thử spare %s", current_model, spare)
                current_model = spare
                attempt = 0
                continue
            raise


def _next_distinct_spare(spares, current_model: str) -> str | None:
    current = str(current_model).strip().lower()
    for spare in spares:
        if str(spare).strip().lower() != current:
            return spare
    return None


# ── Agent class ───────────────────────────────────────────────────────────────

class Agent:
    def __init__(
        self,
        role: AgentRole,
        client: Optional[OpenAI] = None,
        system_prompt: Optional[str] = None,
    ):
        self.agent_id      = f"{role.value}-{str(uuid.uuid4())[:8]}"
        self.role          = role
        self.model         = ROLE_TO_MODEL[role]
        self.system_prompt = system_prompt or SYSTEM_PROMPTS[role]
        self.client        = client or get_llm_client()
        self.history: list[AgentMessage] = []
        self._history_lock = threading.RLock()

    def run(
        self,
        task: str,
        extra_context: str = "",
        *,
            json_mode: bool = False,
            max_output_tokens: int = MAX_OUTPUT_TOKENS,
            timeout: Optional[float] = None,
            timeout_retries: int = 1,
            use_spares: bool = True,
    ) -> AgentResult:
        start = time.time()
        messages: list[dict] = [{"role": "system", "content": self.system_prompt}]

        # History trước, message hiện tại sau cùng — đúng thứ tự hội thoại
        with self._history_lock:
            history_snapshot = list(self.history[-6:])
        for msg in history_snapshot:
            messages.append({"role": msg.role, "content": msg.content})

        user_content = (
            f"=== CONTEXT ===\n{extra_context}\n\n=== TASK ===\n{task}"
            if extra_context else task
        )
        messages.append({"role": "user", "content": user_content})

        try:
            raw_timeout = timeout if timeout is not None else ROLE_TIMEOUTS.get(self.role.value, REQUEST_TIMEOUT)
            try:
                call_timeout = float(raw_timeout)
                if not math.isfinite(call_timeout):
                    raise ValueError("timeout must be finite")
                call_timeout = max(1.0, call_timeout)
            except (TypeError, ValueError):
                _log.warning("ROLE_TIMEOUTS[%r]=%r không hợp lệ — dùng REQUEST_TIMEOUT=%s", self.role.value, raw_timeout, REQUEST_TIMEOUT)
                try:
                    call_timeout = max(1.0, float(REQUEST_TIMEOUT))
                    if not math.isfinite(call_timeout):
                        call_timeout = 30.0
                except (TypeError, ValueError):
                    call_timeout = 30.0
            result_text, model_used, p_tok, c_tok = chat_completion(
                self.client, self.model, messages,
                json_mode=json_mode,
                max_output_tokens=max_output_tokens,
                temperature=ROLE_TEMPERATURE.get(self.role, 0.3),
                timeout=call_timeout,
                timeout_retries=timeout_retries,
                use_spares=use_spares,
            )
            duration = int((time.time() - start) * 1000)

            with self._history_lock:
                self.history.append(AgentMessage(role="user",      content=user_content))
                self.history.append(AgentMessage(role="assistant", content=result_text))

            # Ghi log step vào FinOps DB
            run_id = current_run_id.get()
            if run_id:
                log_step_to_db(run_id, self.role.value, model_used, p_tok, c_tok, duration, False)

            return AgentResult(
                agent_id=self.agent_id, agent_role=self.role,
                model_used=model_used,  task=task,
                result=result_text,     duration_ms=duration,
                status="success",
            )
        except Exception as e:
            return AgentResult(
                agent_id=self.agent_id, agent_role=self.role,
                model_used=self.model,  task=task,
                result="",              duration_ms=int((time.time() - start) * 1000),
                status="error",         error=f"{type(e).__name__}: {e}",
            )

    async def run_async(
        self,
        task: str,
        extra_context: str = "",
        *,
        json_mode: bool = False,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
        timeout: Optional[float] = None,
        timeout_retries: int = 1,
        use_spares: bool = True,
    ) -> AgentResult:
        return await asyncio.to_thread(
            self.run, task, extra_context,
            json_mode=json_mode, max_output_tokens=max_output_tokens, timeout=timeout,
            timeout_retries=timeout_retries, use_spares=use_spares,
        )


def get_finops_stats() -> dict:
    conn = None
    try:
        conn = _connect_finops_db()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                COUNT(*) as total_steps,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(latency_ms) as total_latency_ms,
                SUM(cost_usd) as total_cost_usd,
                SUM(cache_hit) as total_cache_hits
            FROM steps
        """)
        row = cursor.fetchone()
        
        cursor.execute("""
            SELECT 
                model,
                COUNT(*) as count,
                SUM(prompt_tokens) as prompt_tokens,
                SUM(completion_tokens) as completion_tokens,
                SUM(cost_usd) as cost_usd,
                AVG(latency_ms) as avg_latency_ms
            FROM steps
            GROUP BY model
        """)
        model_stats = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("""
            SELECT 
                agent_role,
                COUNT(*) as count,
                SUM(cost_usd) as cost_usd
            FROM steps
            GROUP BY agent_role
        """)
        role_stats = [dict(r) for r in cursor.fetchall()]
        
        cursor.execute("""
            SELECT run_id, ts, workflow_type, duration_ms, total_cost
            FROM runs
            ORDER BY ts DESC
            LIMIT 5
        """)
        recent_runs = [dict(r) for r in cursor.fetchall()]
        
        return {
            "total_steps": row["total_steps"] or 0,
            "total_prompt_tokens": row["total_prompt_tokens"] or 0,
            "total_completion_tokens": row["total_completion_tokens"] or 0,
            "total_latency_ms": row["total_latency_ms"] or 0,
            "total_cost_usd": round(row["total_cost_usd"] or 0.0, 6),
            "total_cache_hits": row["total_cache_hits"] or 0,
            "model_stats": model_stats,
            "role_stats": role_stats,
            "recent_runs": recent_runs
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn is not None:
            conn.close()
