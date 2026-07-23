"""Setup helper — được install.ps1 gọi, hoặc chạy trực tiếp: python merge_settings.py
Merge cấu hình harness vào ~/.claude/CLAUDE.md và ~/.claude/settings.json.
Idempotent: chạy lại bao nhiêu lần cũng không tạo trùng lặp.
"""
import json
import os
import re
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
RULES_VERSION = "2026-07-23-precode-lifecycle-r1"
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

Claude/Gemini/Codex contract: không dùng profile nhớ từ prompt/repo trước. Khi chuẩn bị gọi harness tool, tự nhắc một dòng nội bộ: `active harness profile=<profile>, llm.enabled=<true/false>`. Nếu không đọc được profile thì default an toàn là `off` cho tool LLM/chạy nền. Khi `workflow_router` trả `market_research_advisor`, chỉ dùng web/LLM research nếu profile cho phép và user/task thật sự liên quan feature/UI/UX; nếu bị chặn thì báo `profile <name> đang chặn LLM/research` và đưa static checklist thay thế.

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
- `ibelick/ui-skills` đã được chưng cất thành `ui_skill_router`: trước UI/UX work rõ ràng, chọn tối đa 3 checklist nhỏ (`ui-ux-advisor`, `baseline-ui`, `fixing-accessibility`, `fixing-motion-performance`, `fixing-metadata`, `improve-ui`) thay vì nạp cả đống review. `ui-ux-advisor` là cố vấn product-design theo kiểu thị trường đang làm: anchor user job/audience/success metric, kiểm primary flow/state/microcopy/hierarchy trước khi code; baseline/a11y/motion/metadata là pre/post static guidance; `a11y_auditor` và `visual_reviewer` vẫn là post-code audits.
- Spec Kit đã được chưng cất thành spec-first bridge: khi task là feature/project/module/API/schema/auth/workflow mới hoặc đổi nhiều file, gọi `workflow_router` để lấy `ba_discovery` trước, rồi gọi `speckit_bridge(action="status" hoặc "snapshot")` trước khi plan. Nếu repo có Spec Kit artifacts/commands/skills thì dùng `/speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement` hoặc skill tương ứng; nếu chưa init thì chỉ dùng `speckit_bridge(action="init" hoặc "scaffold", allow_mutation=true)` khi profile cho phép và user/setup đã chọn rõ. Harness vẫn là lớp profile gate, checks, lessons, FinOps và final review.
- `mattpocock/skills` đã được chưng cất thành `workflow_router` + `bug_repro_guard`: feature/product/workflow/project mới đi BA discovery trước, rồi `market_research_advisor` đi research sản phẩm/đối thủ/pattern thị trường trước spec/tickets; UI/UX edit cũng đi `market_research_advisor` trước `ui_ux_advisor`; debug/bug phải có red-capable repro command/output trước khi fix; task mơ hồ lớn đi wayfinder; domain/ADR dùng CONTEXT.md; review tách Standards vs Spec; refactor lớn dùng module/interface/seam/adapter/depth vocabulary và deletion test; tests đi qua public seam.
- `kangarooking/cangjie-skill` đã được chưng cất vào lesson global promotion: procedure lesson phải qua quality gate có title/summary, actionable steps, trigger, boundary, test_prompts should-trigger/should-not-trigger/edge-case, và bị chặn nếu generic/common-sense/secret/local/debug-only.
- `integration_router` là static MCP tool để kiểm route này mà không gọi LLM hoặc mutate files. `auto_trigger` trả `integration_routes` và `workflow_routes`; `goal_runner` tự bơm guidance này vào prompt agent ngoài.
- `a11y_auditor` và `visual_reviewer` là post-code audit/check sau UI implementation, không thay thế Hallmark preflight/design bridge.
- Profile vẫn thắng: `off` chỉ được gọi bridge read-only (`status`, `preflight`, `audit_plan`, `snapshot`); không tự init/scaffold/write preflight, không gọi Hallmark/Spec Kit LLM workflow, không gọi `goal_runner`; dùng static/local fallback và báo `profile off đang chặn LLM`.
"""


def _runtime_profile_policy(off_status_command: str) -> str:
    return COMMON_RUNTIME_PROFILE_POLICY_TEMPLATE.format(off_status_command=off_status_command)


def _shared_rule_source_note() -> str:
    return f"> {SHARED_AGENT_RULE_SOURCE}"


COMMON_AUTO_PILOT_RULES = """\
## Auto-Pilot — theo runtime profile

