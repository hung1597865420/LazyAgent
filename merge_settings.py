"""Setup helper — được install.ps1 gọi, hoặc chạy trực tiếp: python merge_settings.py
Merge cấu hình harness vào ~/.claude/CLAUDE.md và ~/.claude/settings.json.
Idempotent: chạy lại bao nhiêu lần cũng không tạo trùng lặp.
"""
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

CLAUDE_MARKER = "<!-- agent-harness-managed -->"
GEMINI_MARKER = "<!-- agent-harness -->"
CODEX_PROFILE_MARKER = "<!-- agent-harness-runtime-profile-policy -->"
HOOK_ID = "agent-harness-panel-reminder"
LESSON_HOOK_ID = "agent-harness-lesson-recorder"
RULES_VERSION = "2026-07-20-ecc-ops-r1"
RULES_STAMP_FILE = ".harness_rules_version"


def _harness_root() -> Path:
    return Path(__file__).resolve().parent


def _harness_server() -> str:
    return str(_harness_root() / "mcp_server.py")


def _shell_join(argv: list[str]) -> str:
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def _toml_basic_string(value: str) -> str:
    out = ['"']
    escapes = {
        "\\": "\\\\",
        "\"": "\\\"",
        "\b": "\\b",
        "\t": "\\t",
        "\n": "\\n",
        "\f": "\\f",
        "\r": "\\r",
    }
    for ch in value:
        if ch in escapes:
            out.append(escapes[ch])
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _home_dir(home: Path | None = None) -> Path:
    return home or Path.home()


def _rules_stamp_path(claude_dir: Path | None = None, home: Path | None = None) -> Path:
    return (claude_dir or (_home_dir(home) / ".claude")) / RULES_STAMP_FILE


def installed_rules_version(claude_dir: Path | None = None, home: Path | None = None) -> str | None:
    try:
        path = _rules_stamp_path(claude_dir, home)
        return path.read_text(encoding="utf-8").strip() if path.exists() else None
    except OSError:
        return None


def needs_update(claude_dir: Path | None = None, home: Path | None = None) -> bool:
    return installed_rules_version(claude_dir, home) != RULES_VERSION


def mark_rules_merged(claude_dir: Path | None = None, home: Path | None = None) -> None:
    path = _rules_stamp_path(claude_dir, home)
    _atomic_write_text(path, RULES_VERSION + "\n")


def _read_json_object(path: Path, label: str, *, missing_ok: bool = True) -> tuple[dict, int]:
    if not path.exists():
        if missing_ok:
            return {}, 0
        print(f"[error] Khong tim thay {label}: {path}.")
        return {}, 1
    try:
        raw_bytes = path.read_bytes()
        if raw_bytes[:2] in (b"\xff\xfe", b"\xfe\xff"):
            raw = raw_bytes.decode("utf-16")
        elif raw_bytes[:3] == b"\xef\xbb\xbf":
            raw = raw_bytes.decode("utf-8-sig")
        else:
            raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        print(f"[error] {label} khong doc duoc UTF-8 ({e}). Giu nguyen file, khong ghi de.")
        return {}, 1
    except OSError as e:
        print(f"[error] Khong doc duoc {label} ({e}). Giu nguyen file, khong ghi de.")
        return {}, 1
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[error] {label} khong phai JSON hop le ({e}). Giu nguyen file, khong ghi de.")
        return {}, 1
    if not isinstance(data, dict):
        print(f"[error] {label} root phai la object JSON, hien la {type(data).__name__}. Giu nguyen file.")
        return {}, 1
    return data, 0

SHARED_AGENT_RULE_SOURCE = (
    "Agent rule source of truth: update the COMMON_* fragments in merge_settings.py once; "
    "the generator renders Claude, Codex, and Gemini/Antigravity from the same shared policy."
)

COMMON_RUNTIME_PROFILE_POLICY_TEMPLATE = """\
## Runtime Profile Policy — profile thắng mọi rule bên dưới

Trước khi tự gọi bất kỳ tool Agent Harness nào có thể dùng LLM hoặc chạy nền, đọc profile global `%USERPROFILE%\\.agent-harness\\harness.features.json` hoặc dùng `{off_status_command}`. `HARNESS_FEATURES_FILE` bị bỏ qua trừ khi `HARNESS_ALLOW_FEATURE_FILE_OVERRIDE=1` để test/debug rõ ràng. Không tự đổi profile. Không chạy `harness-toggle.bat <profile>`, `set`, `toggle`, `mode`, hoặc `timing` trừ khi user vừa yêu cầu rõ trong prompt hiện tại; CLI write còn phải có `HARNESS_ALLOW_PROFILE_WRITE=1`.

Ngay đầu mỗi user prompt/session mới, refresh profile bằng profile global và coi đó là runtime profile snapshot hiện hành cho mọi repo. Với client có hook prompt, snapshot có thể đã được inject sẵn; với Gemini/Antigravity không có hook prompt tương đương trong config hiện tại, tự đọc file global hoặc gọi status/json trước khi quyết định gọi tool LLM/chạy nền.

| Profile | Agent được làm | Agent không được làm |
|---|---|---|
| `off` | Chỉ read-only/static local: đọc file, `{off_status_command}`, git diff/status, py_compile/lint/test user yêu cầu rõ. | Không gọi LLM tools: `consult`, `panel_review`, `ask_codebase`, `alt_implementation`, `suggest_fix`, `quick_task`, `swarm_debug`, `auto_trigger` có LLM, `goal_runner`, `prod_readiness_gate mode=max`; không bật hooks/lessons/finops/watch. |
| `light` | Static-first checks, hooks/lessons/finops nếu đang enabled, `auto_trigger mode=safe` không LLM, secret/env/config/devops/static analyzers. Manual LLM chỉ khi user yêu cầu rõ hoặc task thật sự cần theo rule bắt buộc. | Không tự gọi auto LLM enrichment; không bật watcher; không tự đổi profile. |
| `standard` | Như `light` + watcher safe được phép chạy static checks. Manual LLM vẫn chỉ khi có lý do rõ. | Watcher/Auto-Pilot không được tự gọi LLM; không dùng `static_llm`; không fan-out max. |
| `balanced` / `4` | Coding/review chủ động: `auto_trigger safe`, `consult`/`panel_review`/`ask_codebase` được phép khi rule bắt buộc khớp. | Không bật watcher; không static LLM enrichment nền; không gọi max/prod fan-out trừ khi user yêu cầu. |
| `review` / `5` | Review kỹ hơn: Auto-Pilot LLM + static LLM được phép cho batch review; watcher safe nhưng không watcher LLM. | Watcher không được gọi LLM; không dùng max fan-out mặc định. |
| `heavy` / `7` | Refactor lớn/debug khó: Auto-Pilot max, static LLM; watcher chỉ chạy nếu user bật riêng `auto-watch`. | Không tự bật watcher nền cho mọi repo; không chạy aggressive release/prod gates liên tục; vẫn phải gom batch, tránh gọi panel lặp. |
| `max` | Full audit/release khi user chọn rõ: aggressive checks, watcher fast, LLM enrichment, prod/release gates. | Không để mặc định cả ngày; không tự chuyển từ profile thấp lên `max`. |

Nếu profile không cho phép tool LLM, thay bằng static/local tương đương và báo ngắn: `profile <name> đang chặn LLM`. Runtime hard-kill `llm.enabled=false` là tuyệt đối, không retry và không tìm cách bypass.
"""

