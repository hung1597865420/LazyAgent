# Hướng Dẫn Cài Đặt và Khai Thác Kỹ Thuật Trong Agent Harness & Claude Code

Tài liệu này cung cấp hướng dẫn cài đặt, vận hành và phân tích chuyên sâu các kỹ thuật kỹ nghệ AI (AI Engineering), quản lý bộ nhớ (Memory) và bộ thư viện 13 kỹ năng tùy chỉnh (Custom Skills) đang được áp dụng trong hệ thống **Agent Harness (12-Agent support team)** kết hợp với **Claude Code**.

---

## 1. Tổng Quan Kiến Trúc & Phân Vai Agent

Hệ thống Agent Harness được xây dựng để làm "hội đồng cố vấn" hỗ trợ cho AI coder chính (**Claude Code**, **Gemini** trên Antigravity IDE). Nó cung cấp **58 MCP tools** tích hợp trực tiếp thông qua 12 AI agents chạy trên Azure AI Foundry; Auto-Pilot có thể tự gọi các scanner/reviewer phù hợp sau edit.

```
        Claude Code / Gemini (AI coder chính)
                          │
  ┌───────────────────────┴────────────────────────────┐
  ▼ (Tự động — Tier 1/2/3)                             ▼ (Gọi theo điều kiện)
MCP Server (agent-harness)                         MCP Server (agent-harness)
  │                                                    │
  ├─► panel_review     (Reviewer+Security+Tester)      ├─► consult          (Analyzer — Grok)
  ├─► secret_scanner   (entropy + regex + DOTALL)      ├─► alt_implementation(Code A/B song song)
  ├─► env_parity_checker(key diff .env vs .example)    ├─► suggest_fix      (Debugger — patch)
  ├─► complexity_analyzer(AST cyclomatic)              ├─► ask_codebase     (Manager 1M ctx)
  ├─► changelog_generator(conventional commits)        ├─► quick_task       (Worker)
  ├─► load_tester      (SSRF-safe, p50/p95/p99)        └─► dead_code_scanner, profiler, ...
  ├─► pr_generator, license_scanner, a11y_auditor, ...
  └─► incident_responder, coverage_analyzer, ...
  ▼
Web Dashboard (FastAPI + SSE) ──► http://localhost:8000
```

Các vai trò chi tiết của 12 Agent được mô tả trong bảng dưới đây:

| Tên Agent | Deployment Model | Vai trò kỹ thuật |
| :--- | :--- | :--- |
| **Manager** | `gpt-5.4-pro-3` | Q&A codebase lớn — true 1M context (2026-03-05). Trích dẫn chính xác `file:line`. |
| **Synthesizer** | `gpt-5.4-pro-2` | Long-context pre-pass summarizer cho `panel_review` khi context >200KB, giúp Manager rảnh cho `ask_codebase`. |
| **Analyzer** | `grok-4-20-reasoning` | Đề xuất giải pháp kiến trúc và phân tích trade-offs (concurrency, performance). |
| **Code A** | `Kimi-K2.6` | Code agent thứ nhất, đưa ra giải pháp triển khai tối ưu nhất. |
| **Code B** | `gpt-5.4` | Code agent thứ hai, cố ý chọn cách cài đặt khác biệt (alternative design) để so sánh. |
| **Reviewer** | `gpt-5.3-codex` | Phân tích chất lượng mã nguồn, phát hiện code smells, bugs và logic gaps. |
| **Tester** | `gpt-5.3-codex-2` | **Adversarial devil's advocate** — tìm race conditions, hidden assumptions và edge cases mà Reviewer + Security bỏ sót. Mỗi finding kèm input/scenario cụ thể làm code fail. |
| **Security** | `gpt-5.3-codex-3` | Dò quét lỗ hổng bảo mật (Injection, XSS, Secret exposure) có kèm attack vector. |
| **Integrity** | `gpt-5.3-codex-4` | **Stage 2 của panel** — chạy sau 3 reviewer: (1) tìm race condition/missing transaction/partial failure gap; (2) synthesize + dedupe toàn bộ findings. 25.77M TPM. |
| **Scanner** | `gpt-5.3-codex-4` | **Static analysis engine** — deterministic, temperature=0.0. Dùng cho các tool metric/syntactic: `dead_code_scanner`, `performance_regression_detector`. Tận dụng 25.77M TPM cho throughput cao. |
| **Debugger** | `gpt-5.4-2` | Tiếp nhận mã lỗi hoặc trace log, phân tích root cause và tạo file patch (`.diff`). |
| **Worker** | `gpt-5.4-mini` | Giải quyết tác vụ nhỏ: sinh mock data, viết docstring, boilerplate code. |

---

## 2. Hướng Dẫn Cài Đặt Full Agent Harness

> **Triết lý: setup 1 lần, mọi project dùng được.**
> MCP server đăng ký `--scope user`; `merge_settings.py` ghi quy trình vào `~/.claude/CLAUDE.md` và hooks toàn cục; `WORKSPACE_ROOT=` nên để trống để harness tự bám theo project runtime của Claude/Codex/Gemini.

### 2.1. Cần cài gì trước

| Thứ cần có | Dùng cho tính năng nào | Cách kiểm tra |
|---|---|---|
| Python 3.10+ trên `PATH` | Chạy `mcp_server.py`, `tools/*`, smoke tests | `python --version` hoặc `py -3 --version` |
| Claude Code CLI `claude` | Đăng ký MCP server `agent-harness` | `claude --version` |
| Azure AI Foundry/OpenAI key | 7 nhóm tool gọi LLM: `consult`, `panel_review`, `ask_codebase`, `suggest_fix`, `alt_implementation`, `quick_task`, `swarm_debug`, các enrichment LLM | `.env` có `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_API_KEY` |
| Responses endpoint `*.cognitiveservices.azure.com` | Model `pro`/`codex` chạy Responses API | `.env` có `AZURE_RESPONSES_ENDPOINT`, hoặc để trống để tự suy từ endpoint chính |
| Playwright Chromium | `visual_reviewer` chụp screenshot UI | `python -m playwright install chromium` |
| Git | diff, blame, changelog, PR text, isolated worktree autofix | `git --version` |
| pytest + coverage | `auto_tester`, `coverage_analyzer`, isolated patch tests | Được cài qua `requirements.txt` |
| tree-sitter-languages | `index_codebase`, `semantic_search`, `dead_code_scanner` polyglot | Được cài qua `requirements.txt` |

Dependencies Python tối thiểu nằm trong `requirements.txt`: `openai`, `python-dotenv`, `pydantic`, `mcp`, `fastapi`, `uvicorn`, `playwright`, `pytest`, `coverage`, `httpx`, `tree-sitter-languages`.

### 2.2. Chuẩn bị `.env`

Tạo `.env` từ `.env.example` rồi điền credentials thật. Không commit `.env`.
Mặc định harness đọc `.env` cạnh `mcp_server.py`; nếu cần env file khác, set `HARNESS_ENV_FILE=<path-to-harness>\.env`, hoặc set `HARNESS_DISABLE_DOTENV=1` để chỉ dùng biến môi trường đã inject.

```env
# Chat Completions / model inference endpoint
AZURE_OPENAI_ENDPOINT=https://your-resource.services.ai.azure.com/models
AZURE_OPENAI_API_KEY=your-api-key-here
AZURE_API_VERSION=2024-05-01-preview

# Responses API cho dòng pro/codex. Để trống nếu muốn tự suy từ endpoint chính.
AZURE_RESPONSES_ENDPOINT=https://your-resource.cognitiveservices.azure.com
AZURE_RESPONSES_API_VERSION=2025-04-01-preview

# 12-agent role mapping. Đổi nếu deployment name trên Azure khác mặc định.
MODEL_MANAGER=gpt-5.4-pro-3
MODEL_SYNTHESIZER=gpt-5.4-pro-2
MODEL_ANALYZER=grok-4-20-reasoning
MODEL_CODE_A=Kimi-K2.6
MODEL_CODE_B=gpt-5.4
MODEL_REVIEWER=gpt-5.3-codex
MODEL_TESTER=gpt-5.3-codex-2
MODEL_SECURITY=gpt-5.3-codex-3
MODEL_INTEGRITY=gpt-5.3-codex-4
MODEL_SCANNER=gpt-5.3-codex-4
MODEL_DEBUGGER=gpt-5.4-2
MODEL_WORKER=gpt-5.4-mini

# Fallback khi primary model bị timeout/rate-limit.
SPARE_MODELS=gpt-5.4-pro-2,gpt-5.4,gpt-5.4-2,gpt-5.3-codex-4,gpt-5.4-3,gpt-5.4-4,gpt-4.1-mini

# Để trống để MCP scope user tự dùng project đang mở.
WORKSPACE_ROOT=

# Auto features.
HARNESS_AUTO_PILOT=1
HARNESS_AUTO_MODE=max
HARNESS_STATIC_LLM=1
HARNESS_AUTO_WATCH=1
HARNESS_AUTO_WATCH_INTERVAL=3
HARNESS_AUTO_WATCH_DEBOUNCE=2
```

Nếu chỉ muốn static tools chạy nhanh và ít tốn token, đặt `HARNESS_STATIC_LLM=0`. Nếu muốn vắt tối đa panel/enrichment, giữ `HARNESS_STATIC_LLM=1`.

### 2.3. Cài tự động trên Windows

Mở PowerShell ngay trong folder harness rồi chạy:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Script làm đúng 4 bước:
1. Check `python`/`py`, check `claude`, check `.env`.
2. Chạy `python -m pip install -r requirements.txt` và `python -m playwright install chromium`.
3. Chạy `claude mcp remove --scope user agent-harness` rồi `claude mcp add --scope user agent-harness -- <python> <folder>\mcp_server.py` để idempotent.
4. Chạy `python merge_settings.py` và `python smoke_test.py`.

Sau đó restart Claude Code và gõ:

```text
/mcp
```

Kỳ vọng thấy `agent-harness` connected. Nếu client là Codex hoặc một MCP client có lazy/deferred tools, tool có thể chưa hiện hết ngay; dùng discovery/search theo tên tool hoặc capability, ví dụ `a11y_auditor`, rồi namespace `mcp__agent_harness__...` mới được expose.