- **Tool lifecycle bắt buộc:** `preflight_trigger` chạy TRƯỚC khi plan/code để phân bổ BA/market research/UI/spec/ask_codebase/consult/alt_implementation. Client hook như Claude `UserPromptSubmit` có thể đã inject `Harness pre-code lifecycle snapshot`; coi snapshot đó là preflight bắt buộc, không bỏ qua chỉ vì chưa tự gọi tool. `auto_trigger` chỉ chạy SAU batch edit hoặc final. Không chờ `auto_trigger` cuối mới phát hiện BA/consult/ask_codebase.
- `tool_lifecycle` là source map toàn bộ MCP tools theo phase: session_start, cross_session_coordination, orchestration_loop, preflight_before_code, during_implementation, post_edit_batch, background_watch, final_review, release_gate, memory_docs_ops. Khi phân vân tool nào chạy lúc nào, gọi static tool này trước.
- Trước mọi auto tool, đọc runtime profile global. Chọn mode như sau: `off/light/standard/balanced/review` dùng `mode="safe"`; chỉ `heavy`/`max` hoặc prompt hiện tại yêu cầu rõ full/max/prod/release mới dùng `mode="max"`. Không dùng `mode=max` chỉ vì rule cũ hoặc vì tên profile là `balanced`.
- Khi bắt đầu coding task không tầm thường: gọi `preflight_trigger(task="<prompt>", changed_files=[... nếu đã biết], mode="<safe|max theo profile>")`. Chạy/áp dụng các item `required=true` không bị profile block trước khi code: BA checklist, `ask_codebase`, `consult`, `ui_skill_router`, `hallmark_bridge`, `speckit_bridge`, `bug_repro_guard`.
- Khi user đưa prompt coding task có nhiều bước hoặc không xong ngay bằng một edit nhỏ: chỉ gọi `goal_autopilot(mode="init", goal="<nguyên prompt user>")` khi profile cho phép goal automation. Nếu hook đã báo `Harness goal lifecycle ... status=initialized_static/existing_active`, dùng active goal đó ngay và không init trùng. Làm từng part theo thứ tự; sau mỗi batch edit, gọi `auto_trigger` bằng mode được profile cho phép, rồi gọi `goal_supervisor(last_checks=<auto_trigger result>, changed_files=[...], diff="<nếu có>")` để lấy next_action cứng: `continue_part`, `run_check`, `run_final`, `blocked_ask_user`, hoặc `complete`.
- Khi user muốn nhập prompt trực tiếp cho harness tự lái từ đầu đến cuối, hoặc nói "không phụ thuộc client tự gọi tool": dùng `goal_runner(prompt="<nguyên prompt>", mode="<safe|max theo profile>")`. Tool này tự init goal, gọi agent CLI nếu có, chạy `auto_trigger`, hỏi `goal_supervisor`, rồi final qua `prod_readiness_gate` khi phù hợp.
- Ưu tiên next_action từ `goal_supervisor`: `continue_part` = code tiếp part hiện tại; `run_check` = gọi lại `auto_trigger`/goal check sau khi sửa; `run_final` = gọi `goal_autopilot(mode="complete", ...)`; `blocked_ask_user` = dừng và hỏi user quyết định; `complete` = được báo hoàn thành.
- Sau mọi batch Edit/Write đáng kể, gọi `auto_trigger` với `changed_files`, `task`, `stage="post_edit"`, `mode="<safe|max theo profile>"`. Tool này tự chạy static/risk checks theo context; không dùng nó thay BA/preflight.
- `auto_watch` chỉ được xem là `background_watch`: hậu kiểm post-edit safe/static sau debounce. Watcher không được gọi BA/market research/ask_codebase/consult/alt_implementation/panel_review/goal_runner, không tự bật LLM, không tự nâng safe lên max, và không thay thế `preflight_trigger`.
- Trước khi báo hoàn thành, nếu có active goal thì gọi `goal_supervisor(...)` trước; chỉ gọi `goal_autopilot(mode="complete", changed_files=[...], diff="<nếu có>", context="<summary>")` khi supervisor trả `run_final`, và chỉ báo xong khi supervisor trả `complete`. Nếu không có active goal, gọi `auto_trigger(stage="final", mode="<safe|max theo profile>")` hoặc `panel_review` một lần cho toàn bộ batch.
"""


def _norm_command(command: object) -> str:
    return " ".join(str(command or "").split())


CLAUDE_MD_SECTION = f"""\
<!-- agent-harness-managed -->
# Agent Harness — quy trình khi làm coding task