COMMON_DISTILLED_INTEGRATIONS = """\
## Distilled Integrations — Hallmark + Spec Kit + UI Skills + Workflow

- Hallmark đã được chưng cất thành UI/design bridge: khi task là frontend, landing page, component, redesign, audit UI, screenshot/URL design study, hoặc file đổi là HTML/CSS/JSX/TSX/Vue/Svelte/Astro, gọi `hallmark_bridge(action="preflight")` trước khi sửa UI nếu MCP có sẵn. Nếu skill `hallmark` có sẵn thì dùng skill; nếu không có thì áp dụng trực tiếp: pre-flight tokens/fonts/framework/motion/spacing, phân biệt component vs full page, giữ route/content ownership, không bịa metrics, không fake browser/phone/code chrome, verify mobile 320/375/414/768, component đủ default/hover/focus/active/disabled/loading/error/success.
- `ibelick/ui-skills` đã được chưng cất thành `ui_skill_router`: trước UI work rõ ràng, chọn tối đa 3 checklist nhỏ (`baseline-ui`, `fixing-accessibility`, `fixing-motion-performance`, `fixing-metadata`, `improve-ui`) thay vì nạp cả đống review. Baseline/a11y/motion/metadata là pre/post static guidance; `a11y_auditor` và `visual_reviewer` vẫn là post-code audits.
- Spec Kit đã được chưng cất thành spec-first bridge: khi task là feature/project/module/API/schema/auth/workflow mới hoặc đổi nhiều file, gọi `speckit_bridge(action="status" hoặc "snapshot")` trước khi plan. Nếu repo có Spec Kit artifacts/commands/skills thì dùng `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` hoặc skill tương ứng; nếu chưa init thì chỉ dùng `speckit_bridge(action="init" hoặc "scaffold", allow_mutation=true)` khi profile cho phép và user/setup đã chọn rõ. Harness vẫn là lớp profile gate, checks, lessons, FinOps và final review.
- `mattpocock/skills` đã được chưng cất thành `workflow_router` + `bug_repro_guard`: debug/bug phải có red-capable repro command/output trước khi fix; feature lớn đi spec/tickets; task mơ hồ lớn đi wayfinder; domain/ADR dùng CONTEXT.md; review tách Standards vs Spec; refactor lớn dùng module/interface/seam/adapter/depth vocabulary và deletion test; tests đi qua public seam.
- `kangarooking/cangjie-skill` đã được chưng cất vào lesson global promotion: procedure lesson phải qua quality gate có title/summary, actionable steps, trigger, boundary, test_prompts should-trigger/should-not-trigger/edge-case, và bị chặn nếu generic/common-sense/secret/local/debug-only.
- `integration_router` là static MCP tool để kiểm route này mà không gọi LLM hoặc mutate files. `auto_trigger` trả `integration_routes` và `workflow_routes`; `goal_runner` tự bơm guidance này vào prompt agent ngoài.
- `a11y_auditor` và `visual_reviewer` là post-code audit/check sau UI implementation, không thay thế Hallmark preflight/design bridge.
- Profile vẫn thắng: `off` chỉ được gọi bridge read-only (`status`, `preflight`, `audit_plan`, `snapshot`); không tự init/scaffold/write preflight, không gọi Hallmark/Spec Kit LLM workflow, không gọi `goal_runner`; dùng static/local fallback và báo `profile off đang chặn LLM`.
"""


def _runtime_profile_policy(off_status_command: str) -> str:
    return COMMON_RUNTIME_PROFILE_POLICY_TEMPLATE.format(off_status_command=off_status_command)


def _shared_rule_source_note() -> str:
    return f"> {SHARED_AGENT_RULE_SOURCE}"


def _norm_command(command: object) -> str:
    return " ".join(str(command or "").split())