### 2.4. Cài thủ công trên macOS/Linux/WSL

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
claude mcp remove --scope user agent-harness || true
claude mcp add --scope user agent-harness -- python "/absolute/path/to/mcp_server.py"
python merge_settings.py
python smoke_test.py
```

Nếu dùng `uv`, `conda`, hoặc venv riêng, thay `python` trong lệnh `claude mcp add` bằng đường dẫn Python thật của environment đó. MCP server sẽ chạy bằng đúng interpreter được đăng ký.

### 2.5. Enable đủ tính năng

| Tính năng | Bật bằng gì | Verify nhanh |
|---|---|---|
| MCP tool registry | `claude mcp add --scope user agent-harness -- python mcp_server.py` | `/mcp`, hoặc gọi `list_agents` |
| Global workflow rules | `python merge_settings.py` | Kiểm tra `~/.claude/CLAUDE.md` có block `agent-harness` |
| Hook nhắc review | `python merge_settings.py` | Sửa code xong Claude được nhắc gọi `panel_review` |
| Auto-Pilot | `.env`: `HARNESS_AUTO_PILOT=1`, `HARNESS_AUTO_MODE=max` | Gọi `auto_trigger(changed_files=[...], stage="post_edit")` |
| Auto-Watch daemon | `.env`: `HARNESS_AUTO_WATCH=1`; MCP tự spawn watcher nền đúng project bằng `pythonw`/no-window khi tool đầu tiên được gọi | Xem `.harness_auto_watch.log` |
| Local/global llmwiki | Local wiki tự bootstrap `llmwiki/raw` + `wiki/*` lần đầu; copy seed vào `~/.claude/llmwiki` nếu muốn share global knowledge | `wiki_query("jwt")`, `wiki_lint` |
| Code index polyglot | `tree-sitter-languages` + `index_codebase` | `semantic_search("panel_review")` |
| Visual review | Playwright Chromium | `visual_reviewer(url="http://localhost:3000")` |
| Test/coverage | pytest + coverage | `coverage_analyzer` |
| Security/config scan | `.env.example` đầy đủ, repo không commit secrets | `secret_scanner`, `env_parity_checker`, `config_security_audit` |
| FinOps | SQLite file `.harness_finops.db` tự tạo | `finops_stats` |
| Web dashboard tùy chọn | `python server.py` | Mở `http://localhost:8000` |

### 2.6. Danh mục đủ 58 MCP tools và cần chuẩn bị gì

| Nhóm | Tools | Phụ thuộc chính | Khi dùng |
|---|---|---|---|
| Orchestration | `auto_trigger`, `run_single_agent`, `list_agents` | MCP connected, `.env` nếu gọi agent LLM | Auto-Pilot, gọi thẳng agent, xem model mapping |
| Deep reasoning/review | `consult`, `alt_implementation`, `panel_review`, `suggest_fix`, `quick_task`, `ask_codebase`, `swarm_debug` | Azure models, `SPARE_MODELS`, workspace files | Design, alternative implementation, review cuối, debug bí, việc vặt, hỏi codebase |
| Security fix loop | `security_autofix`, `auto_tester`, `run_in_sandbox` | Git worktree, pytest, Azure debugger/tester | Auto-fix Critical/High security finding, sinh test, chạy reproducer cô lập |
| Wiki/memory | `wiki_ingest`, `wiki_query`, `wiki_lint`, `doc_sync` | `llmwiki/raw`, `llmwiki/wiki`, README | Ingest knowledge, tìm concept/entity, lint wiki, đồng bộ docs |
| Static/code index | `index_codebase`, `semantic_search`, `dead_code_scanner`, `dependency_graph_visualizer` | tree-sitter-languages, SQLite cache | Search polyglot, dead code, import graph/cycle |
| Security/config | `secret_scanner`, `config_security_audit`, `env_parity_checker`, `data_flow_taint_analyzer` | `.env.example`, source files | Secrets, CORS/env drift, taint user input to dangerous sinks |
| Quality gates | `devops_pipeline`, `complexity_analyzer`, `duplicate_code_scanner`, `polyglot_reviewer` | ruff/flake8/mypy/black optional fallback, AST/LLM | Pre-PR quality, complexity, copy-paste, language-specific review |
| API/data contracts | `api_contract_tester`, `openapi_spec_sync`, `schema_drift`, `breaking_change_detector`, `migration_validator`, `sql_query_analyzer` | pytest, OpenAPI/Pydantic/ORM/migrations if present | Endpoint contract, schema drift, breaking changes, DB migration/query risk |
| Testing/resilience/perf | `coverage_analyzer`, `flaky_test_detector`, `mutation_tester`, `load_tester`, `chaos_tester`, `benchmarker`, `profiler`, `performance_regression_detector` | pytest, coverage, httpx, cProfile/tracemalloc, Git diff | Test coverage, flaky/mutation, load/chaos, benchmark/profile/regression |
| UI/product docs | `visual_reviewer`, `a11y_auditor`, `i18n_auditor`, `pr_generator`, `changelog_generator` | Playwright for screenshots, HTML/CSS/JSX files, Git log/diff | UI screenshot audit, WCAG, hardcoded strings, PR/changelog |
| Supply chain/release | `dependency_upgrader`, `license_scanner`, `sbom_generator`, `container_linter`, `ci_pipeline_validator`, `feature_flag_auditor` | requirements/package files, Docker/CI files, Git | Upgrade dry-run, license/SBOM, Docker/CI lint, stale flags |
| Incident/intel | `incident_responder`, `telemetry_debugger`, `git_archaeologist`, `finops_stats` | Logs/stack traces, Git blame, `.harness_finops.db` | Incident triage, stack trace patch hint, why code changed, cost/token stats |

### 2.7. Cách “cày” kiểm tra sau khi cài

Chạy theo thứ tự này để biết full harness đã hoạt động:

1. **Smoke offline:** `python smoke_test.py`.
2. **MCP handshake:** restart client, `/mcp`, thấy `agent-harness connected`.
3. **Registry:** gọi `list_agents`; phải thấy 12 role và model deployment.
4. **Static tools không tốn token:** gọi `index_codebase(force=true)`, `semantic_search("mcp server")`, `secret_scanner(paths=[".env.example"])`.
5. **Azure LLM path:** gọi `quick_task(instruction="Trả lời một câu ngắn: harness OK")`.
6. **Review path:** tạo diff nhỏ rồi gọi `panel_review(files=["file_vua_sua.py"])`.
7. **Visual path:** chạy app local rồi gọi `visual_reviewer(url="http://localhost:<port>")`.
8. **Wiki path:** gọi `wiki_query("keyword")`; project mới sẽ tự tạo `llmwiki/` và auto-ingest docs sẵn có.
9. **Auto path:** gọi `auto_trigger(changed_files=["src/app.py"], task="verify install", stage="post_edit", mode="safe")`.
10. **FinOps:** gọi `finops_stats` để chắc LLM calls được log.

### 2.8. Troubleshooting nhanh

| Triệu chứng | Nguyên nhân hay gặp | Cách sửa |
|---|---|---|
| `/mcp` không thấy `agent-harness` | Chưa restart client hoặc `claude mcp add` dùng sai Python/path | Chạy lại installer, dùng absolute path tới `mcp_server.py` |
| Tool như `a11y_auditor` không hiện trong list | Client lazy-load/deferred tool exposure | Search đúng capability/tool name; namespace thường là `mcp__agent_harness__a11y_auditor` |
| `ValueError: Thiếu AZURE...` | `.env` thiếu endpoint/key hoặc MCP chạy từ env khác | Đặt `.env` cạnh `mcp_server.py`, đăng ký đúng Python/interpreter |
| `panel_review`/`ask_codebase` timeout | Azure quota thấp, context quá lớn, primary model chậm | Tăng `ROLE_TIMEOUT_*`, bật `SPARE_MODELS`, giảm files/diff, dùng `HARNESS_ASK_CODEBASE_CONTEXT_BYTES` |
| `visual_reviewer` fail browser | Chưa cài Chromium | `python -m playwright install chromium` |
| Static index chậm/lỗi native package | `tree-sitter-languages` chưa cài đúng env | `python -m pip install -r requirements.txt` bằng cùng Python đã đăng ký MCP |
| Auto-Watch không chạy | Env tắt hoặc MCP chưa được gọi trong project | Đảm bảo `HARNESS_AUTO_WATCH=1`; khi bạn prompt làm coding task và harness tool chạy, watcher tự spawn theo project |
| Workspace sai project | `WORKSPACE_ROOT` bị hardcode | Để `WORKSPACE_ROOT=` trống để dùng `CLAUDE_PROJECT_DIR` runtime |

### 2.9. Local wiki có phải tạo `docs/raw` thủ công không?

Không cần nữa. Harness tự bootstrap local wiki khi MCP tool đầu tiên được gọi trong project:

1. Tạo `<project>/llmwiki/raw/processed/`.
2. Tạo `<project>/llmwiki/wiki/concepts`, `entities`, `sources`.
3. Nếu local wiki còn trống, copy seed docs phổ biến vào raw: `README*.md`, `*.md` ở root, `docs/**/*.md`, `specs/**/*.md`, `adr/**/*.md`, `architecture/**/*.md`.
4. `_kick_auto_wiki_ingest()` thấy raw pending và chạy `wiki_ingest(target="local")` nền.

Harness bỏ qua `.git`, `.Codex`, `.claude`, `llmwiki`, `node_modules`, venv/cache, `.env*`, file quá 500KB, và không overwrite file raw đã có.

### 2.10. Share luôn global knowledge base

Local wiki **không tự sync từ global** theo nghĩa copy file hai chiều. Cơ chế thật là:

```text
Khi query/inject context:
1. Đọc <project>/llmwiki/wiki trước.
2. Đọc ~/.claude/llmwiki/wiki sau.
3. Nếu trùng slug, local thắng global.
```

Vì vậy có 2 cách share knowledge:

1. **Bundled seed trong repo:** thư mục `llmwiki/` đi kèm repo là bản seed public đã scrub secret. Người nhận repo có knowledge base để dùng local ngay.
2. **Restore thành global wiki trên máy mới:** chỉ copy `llmwiki/` đã scrub/allowlist public vào `~/.claude/llmwiki/`. Không publish global wiki cá nhân nếu có token, URL nội bộ, log vận hành, khách hàng, hoặc ghi chú riêng.

Windows:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude" | Out-Null
robocopy ".\llmwiki" "$env:USERPROFILE\.claude\llmwiki" /E
```

macOS/Linux:

```bash
mkdir -p ~/.claude
rsync -a ./llmwiki/ ~/.claude/llmwiki/
```

Verify sau khi copy:

```text
wiki_lint
wiki_query("jwt")
wiki_query("xss")
```

Nếu máy đích đã có global wiki riêng, backup trước rồi merge bằng copy/rsync; local project vẫn ưu tiên khi trùng tên trang, nên project-specific knowledge không bị global ghi đè lúc runtime.

### 2.11. Dùng harness với nhiều agent chính khác nhau

Agent Harness có 3 lớp tách biệt:

| Lớp | Mục đích | File/cấu hình |
|---|---|---|
| MCP server | Cho agent chính gọi được 58 tools | `mcp_server.py` qua MCP config |
| Memory/rules | Dạy agent chính khi nào phải gọi tool | `CLAUDE.md`, `GEMINI.md`, `AGENTS.md`, `.cursor/rules`, ... |
| Knowledge wiki | Kiến thức domain dùng chung khi tool chạy | `~/.claude/llmwiki/` + `<project>/llmwiki/` |

Nói ngắn: **MCP config = tay chân**, **memory/rules = não biết dùng tay chân lúc nào**, **llmwiki = kiến thức nền dùng chung**.

#### MCP config cho từng agent

`merge_settings.py` hiện tự cấu hình 3 môi trường chính khi chạy installer:

| Agent chính | MCP config được ghi | Memory/rules được ghi |
|---|---|---|
| Claude Code | `~/.claude/claude_mcp_config.json` + `claude mcp add --scope user` | `~/.claude/CLAUDE.md` |
| Gemini / Antigravity | `~/.gemini/config/mcp_config.json`, `~/.gemini/antigravity-ide/mcp_config.json` | `~/.gemini/GEMINI.md` |
| Codex | `~/.codex/config.toml` | Project/user `AGENTS.md` hoặc Codex instructions |

MCP JSON chuẩn cho client hỗ trợ `mcpServers`:

```json
{
  "mcpServers": {
    "agent-harness": {
      "command": "python",
      "args": ["C:/path/to/harness/mcp_server.py"],
      "env": {
        "PYTHONPATH": "C:/path/to/harness"
      }
    }
  }
}
```

Codex TOML tương đương:

```toml
[mcp_servers.agent-harness]
command = "python"
args = [ "C:/path/to/harness/mcp_server.py" ]
```

Cursor/Windsurf/generic MCP clients dùng cùng server command/path ở trên. Nếu một agent chính không hỗ trợ MCP thì không gọi trực tiếp được 58 tools; cần wrapper/bridge riêng.

#### Memory/rules tối thiểu cho agent khác

Không cần copy schema của 58 tools vào rules file. Tool schema nằm trong `mcp_server.py -> list_tools()`. Rules chỉ cần policy gọi tool:

```md
# Agent Harness Usage

Use MCP server `agent-harness`.

Before coding:
- Use `consult` for design/security/auth/API/schema/concurrency decisions.
- Use `alt_implementation` for reusable modules or unclear approaches.
- Use `ask_codebase` before reading many files.

After edits:
- Use `auto_trigger` after meaningful code changes.
- Use `panel_review` once before reporting done.
- Fix or explain critical/high findings.

Contextual tools:
- UI changes -> `a11y_auditor`, `visual_reviewer`
- API changes -> `api_contract_tester`, `openapi_spec_sync`
- DB/migrations -> `migration_validator`, `sql_query_analyzer`
- Security/config -> `secret_scanner`, `config_security_audit`, `env_parity_checker`
- Release/PR -> `pr_generator`, `changelog_generator`, `sbom_generator`
```

File đích theo agent:

| Agent chính | Nơi đặt rules |
|---|---|
| Claude Code | `~/.claude/CLAUDE.md` |
| Gemini / Antigravity | `~/.gemini/GEMINI.md` |
| Codex | `AGENTS.md` hoặc instructions của Codex runtime |
| Cursor | `.cursor/rules/agent-harness.mdc` |
| Windsurf | `.windsurf/rules/agent-harness.md` |
| Agent custom | System prompt / developer instructions của agent đó |

#### Kiểm tra agent đã đọc memory/rules chưa

Sau khi đặt rules file, hỏi agent chính một câu test:

```text
Bạn đang thấy rule Agent Harness nào? Khi nào phải gọi consult/panel_review?
```

Kỳ vọng agent trả lời được:

- Có MCP server `agent-harness`.
- Trước phần design/security/concurrency/API/schema phải gọi `consult`.
- Sau batch code phải gọi `auto_trigger(stage="final")` hoặc `panel_review`.
- UI/API/DB/security/release có tool contextual riêng.

Nếu agent không trả lời đúng:

| Agent | Cách xử lý |
|---|---|
| Claude Code | Chạy lại `python merge_settings.py`, restart Claude Code, kiểm tra `~/.claude/CLAUDE.md` có block `agent-harness-managed` |
| Gemini / Antigravity | Chạy lại `python merge_settings.py`, restart IDE, kiểm tra `~/.gemini/GEMINI.md` có block `agent-harness` |
| Codex | Copy policy vào `AGENTS.md` của project hoặc user instructions mà Codex runtime thật sự đọc; reconnect session |
| Cursor | Đặt rule trong `.cursor/rules/agent-harness.mdc`, bật rule scope phù hợp, reload window |
| Windsurf | Đặt rule trong `.windsurf/rules/agent-harness.md`, reload workspace |
| Agent custom | Đưa policy vào system/developer prompt, không chỉ để trong README |

Rules file chỉ có tác dụng nếu agent chính thật sự nạp nó vào context. MCP connected nhưng rules không được đọc thì agent vẫn “có tool” nhưng không biết lúc nào phải dùng.

#### Agent không hỗ trợ MCP thì dùng bridge/wrapper

Nếu agent chính không support MCP, nó không thể gọi trực tiếp 58 tools. Có 3 hướng:

| Hướng | Khi dùng | Cách làm |
|---|---|---|
| Dùng agent hỗ trợ MCP làm runner | Muốn giữ harness nguyên bản | Chạy task qua Claude/Codex/Gemini đã kết nối MCP |
| Viết CLI bridge | Agent chỉ gọi được shell command | Tạo script nhỏ nhận `tool_name + JSON args`, gọi MCP server hoặc import `tools/*`, in JSON ra stdout |
| Viết HTTP bridge | Agent gọi được HTTP/webhook | Bọc các tool cần dùng bằng FastAPI endpoint, thêm auth key, gọi từ agent chính |

CLI bridge tối thiểu cho agent chỉ biết chạy shell:

```powershell
python harness_cli.py panel_review --files src/app.py
python harness_cli.py consult --question "Nên làm A hay B?" --files src/app.py
```

HTTP bridge tối thiểu:

```text
POST http://localhost:<port>/tool/panel_review
Authorization: Bearer <HARNESS_API_KEY>
Body: {"files":["src/app.py"]}
```

Nguyên tắc bảo mật cho bridge:

- Không expose ra public internet.
- Bắt buộc có API key nếu dùng HTTP.
- Không truyền `.env` thật vào `panel_review` hoặc LLM tools.
- Log redact token/secret.
- Giới hạn allowlist tool nếu agent ngoài chỉ cần vài tool.

#### Checklist setup máy mới cho user khác

1. Copy repo harness sang máy mới.
2. Tạo `.env` từ `.env.example` với Azure key/deployment thật. Không copy hoặc commit `.env` thật qua repo/chat/email.
3. Chạy installer:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

4. Restore global wiki nếu muốn dùng knowledge giống máy gốc:

   ```powershell
   robocopy ".\llmwiki" "$env:USERPROFILE\.claude\llmwiki" /E
   ```

5. Với agent ngoài Claude/Gemini/Codex, thêm MCP config trỏ tới `mcp_server.py`.
6. Với agent ngoài Claude/Gemini, thêm rules file tương ứng từ policy tối thiểu ở trên.
7. Nếu agent không support MCP, dùng CLI/HTTP bridge thay vì gọi MCP trực tiếp.

Sau đó user chỉ cần prompt cho agent chính. Harness tự lo phần còn lại:

- Auto-Watch tự spawn theo đúng project khi MCP tool đầu tiên được gọi, chạy nền bằng `pythonw`/no-window trên Windows.
- Project mới tự tạo local `llmwiki/raw` + `wiki/*` và auto-ingest docs có sẵn.
- Global + local wiki tự merge khi `consult`, `panel_review`, `suggest_fix`, `ask_codebase`, `wiki_query` chạy.
- Tool có thể lazy-load trong một số client; nếu không thấy ngay `a11y_auditor` hoặc tool khác, search đúng capability/tool name để client expose namespace.

---

## 3. Phân Tích Chuyên Sâu Các Kỹ Thuật AI Engineering (Backend Harness)

Codebase này triển khai nhiều kỹ thuật lập trình tích hợp mô hình ngôn ngữ lớn (LLM) nâng cao nhằm tăng cường độ tin cậy và khả năng chống lỗi. Dưới đây là phân tích chi tiết:

### Kỹ thuật 1: Adaptive Endpoint & Parameter Tuning (Thích ứng tham số API)
* **Tệp mã nguồn:** [agents.py](agents.py) tại hàm [_chat_completion](agents.py#L284-L363).

#### Thử thách
Mỗi mô hình trên Azure AI Foundry có thể yêu cầu endpoint API và tham số khác nhau:
1. Các mô hình dòng `pro` hoặc `codex` (như GPT-5.4 Pro) chỉ hỗ trợ **Responses API** (`https://<resource>.cognitiveservices.azure.com`) với tham số `instructions` thay vì `messages`.
2. Các mô hình thường (Kimi, Grok, GPT thường) chạy **Chat Completions API** (`https://<resource>.services.ai.azure.com/models`).
3. Một số mô hình lý luận (Reasoning Models) sẽ trả lỗi `BadRequestError` nếu truyền các tham số như `temperature`, `response_format`, hoặc sử dụng tên tham số token đầu ra sai cách (ví dụ `max_tokens` thay cho `max_completion_tokens`).

#### Giải pháp trong mã nguồn
Hệ thống sử dụng cơ chế tự động học (adaptive heuristics) để thăm dò và điều chỉnh cấu hình API cho từng model thông qua một cache toàn cục `_MODEL_QUIRKS`.

```python
# agents.py
_MODEL_QUIRKS: dict[str, dict[str, Any]] = {}
_model_quirks_lock = threading.Lock()  # bảo vệ concurrent init + mutation

def _quirks_for(model: str) -> dict[str, Any]:
    if not isinstance(model, str) or not model:
        raise ValueError(f"model phải là non-empty string, nhận: {model!r}")
    with _model_quirks_lock:
        if model not in _MODEL_QUIRKS:
            responses_only = "codex" in model or re.search(r"-pro(-\d+)?$", model) is not None
            _MODEL_QUIRKS[model] = {
                "api":         "responses" if responses_only else "chat",
                "api_locked":  False,  # Chỉ cho phép flip api 1 lần để tránh lặp vô hạn
                "token_param": "max_completion_tokens",
                "temperature": True,
                "json_mode":   True,
            }
        return _MODEL_QUIRKS[model]
```

Khi thực hiện yêu cầu gọi LLM trong hàm [_chat_completion](agents.py#L284-L363), nếu gặp lỗi `BadRequestError` hoặc `NotFoundError`, hệ thống sẽ bóc tách chuỗi thông báo lỗi (error message), cập nhật trạng thái "quirks" của mô hình đó và **thử lại ngay lập tức** trong cùng luồng xử lý:

```python
# agents.py:318-342
        except BadRequestError as e:
            msg = str(e).lower()
            # Nếu Chat API không được hỗ trợ -> Đổi sang Responses API
            if quirks["api"] == "chat" and "unsupported" in msg and not quirks["api_locked"]:
                quirks["api"], quirks["api_locked"] = "responses", True
                continue
            if quirks["api"] == "chat":
                # Đổi tên tham số giới hạn token
                if quirks["token_param"] == "max_completion_tokens" and "max_completion_tokens" in msg:
                    quirks["token_param"] = "max_tokens"
                    continue
                if quirks["token_param"] == "max_tokens" and "max_tokens" in msg:
                    quirks["token_param"] = "max_completion_tokens"
                    continue
                # Tắt tham số temperature nếu mô hình lý luận không hỗ trợ
                if quirks["temperature"] and "temperature" in msg:
                    quirks["temperature"] = False
                    continue
                # Tắt JSON mode nếu endpoint không hỗ trợ định dạng
                if json_mode and quirks["json_mode"] and "response_format" in msg:
                    quirks["json_mode"] = False
                    continue
            raise
```

---

### Kỹ thuật 2: Parallel Multi-Agent Orchestration & Aggregation (Xử lý song song & Tổng hợp)
* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm [panel_review](support_tools.py#L203-L281).

#### Thử thách
Việc review mã nguồn đòi hỏi nhiều khía cạnh phân tích chuyên sâu (Bugs, Security, Testing). Nếu dùng chung 1 prompt để yêu cầu một mô hình làm tất cả, chất lượng đánh giá sẽ bị loãng và bỏ sót lỗi. Tuy nhiên, nếu gọi từng mô hình một cách tuần tự (sequential) thì thời gian phản hồi (latency) sẽ quá chậm, ảnh hưởng trải nghiệm lập trình viên.

#### Giải pháp trong mã nguồn
Panel review chạy **2 stage**:

**Stage 1 — Song song** (`asyncio.gather`): 3 model codex chạy đồng thời, mỗi con chuyên 1 chiều:
1. `REVIEWER` — bugs, logic errors, anti-patterns (`gpt-5.3-codex`)
2. `SECURITY` — OWASP: injection, XSS, auth flaws, secrets (`gpt-5.3-codex-2`)
3. `TESTER` — **Adversarial devil's advocate**: tìm những gì 2 reviewer kia BỎ SÓT — race conditions, hidden assumptions, non-obvious edge cases. Mỗi finding bắt buộc kèm input/scenario cụ thể làm code fail. (`gpt-5.3-codex-3`)

```python
# tools/review.py — Stage 1
results = await asyncio.gather(*[_run_with_timeout(role) for role in panel])
```

**Pre-pass Summarizer** (khi diff/code > 200KB): MANAGER (`gpt-5.4-pro-3`, true 1M context) tóm gọn xuống ~100KB trước khi đưa vào 3 reviewer. Giữ lại: mọi thay đổi security-relevant, logic phân nhánh phức tạp, API/schema thay đổi, dependency imports, tên file + line number chính xác. Bỏ: style/whitespace/comment-only. `fast=True` → bỏ qua pre-pass.

**Stage 2 — Sequential** (`INTEGRITY`, `gpt-5.3-codex-4`, 25.77M TPM): nhận code + toàn bộ findings từ Stage 1 làm input, thực hiện 2 việc trong 1 call:
1. **Data integrity review**: race condition (TOCTOU, shared mutable state), missing transaction boundary, non-idempotent ops, partial failure gap, saga/compensation gap
2. **Synthesis**: dedupe findings từ cả 4 reviewer, sort theo severity, merge `found_by`, trả verdict cuối

Nếu Integrity fail/timeout → `degraded: true` trong output, fallback local dedup. `fast=True` → skip Integrity, warning rõ ràng.

Mỗi finding trong output có 2 trường:
* **`triage`**: `"auto_fix"` (fix mechanical — áp ngay) hoặc `"ask_user"` (cần developer quyết). Conflict → luôn `ask_user`.
* **`warnings[]`**: chứa **anti-consensus alert** khi cả panel báo clean dù diff lớn, hoặc chỉ 1 reviewer có findings.

---

### Kỹ thuật 3: Rate Limit Resilience & Dynamic Fallback Model
* **Tệp mã nguồn:** [agents.py](agents.py) tại hàm [_chat_completion](agents.py#L344-L354).

#### Thử thách
Các dịch vụ AI trên đám mây (Azure OpenAI, OpenAI) giới hạn tần suất yêu cầu trên mỗi phút (Rate Limits - HTTP 429). Khi nhiều người dùng hoặc nhiều agent chạy song song, việc chạm ngưỡng giới hạn là không thể tránh khỏi.

#### Giải pháp trong mã nguồn
1. **Exponential Backoff kết hợp Jitter:** Khi nhận mã lỗi `RateLimitError` (HTTP 429), luồng xử lý sẽ tạm dừng (`time.sleep`) với khoảng thời gian tăng dần theo lũy thừa của 2, kết hợp với một lượng trễ ngẫu nhiên (jitter) để tránh hiện tượng dồn nghẽn yêu cầu (thần bài nghẽn mạng).
2. **Dynamic Fallback Model:** Nếu đã thử lại tối đa `MAX_RETRIES` lần mà vẫn bị chặn rate limit, hệ thống sẽ tự động bóc tách danh sách mô hình dự phòng `SPARE_MODELS` đã được định nghĩa trong `.env` để chuyển sang deployment tiếp theo và reset số lần thử lại về 0.

---

### Kỹ thuật 4: Resilient JSON Output Extraction & Fallback Parser (Trích xuất JSON an toàn)
* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm [_parse_json_object](support_tools.py#L171-L189).

#### Thử thách
Dù được set tham số `response_format={"type": "json_object"}`, mô hình ngôn ngữ lớn đôi lúc vẫn bao bọc kết quả trong các khối code block của markdown (ví dụ: ` ```json { ... } ``` `) hoặc viết thêm các câu dẫn trước và sau JSON, gây lỗi cho trình phân tích cú pháp tiêu chuẩn `json.loads`.

#### Giải pháp trong mã nguồn
Hàm [_parse_json_object](support_tools.py#L171-L189) thực hiện phân tích cú pháp qua 3 tầng bảo vệ để đảm bảo luôn trích xuất được dữ liệu:

1. **Tầng 1 (Direct Parse):** Cố gắng parse trực tiếp toàn bộ chuỗi text bằng `json.loads`.
2. **Tầng 2 (Regex Extraction):** Sử dụng biểu thức chính quy (regular expression) để quét tìm khối markdown chứa định dạng json: `r"```(?:json)?\s*(\{.*?\})\s*```"`.
3. **Tầng 3 (Brace Matching):** Dò tìm vị trí dấu mở ngoặc nhọn `{` đầu tiên và dấu đóng ngoặc nhọn `}` cuối cùng trong văn bản để cắt chuỗi và phân tích.

---

### Kỹ thuật 5: Jailbreak Mitigation via Safe Path Resolution (Bảo mật Workspace)
* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm [read_workspace_files](support_tools.py#L80-L136).

#### Thử thách
Khi Claude Code chạy tự động, nó có thể gọi các MCP tool của Agent Harness và truyền vào các đường dẫn file. Nếu mô hình bị tấn công Prompt Injection (Jailbreak), tin tặc có thể lừa agent đọc các file hệ thống nhạy cảm bên ngoài thư mục dự án bằng kỹ thuật Path Traversal (ví dụ: `../../../../etc/passwd` hoặc `..\..\..\Windows\System32\cmd.exe`).

#### Giải pháp trong mã nguồn
Trước khi tiến hành đọc bất kỳ file nào từ tham số đầu vào, hệ thống thực hiện phân giải đường dẫn tuyệt đối (canonical path resolution) và kiểm tra tính bao hàm của thư mục dự án (`WORKSPACE_ROOT`):

```python
# support_tools.py:97-107
        try:
            # Phân giải đường dẫn tuyệt đối, loại bỏ các ký tự đại diện như .. hay symlink
            full = os.path.realpath(os.path.join(WORKSPACE_ROOT, p))
        except (ValueError, OSError) as e:
            warnings.append(f"{p}: không thể resolve path — {e}")
            continue
        try:
            # Kiểm định xem thư mục chung gần nhất có phải là WORKSPACE_ROOT không
            outside = os.path.commonpath([full, os.path.realpath(WORKSPACE_ROOT)]) != os.path.realpath(WORKSPACE_ROOT)
        except ValueError:
            outside = True  # Xử lý trường hợp khác phân vùng ổ đĩa trên Windows
            
        if outside:
            warnings.append(f"{p}: nằm ngoài WORKSPACE_ROOT — bỏ qua")
            continue
```

---

### Kỹ thuật 6: Server-Sent Events (SSE) for Real-Time Streaming UI
* **Tệp mã nguồn:** [server.py](server.py).

#### Thử thách
Mô hình chạy song song có thể mất từ vài giây đến hàng chục giây để xử lý xong. Nếu sử dụng Rest API truyền thống (Request-Response), giao diện web Dashboard sẽ rơi vào trạng thái đơ (loading) và lập trình viên không biết các agent đang hoạt động thế nào hoặc có bị kẹt hay không.

#### Giải pháp trong mã nguồn
FastAPI server tận dụng cơ chế streaming dữ liệu một chiều qua giao thức **Server-Sent Events (SSE)**. Mỗi bước xử lý của agent sẽ phát đi một event đến Client ngay lập tức:

```python
# server.py
# Sử dụng EventSource trên trình duyệt kết nối đến route: /api/run-pipeline
# Luồng dữ liệu truyền tải liên tục dạng generator:
# "data: {\"agent\": \"reviewer\", \"status\": \"running\"}\n\n"
```

---

## 4. Kỹ Thuật Quản Lý Bộ Nhớ (Claude's Memory & Context Persistence)

Hệ thống tận dụng cơ chế quản lý và lưu giữ ngữ cảnh theo hai tầng: **per-project** (`.claude/` trong project) và **global** (`~/.claude/`), giúp Claude Code giữ vững thông tin kiến trúc dự án và kiến thức domain dùng chung qua các phiên làm việc.

* **Tệp cấu hình toàn cục:** [CLAUDE.md](~/.claude/CLAUDE.md) tại phần **Context Persistence**.
* **Thư mục lưu trữ cục bộ:** Thư mục `.claude/` tại gốc của project hiện tại.

### A. Navigation Map (`.claude/index.md`)
* **Tệp mã nguồn ví dụ:** [.claude/index.md](.claude/index.md).

#### Giải pháp
Khi bắt đầu một project mới, Claude Code sẽ tự động khởi tạo tệp tin `.claude/index.md` (giới hạn ~50 dòng để tối ưu token). File này chứa:
* **File map:** Khai báo nhanh vai trò của từng file chính trong dự án.
* **Architecture:** Sơ đồ kiến trúc dạng văn bản đơn giản.
* **Constraints / Gotchas:** Các lưu ý đặc biệt, cấu hình bảo mật hoặc quy tắc bắt buộc của dự án.

### B. Quyết định Kiến trúc (`.claude/decisions.md`)
* **Tệp mã nguồn ví dụ:** [.claude/decisions.md](.claude/decisions.md).

#### Giải pháp
Tệp tin này ghi chép lại lịch sử các quyết định kiến trúc lớn (Decision Log). Mỗi khi lập trình viên đồng ý với các phương án thiết kế được đề xuất bởi công cụ `consult` hoặc `alt_implementation`, một bản ghi sẽ được lưu lại theo cấu trúc:
1. **Context:** Bối cảnh và yêu cầu kỹ thuật cần giải quyết.
2. **Decision:** Giải pháp được chọn.
3. **Alternatives bỏ:** Các giải pháp thay thế đã bị loại bỏ và lý do vì sao loại bỏ.

### C. Cơ chế Context Injection (Nạp ngữ cảnh tối ưu)
Thay vì nạp toàn bộ mã nguồn vào cửa sổ ngữ cảnh (context window) gây lãng phí token và làm loãng sự tập trung của mô hình:
1. Claude Code đọc bản đồ [.claude/index.md](.claude/index.md) trước để xác định những tệp tin liên quan trực tiếp đến câu hỏi hoặc tính năng cần thực hiện.
2. Đọc trực tiếp các tệp tin nguồn đó (Source of Truth) thay vì dùng tóm tắt cũ.
3. Nạp nội dung tệp tin thực tế kèm theo lịch sử [.claude/decisions.md](.claude/decisions.md) vào Agent để đưa ra quyết định có độ chính xác 100%.

### D. Global Wiki (`~/.claude/llmwiki/`) — Knowledge Base Dùng Chung Mọi Project

* **Tệp mã nguồn:** [llmwiki_tool.py](llmwiki_tool.py) — `wiki_ingest`, `wiki_query`, `wiki_lint`.
* **MCP tool:** `wiki_ingest(target='global')`, `wiki_query`, `wiki_lint`.
* **Hook tự động:** `~/.claude/hooks/session_start.py` — check cả local lẫn global raw dirs đầu mỗi phiên.

#### Kiến trúc hai tầng

```
Per-project (local)               Global (dùng chung mọi project)
<project>/llmwiki/                ~/.claude/llmwiki/
  raw/          ← drop docs vào     raw/          ← kiến thức domain chung
  raw/processed/                    raw/processed/
  wiki/                             wiki/
    concepts/                         concepts/   ← local ưu tiên nếu trùng key
    entities/                         entities/
    sources/                          sources/
```

#### wiki_query — merge hai tầng, local ưu tiên

```python
# llmwiki_tool.py
for wiki_dir, scope in [(WIKI_DIR, "local"), (GLOBAL_WIKI_DIR, "global")]:
    for sub in ["concepts", "entities"]:
        key = f"{sub}/{fname}"
        if key in seen: continue   # local đã có → bỏ qua global trùng tên
        ...
        seen.add(key)
```

#### wiki_ingest — target param chọn đích

```python
# mcp_server.py — tool schema
{"name": "target", "type": "string", "enum": ["local", "global"]}

# Gọi:
wiki_ingest(target="local")   # → <project>/llmwiki/raw/   (mặc định)
wiki_ingest(target="global")  # → ~/.claude/llmwiki/raw/
```

#### SessionStart auto-check cả hai tầng

```python
# ~/.claude/hooks/session_start.py
def auto_ingest_wiki(root: Path) -> None:
    messages = []
    # Local wiki: so raw/ vs wiki/sources/
    raw_dir = root / "llmwiki" / "raw"
    if raw_dir.is_dir():
        new_files = sorted(raw_stems - ingested_stems)[:10]
        if new_files:
            messages.append("llmwiki [local]: N file mới chưa ingest. Gọi wiki_ingest...")

    # Global wiki
    global_raw = Path.home() / ".claude" / "llmwiki" / "raw"
    if global_raw.is_dir():
        ...
        messages.append("llmwiki [global]: ... Gọi wiki_ingest với target='global'.")

    _emit_context(messages)  # output JSON hookSpecificOutput.additionalContext

def _emit_context(lines: list[str]) -> None:
    if not lines: return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }))
```

**Quan trọng:** Hook phải output JSON `hookSpecificOutput.additionalContext` — không phải `print()` thuần. Plain print không inject vào Claude context. `_emit_context` bọc đúng format này.

Đầu mỗi phiên làm việc, hook tự so sánh `raw/` vs `wiki/sources/` của cả hai tầng — nếu có file mới chưa ingest, inject message vào context nhắc Claude Code gọi `wiki_ingest` trước khi làm task. Người dùng không cần làm gì.

#### wiki_lint — kiểm tra cả hai tầng, có tag scope

```python
for wiki_dir, raw_dir, scope in [
    (WIKI_DIR, RAW_DIR, "local"),
    (GLOBAL_WIKI_DIR, GLOBAL_RAW_DIR, "global"),
]:
    ...errors.append(f"[{scope}] Link hỏng: {p_info['type']}/{fname} → [[{link}]]")
```

---

## 5. Quy Tắc Kích Hoạt Kỹ Năng Chung Của Claude Code

Claude Code được cấu hình để tự động nhận diện bối cảnh và áp dụng kỹ năng chung (General Skills) dựa trên **loại tác vụ**, **cú pháp lệnh**, hoặc **slash commands** được sử dụng. Quy tắc ánh xạ chi tiết như sau:

| Trạng thái / Loại công việc | Skill áp dụng | Mô tả & Cách thức kích hoạt |
| :--- | :--- | :--- |
| **Chưa rõ yêu cầu hoặc mơ hồ** | `interview-me` | Tự động kích hoạt khi Prompt đầu vào thiếu thông tin kỹ thuật hoặc có nhiều assumptions. Agent sẽ hỏi từng câu một để làm rõ đến khi đạt **95% clarity**. |
| **Có ý tưởng mờ nhạt** | `idea-refine` | Phân tích sâu và mài giũa ý tưởng thô từ user. |
| **Bắt đầu Feature / Dự án mới** | `spec-driven-development` | **Kích hoạt qua lệnh `/spec`**. Buộc agent phải thiết kế và thống nhất tài liệu PRD/Specification trước khi viết dòng code đầu tiên. |
| **Có Spec, cần phân rã công việc** | `planning-and-task-breakdown` | **Kích hoạt qua lệnh `/plan`**. Chia nhỏ spec thành các checklist cụ thể ( TODO lists). |
| **Thiết kế API / Đầu nối** | `api-and-interface-design` | Tự động áp dụng khi sửa hoặc viết mới router, controllers hoặc API endpoints. |
| **Xử lý khu vực bảo mật nhạy cảm** | `security-and-hardening` | Tự động kích hoạt khi chạm đến logic Auth, RLS, phân quyền, Payment, Webhook hoặc mã hóa dữ liệu. |
| **Logic phức tạp / Rủi ro cao** | `doubt-driven-development` | Áp dụng khi refactor các hàm lớn, thuật toán tối ưu hoặc xử lý đồng thời (concurrency). Agent sẽ liên tục giả định các trường hợp biên lỗi để viết mã tự bảo vệ (defensive coding). |
| **Khắc phục lỗi / Debug** | `debugging-and-error-recovery` | Tự động kích hoạt khi Prompt chứa stack trace, log lỗi hoặc test fail. Áp dụng quy trình 5 bước: **Reproduce** (Tái dựng) → **Localize** (Khoanh vùng) → **Reduce** (Thu gọn) → **Fix** (Sửa đổi) → **Guard** (Phòng ngự). |
| **Yêu cầu review chất lượng code** | `code-review-and-quality` | **Kích hoạt qua lệnh `/review`** hoặc tự động chạy `panel_review` trước khi hoàn tất task. |
| **Rút gọn mã nguồn** | `code-simplification` | **Kích hoạt qua lệnh `/code-simplify`** khi mã nguồn quá rườm rà. |
| **Chuẩn bị bàn giao / Triển khai** | `shipping-and-launch` | **Kích hoạt qua lệnh `/ship`** để chạy build production, rà soát linting và tạo file walkthrough bàn giao. |
| **Ép buộc sinh code đầy đủ** | [full-output-enforcement](~/.claude/skills/full-output-enforcement/SKILL.md) | **Tự động kích hoạt khi sinh/chỉnh sửa code**. Cấm triệt để code placeholder dạng `// ...` hay `// TODO`. Tự động dừng tại điểm biên an toàn và in ra `[PAUSED - X of Y complete]` khi hết token limit, khôi phục lại khi nhận lệnh "continue". |

---

## 6. Bộ Thư Viện Kỹ Năng Thiết Kế Giao Diện & Thương Hiệu (Visual & Brand Skills Library)

Trong thư mục cấu hình [skills](~/.claude/skills/), Claude Code sở hữu một bộ kỹ năng độc quyền liên quan đến mỹ thuật, định hình cấu trúc giao diện cao cấp và chuyển đổi hình ảnh.

### Nhóm 1: Hệ Thống Thẩm Mỹ Front-End Chống AI-Slop (Tasteskill Family)
Nhóm kỹ năng này bao gồm các chỉ thị nhằm triệt tiêu các thói quen thiết kế mặc định xấu xí của AI thông thường (ví dụ: dùng font Inter đại trà, bo viền đổ bóng đậm, hero center lặp lại).

* **Trigger chung:** Chỉ chạy cho các tác vụ thuộc nhóm phát triển **Landing Pages (Trang giới thiệu)**, **Portfolios (Hồ sơ năng lực)**, **Marketing Sites (Mạng tiếp thị)**, và **Redesign Projects (Nâng cấp giao diện)**.
* **Banned Scope:** Không được phép kích hoạt khi xây dựng **Bảng điều khiển (Dashboards)**, **Bảng quản trị dữ liệu (Data Tables)**, hoặc **Giao diện sản phẩm có nhiều bước nhập liệu (Multi-step products UI)**.

#### A. Kỹ năng Thẩm mỹ Cơ bản ([design-taste-frontend](~/.claude/skills/design-taste-frontend/SKILL.md) & [design-taste-frontend-v1](~/.claude/skills/design-taste-frontend-v1/SKILL.md))
* **Quy tắc điều hướng (The Three Dials):** Điều chỉnh giao diện dựa trên 3 biến số toàn cục:
  * `DESIGN_VARIANCE` (Độ phá cách/Bất đối xứng): 1 (Đối xứng hoàn hảo) đến 10 (Masonry/Bento bất đối xứng).
  * `MOTION_INTENSITY` (Động học): 1 (Tĩnh) đến 10 (Cinematic GSAP/Spring physics).
  * `VISUAL_DENSITY` (Mật độ thông tin): 1 (Không gian thoáng như triển lãm) đến 10 (Dày đặc).
* **Màu sắc và Typography:** Cấm bảng màu kem + đồng (Beige/Brass) mặc định của AI cho các trang cao cấp (Premium-consumer), buộc phải quay vòng sang Cold Luxury (Chrome + Smoke), Forest Premium hoặc Cobalt. Cấm font Inter, bắt buộc dùng Geist, Satoshi hoặc Outfit.

#### B. Kỹ năng Chuyển động Kịch bản Cao cấp ([gpt-taste](~/.claude/skills/gpt-taste/SKILL.md))
* **Random ngẫu nhiên bố cục (Python RNG):** Agent bắt buộc mô phỏng một script Python tính toán seed ngẫu nhiên từ độ dài ký tự của prompt để tự động gán cấu trúc Hero, Typography Stack và GSAP Motion, đảm bảo không bao giờ sinh 2 layout giống nhau liên tiếp.
* **Quy tắc H1 tối đa 2 dòng (2-Line Iron Rule):** Nới rộng container H1 (`max-w-5xl` hoặc `max-w-6xl`) và tự động co giãn font chữ bằng `clamp()` để tiêu đề không bao giờ bị ngắt dòng thành 5-6 dòng vụn vặt.

#### C. Kiến Trúc Thẩm Mỹ Haptic UI ([high-end-visual-design](~/.claude/skills/high-end-visual-design/SKILL.md))
* **Cấu trúc viền kép lồng nhau (Double-Bezel Doppelrand):** Lồng ghép core container bên trong vỏ ngoài mờ (`border-white/10` hoặc `ring-black/5`) bo góc lớn (`rounded-[2rem]`) với tỷ lệ curve đồng tâm: `rounded-[calc(2rem-outer_padding)]`.
* **CTA lồng Icon:** Mũi tên điều hướng (`↗`) được bao trong vòng tròn mờ (`bg-white/10`) nằm flush với padding phải của nút. Khi hover, nút scale nhẹ xuống (`active:scale-[0.98]`) và icon trượt chéo lên (`group-hover:translate-x-1 group-hover:-translate-y-[1px]`).

---

### Nhóm 2: Nhóm Kỹ Năng Thiết Kế Visual Chủ Đề Riêng Biệt (Alternative Aesthetics)

#### A. Kỹ năng Tối Giản Thực Dụng ([minimalist-ui](~/.claude/skills/minimalist-ui/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Tự động áp dụng khi prompt chứa các mô tả về "workspace", "document-style", "Notion-like", "minimalist", "clean", "flat".
* **Đặc trưng thiết kế:**
  * Sử dụng tông màu Warm Bone / Off-White (`#F7F6F3` hoặc `#FBFBFA`) làm nền canvas chính.
  * Card phẳng tuyệt đối không đổ bóng, phân tách thuần bằng viền siêu mờ `1px solid #EAEAEA` hoặc `rgba(0,0,0,0.06)`. Góc bo cứng cáp tối đa `8px` hoặc `12px`.
  * Điểm xuyết các màu phấn nhạt cực dịu (Pale pastels) như Pale Red (`#FDEBEC`), Pale Blue (`#E1F3FE`), Pale Green (`#EDF3EC`), Pale Yellow (`#FBF3DB`) cho các thẻ tag.

#### B. Kỹ năng Thô Mộc Công Nghiệp ([industrial-brutalist-ui](~/.claude/skills/industrial-brutalist-ui/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Kích hoạt khi có yêu cầu thiết kế phong cách "brutalist", "tactical", "blueprints", "telemetry", "military", hoặc "data-heavy dashboard".
* **Đặc trưng thiết kế (Lựa chọn 1 trong 2 phân nhánh):**
  1. *Swiss Industrial Print (Light mode):* Giả lập giấy in tài liệu cũ `#F4F4F0`, chữ đen đậm monolithic, chia grid thô bằng các thanh chia lực cực dày, sử dụng duy nhất một màu accent Aviation Red (`#E61919`). Góc bo chính xác 90 độ.
  2. *Tactical Telemetry & CRT Terminal (Dark mode):* Nền đen CRT `#0A0A0A`, chữ xanh Phosphor phát sáng, chèn các ký tự ASCII định khung dữ liệu như `[ SYSTEM DEPLOY ]`, dấu hồng tâm (`+`) tại các góc cắt, và áp dụng hiệu ứng CRT scanlines.

---

### Nhóm 3: Nhóm Kỹ Năng Thiết Kế Trước - Code Sau (Image-First Workflow)

#### A. Kỹ năng Chuyển Ảnh Thành Code ([image-to-code](~/.claude/skills/image-to-code/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Tự động chạy khi user yêu cầu sinh code cho giao diện UI quan trọng về thị giác (landing page, mockup, portfolio, redesign) khi môi trường có sẵn công cụ sinh ảnh (`generate_image`).
* **Đặc trưng quy trình:**
  1. **Tạo ảnh trước (Image-first):** Không cho phép code tự do ngay từ đầu. Bắt buộc gọi tool sinh ảnh để tạo ra bản vẽ visual mockups chất lượng cao cho từng section độc lập.
  2. **Phân tích chiều sâu (Deep Analysis):** Phân tích chi tiết và trích xuất hệ thống typography, spacing, và button shapes từ ảnh.
  3. **Lập trình chính xác (Translate to Code):** Code React/Tailwind bám sát 100% bản vẽ, cấm tuyệt đối cấu trúc Card lồng Card lồng Card (Anti-nested box) và các tiểu tiết rườm rà (Micro-UI Clutter).

#### B. Kỹ năng Sinh Ảnh Hỗ Trợ Web / Mobile ([imagegen-frontend-web](~/.claude/skills/imagegen-frontend-web/SKILL.md) & [imagegen-frontend-mobile](~/.claude/skills/imagegen-frontend-mobile/SKILL.md))
* **Trigger:** Khi `image-to-code` cần sinh layout comp cho bản desktop hoặc mobile tương ứng. Đưa ra các prompt cấu trúc chuẩn giúp AI sinh ảnh tạo ra các mockup sạch, không bị méo chữ và có độ sâu vật lý.

---

### Nhóm 4: Nhóm Kỹ Năng Nhận Diện Thương Hiệu & Đồng Bộ Nền Tảng

#### A. Kỹ năng Art Direction Thương Hiệu ([brandkit](~/.claude/skills/brandkit/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Chạy khi người dùng yêu cầu thiết kế hệ thống nhận diện, logo, guidelines hoặc bảng trình diễn thế giới thương hiệu (Brand Guidelines Deck).
* **Đặc trưng thiết kế:** Tạo bảng trình diễn lưới chuẩn `3x3` hoặc `2x3` trên canvas xám đậm. Phân chia các panel nhịp điệu: Logo Cover, Sơ đồ hình học (Construction), Mockup ứng dụng, Typography Specimen, Bảng màu và Tagline cô đọng.

#### B. Kỹ năng Đồng bộ Google Stitch ([stitch-design-taste](~/.claude/skills/stitch-design-taste/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Chạy khi người dùng cần xuất bản thiết kế sang hệ thống Google Stitch.
* **Đặc trưng:** Biên dịch các quy tắc chống AI-slop frontend thành các chỉ dẫn ngôn ngữ tự nhiên (Semantic Design Language) lưu vào file `DESIGN.md` để Stitch AI Agent đọc hiểu và vẽ màn hình chính xác.

#### C. Kỹ năng Nâng Cấp Dự Án Hiện Tại ([redesign-existing-projects](~/.claude/skills/redesign-existing-projects/SKILL.md))
* **Quy tắc kích hoạt (Trigger):** Tự động chạy khi có yêu cầu nâng cấp/sửa đổi một trang web có sẵn.
* **Quy trình thực thi:** Thực hiện tuần tự 3 bước: **Scan** (Quét stack công nghệ và CSS) → **Diagnose** (Chạy danh sách kiểm lỗi thiết kế: font Inter đại trà, lỗi tương phản nút, text wrap lỗi) → **Fix** (Sửa mục tiêu trực tiếp tại chỗ, không viết lại từ đầu).

---

## 7. Các Chỉ Thị & Công Cụ Tự Động Toàn Cục (Claude's Global Automation)

Tệp tin cấu hình toàn cục [CLAUDE.md](~/.claude/CLAUDE.md) của Claude Code thiết lập các kỹ thuật tự động hóa quan trọng sau:

### A. Tự động Tra Cứu Tài Liệu (Context7 Auto-docs)
* **Quy tắc:** Khi làm việc với bất kỳ thư viện hoặc framework bên ngoài nào (ví dụ: React, FastAPI, SQLAlchemy, Express, Django, Tailwind, v.v.), Claude Code tự động gọi công cụ **context7** để lấy tài liệu API mới nhất.
* **Lợi ích:** Loại bỏ nguy cơ sử dụng các hàm hoặc syntax cũ đã bị deprecated do tri thức tĩnh của mô hình.

### B. Tự động Nghiên cứu Công nghệ (Auto-Research Protocol)
* **Quy tắc:** Khi bắt đầu một dự án mới hoặc phát triển một tính năng quan trọng (auth, payment, realtime, upload, AI, dashboard):
  1. Tự động thực hiện WebSearch với từ khóa `"best [technology/feature] 2026 enterprise production"` trước khi đề xuất.
  2. Báo cáo ngắn gọn cho người dùng các công nghệ đang dẫn đầu xu hướng và những cập nhật mới đáng lưu ý.
  3. Chỉ triển khai sau khi đã làm rõ các options. Không áp dụng cho bugfix hoặc thay đổi nhỏ.

### C. Quy tắc Ưu tiên Tech Stack Mặc định (Default Tech Stack Priorities)
Khi đề xuất giải pháp công nghệ, Claude tuân thủ nghiêm ngặt 3 tiêu chí:
1. **Mới nhất & Được bảo trì chủ động (Active):** Kiểm tra phiên bản thực tế qua context7, tuyệt đối không dùng cú pháp lỗi thời.
2. **Bảo mật là trên hết (Security-first):** Mặc định áp dụng các giải pháp an toàn cao: Parameterized Queries (chống SQLi), lưu trữ key trong biến môi trường `.env`, mã hóa HTTPS, và xác thực dữ liệu tại ranh giới (boundary input validation).
3. **Đã được kiểm chứng trong Production (Production-proven):** Chỉ dùng các thư viện có cộng đồng lớn và hoạt động tối thiểu 6 tháng.

### D. Nguyên Tắc Lập Trình Bất Biến (General Coding Principles)
1. **Nêu rõ Assumptions:** Luôn khai báo rõ ràng các giả định kỹ thuật trước khi code, không tự ý đoán mò khi yêu cầu bị mơ hồ.
2. **Dừng lại khi nghi ngờ:** Nếu gặp mâu thuẫn hoặc không rõ luồng dữ liệu, dừng lại và hỏi ý kiến user thay vì cố viết code lỗi.
3. **Giữ đúng Scope:** Chỉ thay đổi và tác động đúng những file/khu vực được yêu cầu, không lan man.
4. **Boring Solution:** Ưu tiên giải pháp đơn giản, tường minh, dễ đọc hơn là viết code "thông minh" nhưng phức tạp.

---

## 8. Hướng Dẫn Sử Dụng Trong Quy Trình Hàng Ngày

Khi cài đặt thành công, Claude Code sẽ tự động vận hành hệ thống thông qua các cấu hình tích hợp sẵn. Bạn cũng có thể điều khiển thủ công theo các cách sau:

### Chế độ Tự Động (Khuyến nghị)
Claude Code sẽ tự đọc file `~/.claude/CLAUDE.md` và áp dụng các rule tự động:
* Khi bạn bắt đầu viết các logic phức tạp, Claude Code sẽ tự động chạy tool `consult` để hỏi ý kiến thiết kế trước.
* Khi bạn hoàn thành coding, trước khi báo cáo kết quả, Claude Code sẽ tự động kích hoạt `panel_review` để kiểm duyệt lỗi.

### Chế độ Thủ Công qua Claude CLI
Bạn có thể yêu cầu trực tiếp Claude Code kích hoạt các tool MCP của Agent Harness:
```bash
# Hỏi ý kiến thiết kế về cấu trúc cache
Dùng tool consult hỏi xem nên dùng Redis hay in-memory cache cho use case này?

# Chạy review thủ công cho file vừa sửa
Chạy panel_review file src/api/upload.py với focus vào logic và security.

# Yêu cầu tìm lỗi và đề xuất patch sửa đổi cho trace log
suggest_fix lỗi sau: [paste stack trace hoặc mã lỗi ở đây]

# Liệt kê thông tin các mô hình đang phụ trách
Chạy tool list_agents xem cấu hình hệ thống hiện tại.
```

### Sử dụng Web Dashboard
Mở terminal tại thư mục dự án và chạy server:
```bash
python server.py
```
Sau đó truy cập địa chỉ [http://localhost:8000](http://localhost:8000) trên trình duyệt. Dashboard bao gồm **Wiki Explorer** (tìm kiếm & duyệt kiến thức tự học) và **Security Scanner** (scan + autofix trực tiếp từ UI).

---

## 9. Kỹ Thuật Nâng Cao (Cập Nhật Mới Nhất)

### Kỹ thuật 7: panel_review Optimization — Timeout + Fast Mode + Local Dedup

* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm `panel_review` và `_dedup_findings_local`.

#### Vấn đề gốc
`panel_review` bị chậm vì: context 400KB nhét vào 3 agent song song + SYNTHESIZER luôn được gọi + không có timeout → có thể treo vô hạn.

#### 3 tối ưu đã triển khai

**1. Per-agent timeout (mặc định 90s):**
```python
async def _run_with_timeout(role: AgentRole) -> AgentResult:
    try:
        return await asyncio.wait_for(
            Agent(role, client).run_async(task, ctx, json_mode=True),
            timeout=agent_timeout,  # default 90s
        )
    except asyncio.TimeoutError:
        warnings.append(f"{role.value}: timeout — bỏ qua")
        return AgentResult(status="error", error=f"Timeout sau {agent_timeout:.0f}s", ...)
```

**2. Fast mode** — cap context 80KB thay vì 400KB, ~2x nhanh hơn:
```python
panel_review(..., fast=True)  # context capped ở 80KB
```

**3. Skip Synthesizer khi findings ≤ 8** — tự dedupe bằng Python, tiết kiệm 1 API call:
```python
SYNTH_THRESHOLD = 8
use_synthesizer = (not fast) and (len(raw_findings) > SYNTH_THRESHOLD)
```

Hàm `_dedup_findings_local` merge các findings trùng `(file, line, issue[:60])` và giữ severity cao nhất, không tốn thêm token.

---

### Kỹ thuật 8: Git Worktree Isolation — Test Patch Không Làm Bẩn Workspace

* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm `_apply_and_test_isolated`.

#### Nguyên lý (Orca-style)
Thay vì apply patch trực tiếp rồi test (nguy hiểm nếu test fail), hệ thống tạo một **môi trường cô lập** qua `git worktree`:

```
Workspace chính (an toàn)
    │
    └── git worktree add --detach .harness_worktree_<uid>
            │
            ├── Apply patch trong worktree
            ├── Chạy smoke_test.py trong worktree
            │
            ├── PASS → copy file về workspace chính (git status --porcelain -z)
            └── FAIL → xóa worktree, workspace chính nguyên vẹn
```

> [!IMPORTANT]
> Dùng `--porcelain -z` (null-byte separated) thay vì `--porcelain` để parse đúng tên file có space, ký tự đặc biệt, và trường hợp rename/copy mà Git biểu diễn dưới dạng `R`/`C`.

Sau khi test pass, worktree và branch tạm được dọn sạch hoàn toàn trong khối `finally`.

---

### Kỹ thuật 9: Security Autofix Coordinator — Quét → Vá → Test → Wiki (100% Tự Động)

* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm `security_autofix`.
* **MCP Tool:** `security_autofix` (đã đăng ký trong [mcp_server.py](mcp_server.py)).
* **Web Endpoint:** `POST /api/security/scan` với X-API-Key guard (nếu `HARNESS_API_KEY` env được set).

#### Pipeline tự động 4 bước
```
panel_review(files) ──► lọc Critical/High security findings
        │
        ▼
suggest_fix(lỗi bảo mật cụ thể) ──► sinh unified diff patch
        │
        ▼
_apply_and_test_isolated(patch) ──► worktree test, copy nếu pass
        │
        ▼
_extract_and_save_lesson(error, patch) ──► ghi wiki concept (background task)
```

Hàm lọc findings dùng **chuẩn hóa `found_by`** trước khi kiểm tra để tránh false positive khi field là string thay vì list:
```python
"security" in (
    f.get("found_by") if isinstance(f.get("found_by"), list)
    else ([f.get("found_by")] if f.get("found_by") else [])
)
```

---

### Kỹ thuật 10: Auto-Learning Wiki — Tự Đúc Kết Kinh Nghiệm Sau Mỗi Bug Fix

* **Tệp mã nguồn:** [support_tools.py](support_tools.py) tại hàm `_extract_and_save_lesson`.

#### Cơ chế
Sau mỗi lần `suggest_fix` thành công và patch vượt qua test, hệ thống tự động kích hoạt `_extract_and_save_lesson` chạy **ở background** (không block luồng chính):

1. WORKER agent được giao task viết một trang wiki Markdown với Front Matter (`title`, `type: concept`, `related`).
2. Nội dung gồm: **Mô tả lỗi** → **Giải pháp chuẩn** → **Code ví dụ** (sai vs đúng).
3. Slug được tạo từ title (unicode normalize → ASCII), lưu vào `llmwiki/wiki/concepts/`.
4. Lần sau khi gặp tác vụ tương tự, `_load_relevant_wiki_context` tự inject bài học này vào context.

```python
# Gọi bất đồng bộ, không block suggest_fix
asyncio.create_task(_extract_and_save_lesson(error, files, patch))
```

---

### Kỹ thuật 11: Wiki Explorer API + Selective Context Injection (Local + Global)

* **Tệp mã nguồn:** [tools/core.py](tools/core.py) — `_assemble_context`, `_load_relevant_wiki_context`, `_wiki_roots`.
* **Web API:** [server.py](server.py) — endpoints `/api/wiki/pages` và `/api/wiki/search`.

#### Khi nào wiki được inject

Wiki inject **tự động** — không phân biệt framework hay ngôn ngữ. Mọi tool gọi LLM đều chạy qua `_assemble_context()` trước khi gửi prompt lên Azure:

| Tool MCP | Trigger |
|---|---|
| `panel_review` | Trước khi 3 agent reviewer/security/tester chạy |
| `suggest_fix` | Trước khi debugger phân tích |
| `consult` | Trước khi analyzer (Grok) trả lời |
| `auto_tester` | Trước khi tester sinh test |

`ask_codebase` tự inject selective wiki context riêng; `alt_implementation`, `quick_task` không dùng `_assemble_context`.

Flow thực tế (hoàn toàn tự động):
```
User yêu cầu task → Claude sửa file (Edit/Write)
    → PostToolUse hook inject nhắc panel_review
    → Claude gọi panel_review(files=[...])
    → _assemble_context() → _load_relevant_wiki_context()
    → keyword match file/diff với wiki → top 5 trang inject vào prompt
    → 3 reviewer thấy knowledge JWT/IDOR/XSS... từ local + global wiki
```

#### Selective Injection — hai tầng local + global

```python
# tools/core.py
def _wiki_roots() -> list[tuple[str, str]]:
    """Local (runtime project) trước, global (~/.claude/llmwiki/) sau.
    Dedupe by sub/fname: local ưu tiên nếu trùng tên."""
    roots = []
    local_wiki = os.path.join(_get_active_workspace(), "llmwiki", "wiki")
    if os.path.isdir(local_wiki):
        roots.append((local_wiki, "local"))
    global_wiki = os.path.join(os.path.expanduser("~"), ".claude", "llmwiki", "wiki")
    if os.path.isdir(global_wiki):
        roots.append((global_wiki, "global"))
    return roots

# Chấm điểm mỗi trang wiki từ cả 2 tầng:
score = sum((5 if kw in fname_lower else 0) + content_lower.count(kw) for kw in keywords)
# Lấy top 5 cao điểm nhất — có thể mix local + global
top_pages = matched_pages[:5]
```

**Quan trọng:** `_get_active_workspace()` đọc `CLAUDE_PROJECT_DIR` **runtime** thay vì module-level constant — tránh bị freeze khi MCP process reuse qua nhiều project (`--scope user`).

#### Wiki Search API
`GET /api/wiki/search?q=<keyword>` trả về tối đa 10 kết quả xếp hạng theo relevance score, có snippet preview. Dùng debounce 300ms ở frontend để không spam request khi gõ.

---

### Kỹ thuật 12: Python-Level Timeout Enforcement cho Responses API

* **Tệp mã nguồn:** [agents.py](agents.py) — `_responses_call`, `chat_completion`, `_ResponsesTimeoutError`.

#### Vấn đề gốc
`gpt-5.4-pro` chạy qua Azure Responses API (`cognitiveservices.azure.com`). SDK timeout kwarg bị Azure gateway ignore — request treo đủ 636s mới chết thay vì cắt đúng 120s như cấu hình.

#### Giải pháp

**1. Per-request ThreadPoolExecutor + Python-level timeout:**
```python
class _ResponsesTimeoutError(Exception):
    """Raised khi _responses_call vượt Python-level timeout."""

def _responses_call(model, messages, max_output_tokens, timeout):
    def _do_call():
        return client.responses.create(model=model, ..., timeout=timeout)

    ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix="harness-resp")
    future = ex.submit(_do_call)
    try:
        response = future.result(timeout=timeout)   # Python-level enforcement
        ex.shutdown(wait=False)
    except concurrent.futures.TimeoutError:
        ex.shutdown(wait=False, cancel_futures=True)
        raise _ResponsesTimeoutError(f"timeout after {timeout}s on {model}")
```

Per-request executor (không phải shared pool) tránh zombie-fill: mỗi call timeout giải phóng executor riêng của nó, không block các call tiếp theo.

**2. Timeout không retry cùng model — switch spare ngay sau 1 lần:**
```python
except (APITimeoutError, _ResponsesTimeoutError):
    timeout_attempt += 1
    if timeout_attempt <= 1:
        time.sleep(1.0); continue          # 1 retry ngắn
    spare = next(spares, None)
    if spare:
        current_model = spare
        timeout_attempt = 0; continue
    raise
```

`timeout_attempt` reset về 0 khi switch sang lỗi loại khác (`RateLimitError`, `InternalServerError`) để chỉ track consecutive timeout streak, không tích lũy toàn phiên.

**3. ROLE_TIMEOUTS configurable qua env — manager/analyzer tăng lên 300s:**
```python
ROLE_TIMEOUTS = {
    "manager":  _safe_float("ROLE_TIMEOUT_MANAGER",  300.0),  # codebase lớn
    "analyzer": _safe_float("ROLE_TIMEOUT_ANALYZER", 300.0),  # grok reasoning
    ...
}
```

---

### Kỹ thuật 13: 5 Analysis Tools Mới — SSRF, Entropy, Multiline, Quota

* **Tệp mã nguồn:** [tools/analysis.py](tools/analysis.py).

Năm tool mới tự động kích hoạt theo Tier 1/2 trong CLAUDE.md và GEMINI.md:

#### A. `secret_scanner` — 3 tầng phát hiện
1. **Regex line-by-line** — 9 pattern (private key, AWS key, Stripe, GitHub token, v.v.)
2. **Shannon entropy trên AST** — string literal Python ≥24 ký tự, entropy ≥4.2 → flag
3. **Full-content DOTALL scan** — bắt secret trong triple-quoted / multiline string:
```python
for secret_type, pattern, severity in _SECRET_PATTERNS:
    try:
        for m in re.finditer(pattern, content, re.DOTALL | re.MULTILINE):
            ...
    except re.error as exc:
        warnings.append(f"Pattern '{secret_type}' lỗi khi multiline scan: {exc}")
```
Tự động bỏ qua file `.env` (`skip_env=True`) để không lộ secret trong output. Quota cứng 2000 file, sắp xếp deterministic trước khi cắt.

#### B. `load_tester` — SSRF-safe HTTP benchmark
SSRF check dùng `socket.getaddrinfo` (tất cả IPv4+IPv6, không chỉ 1 địa chỉ) + fail-closed khi không resolve được:
```python
infos = socket.getaddrinfo(hostname, port, proto=IPPROTO_TCP)  # ALL records
for _fam, _type, _proto, _canon, sockaddr in infos:
    ip = ipaddress.ip_address(sockaddr[0])
    if ip.is_private or ip.is_loopback or ip.is_link_local ...:
        return f"URL tới địa chỉ nội bộ: {ip}"
```
Cap cứng: `requests_count ≤ 1000`, `concurrency ≤ 50`. Trả p50/p95/p99 latency.

#### C. `complexity_analyzer` — AST cyclomatic
Visitor đếm `if/for/while/BoolOp/IfExp/comprehension` mỗi function, flag hotspot > threshold (default 10, castable từ string).

#### D. `env_parity_checker` — key diff .env vs .env.example
Parse key từ cả 2 file, trả `missing_in_env`, `extra_in_env`, `parity_score`.

#### E. `changelog_generator` — conventional commits
`git log` → group by type (`feat/fix/chore/refactor/...`) → markdown hoặc text output.

---

### Kỹ thuật 15: Polyglot Codebase Index — tree-sitter + SQLite FTS5 (158 Ngôn Ngữ)

* **Tệp mã nguồn:** [tools/codebase_index.py](tools/codebase_index.py).
* **MCP Tools sử dụng:** `semantic_search`, `dead_code_scanner`, `ask_codebase` (auto-discovery), `index_codebase`.

#### Vấn đề gốc
`semantic_search` cũ rebuild TF-IDF mỗi lần gọi, chỉ hỗ trợ `.py/.html/.css/.md`. `dead_code_scanner` chỉ parse Python AST. `ask_codebase` buộc caller phải biết trước danh sách file cần tải.

#### Kiến trúc

```
Lần gọi đầu tiên (lazy build)
        │
        ▼
CodebaseIndex._ensure_indexed()  ──► _has_index_data() == False
        │
        ▼
_compute_snapshot()  ──► SHA256(tất cả mtime+size)
        │                Nếu digest khớp cache → reuse ngay
        ▼
_iter_files()  ──► 30+ extensions, bỏ qua .git/node_modules/__pycache__/...
        │
        ├─► language == "python"  →  Python ast.parse() (qualified names, refs)
        ├─► tree_sitter_languages available  →  get_parser(language) (158 ngôn ngữ)
        └─► fallback  →  regex patterns (function/class/const)
        │
        ▼
SQLite FTS5 (WAL mode, explicit IMMEDIATE transaction)
┌─────────────────────────────────────────────────────┐
│  files       │ path, language, mtime, content[:10K] │
│  symbols     │ path, symbol, kind, line, signature  │
│  refs        │ path, owner_symbol, ref_symbol, line │
│  search_source (content table)                      │
│  search_index (FTS5 virtual, BM25 ranking)          │
└─────────────────────────────────────────────────────┘
        │
        ▼
search() → FTS5 MATCH query → BM25 rank → fallback LIKE nếu OperationalError
```

#### Singleton & Thread Safety
```python
# Module-level registry — 1 instance per workspace root
_INSTANCES: dict[str, CodebaseIndex] = {}
_GLOBAL_LOCK = threading.Lock()

def get_index(workspace_root=None) -> CodebaseIndex:
    with _GLOBAL_LOCK:
        if key not in _INSTANCES:
            _INSTANCES[key] = CodebaseIndex(key)
    return _INSTANCES[key]

# Double-checked locking trong _ensure_indexed():
def _ensure_indexed(self) -> None:
    if self._has_index_data(): return          # fast path (no lock)
    with self._rlock:                          # slow path — thread 2 waits
        if not self._has_index_data():         # re-check after acquiring lock
            self.build()
```

#### Tích hợp vào tools hiện có

| Tool | Trước | Sau |
|---|---|---|
| `semantic_search` | TF-IDF rebuild mỗi call, 4 ext | FTS5 BM25, 158 ngôn ngữ, persistent |
| `dead_code_scanner` | Python AST only | Polyglot — query `refs` table |
| `ask_codebase` | Caller phải biết `files` | Auto-discover 15 file liên quan qua `search()` |
| `index_codebase` | *(mới)* | Build/rebuild thủ công, force=True |

#### Incremental — không rebuild khi không cần
```python
snapshot = _compute_snapshot()   # SHA256 của tất cả mtime+size
if prev["snapshot_digest"] == snapshot["digest"] and _has_index_data():
    return {"status": "reused", ...}   # < 5ms, không đọc lại file nào
```

---

### Kỹ thuật 16: FinOps — Theo Dõi Chi Phí & Latency Từng Agent Call

* **Tệp mã nguồn:** [agents.py](agents.py) — `init_finops_db`, `calculate_cost`, `log_step_to_db`, `log_run_to_db`, `get_finops_stats`.
* **MCP Tool:** `finops_stats` — xem từ Claude Code bằng lệnh `mcp__agent-harness__finops_stats`.
* **DB:** `.harness_finops.db` (SQLite) tại WORKSPACE_ROOT.

#### Vấn đề gốc
Không có cách nào biết mỗi `panel_review` hay `consult` tốn bao nhiêu token, bao nhiêu tiền, agent nào chậm nhất — không thể tối ưu chi phí khi không có số liệu.

#### Schema SQLite

```sql
-- Một "run" = 1 lần gọi MCP tool (panel_review, consult, alt_implementation...)
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    workflow_type TEXT,   -- "mcp_panel_review", "mcp_consult", ...
    duration_ms INTEGER,
    total_cost REAL       -- SUM của tất cả steps trong run
);

-- Một "step" = 1 lần agent call LLM (mỗi panel có 3 steps: reviewer, tester, security)
CREATE TABLE steps (
    step_id TEXT PRIMARY KEY,
    run_id TEXT,
    agent_role TEXT,       -- "reviewer", "security", "analyzer"...
    model TEXT,            -- tên deployment thực tế đã dùng
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    latency_ms INTEGER,
    cache_hit INTEGER,     -- 0/1
    cost_usd REAL,
    FOREIGN KEY(run_id) REFERENCES runs(run_id)
);
```

#### Cost model (per 1M tokens)

| Model tier | Input | Output |
|---|---|---|
| pro (gpt-5.4-pro) | $5.00 | $15.00 |
| reasoning / grok | $10.00 | $30.00 |
| codex / gpt-5.3 / gpt-5.4 / Kimi | $1.50 | $4.50 |
| mini | $0.15 | $0.60 |
| default | $2.00 | $6.00 |

#### Flow ghi log

```python
# mcp_server.py — mọi tool call đều được wrap:
run_id = f"run-{uuid.uuid4().hex[:8]}"
current_run_id.set(run_id)            # ContextVar — thread-safe, không cần pass qua tham số

# agents.py — sau mỗi LLM call thành công:
log_step_to_db(run_id, role, model, p_tok, c_tok, duration_ms, cache_hit)

# mcp_server.py — sau khi tool hoàn thành (finally block):
log_run_to_db(run_id, f"mcp_{name}", duration_ms)
# Ngoại lệ: list_agents và finops_stats không ghi log (tránh đệ quy)
```

#### Output của `finops_stats`

```json
{
  "total_steps": 142,
  "total_prompt_tokens": 1_840_000,
  "total_completion_tokens": 210_000,
  "total_cost_usd": 0.0312,
  "total_cache_hits": 38,
  "model_stats": [
    {"model": "gpt-5.3-codex", "count": 54, "cost_usd": 0.009, "avg_latency_ms": 8200}
  ],
  "role_stats": [{"agent_role": "reviewer", "count": 48, "cost_usd": 0.007}],
  "recent_runs": [{"workflow_type": "mcp_panel_review", "duration_ms": 15094, "total_cost": 0.0021}]
}
```

---

### Kỹ thuật 17: Panel Review v2 — Adversarial Seeding, Triage Taxonomy & Anti-Consensus

* **Tệp mã nguồn:** [tools/review.py](tools/review.py), [agents.py](agents.py).
* **Lấy ý tưởng từ:** [ai-berkshire](https://github.com/xbtlin/ai-berkshire) (adversarial seeding), [no-mistakes](https://github.com/kunchenguid/no-mistakes) (triage taxonomy).

#### 3 nâng cấp tự động — không cần thay đổi cách gọi

**1. Adversarial Seeding (TESTER là devil's advocate)**

Trước đây TESTER tìm "test gaps" chung chung. Giờ TESTER được giao vai **phản biện độc lập** — nhiệm vụ là tìm những gì REVIEWER và SECURITY bỏ sót:

```
REVIEWER  → code quality, bugs, anti-patterns
SECURITY  → OWASP, injection, auth flaws, secrets
TESTER    → Adversarial: race conditions, hidden assumptions,
             non-obvious edge cases mà 2 kia không nghĩ đến
             (BẮT BUỘC kèm input/scenario cụ thể mỗi finding)
```

Diversity của 3 góc nhìn tăng coverage — cùng 1 code có thể qua REVIEWER + SECURITY nhưng bị TESTER bắt qua race condition chỉ xảy ra dưới concurrent load.

**2. Triage Taxonomy — mỗi finding có nhãn xử lý**

```json
{
  "file": "auth.py", "line": 42, "severity": "high",
  "issue": "SQL injection via f-string",
  "suggested_fix": "dùng parameterized query",
  "triage": "auto_fix"   // ← MỚI
}
```

| `triage` | Ý nghĩa | Ví dụ |
|---|---|---|
| `auto_fix` | Fix mechanical, deterministic | Thêm null check, đổi f-string → parameterized, encode output |
| `ask_user` | Cần developer judgment | Thay đổi auth flow, refactor architecture, behavioral change |

Conflict giữa reviewers → luôn chọn `ask_user` (conservative). Backfill tự động nếu model bỏ sót field.

**3. Anti-Consensus Warning — phát hiện "đồng thuận mù"**

```python
# Tự động thêm vào warnings[] nếu:
# (A) cả 3 reviewer báo clean nhưng diff lớn/phức tạp
# (B) chỉ 1 reviewer có findings, 2 kia hoàn toàn im lặng
warnings.extend(_check_anti_consensus(results, raw_findings))
```

Lấy cảm hứng từ AI Berkshire — anti-consensus bias check ngăn panel "đồng thuận mù" bỏ sót issue thật.

#### Per-role timeout — không còn shared 90s

```python
# config.py — configurable qua env var
ROLE_TIMEOUTS = {
    "reviewer":    180.0,   # ROLE_TIMEOUT_REVIEWER
    "tester":      180.0,   # ROLE_TIMEOUT_TESTER
    "security":    180.0,   # ROLE_TIMEOUT_SECURITY
    "synthesizer": 120.0,   # ROLE_TIMEOUT_SYNTHESIZER
    ...
}

# agent_timeout param = hard cap nếu caller muốn override
role_t = ROLE_TIMEOUTS.get(role.value, agent_timeout)
if agent_timeout != 90.0:          # caller truyền vào khác default
    role_t = min(role_t, agent_timeout)
```

Trước đây cả 3 panel agent dùng chung 1 timeout 90s → tester hay bị timeout trên diff lớn. Giờ mỗi role có timeout riêng, tăng lên 180s mặc định.

---

### Kỹ thuật 18: GEMINI.md Auto-Setup — Đồng Bộ Quy Trình Harness Sang Antigravity IDE

* **Tệp mã nguồn:** [merge_settings.py](merge_settings.py) tại hàm `merge_gemini_md`.

#### Vấn đề gốc
`install.ps1` chỉ setup cho Claude Code (`~/.claude/CLAUDE.md` + `~/.claude/settings.json`). Người dùng Antigravity IDE (dùng Gemini) không được inject quy trình harness vào `~/.gemini/GEMINI.md` → phải setup thủ công.

#### Giải pháp
`merge_settings.py` (được `install.ps1` gọi) giờ tự động setup cả `~/.gemini/GEMINI.md`:

```python
def main() -> int:
    claude_dir = Path.home() / ".claude"
    merge_claude_md(claude_dir)          # ← đã có từ trước
    err = merge_settings_json(claude_dir)
    if err: return err
    gemini_dir = Path.home() / ".gemini"
    merge_gemini_md(gemini_dir)          # ← MỚI: tạo/append GEMINI.md
    return 0
```

`merge_gemini_md` idempotent: kiểm tra marker `agent-harness` trước khi append — chạy lại không tạo trùng lặp. GEMINI.md được inject đầy đủ: bắt buộc (consult + panel_review), dùng khi phù hợp (suggest_fix, ask_codebase, alt_implementation, quick_task, semantic_search, index_codebase), ngoại lệ, token efficiency rules.

---

### Kỹ thuật 14: Multi-Agent Token Efficiency — CLAUDE.md & GEMINI.md

* **Tệp cấu hình:** [`~/.claude/CLAUDE.md`](~/.claude/CLAUDE.md), [`~/.gemini/GEMINI.md`](~/.gemini/GEMINI.md).

Harness models (10 Azure) chạy max — không giới hạn. Tối ưu áp dụng cho **AI coder chính** (Claude Code, Gemini trên Antigravity IDE):

| Quy tắc | Lý do |
|---|---|
| **Grep → Read(offset+limit)**: không Read toàn file >150 dòng nếu chỉ cần 1 đoạn | File 900 dòng đọc 3-4 lần/session = phần lớn context lãng phí |
| **Không Read lại sau Edit/Write** | Tool confirm thành công = đủ |
| **Gom hết fix → 1 panel_review cuối** | 6-8 vòng review/session → 1 vòng nếu batch đúng |
| **ask_codebase tối đa 5 file** | 9 file → timeout 636s + tốn round-trip không ra kết quả |
| **Fix <20 dòng từ suggestion vòng trước → miễn panel_review** | Vòng lặp trivial fix không cần 3 reviewer |

`GEMINI.md` tại `%USERPROFILE%\.gemini\GEMINI.md` — Antigravity IDE tự đọc, áp dụng cùng quy trình harness + token efficiency cho Gemini.

---

### Kỹ thuật 19: merge_settings.py — Robust Encoding & Idempotency

* **Tệp mã nguồn:** [merge_settings.py](merge_settings.py)

#### Vấn đề ban đầu
`merge_settings.py` (installer helper) dùng `errors='replace'` khi đọc CLAUDE.md → file non-UTF-8 bị decode sai rồi ghi lại, mất dữ liệu im lặng. Ngoài ra idempotency check dùng chuỗi `"agent-harness"` quá rộng → false positive skip.

#### Các cải tiến đã làm

**1. BOM-aware encoding detection — áp dụng cho `_read_md`, `_read_settings`, `merge_gemini_md`**

```python
def _read_md(md_path: Path) -> tuple[str, str] | None:
    try:
        raw = md_path.read_bytes()
    except OSError as e:
        print(f"[error] Khong doc duoc {md_path} ({e}).")
        return None
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):   # UTF-16 LE/BE BOM
        return raw.decode("utf-16"), "utf-16"
    if raw[:3] == b"\xef\xbb\xbf":               # UTF-8 BOM
        return raw[3:].decode("utf-8"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"      # plain UTF-8
    except UnicodeDecodeError:
        print(f"[error] {md_path}: encoding khong phai UTF-8/UTF-16.")
        return None
```

Trả về `write_encoding` cùng content → `write_text(encoding=enc)` giữ nguyên BOM/encoding gốc sau merge (round-trip safe).

**2. Specific idempotency markers — tránh false positive**

```python
CLAUDE_MARKER = "<!-- agent-harness-managed -->"   # thay vì check "agent-harness" substring
GEMINI_MARKER = "<!-- agent-harness -->"
```

**3. Legacy hook idempotency — nhận diện hook cũ không có `id`**

```python
_cmd_norm = " ".join(HOOK_REMINDER_CMD.split())   # normalize whitespace

def _is_existing_hook(e: dict) -> bool:
    if e.get("id") == HOOK_ID:
        return True
    sub = e.get("hooks", [])
    return (e.get("matcher") == "Edit|Write|NotebookEdit"
            and isinstance(sub, list)
            and any(" ".join((h.get("command") or "").split()) == _cmd_norm for h in sub))
```

**4. Defensive type validation trước khi setdefault**

```python
hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    print(f"[error] 'hooks' phai la object, hien la {type(hooks).__name__}.")
    return 1
post = hooks.setdefault("PostToolUse", [])
if not isinstance(post, list):
    print(f"[error] 'hooks.PostToolUse' phai la array.")
    return 1
```

**5. Atomic write với OS-policy fallback**

```python
try:
    fd, tmp_path = tempfile.mkstemp(dir=st_path.parent, suffix=".tmp")
    # ... ghi + os.replace (atomic)
except OSError:
    # fallback: backup .bak + ghi thẳng
    bak = st_path.with_suffix(".json.bak")
    shutil.copy2(st_path, bak)
    st_path.write_text(content, encoding="utf-8")
```

**6. OSError catch toàn diện** — `_read_md`, `_read_settings`, `merge_claude_md`, `merge_gemini_md` đều bọc `read_bytes()` và `write_text()` trong `try/except OSError` → không crash, báo lỗi rõ ràng, script tiếp tục xử lý phần còn lại.

#### Nguyên tắc rút ra

| Vấn đề | Pattern |
|---|---|
| File encoding không đồng nhất | Detect by BOM bytes, không assume UTF-8 |
| Idempotency check | Dùng marker HTML comment duy nhất, không check substring rộng |
| Atomic write | `mkstemp` trong cùng dir → `os.replace`; fallback nếu policy chặn mkstemp |
| Defensive validation | Validate type trước khi dùng, không để AttributeError crash giữa chừng |

---

### Kỹ thuật 20: MCP Tool Description — Cập Nhật Khi Thay Đổi Output Schema

* **Tệp mã nguồn:** [mcp_server.py](mcp_server.py) — `list_tools()` và `AGENT_INFO`.

#### Vấn đề
Khi panel_review được nâng cấp (thêm `triage`, `warnings[]`, adversarial tester), description trong `mcp_server.py` vẫn là bản cũ → AI coder không biết output có field mới, không tận dụng được `triage` để auto-apply fix.

#### Nguyên tắc: description = contract giữa MCP server và AI coder

Mỗi khi thay đổi:
- **Output schema** (thêm/bớt field) → cập nhật `description` trong `types.Tool(...)`
- **Agent role** (đổi behavior) → cập nhật `AGENT_INFO[role]["specialty"]`
- **Workflow mới** (auto-trigger condition) → cập nhật CLAUDE.md + GEMINI.md + description

Ví dụ sau khi nâng cấp panel_review v2:

```python
types.Tool(
    name="panel_review",
    description=(
        "... Panel gồm: reviewer (code quality), security (OWASP), "
        "tester (adversarial devil's advocate — tìm race condition, "
        "hidden assumption, edge case mà 2 kia bỏ sót). "
        "Output mỗi finding có field `triage`: `auto_fix` = fix mechanical, "
        "`ask_user` = cần developer quyết. `warnings[]` có thể chứa "
        "cảnh báo anti-consensus nếu panel đồng thuận bất thường."
    ),
)
```

```python
AGENT_INFO = [
    # ...
    {"role": "tester", "tool": "panel_review",
     "specialty": "Adversarial devil's advocate — race condition, hidden assumption, "
                  "edge case mà quality/security bỏ sót"},
]
```

#### Checklist khi thêm tính năng mới vào harness

- [ ] Cập nhật `description` trong `mcp_server.py → list_tools()`
- [ ] Cập nhật `AGENT_INFO` nếu role thay đổi behavior
- [ ] Cập nhật `CLAUDE.md` (user-level) — quy trình gọi
- [ ] Cập nhật `GEMINI.md` — đồng bộ với Claude
- [ ] Cập nhật `TECHNIQUES_GUIDE.md` — kỹ thuật mới + nguyên tắc rút ra
- [ ] Cập nhật `CLAUDE_MD_SECTION` + `GEMINI_MD_SECTION` trong `merge_settings.py` nếu quy trình thay đổi (để installer đồng bộ cho user mới)

---

### Kỹ thuật 21: 12 Quality & Analysis Tools — LLM-Based Static Analysis

* **Tệp mã nguồn:** [tools/quality.py](tools/quality.py) — 12 async functions mới.

#### Tổng quan

12 tools phân tích tĩnh dựa trên LLM, không cần external tool (không phụ thuộc `mutmut`, `semgrep`, v.v.). Tất cả dùng pattern `_llm_analyze(prompt, ctx, AgentRole.X)` + `_parse_json_result()`.

| Tool | Trigger | AgentRole |
|---|---|---|
| `migration_validator` | migrations/, alembic/versions/ | ANALYZER |
| `sql_query_analyzer` | ORM query mới, endpoint DB access | ANALYZER |
| `openapi_spec_sync` | Route handler mới, Pydantic model | ANALYZER |
| `breaking_change_detector` | Trước PR vào main | ANALYZER |
| `flaky_test_detector` | CI fail không rõ lý do | TESTER |
| `duplicate_code_scanner` | Module mới lớn, refactor lớn | ANALYZER |
| `container_linter` | Dockerfile, docker-compose | SECURITY |
| `dependency_graph_visualizer` | ImportError, circular import | ANALYZER |
| `ci_pipeline_validator` | .github/workflows/, .gitlab-ci.yml | SECURITY |
| `mutation_tester` | Coverage cao nhưng nghi thiếu assertion | TESTER |
| `data_flow_taint_analyzer` | Endpoint mới nhận user input | SECURITY |
| `performance_regression_detector` | Refactor function critical | ANALYZER |

#### Pattern cốt lõi

```python
async def tool_name(param: Optional[...] = None) -> dict:
    # 1. Thu thập files liên quan
    files = _collect_files([".py"])  # hoặc filter theo tên/nội dung

    # 2. Build context (tối đa MAX_TOTAL_BYTES)
    ctx = "\n\n".join(f"=== {rel} ===\n{content}" for rel, content in ...)[:MAX_TOTAL_BYTES]

    # 3. LLM phân tích
    result = await _llm_analyze(prompt, ctx, AgentRole.ANALYZER)

    # 4. Parse JSON an toàn — KHÔNG dùng greedy regex fallback
    data = _parse_json_result(result, {"findings": [], "summary": ""})
    data.setdefault("warnings", warnings)
    return data
```

#### `_parse_json_result` — safe JSON parser

Thay thế pattern cũ `json.loads(m.group()) if m else ...` dễ crash khi output LLM có nhiều `{}`:

```python
def _parse_json_result(text: str, fallback: dict) -> dict:
    # 1. Full parse
    # 2. Fenced ```json block
    # 3. Balanced-brace scan — tìm object JSON hợp lệ đầu tiên
    # → fallback với warning "parse_failed" nếu tất cả fail
```

**Lý do**: greedy `re.search(r"\{.*\}", text, re.DOTALL)` bắt từ `{` đầu tiên đến `}` cuối cùng — crash khi LLM có text prefix hoặc trailing `{}`.

#### `mutation_tester` — file safety pattern

Khi rename file để inject mutation, luôn khởi tạo `tmp_path = None` trước `try` và restore file trong `finally` độc lập với cleanup temp:

```python
tmp_path = None
try:
    with NamedTemporaryFile(..., delete=False) as tmp:
        tmp_path = tmp.name  # chỉ assign SAU khi file tạo thành công
        ...
    os.rename(src_file, backup)
    os.rename(tmp_path, src_file)
    tmp_path = None  # consumed by rename
    ...
finally:
    # Restore original TRƯỚC (độc lập với tmp)
    if os.path.isfile(backup):
        ...os.rename(backup, src_file)
    # Cleanup tmp CHỈ khi chưa consumed
    if tmp_path and os.path.isfile(tmp_path):
        os.remove(tmp_path)
```

**Lý do**: `UnboundLocalError` nếu exception xảy ra trước khi `tmp_path` được assign — che mất lỗi gốc và có thể để file ở trạng thái corrupt.

#### `breaking_change_detector` — git ref validation

Không dùng regex whitelist để validate git ref (dễ reject ref hợp lệ như `HEAD~1`). Dùng `git rev-parse --verify` qua argv list:

```python
rc_v, _, _ = _run_cmd_safe(["git", "rev-parse", "--verify", base_ref])
if rc_v != 0:
    return {"error": "invalid_base_ref", ...}  # return early, KHÔNG silent fallback
```

**Lý do**: silent fallback sang main/master khi user truyền base_ref invalid dẫn đến diff sai ngữ cảnh mà không có warning rõ ràng.

#### `flaky_test_detector` — pytest output parsing

Dùng fnmatch thay `.endswith` để collect test files, và regex bắt full nodeid kể cả `[param]`:

```python
# Thu thập file
test_files = [f for f in _collect_files([".py"])
              if fnmatch.fnmatch(os.path.basename(f), "test_*.py")
              or fnmatch.fnmatch(os.path.basename(f), "*_test.py")]

# Parse FAILED lines
m = re.match(r"^FAILED\s+(.+?)(?:\s+-\s+.*)?$", line.strip(), re.IGNORECASE)
```

**Lý do**: `.endswith("test_*.py")` không bao giờ match (wildcard không work với endswith). Regex `[\w./:-]+` cắt mất `[param]` trong parametrized tests.

#### Auto-trigger tiers (Tier 2 & 3)

Các tool được khai báo trong CLAUDE.md, GEMINI.md, và `merge_settings.py` (`CLAUDE_MD_SECTION`/`GEMINI_MD_SECTION`) để AI tự quyết khi nào gọi. Không cần user nhắc thủ công.

---

### Kỹ thuật 22: Phân Vai 12 Model — 58 MCP Tools, Auto-Pilot + Auto-Watch

* **Tệp mã nguồn:** [agents.py](agents.py) — `AgentRole`, `ROLE_TIMEOUTS`; [mcp_server.py](mcp_server.py) — `list_tools()`, `AGENT_INFO`; [tools/auto.py](tools/auto.py) — `auto_trigger`; [auto_watch.py](auto_watch.py) — watcher tự chạy.

#### Tổng quan phân vai

Hệ thống có **58 MCP tools**: 7 tool gọi LLM, 50 static analyzers, và `auto_trigger` để tự fan-out các tool phù hợp. Mặc định Auto-Pilot bật `HARNESS_STATIC_LLM=1`, nên các static scanner vẫn chạy phân tích tĩnh trước rồi gọi Azure để enrich/triage khi tool hỗ trợ.

| Tool (gọi LLM) | AgentRole | Model Azure | Mục đích |
|---|---|---|---|
| `ask_codebase` | MANAGER | `gpt-5.4-pro-3` | Q&A xuyên file, 1M context window |
| `panel_review` (merge/dedupe) | SYNTHESIZER | `gpt-5.4-pro-2` | Gộp findings từ 3 reviewer |
| `consult` | ANALYZER | `grok-4-20-reasoning` | Kiến trúc + trade-offs, deep reasoning |
| `alt_implementation` (approach A) | CODE_A | `Kimi-K2.6` | Implementation tối ưu |
| `alt_implementation` (approach B) | CODE_B | `gpt-5.4` | Implementation khác biệt để so sánh |
| `panel_review` (reviewer/tester/security — 3 song song) | REVIEWER + TESTER + SECURITY | `gpt-5.3-codex` / `gpt-5.3-codex-2` / `gpt-5.3-codex-3` | Code quality + adversarial + OWASP |
| `suggest_fix`, `security_autofix` | DEBUGGER | `gpt-5.4-2` | Root cause + unified diff patch |
| `quick_task` | WORKER | `gpt-5.4-mini` | Boilerplate, fixtures, docstring |

> **Ghi chú `panel_review`:** Mỗi lần gọi `panel_review` tốn **4 LLM calls** — 3 parallel (REVIEWER + TESTER + SECURITY) + 1 SYNTHESIZER (nếu findings > 8). Nếu findings ≤ 8, SYNTHESIZER bị skip → chỉ 3 LLM calls, dedup bằng Python local.

#### Auto-Pilot và Auto-Watch

`auto_trigger` là Auto-Pilot chạy trong MCP: khi client/agent gọi tool này sau một batch edit, nó nhìn danh sách file đổi và tự gọi scanner/reviewer phù hợp theo mode:

```text
HARNESS_AUTO_PILOT=1
HARNESS_AUTO_MODE=max
HARNESS_STATIC_LLM=1
```

`auto_watch.py` là daemon polling riêng để đạt mức tự động cao hơn: nó không chờ model chính gọi MCP tool, mà tự thấy file trong workspace đổi rồi gọi thẳng `tools.auto.auto_trigger(mode="max")`.

```powershell
python auto_watch.py
```

Config nhanh:

```text
HARNESS_AUTO_WATCH=1
HARNESS_AUTO_WATCH_INTERVAL=3
HARNESS_AUTO_WATCH_DEBOUNCE=2
```

Giới hạn cần nhớ: MCP server không được tự ý chạy ngầm sau mọi edit nếu MCP client không dispatch tool. Muốn tự động tuyệt đối hơn thì phải giữ một process watcher đang chạy. Watcher bỏ qua `.git`, cache, venv, node_modules; gom thay đổi bằng debounce; dùng lock atomic `.harness_auto_watch.lock` để chống chạy chồng; log vào `.harness_auto_watch.log` với redaction và rotation.

#### 50 tools static analysis (không tốn token LLM)

Các tool sau chạy pure Python/subprocess, không gọi Azure AI Foundry:

| Nhóm | Tools |
|---|---|
| File/code analysis | `secret_scanner`, `complexity_analyzer`, `dead_code_scanner`, `duplicate_code_scanner`, `dependency_graph_visualizer` |
| Git/environment | `git_archaeologist`, `env_parity_checker`, `changelog_generator`, `breaking_change_detector` |
| Test/quality | `coverage_analyzer`, `flaky_test_detector`, `mutation_tester` |
| Security/infra | `config_security_audit`, `container_linter`, `ci_pipeline_validator`, `sbom_generator`, `license_scanner` |
| DB/API | `migration_validator`, `sql_query_analyzer`, `openapi_spec_sync`, `api_contract_tester`, `data_flow_taint_analyzer` |
| Monitoring/perf | `profiler`, `benchmarker`, `load_tester`, `chaos_tester`, `performance_regression_detector` |
| Docs/misc | `doc_sync`, `i18n_auditor`, `a11y_auditor`, `pr_generator`, `polyglot_reviewer`, `feature_flag_auditor` |
| Index/wiki | `index_codebase`, `semantic_search`, `wiki_ingest`, `wiki_query`, `wiki_lint` |
| Dev | `run_in_sandbox`, `finops_stats`, `list_agents`, `schema_drift`, `devops_pipeline` |

#### Nguyên tắc rút ra

| Vấn đề | Pattern |
|---|---|
| Không biết tool nào tốn token | Tools trong bảng AgentRole → LLM; còn lại → static analysis Python |
| Tối ưu chi phí | Ưu tiên static tools trước; chỉ gọi LLM khi cần reasoning hoặc synthesis |
| panel_review tốn 3-4 LLM calls | Gom hết fix vào 1 batch → 1 panel_review cuối; fix <20 dòng từ vòng trước → miễn review |
| MCP description = contract | Mỗi khi output schema thay đổi → cập nhật description để AI coder biết field mới |

---

### Kỹ thuật 23: 2026-07-07 Harness Hardening — Auto Wiki, Fast Static Tools, Multi-Agent Config

* **Tệp mã nguồn:** [mcp_server.py](mcp_server.py), [llmwiki_tool.py](llmwiki_tool.py), [tools/core.py](tools/core.py), [tools/devops.py](tools/devops.py), [tools/analysis.py](tools/analysis.py), [merge_settings.py](merge_settings.py), [smoke_test.py](smoke_test.py).

#### Auto wiki/concepts không cần gọi tay

MCP server giờ tự kiểm `llmwiki/raw/` local và `~/.claude/llmwiki/raw/` global khi bất kỳ tool nào được gọi. Nếu có raw `.md/.txt` mới, server tự kick `wiki_ingest` chạy nền, không block tool chính.

`wiki_ingest` đã hỗ trợ recursive raw folders, nên các pack kiểu Strix có thể nằm trong `llmwiki/raw/strix/...` thay vì phải copy toàn bộ file lên root `raw/`.

`ask_codebase`, `panel_review`, `consult`, `suggest_fix`, và các flow dùng `_assemble_context` đều nhận selective wiki context. `tools/core.py` cache wiki pages theo `(mtime, size)` để không đọc lại hàng trăm concept/entity mỗi lần assemble context.

`ask_codebase` vẫn ưu tiên MANAGER model trên Azure (`gpt-5.4-pro-3`), và mặc định được thử spare model nếu primary timeout. Auto-discovery chỉ lấy top 10 file để tránh context loãng. Nếu model chain error/empty, hoặc Manager trả câu generic thiếu citation `file:line`, fallback local tự rank context đã load, trả `Kết luận khả dĩ`, evidence snippet có `file:line`, và gợi ý file cần đọc tiếp; không còn trả câu xin lỗi nghèo thông tin kiểu "fallback extractive" đơn thuần. Tool cũng unwrap được JSON wrapper như `{"answer": "..."}` nếu Manager lỡ trả JSON.

Tuning nhanh:

```text
HARNESS_ASK_CODEBASE_TIMEOUT=45
HARNESS_ASK_CODEBASE_USE_SPARES=1
HARNESS_ASK_CODEBASE_TIMEOUT_RETRIES=0
HARNESS_ASK_CODEBASE_CONTEXT_BYTES=250000
```

#### Static tools phải nhanh mặc định

Các static analyzers không nên treo vì model timeout. Những phần LLM phụ trợ đã chuyển sang opt-in:

```text
HARNESS_STATIC_LLM=1
```

Mặc định:

- `devops_pipeline` chạy ruff/black/mypy và trả trong ~0.2s trên repo hiện tại, không gọi synthesizer.
- `dead_code_scanner`, `secret_scanner`, `complexity_analyzer`, `dependency_upgrader(dry_run=True)` trả static result trước; LLM triage/risk/refactor chỉ chạy khi bật env trên.
- Subprocess text output dùng UTF-8 + `errors="replace"` để tránh crash CP932/Windows console.
- `run_in_sandbox` dùng temp dir riêng cho từng invocation; Swarm reproducer dùng filename UUID trong sandbox, không ghi `test_swarm_reproducer.py` vào workspace thật.
- FastAPI backend reject dot-segment/encoded slash dưới `/api` và bảo vệ endpoint nhạy cảm bằng `HARNESS_API_KEY` khi env này được set.

#### Multi-agent config tự đồng bộ

`merge_settings.py` giờ replace managed sections thay vì skip khi thấy marker cũ, và tự ghi MCP path hiện tại cho:

- Claude: `~/.claude/claude_mcp_config.json`
- Codex: `~/.codex/config.toml`
- Gemini/Antigravity: `~/.gemini/config/mcp_config.json`, `~/.gemini/antigravity-ide/mcp_config.json`

Chạy installer hoặc `python merge_settings.py` là đủ; user không cần tự thêm command MCP riêng cho từng agent.

MCP server expose resources/templates no-op:

```python
@app.list_resources() -> []
@app.list_resource_templates() -> []
```

Lý do: một số Codex client mới query `resources/list` và `resources/templates/list` trong handshake dù harness chỉ dùng tools. Trả list rỗng đúng protocol sẽ tránh lỗi `-32601 Method not found` làm app-server crash.

`visual_reviewer` cần cả package Python `playwright` lẫn browser binary Chromium. Installer chạy thêm:

```powershell
python -m playwright install chromium
```

Nếu thiếu, tool vẫn fallback static analysis nhưng warning sẽ chỉ rõ lệnh cần chạy.

#### Smoke test hiện tại

`smoke_test.py` kiểm 58 MCP tools, resources/templates handshake, sandbox Windows, benchmark subprocess, Unicode-safe fix/debug output, Auto-Pilot trigger, Auto-Watch detect/ignore/lock/log-redaction, ask_codebase JSON unwrap + fallback citation, devops/security scanners, swarm state machine, và các tool quality. Scratch file chạy trong `.harness_smoke/` và tự cleanup; `doc_sync` chạy trên workspace tạm nên không append README thật.

Kết quả mong muốn:

```text
ruff check . ...        -> All checks passed
devops_pipeline         -> score 100, findings_count 0
config_security_audit   -> secrets_found [], findings_count 0
python smoke_test.py    -> Tất cả smoke tests pass
```