Có MCP server `agent-harness` (12 model trên 9Router Proxy) hỗ trợ coding. Khi nhận task viết/sửa code, áp dụng quy tắc sau:

{_shared_rule_source_note()}

{_runtime_profile_policy("status/list/json")}

## Auto-Pilot — theo runtime profile

- **Tool lifecycle bắt buộc:** `preflight_trigger` chạy TRƯỚC khi plan/code để phân bổ BA/market research/UI/spec/ask_codebase/consult/alt_implementation. Client hook như Claude `UserPromptSubmit` có thể đã inject `Harness pre-code lifecycle snapshot`; coi snapshot đó là preflight bắt buộc, không bỏ qua chỉ vì chưa tự gọi tool. `auto_trigger` chỉ chạy SAU batch edit hoặc final. Không chờ `auto_trigger` cuối mới phát hiện BA/consult/ask_codebase.
- `tool_lifecycle` là source map toàn bộ MCP tools theo phase: session_start, cross_session_coordination, orchestration_loop, preflight_before_code, during_implementation, post_edit_batch, background_watch, final_review, release_gate, memory_docs_ops. Khi phân vân tool nào chạy lúc nào, gọi static tool này trước.
- **Cross-session coordinator tự động:** đầu session/prompt mới gọi hoặc tin vào heartbeat MCP tự động `session_heartbeat`; trước khi sửa file đã biết rõ scope thì gọi `claim_files(files=[...], task="<prompt>")`; trước `auto_trigger`, `panel_review`, `prod_readiness_gate`, commit hoặc báo xong phải để `conflict_check(files=[...], stage="<phase>")` chạy. Nếu trả `blocked_conflict`, dừng, refresh diff hoặc chờ owner; không tự takeover active owner. `takeover_stale_claim` chỉ dùng khi claim stale rõ ràng. Watcher chỉ ghi event + conflict_check, không claim/merge.
- Trước mọi auto tool, đọc runtime profile global. Chọn mode như sau: `off/light/standard/balanced/review` dùng `mode="safe"`; chỉ `heavy`/`max` hoặc prompt hiện tại yêu cầu rõ full/max/prod/release mới dùng `mode="max"`. Không dùng `mode=max` chỉ vì rule cũ hoặc vì tên profile là `balanced`.
- Khi bắt đầu coding task không tầm thường: gọi `preflight_trigger(task="<prompt>", changed_files=[... nếu đã biết], mode="<safe|max theo profile>")`. Chạy/áp dụng các item `required=true` không bị profile block trước khi code: BA checklist, `ask_codebase`, `consult`, `ui_skill_router`, `hallmark_bridge`, `speckit_bridge`, `bug_repro_guard`.
- Khi user đưa prompt coding task có nhiều bước hoặc không xong ngay bằng một edit nhỏ: chỉ gọi `mcp__agent-harness__goal_autopilot(mode="init", goal="<nguyên prompt user>")` khi profile cho phép goal automation. Nếu hook đã báo `Harness goal lifecycle ... status=initialized_static/existing_active`, dùng active goal đó ngay và không init trùng. Làm từng part theo thứ tự; sau mỗi batch edit, gọi `auto_trigger` bằng mode được profile cho phép, rồi gọi `goal_supervisor(last_checks=<auto_trigger result>, changed_files=[...], diff="<nếu có>")` để lấy next_action cứng: `continue_part`, `run_check`, `run_final`, `blocked_ask_user`, hoặc `complete`.
- Khi user muốn nhập prompt trực tiếp cho harness tự lái từ đầu đến cuối, hoặc nói "không phụ thuộc client tự gọi tool": dùng `mcp__agent-harness__goal_runner(prompt="<nguyên prompt>", mode="<safe|max theo profile>")`. Tool này tự init goal, gọi agent CLI nếu có, chạy `auto_trigger`, hỏi `goal_supervisor`, rồi final qua `prod_readiness_gate` khi phù hợp.
- Khi user hỏi "đã nạp chưa", "harness ổn chưa", cài qua agent nào, MCP config có drift không, context có đủ/tiết kiệm không, hoặc cần benchmark/resume: dùng ops tools tương ứng `harness_doctor`, `install_manifest`, `adapter_parity_doctor`, `mcp_inventory`, `context_budget`, `context_auditor`, `ask_codebase_health`, `goal_runner_control`, `run_ledger`, `policy_profile`, `agent_adapters`, `benchmark_runner`, `patch_safety_check`.
- Ưu tiên next_action từ `goal_supervisor`: `continue_part` = code tiếp part hiện tại; `run_check` = gọi lại `auto_trigger`/goal check sau khi sửa; `run_final` = gọi `goal_autopilot(mode="complete", ...)`; `blocked_ask_user` = dừng và hỏi user quyết định; `complete` = được báo hoàn thành.
- Sau mọi batch Edit/Write đáng kể, gọi `mcp__agent-harness__auto_trigger` với `changed_files`, `task`, `stage="post_edit"`, `mode="<safe|max theo profile>"`. Tool này tự chạy secret/env/config/devops/complexity/dead-code/duplicate/panel_review theo context.
- `auto_watch` chỉ được xem là `background_watch`: hậu kiểm post-edit safe/static sau debounce. Watcher không được gọi BA/market research/ask_codebase/consult/alt_implementation/panel_review/goal_runner, không tự bật LLM, không tự nâng safe lên max, và không thay thế `preflight_trigger`.
- Khi user hỏi deploy/release/production-ready hoặc trước khi nói "sẵn sàng lên prod": gọi `mcp__agent-harness__prod_readiness_gate(changed_files=[...], task="<prompt>", mode="<safe|max theo profile/yêu cầu release>")`. Chỉ được claim prod-ready khi verdict là `ready_to_deploy`; `deploy_then_verify` cần nói rõ bước verify sau deploy; `fix_required` thì sửa rồi chạy lại; `blocked_needs_user` thì hỏi user; `rollback_required` thì dừng deploy/rollback nếu đã deploy.
- Trước khi báo hoàn thành, nếu có active goal thì gọi `goal_supervisor(...)` trước; chỉ gọi `goal_autopilot(mode="complete", changed_files=[...], diff="<nếu có>", context="<summary>")` khi supervisor trả `run_final`, và chỉ báo xong khi supervisor trả `complete`. Nếu không có active goal, gọi `mcp__agent-harness__auto_trigger` với `stage="final"`, `mode="<safe|max theo profile>"` cho toàn bộ files đã sửa trong batch. Nếu `auto_trigger` đã chạy `panel_review` trên batch cuối thì không gọi `panel_review` riêng lần nữa.
- Goal progress summary được harness tự prepend vào context của `consult`/`panel_review`/`ask_codebase`/checks liên quan: `Goal: X | Part N/M | Last verdict: ... | Blockers: ... | Next: ...`.
- Docs-gate chỉ được tự ghi backlog hoặc tự cập nhật docs nhẹ khi phù hợp; TUYỆT ĐỐI không hỏi user kiểu "có muốn bổ sung tài liệu cho 5 prompt vừa rồi không?". User chỉ gõ prompt chính, không bị ngắt bởi maintenance docs.
- Không gửi `.env` thật vào `panel_review`; `auto_trigger` sẽ tự lọc `.env` khỏi review LLM và dùng secret/config scanners thay thế.
- Chỉ bỏ qua Auto-Pilot khi user nói rõ "khỏi review", "nhanh thôi", hoặc task chỉ sửa docs/comment/format dưới ~10 dòng.