CLAUDE_MD_SECTION = f"""\
<!-- agent-harness-managed -->
# Agent Harness — quy trình khi làm coding task

Có MCP server `agent-harness` (12 model trên 9Router Proxy) hỗ trợ coding. Khi nhận task viết/sửa code, áp dụng quy tắc sau:

{_shared_rule_source_note()}

{_runtime_profile_policy("status/list/json")}

## Auto-Pilot — mặc định bật

- Khi user đưa prompt coding task có nhiều bước hoặc không xong ngay bằng một edit nhỏ: gọi `mcp__agent-harness__goal_autopilot(mode="init", goal="<nguyên prompt user>")` trước khi code. Tool này chia goal thành parts nhỏ. Làm từng part theo thứ tự; sau mỗi batch edit, `auto_trigger(mode="max")` sẽ chạy full harness checks song song kèm goal alignment, rồi gọi `goal_supervisor(last_checks=<auto_trigger result>, changed_files=[...], diff="<nếu có>")` để lấy next_action cứng: `continue_part`, `run_check`, `run_final`, `blocked_ask_user`, hoặc `complete`.
- Khi user muốn nhập prompt trực tiếp cho harness tự lái từ đầu đến cuối, hoặc nói "không phụ thuộc client tự gọi tool": dùng `mcp__agent-harness__goal_runner(prompt="<nguyên prompt>", mode="max")`. Tool này tự init goal, gọi agent CLI nếu có, chạy `auto_trigger`, hỏi `goal_supervisor`, rồi final qua `prod_readiness_gate`.
- Khi user hỏi "đã nạp chưa", "harness ổn chưa", cài qua agent nào, MCP config có drift không, context có đủ/tiết kiệm không, hoặc cần benchmark/resume: dùng ops tools tương ứng `harness_doctor`, `install_manifest`, `adapter_parity_doctor`, `mcp_inventory`, `context_budget`, `context_auditor`, `ask_codebase_health`, `goal_runner_control`, `run_ledger`, `policy_profile`, `agent_adapters`, `benchmark_runner`, `patch_safety_check`.
- Ưu tiên next_action từ `goal_supervisor`: `continue_part` = code tiếp part hiện tại; `run_check` = gọi lại `auto_trigger`/goal check sau khi sửa; `run_final` = gọi `goal_autopilot(mode="complete", ...)`; `blocked_ask_user` = dừng và hỏi user quyết định; `complete` = được báo hoàn thành.
- Sau mọi batch Edit/Write đáng kể, gọi `mcp__agent-harness__auto_trigger` với `changed_files`, `task`, `stage="post_edit"`, `mode="max"`. Tool này tự chạy secret/env/config/devops/complexity/dead-code/duplicate/panel_review theo context.
- Khi user hỏi deploy/release/production-ready hoặc trước khi nói "sẵn sàng lên prod": gọi `mcp__agent-harness__prod_readiness_gate(changed_files=[...], task="<prompt>", mode="max")`. Chỉ được claim prod-ready khi verdict là `ready_to_deploy`; `deploy_then_verify` cần nói rõ bước verify sau deploy; `fix_required` thì sửa rồi chạy lại; `blocked_needs_user` thì hỏi user; `rollback_required` thì dừng deploy/rollback nếu đã deploy.
- Trước khi báo hoàn thành, nếu có active goal thì gọi `goal_supervisor(...)` trước; chỉ gọi `goal_autopilot(mode="complete", changed_files=[...], diff="<nếu có>", context="<summary>")` khi supervisor trả `run_final`, và chỉ báo xong khi supervisor trả `complete`. Nếu không có active goal, gọi `mcp__agent-harness__auto_trigger` với `stage="final"`, `mode="max"` cho toàn bộ files đã sửa trong batch. Nếu `auto_trigger` đã chạy `panel_review` trên batch cuối thì không gọi `panel_review` riêng lần nữa.
- Goal progress summary được harness tự prepend vào context của `consult`/`panel_review`/`ask_codebase`/checks liên quan: `Goal: X | Part N/M | Last verdict: ... | Blockers: ... | Next: ...`.
- Docs-gate chỉ được tự ghi backlog hoặc tự cập nhật docs nhẹ khi phù hợp; TUYỆT ĐỐI không hỏi user kiểu "có muốn bổ sung tài liệu cho 5 prompt vừa rồi không?". User chỉ gõ prompt chính, không bị ngắt bởi maintenance docs.
- Không gửi `.env` thật vào `panel_review`; `auto_trigger` sẽ tự lọc `.env` khỏi review LLM và dùng secret/config scanners thay thế.
- Chỉ bỏ qua Auto-Pilot khi user nói rõ "khỏi review", "nhanh thôi", hoặc task chỉ sửa docs/comment/format dưới ~10 dòng.

{COMMON_DISTILLED_INTEGRATIONS}

## Bắt buộc

1. **Trước khi implement phần phức tạp** (thuật toán khó, kiến trúc mới, concurrency, auth/security, payment): gọi `mcp__agent-harness__consult` với câu hỏi design cụ thể + files liên quan. Cân nhắc advice nhưng tự quyết định cuối cùng.

2. **Sau khi viết/sửa xong code, TRƯỚC khi báo hoàn thành**: gọi `mcp__agent-harness__auto_trigger` (`stage="final"`, `mode="max"`) hoặc `mcp__agent-harness__panel_review` với danh sách files đã sửa (hoặc diff). Chạy MỘT LẦN cho cả batch thay đổi cuối cùng — không chạy sau mỗi edit lẻ. Findings mức critical/high phải xử lý (fix hoặc giải thích vì sao bỏ qua) trước khi chốt task.

## Dùng khi phù hợp

3. **Debug bí** (sau 1-2 lần thử không ra): `mcp__agent-harness__suggest_fix` với code + error/stack trace.
4. **Cần hiểu flow xuyên nhiều file trong codebase lớn**: `mcp__agent-harness__ask_codebase`.
5. **Cần so sánh 2 hướng implement cho module độc lập**: `mcp__agent-harness__alt_implementation`.
6. **Việc vặt** (fixtures, mock data, boilerplate): `mcp__agent-harness__quick_task`.

## Tự động theo context

**Tier 1:**
- `pr_generator` — task xong, có git changes chưa có PR description
- `dead_code_scanner` — sau refactor lớn hoặc xóa/đổi tên function/class/module
- `coverage_analyzer` — sau khi viết logic mới có nhánh phức tạp (>2 code paths)
- `incident_responder` — user paste log/stack trace kèm: crash, down, 500, exception, FATAL
- `secret_scanner` — trước git commit khi thêm file mới có credentials/token, khi sửa .env.example
- `env_parity_checker` — khi sửa .env.example hoặc .env; trước deploy/release

**Tier 2:**
- `migration_validator` — khi viết/sửa file trong thư mục migrations/, alembic/versions/
- `sql_query_analyzer` — khi viết ORM query mới hoặc thêm endpoint có DB access
- `openapi_spec_sync` — khi thêm/sửa route handler hoặc Pydantic model
- `breaking_change_detector` — trước khi tạo PR vào main; khi sửa public API/function signature
- `container_linter` — khi sửa Dockerfile, docker-compose.yml, hoặc trước deploy
- `ci_pipeline_validator` — khi sửa .github/workflows/ hoặc .gitlab-ci.yml
- `data_flow_taint_analyzer` — khi thêm endpoint nhận user input mới (Body, Form, Query)
- `duplicate_code_scanner` — sau khi viết module mới lớn hoặc sau refactor lớn
- `api_contract_tester` — khi thêm/sửa API endpoint
- `complexity_analyzer` — sau khi viết logic mới có >2 nhánh hoặc sau refactor lớn
- `changelog_generator` — khi user đề cập release, version bump, chuẩn bị deploy
- `release_orchestrator` — khi release/deploy/prod-ready; điều phối checklist release sau prod gate
- `provenance_checker` — trước release/deploy; kiểm commit/remote/hash/SBOM/lockfile/build provenance
- `auth_matrix_auditor` — khi sửa auth/permission/API endpoint có ownership/object-level access
- `incremental_refactor_guard` — sau refactor lớn, rename/delete public symbol, hoặc multi-file refactor
- `harness_trace_viewer` — khi harness timeout/rate-limit/trace/log bất thường hoặc cần xem bottleneck

**Tier 3:**
- `flaky_test_detector` — khi CI thỉnh thoảng fail không rõ lý do
- `mutation_tester` — khi coverage cao nhưng nghi ngờ test không assert đúng
- `performance_regression_detector` — sau refactor function critical; khi user mention "chậm hơn trước"
- `dependency_graph_visualizer` — khi gặp ImportError, circular import, hoặc thêm module mới
- `git_archaeologist` — khi cần hiểu "tại sao code được viết vậy" trước khi sửa
- `sbom_generator` — khi chuẩn bị deploy lên production
- `chaos_tester` — khi implement retry, circuit breaker, timeout, concurrent queue

## Ngoại lệ — KHÔNG cần panel_review

- Sửa docs, comment, README, config nhỏ
- Đổi tên biến, format code, thay đổi tầm thường dưới ~10 dòng
- User nói rõ bỏ qua review (vd: "khỏi review", "nhanh thôi")

## Khi harness lỗi

Nếu tool agent-harness lỗi (server không chạy, 9Router timeout/rate-limit): tiếp tục task bình thường, báo ngắn gọn cho user là harness đang lỗi. Không retry quá 1 lần, không block task vì harness.
<!-- /agent-harness-managed -->
"""

HOOK_REMINDER_CMD = (
    'echo \'{"hookSpecificOutput":{"hookEventName":"PostToolUse",'
    '"additionalContext":"Code da thay doi trong turn nay. Neu day la coding task: '
    'neu co active goal thi auto_trigger se tu check goal alignment. Hay goi mcp__agent-harness__auto_trigger voi changed_files/task/stage=post_edit/mode=max, roi goi goal_supervisor de lay next_action. '
    'Neu task hoi deploy/release/production-ready thi goi prod_readiness_gate mode=max; chi claim prod-ready khi verdict=ready_to_deploy. '
    'Truoc khi bao hoan thanh, goi auto_trigger stage=final mode=max hoac panel_review MOT LAN tren '
    'toan bo files da sua; neu supervisor tra run_final thi goi goal_autopilot mode=complete, neu tra complete moi bao xong. Khong gui .env that vao panel_review."}}\''
)

LESSON_HOOK_CMD = _shell_join([sys.executable, str(_harness_root() / "harness_hook.py")])


def _read_md(md_path: Path) -> tuple[str, str] | None:
    """Đọc file markdown, trả về (content, write_encoding). None nếu không đọc được.
    write_encoding là encoding để ghi lại nhằm giữ nguyên BOM/encoding gốc.
    """
    try:
        raw = md_path.read_bytes()
    except OSError as e:
        print(f"[error] Khong doc duoc {md_path} ({e}).")
        return None
    # UTF-16 LE/BE BOM
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    # UTF-8 BOM — trả về utf-8-sig để write_text tái tạo BOM
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8"), "utf-8-sig"
    # Plain UTF-8
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        print(f"[error] {md_path} khong doc duoc (encoding khong phai UTF-8/UTF-16). Chuyen sang UTF-8 roi chay lai.")
        return None


def _end_marker_for(marker: str) -> str:
    return marker.replace("<!-- ", "<!-- /", 1)


def _find_marker_line(content: str, marker: str, start_at: int = 0) -> int:
    offset = 0
    fence_char: str | None = None
    fence_len = 0
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            current_char = stripped[0]
            current_len = len(stripped) - len(stripped.lstrip(current_char))
            remainder = stripped[current_len:]
            if fence_char is None:
                fence_char = current_char
                fence_len = current_len
            elif current_char == fence_char and current_len >= fence_len and remainder.strip() == "":
                fence_char = None
                fence_len = 0
        if offset >= start_at and fence_char is None and stripped == marker:
            return offset
        offset += len(line)
    return -1


def _replace_managed_section(content: str, marker: str, section: str) -> tuple[str, bool]:
    end_marker = _end_marker_for(marker)
    if end_marker not in section:
        section = section.rstrip() + "\n" + end_marker + "\n"
    start = _find_marker_line(content, marker)
    if start == -1:
        return content.rstrip() + "\n\n" + section, False
    end = _find_marker_line(content, end_marker, start + len(marker))
    if end != -1:
        tail_start = end + len(end_marker)
        return content[:start].rstrip() + "\n\n" + section + "\n\n" + content[tail_start:].lstrip(), True
    # Managed block is corrupt/incomplete. Preserve user content and force a
    # manual repair instead of guessing that the block extends to EOF.
    return content, False


def _strip_managed_section(content: str, marker: str) -> tuple[str, bool]:
    end_marker = _end_marker_for(marker)
    current = content
    removed = False
    while True:
        start = _find_marker_line(current, marker)
        if start == -1:
            return ((current.strip() + "\n") if removed else current), removed
        end = _find_marker_line(current, end_marker, start + len(marker))
        if end == -1:
            raise ValueError(f"Managed section {marker} is missing end marker {end_marker}; keeping file unchanged")
        tail_start = end + len(end_marker)
        current = (current[:start].rstrip() + "\n\n" + current[tail_start:].lstrip()).strip() + "\n"
        removed = True


def merge_claude_md(claude_dir: Path) -> int:
    md_path = claude_dir / "CLAUDE.md"
    if md_path.exists():
        result = _read_md(md_path)
        if result is None:
            return 1
        content, enc = result
        stripped, replaced = _strip_managed_section(content, CLAUDE_MARKER)
        new_content = CLAUDE_MD_SECTION.rstrip() + "\n\n" + stripped.lstrip()
        try:
            _atomic_write_text(md_path, new_content, encoding=enc)
        except OSError as e:
            print(f"[error] Khong ghi duoc CLAUDE.md ({e}). Kiem tra quyen ghi hoac dung luong dia.")
            return 1
        print("[ok]   Da cap nhat section agent-harness trong CLAUDE.md" if replaced else "[ok]   Da append section agent-harness vao CLAUDE.md")
    else:
        try:
            _atomic_write_text(md_path, CLAUDE_MD_SECTION, encoding="utf-8")
        except OSError as e:
            print(f"[error] Khong tao duoc ~/.claude/CLAUDE.md ({e}).")
            return 1
        print("[ok]   Da tao ~/.claude/CLAUDE.md")
    return 0


def _read_settings(st_path: Path) -> tuple[dict, int]:
    """Đọc settings.json, trả về (dict, error_code). error_code=1 nếu fail."""
    try:
        raw = st_path.read_bytes()
        # Detect encoding by BOM: UTF-16 LE/BE, UTF-8 BOM, plain UTF-8
        if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
            text = raw.decode("utf-16")
        elif raw[:3] == b"\xef\xbb\xbf":
            text = raw.decode("utf-8-sig")
        else:
            text = raw.decode("utf-8")
        data = json.loads(text)
    except OSError as e:
        print(f"[error] Khong doc duoc {st_path} ({e}). Kiem tra quyen doc.")
        return {}, 1
    except UnicodeDecodeError as e:
        print(f"[error] {st_path} khong doc duoc ({e}). Luu lai file voi encoding UTF-8 roi chay lai.")
        return {}, 1
    except json.JSONDecodeError as e:
        print(f"[error] {st_path} khong phai JSON hop le ({e}). Sua tay roi chay lai.")
        return {}, 1

    # Validate schema — hooks phai la dict, PostToolUse phai la list
    if not isinstance(data, dict):
        print(f"[error] {st_path} root phai la object JSON. Sua tay roi chay lai.")
        return {}, 1
    if "hooks" in data:
        if not isinstance(data["hooks"], dict):
            print(f"[error] {st_path}: 'hooks' phai la object, hien la {type(data['hooks']).__name__}. Sua tay roi chay lai.")
            return {}, 1
        if "PostToolUse" in data["hooks"] and not isinstance(data["hooks"]["PostToolUse"], list):
            print(f"[error] {st_path}: 'hooks.PostToolUse' phai la array. Sua tay roi chay lai.")
            return {}, 1
    return data, 0