{COMMON_DISTILLED_INTEGRATIONS}

## Bắt buộc

1. **Trước khi implement phần phức tạp** (thuật toán khó, kiến trúc mới, concurrency, auth/security, payment): gọi `mcp__agent-harness__consult` với câu hỏi design cụ thể + files liên quan. Cân nhắc advice nhưng tự quyết định cuối cùng.

2. **Sau khi viết/sửa xong code, TRƯỚC khi báo hoàn thành**: gọi `mcp__agent-harness__auto_trigger` (`stage="final"`, `mode="<safe|max theo profile>"`) hoặc `mcp__agent-harness__panel_review` với danh sách files đã sửa (hoặc diff). Chạy MỘT LẦN cho cả batch thay đổi cuối cùng — không chạy sau mỗi edit lẻ. Findings mức critical/high phải xử lý (fix hoặc giải thích vì sao bỏ qua) trước khi chốt task.

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
    'refresh Agent Harness runtime profile snapshot truoc khi goi tool. Dung mode theo profile hien hanh: off/light/standard uu tien static-safe, balanced/review dung safe khi phu hop, heavy/max moi dung max chu dong. '
    'Bat buoc tu chay post_edit/final review/check sau batch code, khong doi user hoi profile/panel review. '
    'Neu co active goal thi auto_trigger se tu check goal alignment; goi auto_trigger voi changed_files/task/stage=post_edit va mode duoc profile cho phep, roi goi goal_supervisor de lay next_action. '
    'Neu task hoi deploy/release/production-ready thi goi prod_readiness_gate theo profile; chi claim prod-ready khi verdict=ready_to_deploy. '
    'Truoc khi bao hoan thanh, goi auto_trigger stage=final hoac panel_review MOT LAN tren '
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