def merge_settings_json(claude_dir: Path) -> int:
    st_path = claude_dir / "settings.json"
    settings: dict = {}
    if st_path.exists():
        settings, err = _read_settings(st_path)
        if err:
            return err

    # Defensive: hooks phải là dict, PostToolUse phải là list
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(f"[error] settings.json: 'hooks' phai la object, hien la {type(hooks).__name__}. Sua tay roi chay lai.")
        return 1
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        print("[error] settings.json: 'hooks.PostToolUse' phai la array. Sua tay roi chay lai.")
        return 1
    prompt_hooks = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(prompt_hooks, list):
        print("[error] settings.json: 'hooks.UserPromptSubmit' phai la array. Sua tay roi chay lai.")
        return 1

    # Idempotency: nhận diện theo id (ổn định) hoặc theo command (legacy/không có id)
    _cmd_norm = " ".join(HOOK_REMINDER_CMD.split())  # normalize whitespace cho compare

    def _is_existing_hook(e: dict) -> bool:
        sub = e.get("hooks", [])
        has_command = (
            isinstance(sub, list)
            and any(isinstance(h, dict)
                    and " ".join((h.get("command") or "").split()) == _cmd_norm
                    for h in sub)
        )
        if e.get("id") == HOOK_ID:
            return has_command
        # fallback: cùng matcher + command (so sánh sau normalize whitespace) → hook cũ chưa có id
        return (e.get("matcher") == "Edit|Write|NotebookEdit"
                and has_command)

    changed = False
    if any(isinstance(e, dict) and _is_existing_hook(e) for e in post):
        print("[skip] Hook nhac Auto-Pilot da ton tai trong settings.json")
    else:
        post.append({
            "id": HOOK_ID,
            "matcher": "Edit|Write|NotebookEdit",
            "hooks": [{
                "type": "command",
                "command": HOOK_REMINDER_CMD,
                "timeout": 10,
                "suppressOutput": True,
            }],
        })
        changed = True

    def _is_existing_lesson_hook(e: dict) -> bool:
        sub = e.get("hooks", [])
        if not isinstance(sub, list):
            return False
        has_command = any(
            isinstance(h, dict)
            and h.get("type") == "command"
            and _norm_command(h.get("command")) == _norm_command(LESSON_HOOK_CMD)
            for h in sub
        )
        return has_command if e.get("id") == LESSON_HOOK_ID else has_command

    post_before_filter = len(post)
    prompt_before_filter = len(prompt_hooks)
    post[:] = [
        e for e in post
        if not (isinstance(e, dict)
                and e.get("id") in {HOOK_ID, LESSON_HOOK_ID}
                and not (_is_existing_hook(e) if e.get("id") == HOOK_ID else _is_existing_lesson_hook(e)))
    ]
    prompt_hooks[:] = [
        e for e in prompt_hooks
        if not (isinstance(e, dict)
                and e.get("id") == LESSON_HOOK_ID
                and not _is_existing_lesson_hook(e))
    ]
    removed_malformed_managed = len(post) != post_before_filter or len(prompt_hooks) != prompt_before_filter

    if any(isinstance(e, dict) and _is_existing_lesson_hook(e) for e in post):
        print("[skip] Hook ghi lesson da ton tai trong settings.json")
    else:
        post.append({
            "id": LESSON_HOOK_ID,
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [{
                "type": "command",
                "command": LESSON_HOOK_CMD,
                "timeout": 10,
                "suppressOutput": True,
            }],
        })
        changed = True

    if any(isinstance(e, dict) and _is_existing_lesson_hook(e) for e in prompt_hooks):
        print("[skip] Hook prompt lesson da ton tai trong settings.json")
    else:
        prompt_hooks.append({
            "id": LESSON_HOOK_ID,
            "hooks": [{
                "type": "command",
                "command": LESSON_HOOK_CMD,
                "timeout": 10,
                "suppressOutput": True,
            }],
        })
        changed = True

    if removed_malformed_managed:
        changed = True

    if not changed:
        return 0

    try:
        _write_json(st_path, settings)
    except OSError as e:
        print(f"[error] Khong ghi duoc settings.json ({e}). Kiem tra quyen ghi hoac dung luong dia.")
        return 1

    print("[ok]   Da cap nhat hooks agent-harness trong settings.json")
    return 0


def configure_claude_mcp(claude_dir: Path) -> int:
    path = claude_dir / "claude_mcp_config.json"
    data, err = _read_json_object(path, "Claude MCP config")
    if err:
        return err
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        print(f"[error] {path}: 'mcpServers' phai la object, hien la {type(servers).__name__}. Giu nguyen file.")
        return 1
    servers["agent-harness"] = {
        "command": sys.executable,
        "args": [_harness_server()],
        "env": {"PYTHONPATH": str(_harness_root())},
    }
    try:
        _write_json(path, data)
    except OSError as e:
        print(f"[error] Khong ghi duoc Claude MCP config ({e}).")
        return 1
    print("[ok]   Da cau hinh Claude MCP agent-harness dung path hien tai")
    return 0


def configure_gemini_mcp(gemini_dir: Path) -> int:
    for rel in ("config/mcp_config.json", "antigravity-ide/mcp_config.json"):
        path = gemini_dir / rel
        data, err = _read_json_object(path, f"Gemini MCP config {rel}")
        if err:
            return err
        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            print(f"[error] {path}: 'mcpServers' phai la object, hien la {type(servers).__name__}. Giu nguyen file.")
            return 1
        servers["agent-harness"] = {
            "command": sys.executable,
            "args": [_harness_server()],
            "env": {"PYTHONPATH": str(_harness_root())},
        }
        try:
            _write_json(path, data)
        except OSError as e:
            print(f"[error] Khong ghi duoc Gemini MCP config {path} ({e}).")
            return 1
    print("[ok]   Da cau hinh Gemini/Antigravity MCP agent-harness dung path hien tai")
    return 0


def configure_codex_mcp(home: Path | None = None) -> int:
    path = _home_dir(home) / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    server_path = _harness_server().replace("\\", "/")
    block = (
        '[mcp_servers.agent-harness]\n'
        f'command = {_toml_basic_string(sys.executable)}\n'
        f'args = [ {_toml_basic_string(server_path)} ]\n'
    )
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"[error] Khong doc duoc Codex MCP config {path} ({e}). Giu nguyen file.")
            return 1
    else:
        content = ""
    import re
    pattern = r'(?ms)^\s*\[mcp_servers\.(?:"agent-harness"|agent-harness)\]\s*(?:#.*)?\n.*?(?=^\s*\[|\Z)'
    if re.search(pattern, content):
        content = re.sub(pattern, lambda _m: block + "\n", content)
    else:
        content = content.rstrip() + "\n\n" + block
    try:
        _atomic_write_text(path, content)
    except OSError as e:
        print(f"[error] Khong ghi duoc Codex MCP config {path} ({e}).")
        return 1
    print("[ok]   Da cau hinh Codex MCP agent-harness dung path hien tai")
    return 0