def _strip_legacy_harness_section_from_agents(content: str) -> tuple[str, bool]:
    """Remove old AGENTS.md harness blocks, including malformed tail blocks.

    Older setup versions wrote a Claude-style `agent-harness-managed` block into
    AGENTS.md. Some local files lost the closing marker, so normal managed
    stripping correctly fails. In AGENTS.md this legacy block is known harness
    generated content; remove it to avoid stale Azure/57-tool rules fighting the
    current profile policy.
    """
    try:
        return _strip_managed_section(content, CLAUDE_MARKER)
    except ValueError:
        start = _find_marker_line(content, CLAUDE_MARKER)
        if start == -1:
            raise
        tail = content[start:]
        fingerprints = (
            "Có MCP server `agent-harness`",
            "Azure AI Foundry",
            "57 MCP tools",
            "## Bắt buộc",
            "## Khi harness lỗi",
        )
        if sum(1 for item in fingerprints if item in tail) < 3:
            return content, False
        next_heading = re.search(
            r"(?m)^# (?:Context Persistence|Context7|Research công nghệ|Agent Skills|Tech stack|Token efficiency|Project|Team|Repo)\b",
            tail[len(CLAUDE_MARKER):],
        )
        if next_heading:
            keep_from = start + len(CLAUDE_MARKER) + next_heading.start()
            return (content[:start].rstrip() + "\n\n" + content[keep_from:].lstrip()).strip() + "\n", True
        return content[:start].rstrip() + "\n", True


def _strip_unmarked_legacy_harness_section(content: str) -> tuple[str, bool]:
    pattern = re.compile(
        r"(?ms)^# Agent Harness — quy trình khi làm coding task\s*.*?"
        r"(?=^# (?:Context Persistence|Context7|Research công nghệ|Agent Skills|Tech stack|Token efficiency)\b|\Z)"
    )
    current = content
    removed = False
    while True:
        match = pattern.search(current)
        if not match:
            return ((current.strip() + "\n") if removed else current), removed
        legacy_block = match.group(0)
        fingerprints = (
            "Có MCP server `agent-harness`",
            "Azure AI Foundry",
            "57 MCP tools",
            "## Bắt buộc",
            "## Khi harness lỗi",
        )
        if sum(1 for item in fingerprints if item in legacy_block) < 3:
            return current, removed
        current = (current[:match.start()].rstrip() + "\n\n" + current[match.end():].lstrip()).strip() + "\n"
        removed = True


def merge_claude_md(claude_dir: Path) -> int:
    md_path = claude_dir / "CLAUDE.md"
    if md_path.exists():
        result = _read_md(md_path)
        if result is None:
            return 1
        content, enc = result
        stripped, replaced = _strip_managed_section(content, CLAUDE_MARKER)
        stripped, unmarked_legacy_replaced = _strip_unmarked_legacy_harness_section(stripped)
        replaced = replaced or unmarked_legacy_replaced
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

    def _managed_hook_entry(hook_id: str, matcher: str | None, command: str, *, suppress_output: bool = True) -> dict:
        entry = {
            "id": hook_id,
            "hooks": [{
                "type": "command",
                "command": command,
                "timeout": 10,
                "suppressOutput": suppress_output,
            }],
        }
        if matcher:
            entry["matcher"] = matcher
        return entry

    def _upsert_managed(entries: list, hook_id: str, expected: dict, is_valid) -> bool:
        changed_local = False
        kept = []
        found = False
        for entry in entries:
            managed_entry = isinstance(entry, dict) and (entry.get("id") == hook_id or is_valid(entry))
            if not managed_entry:
                kept.append(entry)
                continue
            if not found and is_valid(entry):
                kept.append(expected if entry != expected else entry)
                found = True
                changed_local = changed_local or entry != expected
            else:
                changed_local = True
        if not found:
            kept.append(expected)
            changed_local = True
        if changed_local:
            entries[:] = kept
        return changed_local

    changed = _upsert_managed(
        post,
        HOOK_ID,
        _managed_hook_entry(HOOK_ID, "Edit|Write|NotebookEdit", HOOK_REMINDER_CMD),
        _is_existing_hook,
    )

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

    changed = _upsert_managed(
        post,
        LESSON_HOOK_ID,
        _managed_hook_entry(LESSON_HOOK_ID, "Edit|Write|MultiEdit|NotebookEdit", LESSON_HOOK_CMD),
        _is_existing_lesson_hook,
    ) or changed
    changed = _upsert_managed(
        prompt_hooks,
        LESSON_HOOK_ID,
        _managed_hook_entry(LESSON_HOOK_ID, None, LESSON_HOOK_CMD),
        _is_existing_lesson_hook,
    ) or changed

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

{COMMON_AUTO_PILOT_RULES}

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
            stripped, old_managed_replaced = _strip_legacy_harness_section_from_agents(stripped)
            stripped, unmarked_legacy_replaced = _strip_unmarked_legacy_harness_section(stripped)
            replaced = replaced or old_managed_replaced or unmarked_legacy_replaced
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

## Auto-Pilot — theo runtime profile