def configure_codex_hooks(home: Path | None = None) -> int:
    path = _home_dir(home) / ".codex" / "hooks.json"
    data, err = _read_json_object(path, "Codex hooks config")
    if err:
        return err
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(f"[error] {path}: 'hooks' phai la object, hien la {type(hooks).__name__}. Giu nguyen file.")
        return 1
    post = hooks.setdefault("PostToolUse", [])
    if not isinstance(post, list):
        print(f"[error] {path}: 'hooks.PostToolUse' phai la array, hien la {type(post).__name__}. Giu nguyen file.")
        return 1
    prompt_hooks = hooks.setdefault("UserPromptSubmit", [])
    if not isinstance(prompt_hooks, list):
        print(f"[error] {path}: 'hooks.UserPromptSubmit' phai la array, hien la {type(prompt_hooks).__name__}. Giu nguyen file.")
        return 1

    def _lesson_hook_exists(entries: list) -> bool:
        return any(
            isinstance(e, dict)
            and (
                any(
                    isinstance(h, dict)
                    and h.get("type") == "command"
                    and _norm_command(h.get("command")) == _norm_command(LESSON_HOOK_CMD)
                    for h in (e.get("hooks") if isinstance(e.get("hooks"), list) else [])
                )
            )
            for e in entries
        )

    post_before_filter = len(post)
    prompt_before_filter = len(prompt_hooks)
    post[:] = [
        e for e in post
        if not (isinstance(e, dict) and e.get("id") == LESSON_HOOK_ID and not _lesson_hook_exists([e]))
    ]
    prompt_hooks[:] = [
        e for e in prompt_hooks
        if not (isinstance(e, dict) and e.get("id") == LESSON_HOOK_ID and not _lesson_hook_exists([e]))
    ]
    removed_malformed_managed = len(post) != post_before_filter or len(prompt_hooks) != prompt_before_filter

    changed = removed_malformed_managed
    if not _lesson_hook_exists(post):
        post.append({
            "id": LESSON_HOOK_ID,
            "matcher": "Edit|Write|MultiEdit|NotebookEdit",
            "hooks": [{
                "type": "command",
                "command": LESSON_HOOK_CMD,
                "timeout": 10,
            }],
        })
        changed = True
    if not _lesson_hook_exists(prompt_hooks):
        prompt_hooks.append({
            "id": LESSON_HOOK_ID,
            "hooks": [{
                "type": "command",
                "command": LESSON_HOOK_CMD,
                "timeout": 10,
            }],
        })
        changed = True
    if changed:
        try:
            _write_json(path, data)
        except OSError as e:
            print(f"[error] Khong ghi duoc Codex hooks config {path} ({e}).")
            return 1
        print("[ok]   Da cau hinh Codex hooks ghi/inject lesson")
    else:
        print("[skip] Codex hooks ghi/inject lesson da ton tai")
    return 0


CODEX_PROFILE_POLICY_SECTION = f"""\
<!-- agent-harness-runtime-profile-policy -->
# Agent Harness Runtime Profile Policy

Quy tắc này áp dụng cho Codex và mọi agent đọc `AGENTS.md`. Profile global trong `%USERPROFILE%\\.agent-harness\\harness.features.json` thắng mọi rule tự động khác.

{_shared_rule_source_note()}

{_runtime_profile_policy("harness-toggle.bat status/list/json")}

{COMMON_DISTILLED_INTEGRATIONS}
<!-- /agent-harness-runtime-profile-policy -->
"""