- **Tool lifecycle bắt buộc:** `preflight_trigger` chạy TRƯỚC khi plan/code để phân bổ BA/market research/UI/spec/ask_codebase/consult/alt_implementation. Client hook như Claude `UserPromptSubmit` có thể đã inject `Harness pre-code lifecycle snapshot`; coi snapshot đó là preflight bắt buộc, không bỏ qua chỉ vì chưa tự gọi tool. `auto_trigger` chỉ chạy SAU batch edit hoặc final. Không chờ `auto_trigger` cuối mới phát hiện BA/consult/ask_codebase.
- `tool_lifecycle` là source map toàn bộ MCP tools theo phase: session_start, cross_session_coordination, orchestration_loop, preflight_before_code, during_implementation, post_edit_batch, background_watch, final_review, release_gate, memory_docs_ops. Khi phân vân tool nào chạy lúc nào, gọi static tool này trước.
- **Cross-session coordinator tự động:** đầu session/prompt mới gọi hoặc tin vào heartbeat MCP tự động `session_heartbeat`; trước khi sửa file đã biết rõ scope thì gọi `claim_files(files=[...], task="<prompt>")`; trước `auto_trigger`, `panel_review`, `prod_readiness_gate`, commit hoặc báo xong phải để `conflict_check(files=[...], stage="<phase>")` chạy. Nếu trả `blocked_conflict`, dừng, refresh diff hoặc chờ owner; không tự takeover active owner. `takeover_stale_claim` chỉ dùng khi claim stale rõ ràng. Watcher chỉ ghi event + conflict_check, không claim/merge. Coordinator DB có thể global nhưng scope theo `workspace_id = repo root + git branch`, nên không gộp conflict giữa repo khác nhau.
- Trước mọi auto tool, đọc runtime profile global. Chọn mode như sau: `off/light/standard/balanced/review` dùng `mode="safe"`; chỉ `heavy`/`max` hoặc prompt hiện tại yêu cầu rõ full/max/prod/release mới dùng `mode="max"`. Không dùng `mode=max` chỉ vì rule cũ hoặc vì tên profile là `balanced`.
- Khi bắt đầu coding task không tầm thường: gọi `preflight_trigger(task="<prompt>", changed_files=[... nếu đã biết], mode="<safe|max theo profile>")`. Chạy/áp dụng các item `required=true` không bị profile block trước khi code: BA checklist, `ask_codebase`, `consult`, `ui_skill_router`, `hallmark_bridge`, `speckit_bridge`, `bug_repro_guard`.
- Khi user đưa prompt coding task có nhiều bước hoặc không xong ngay bằng một edit nhỏ: chỉ gọi `goal_autopilot` với `mode="init"` và `goal="<nguyên prompt user>"` khi profile cho phép goal automation. Nếu hook đã báo `Harness goal lifecycle ... status=initialized_static/existing_active`, dùng active goal đó ngay và không init trùng. Làm từng part theo thứ tự; sau mỗi batch edit, gọi `auto_trigger` bằng mode được profile cho phép, rồi gọi `goal_supervisor(last_checks=<auto_trigger result>, changed_files=[...], diff="<nếu có>")` để lấy next_action cứng: `continue_part`, `run_check`, `run_final`, `blocked_ask_user`, hoặc `complete`.
- Khi user muốn nhập prompt trực tiếp cho harness tự lái từ đầu đến cuối, hoặc nói "không phụ thuộc client tự gọi tool": dùng `goal_runner(prompt="<nguyên prompt>", mode="<safe|max theo profile>")`. Tool này tự init goal, gọi agent CLI nếu có, chạy `auto_trigger`, hỏi `goal_supervisor`, rồi final qua `prod_readiness_gate` khi phù hợp.
- Khi user hỏi "đã nạp chưa", "harness ổn chưa", cài qua agent nào, MCP config có drift không, context có đủ/tiết kiệm không, hoặc cần benchmark/resume: dùng ops tools tương ứng `harness_doctor`, `install_manifest`, `adapter_parity_doctor`, `mcp_inventory`, `context_budget`, `context_auditor`, `ask_codebase_health`, `goal_runner_control`, `run_ledger`, `policy_profile`, `agent_adapters`, `benchmark_runner`, `patch_safety_check`.
- Ưu tiên next_action từ `goal_supervisor`: `continue_part` = code tiếp part hiện tại; `run_check` = gọi lại `auto_trigger`/goal check sau khi sửa; `run_final` = gọi `goal_autopilot(mode="complete", ...)`; `blocked_ask_user` = dừng và hỏi user quyết định; `complete` = được báo hoàn thành.
- Sau mọi batch Edit/Write đáng kể, gọi `auto_trigger` với `changed_files`, `task`, `stage="post_edit"`, `mode="<safe|max theo profile>"`. Tool này tự chạy `review_context_graph` static pre-pass trước, rồi secret/env/config/devops/complexity/dead-code/duplicate/panel_review theo context.
- `auto_watch` chỉ được xem là `background_watch`: hậu kiểm post-edit safe/static sau debounce. Watcher không được gọi BA/market research/ask_codebase/consult/alt_implementation/panel_review/goal_runner, không tự bật LLM, không tự nâng safe lên max, và không thay thế `preflight_trigger`.
- Khi user hỏi deploy/release/production-ready hoặc trước khi nói "sẵn sàng lên prod": gọi `prod_readiness_gate(changed_files=[...], task="<prompt>", mode="<safe|max theo profile/yêu cầu release>")`. Chỉ được claim prod-ready khi verdict là `ready_to_deploy`; `deploy_then_verify` cần nói rõ bước verify sau deploy; `fix_required` thì sửa rồi chạy lại; `blocked_needs_user` thì hỏi user; `rollback_required` thì dừng deploy/rollback nếu đã deploy.
- Trước khi báo hoàn thành, nếu có active goal thì gọi `goal_supervisor(...)` trước; chỉ gọi `goal_autopilot(mode="complete", changed_files=[...], diff="<nếu có>", context="<summary>")` khi supervisor trả `run_final`, và chỉ báo xong khi supervisor trả `complete`. Nếu không có active goal, gọi lại `auto_trigger` với `stage="final"`, `mode="<safe|max theo profile>"` cho toàn bộ files đã sửa trong batch. Nếu `auto_trigger` đã chạy `panel_review` trên batch cuối thì không gọi `panel_review` riêng lần nữa.
- Goal progress summary được harness tự prepend vào context của `consult`/`panel_review`/`ask_codebase`/checks liên quan: `Goal: X | Part N/M | Last verdict: ... | Blockers: ... | Next: ...`.
- Docs-gate chỉ được tự ghi backlog hoặc tự cập nhật docs nhẹ khi phù hợp; TUYỆT ĐỐI không hỏi user kiểu "có muốn bổ sung tài liệu cho 5 prompt vừa rồi không?". User chỉ gõ prompt chính, không bị ngắt bởi maintenance docs.
- Không gửi `.env` thật vào `panel_review`; `auto_trigger` tự lọc `.env` khỏi review LLM và dùng secret/config scanners thay thế.
- Chỉ bỏ qua Auto-Pilot khi user nói rõ "khỏi review", "nhanh thôi", hoặc task chỉ sửa docs/comment/format dưới ~10 dòng.

{COMMON_DISTILLED_INTEGRATIONS}

## Bắt buộc

1. **Trước khi implement phần phức tạp** (thuật toán khó, kiến trúc mới, concurrency, auth/security, payment): gọi `consult` với câu hỏi design cụ thể + files liên quan.

2. **Sau khi viết/sửa xong code, TRƯỚC khi báo hoàn thành**: gọi `auto_trigger` (`stage="final"`, `mode="<safe|max theo profile>"`) hoặc `panel_review` với danh sách files đã sửa (hoặc diff). Chạy MỘT LẦN cho cả batch thay đổi cuối. Findings critical/high phải xử lý hoặc giải thích. Panel 3 stage: Pre-pass (khi diff >200KB — SYNTHESIZER fast JSON model tóm gọn xuống ~100KB, giữ security/logic/API changes); Stage 1 song song — reviewer (code quality), security (OWASP), tester (adversarial — race condition, hidden assumption, edge case); Stage 2 sequential — integrity (data integrity: missing transaction, partial failure gap + synthesis toàn bộ findings). Output mỗi finding có field `triage`: `auto_fix` = fix mechanical (áp ngay), `ask_user` = cần developer quyết. `warnings[]` có thể chứa cảnh báo anti-consensus. `degraded: true` nếu integrity stage fail.

## Dùng khi phù hợp

3. **Debug bí** (sau 1-2 lần thử): `suggest_fix` với code + error/stack trace.
4. **Hiểu flow xuyên nhiều file**: `ask_codebase` — không cần truyền `files`, tự tìm file liên quan qua index. Tối đa 15 file per query.
5. **Cần so sánh 2 hướng implement**: `alt_implementation`.
6. **Việc vặt** (fixtures, mock data, boilerplate): `quick_task`.
7. **Tìm kiếm symbol/file/hàm**: `semantic_search` — polyglot, 158 ngôn ngữ, FTS5. Index tự build lần đầu.
8. **Graph review local/static**: `graph_minimal_context` trước task review/debug/refactor lớn; `review_context_graph` trước `panel_review` khi có changed files; `graph_health` khi cần hub/bridge/test-gap/dead-code hotspots. Không gọi 9Router.
9. **Rebuild index sau refactor lớn**: `index_codebase` với `force=true`.

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
- `review_context_graph` — static CRG-lite pre-pass cho changed symbols, blast radius, test gaps, risk score, token savings trước panel/PR review

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
- `graph_health` — sau refactor lớn hoặc trước architecture review để tìm hub nodes, bridge/chokepoint nodes, dead-code candidates, untested hotspots
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
        stripped, unmarked_legacy_replaced = _strip_unmarked_legacy_harness_section(stripped)
        replaced = replaced or unmarked_legacy_replaced
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