def merge_codex_agents(home: Path | None = None) -> int:
    root_home = _home_dir(home)
    had_error = False
    for path in (root_home / ".codex" / "AGENTS.md", root_home / "AGENTS.md"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            result = _read_md(path)
            if result is None:
                had_error = True
                continue
            content, enc = result
            stripped, replaced = _strip_managed_section(content, CODEX_PROFILE_MARKER)
            new_content = CODEX_PROFILE_POLICY_SECTION.rstrip() + "\n\n" + stripped.lstrip()
            try:
                _atomic_write_text(path, new_content, encoding=enc)
            except OSError as e:
                print(f"[error] Khong ghi duoc {path} ({e}).")
                had_error = True
                continue
            print(f"[ok]   {'Da cap nhat' if replaced else 'Da append'} runtime profile policy trong {path}")
        else:
            try:
                _atomic_write_text(path, CODEX_PROFILE_POLICY_SECTION, encoding="utf-8")
            except OSError as e:
                print(f"[error] Khong tao duoc {path} ({e}).")
                had_error = True
                continue
            print(f"[ok]   Da tao {path} voi runtime profile policy")
    return 1 if had_error else 0


GEMINI_MD_SECTION = f"""\
<!-- agent-harness -->
# Agent Harness — quy trình khi làm coding task

Có MCP server `agent-harness` (12 model trên 9Router Proxy) hỗ trợ coding. Khi nhận task viết/sửa code, áp dụng quy tắc sau:

{_shared_rule_source_note()}

{_runtime_profile_policy("status/list/json")}

## Auto-Pilot — mặc định bật

- Khi user đưa prompt coding task có nhiều bước hoặc không xong ngay bằng một edit nhỏ: gọi `goal_autopilot` với `mode="init"` và `goal="<nguyên prompt user>"` trước khi code. Tool này chia goal thành parts nhỏ. Làm từng part theo thứ tự; sau mỗi batch edit, `auto_trigger(mode="max")` sẽ chạy full harness checks song song kèm goal alignment, rồi gọi `goal_supervisor(last_checks=<auto_trigger result>, changed_files=[...], diff="<nếu có>")` để lấy next_action cứng: `continue_part`, `run_check`, `run_final`, `blocked_ask_user`, hoặc `complete`.
- Khi user muốn nhập prompt trực tiếp cho harness tự lái từ đầu đến cuối, hoặc nói "không phụ thuộc client tự gọi tool": dùng `goal_runner(prompt="<nguyên prompt>", mode="max")`. Tool này tự init goal, gọi agent CLI nếu có, chạy `auto_trigger`, hỏi `goal_supervisor`, rồi final qua `prod_readiness_gate`.
- Khi user hỏi "đã nạp chưa", "harness ổn chưa", cài qua agent nào, MCP config có drift không, context có đủ/tiết kiệm không, hoặc cần benchmark/resume: dùng ops tools tương ứng `harness_doctor`, `install_manifest`, `adapter_parity_doctor`, `mcp_inventory`, `context_budget`, `context_auditor`, `ask_codebase_health`, `goal_runner_control`, `run_ledger`, `policy_profile`, `agent_adapters`, `benchmark_runner`, `patch_safety_check`.
- Ưu tiên next_action từ `goal_supervisor`: `continue_part` = code tiếp part hiện tại; `run_check` = gọi lại `auto_trigger`/goal check sau khi sửa; `run_final` = gọi `goal_autopilot(mode="complete", ...)`; `blocked_ask_user` = dừng và hỏi user quyết định; `complete` = được báo hoàn thành.
- Sau mọi batch Edit/Write đáng kể, gọi `auto_trigger` với `changed_files`, `task`, `stage="post_edit"`, `mode="max"`. Tool này tự chạy secret/env/config/devops/complexity/dead-code/duplicate/panel_review theo context.
- Khi user hỏi deploy/release/production-ready hoặc trước khi nói "sẵn sàng lên prod": gọi `prod_readiness_gate(changed_files=[...], task="<prompt>", mode="max")`. Chỉ được claim prod-ready khi verdict là `ready_to_deploy`; `deploy_then_verify` cần nói rõ bước verify sau deploy; `fix_required` thì sửa rồi chạy lại; `blocked_needs_user` thì hỏi user; `rollback_required` thì dừng deploy/rollback nếu đã deploy.
- Trước khi báo hoàn thành, nếu có active goal thì gọi `goal_supervisor(...)` trước; chỉ gọi `goal_autopilot(mode="complete", changed_files=[...], diff="<nếu có>", context="<summary>")` khi supervisor trả `run_final`, và chỉ báo xong khi supervisor trả `complete`. Nếu không có active goal, gọi lại `auto_trigger` với `stage="final"`, `mode="max"` cho toàn bộ files đã sửa trong batch. Nếu `auto_trigger` đã chạy `panel_review` trên batch cuối thì không gọi `panel_review` riêng lần nữa.
- Goal progress summary được harness tự prepend vào context của `consult`/`panel_review`/`ask_codebase`/checks liên quan: `Goal: X | Part N/M | Last verdict: ... | Blockers: ... | Next: ...`.
- Docs-gate chỉ được tự ghi backlog hoặc tự cập nhật docs nhẹ khi phù hợp; TUYỆT ĐỐI không hỏi user kiểu "có muốn bổ sung tài liệu cho 5 prompt vừa rồi không?". User chỉ gõ prompt chính, không bị ngắt bởi maintenance docs.
- Không gửi `.env` thật vào `panel_review`; `auto_trigger` tự lọc `.env` khỏi review LLM và dùng secret/config scanners thay thế.
- Chỉ bỏ qua Auto-Pilot khi user nói rõ "khỏi review", "nhanh thôi", hoặc task chỉ sửa docs/comment/format dưới ~10 dòng.

{COMMON_DISTILLED_INTEGRATIONS}

## Bắt buộc

1. **Trước khi implement phần phức tạp** (thuật toán khó, kiến trúc mới, concurrency, auth/security, payment): gọi `consult` với câu hỏi design cụ thể + files liên quan.

2. **Sau khi viết/sửa xong code, TRƯỚC khi báo hoàn thành**: gọi `auto_trigger` (`stage="final"`, `mode="max"`) hoặc `panel_review` với danh sách files đã sửa (hoặc diff). Chạy MỘT LẦN cho cả batch thay đổi cuối. Findings critical/high phải xử lý hoặc giải thích. Panel 3 stage: Pre-pass (khi diff >200KB — SYNTHESIZER fast JSON model tóm gọn xuống ~100KB, giữ security/logic/API changes); Stage 1 song song — reviewer (code quality), security (OWASP), tester (adversarial — race condition, hidden assumption, edge case); Stage 2 sequential — integrity (data integrity: missing transaction, partial failure gap + synthesis toàn bộ findings). Output mỗi finding có field `triage`: `auto_fix` = fix mechanical (áp ngay), `ask_user` = cần developer quyết. `warnings[]` có thể chứa cảnh báo anti-consensus. `degraded: true` nếu integrity stage fail.

## Dùng khi phù hợp

3. **Debug bí** (sau 1-2 lần thử): `suggest_fix` với code + error/stack trace.
4. **Hiểu flow xuyên nhiều file**: `ask_codebase` — không cần truyền `files`, tự tìm file liên quan qua index. Tối đa 15 file per query.
5. **Cần so sánh 2 hướng implement**: `alt_implementation`.
6. **Việc vặt** (fixtures, mock data, boilerplate): `quick_task`.
7. **Tìm kiếm symbol/file/hàm**: `semantic_search` — polyglot, 158 ngôn ngữ, FTS5. Index tự build lần đầu.
8. **Rebuild index sau refactor lớn**: `index_codebase` với `force=true`.

## Tự động theo context

**Tier 1:**
- `pr_generator` — task xong, có git changes chưa có PR description
- `dead_code_scanner` — sau refactor lớn hoặc xóa/đổi tên function/class/module
- `coverage_analyzer` — sau khi viết logic mới có nhánh phức tạp (>2 code paths)
- `incident_responder` — user paste log/stack trace kèm: crash, down, 500, exception, FATAL
- `secret_scanner` — trước git commit khi thêm file mới có credentials/token, khi sửa .env.example
- `env_parity_checker` — khi sửa .env.example hoặc .env; trước deploy/release
- `config_security_audit` — khi thêm file config mới, sửa .env, CORS config, hoặc trước deploy
- `devops_pipeline` — trước commit/PR: quality gate (ruff+mypy+black) để bắt lỗi lint/type trước panel_review
- `security_autofix` — sau panel_review tìm thấy Critical/High security finding

**Tier 2:**
- `migration_validator` — khi viết/sửa file trong thư mục migrations/, alembic/versions/
- `sql_query_analyzer` — khi viết ORM query mới hoặc thêm endpoint có DB access
- `openapi_spec_sync` — khi thêm/sửa route handler hoặc Pydantic model
- `breaking_change_detector` — trước khi tạo PR vào main; khi sửa public API/function signature
- `container_linter` — khi sửa Dockerfile, docker-compose.yml, hoặc trước deploy
- `ci_pipeline_validator` — khi sửa .github/workflows/ hoặc .gitlab-ci.yml
- `data_flow_taint_analyzer` — khi thêm endpoint nhận user input mới (Body, Form, Query)
- `duplicate_code_scanner` — sau khi viết module mới lớn hoặc sau refactor lớn
- `api_contract_tester` — khi thêm/sửa API endpoint
- `complexity_analyzer` — sau khi viết logic mới có >2 nhánh hoặc sau refactor lớn
- `changelog_generator` — khi user đề cập release, version bump, chuẩn bị deploy
- `schema_drift` — khi sửa Pydantic models hoặc sau refactor data layer
- `swarm_debug` — khi suggest_fix thất bại 2+ lần hoặc bug span nhiều file phức tạp
- `auto_tester` — sau panel_review có findings → sinh và chạy pytest tự động
- `dependency_upgrader` — trước release/deploy; khi requirements.txt có packages lỗi thời
- `doc_sync` — sau khi đổi signature public functions hoặc trước PR vào main
- `polyglot_reviewer` — khi codebase có >1 ngôn ngữ và files vừa sửa span nhiều ngôn ngữ
- `a11y_auditor` — khi có thay đổi HTML/JSX/CSS/template
- `dependency_graph_visualizer` — khi gặp ImportError, circular import, hoặc thêm module mới
- `release_orchestrator` — khi release/deploy/prod-ready; điều phối checklist release sau prod gate
- `provenance_checker` — trước release/deploy; kiểm commit/remote/hash/SBOM/lockfile/build provenance
- `auth_matrix_auditor` — khi sửa auth/permission/API endpoint có ownership/object-level access
- `incremental_refactor_guard` — sau refactor lớn, rename/delete public symbol, hoặc multi-file refactor
- `harness_trace_viewer` — khi harness timeout/rate-limit/trace/log bất thường hoặc cần xem bottleneck

**Tier 3:**
- `flaky_test_detector` — khi CI thỉnh thoảng fail không rõ lý do
- `mutation_tester` — khi coverage cao nhưng nghi ngờ test không assert đúng
- `performance_regression_detector` — sau refactor function critical; khi user mention "chậm hơn trước"
- `git_archaeologist` — khi cần hiểu "tại sao code được viết vậy" trước khi sửa
- `sbom_generator` — khi chuẩn bị deploy lên production
- `feature_flag_auditor` — khi user hỏi về flags, rollout, A/B test, hoặc trước release
- `i18n_auditor` — khi có string literals mới trong UI code (không phải log/comment)
- `load_tester` — khi thêm HTTP endpoint mới và user hỏi về performance/load
- `benchmarker` — sau alt_implementation để so sánh performance 2 approach
- `visual_reviewer` — khi có thay đổi UI và app đang chạy có URL
- `telemetry_debugger` — khi user paste stack trace (bổ sung incident_responder — focus file:line + patch)

## Ngoại lệ — KHÔNG cần panel_review

- Sửa docs, comment, README, config nhỏ
- Đổi tên biến, format code, thay đổi tầm thường dưới ~10 dòng
- Fix trực tiếp từ suggestion của vòng panel_review trước + thay đổi <20 dòng
- User nói rõ bỏ qua review

## Khi harness lỗi

Nếu tool agent-harness lỗi: tiếp tục task bình thường, báo ngắn gọn cho user. Không retry quá 1 lần, không block task vì harness.

## Token efficiency

- **Grep trước, Read sau**: Grep tìm line number → Read với offset+limit chính xác.
- **Không Read lại sau Edit/Write**: tool đã confirm thành công = đủ.
- **Gom hết fix trong batch → 1 panel_review cuối**: không gọi sau mỗi file nhỏ.
<!-- /agent-harness -->
"""


def merge_gemini_md(gemini_dir: Path) -> int:
    gemini_dir.mkdir(parents=True, exist_ok=True)
    md_path = gemini_dir / "GEMINI.md"
    if md_path.exists():
        result = _read_md(md_path)
        if result is None:
            return 1
        content, enc = result
        stripped, replaced = _strip_managed_section(content, GEMINI_MARKER)
        new_content = GEMINI_MD_SECTION.rstrip() + "\n\n" + stripped.lstrip()
        try:
            _atomic_write_text(md_path, new_content, encoding=enc)
        except OSError as e:
            print(f"[error] Khong ghi duoc GEMINI.md ({e}). Kiem tra quyen ghi hoac dung luong dia.")
            return 1
        print("[ok]   Da cap nhat section agent-harness trong GEMINI.md" if replaced else "[ok]   Da append section agent-harness vao GEMINI.md")
    else:
        try:
            _atomic_write_text(md_path, GEMINI_MD_SECTION, encoding="utf-8")
        except OSError as e:
            print(f"[error] Khong tao duoc ~/.gemini/GEMINI.md ({e}).")
            return 1
        print("[ok]   Da tao ~/.gemini/GEMINI.md")
    return 0


def _merge_all(home: Path | None = None) -> int:
    root_home = _home_dir(home)
    claude_dir = root_home / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    steps = [
        lambda: merge_claude_md(claude_dir),
        lambda: merge_settings_json(claude_dir),
        lambda: configure_claude_mcp(claude_dir),
        lambda: configure_codex_mcp(root_home),
        lambda: configure_codex_hooks(root_home),
        lambda: merge_codex_agents(root_home),
    ]
    gemini_dir = root_home / ".gemini"
    steps.extend([
        lambda: merge_gemini_md(gemini_dir),
        lambda: configure_gemini_mcp(gemini_dir),
    ])
    had_error = False
    for step in steps:
        try:
            if step():
                had_error = True
        except Exception as e:
            print(f"[error] Merge step failed: {e}")
            had_error = True
    if had_error:
        print("[error] Khong ghi rules stamp vi co buoc merge/config loi. Lan lazy merge sau se retry.")
        return 1
    mark_rules_merged(claude_dir)
    return 0


@contextmanager
def _merge_file_lock(lock_path: Path, *, timeout: float = 10.0):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    lock_file = open(lock_path, "a+b")
    locked = False
    try:
        while True:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    yield None
                    return
                time.sleep(0.1)
        meta = {"pid": os.getpid(), "token": uuid.uuid4().hex, "ts": time.time(), "version": RULES_VERSION}
        lock_file.seek(0)
        lock_file.truncate()
        lock_file.write(json.dumps(meta, ensure_ascii=False).encode("utf-8"))
        lock_file.flush()
        os.fsync(lock_file.fileno())
        yield lock_file
    finally:
        if locked:
            try:
                lock_file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        lock_file.close()


def lazy_merge_if_needed(home: Path | None = None) -> bool:
    """Merge global rules once per RULES_VERSION. Never raise."""
    if not needs_update(home=home):
        return False
    lock_path = _home_dir(home) / ".claude" / ".harness_rules_merge.lock"
    try:
        with _merge_file_lock(lock_path, timeout=10.0) as lock_file:
            if lock_file is None or not needs_update(home=home):
                return False
            # MCP uses stdout for protocol frames; keep setup chatter off stdout.
            with redirect_stdout(sys.stderr):
                return _merge_all(home) == 0
    except Exception as e:
        print(f"[warn] Lazy harness rules merge skipped: {e}", file=sys.stderr)
        return False


def merge_all_locked(home: Path | None = None, *, timeout: float = 10.0) -> int:
    lock_path = _home_dir(home) / ".claude" / ".harness_rules_merge.lock"
    with _merge_file_lock(lock_path, timeout=timeout) as lock_file:
        if lock_file is None:
            print("[error] Khong lay duoc rules merge lock; thu lai sau.")
            return 1
        return _merge_all(home)


def main() -> int:
    return merge_all_locked()


if __name__ == "__main__":
    sys.exit(main())
