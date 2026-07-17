# Agent Harness — Support Toolbox cho Claude Code

> Cập nhật 2026-06-12: refactor từ "pipeline code thay AI agent" thành
> "toolbox 10 model hỗ trợ Claude Code". Bugs cũ trong handoff trước đã fix hết.

## Kiến trúc

Claude Code là coder chính. Harness cung cấp 6 MCP tool hỗ trợ, dùng đủ 10 deployment:

| Tool | Model | Dùng khi nào |
|------|-------|--------------|
| `panel_review` | reviewer + security + tester (parallel) → synthesizer merge | Sau khi viết/sửa code — 3 góc nhìn độc lập, trả findings JSON có file/line/severity/fix |
| `consult` | analyzer (sonnet reasoning) | Trước khi implement phần khó — approach, trade-offs, edge cases |
| `alt_implementation` | code_a (Gemini High) + code_b (ag/claude-sonnet-4-6) parallel | Cần 2 phương án để so sánh, hợp với module độc lập |
| `suggest_fix` | debugger | Đưa code + error → root cause + patch dạng diff |
| `ask_codebase` | manager (1M context, cap 2.5MB) | Hỏi đáp flow xuyên nhiều file, trích dẫn file:line |
| `quick_task` | worker (mini) | Boilerplate, fixtures, mock data, docs |

Kèm `run_single_agent` (escape hatch) và `list_agents`.

## File structure

| File | Mô tả |
|------|-------|
| `config.py` | ModelConfig 10 role, SPARE_MODELS, WORKSPACE_ROOT, limits, 9Router client |
| `agents.py` | `Agent` class + `_chat_completion`: adaptive params, retry 429, fallback spare |
| `support_tools.py` | Logic 6 support tool, đọc file từ workspace (chặn path ngoài root) |
| `mcp_server.py` | MCP server đăng ký 8 tool |
| `harness.py` | Pipeline 10-agent cũ (chỉ còn web UI dùng), prompt riêng `PIPELINE_*` |
| `server.py` | FastAPI + SSE cho web UI (`index.html`) — secondary, không phải flow chính |
| `smoke_test.py` | 20 test offline, không gọi 9Router: `python smoke_test.py` |

## Điểm kỹ thuật đáng nhớ

- **Hai loại API trên cùng resource 9Router** (verify live 13/13 ngày 2026-06-12):
  - Chat Completions: `http://localhost:20128/v1` — Gemini High, sonnet,
    ag/claude-sonnet-4-6 thường, api-version `2024-05-01-preview`
  - Responses API: `http://localhost:20128/v1` — dòng **Sonnet/Gemini
    CHỈ chạy API này** (chat completions trả "operation is unsupported"), api-version
    `2025-04-01-preview`. Cùng API key.
  - `agents.py::_quirks_for` pre-seed theo tên model (codex/-pro → responses), đoán sai
    thì flip adaptive 1 lần từ error.
- **Adaptive API params** (`agents.py::_chat_completion`): không hardcode model nào là
  reasoning. Gặp `BadRequestError` về `max_tokens`/`max_completion_tokens`/`temperature`/
  `response_format` thì flip quirk per-model (cache trong `_MODEL_QUIRKS`) và retry ngay.
- **Rate limit**: 429 → exponential backoff tối đa `MAX_RETRIES` lần → chuyển sang
  `SPARE_MODELS` theo thứ tự trong `.env`.
- **Workspace access**: tools nhận path tương đối từ `WORKSPACE_ROOT` (.env), tự đọc file,
  đánh số dòng để findings trỏ đúng line. Path ngoài root bị chặn.
- **JSON output**: panel agents bị ép `response_format=json_object`; parse có fallback
  (markdown fence, brace matching). Synthesizer merge fail → trả raw findings đã sort.
- Prompt mặc định của Manager/Synthesizer trong `agents.py` giờ phục vụ toolbox;
  pipeline cũ dùng `PIPELINE_MANAGER_PROMPT`/`PIPELINE_SYNTHESIZER_PROMPT` trong `harness.py`.

## Setup

```bash
pip install -r requirements.txt        # fastapi>=0.136 (starlette 1.x cần bản mới)
# Điền .env: ROUTER_BASE_URL + ROUTER_API_KEY (đang là placeholder!)
# Đối chiếu 10 deployment name trong .env với 9Router Proxy
# WORKSPACE_ROOT trỏ vào repo đang làm việc

python smoke_test.py                   # verify offline, phải 20/20 pass

# Đăng ký MCP với Claude Code — scope user = available trong MỌI project:
claude mcp add --scope user agent-harness -- python "C:/path/to/harness/mcp_server.py"
# (mặc định không có --scope là local: chỉ project hiện tại)
# WORKSPACE_ROOT để trống → harness tự bám theo project đang mở (CLAUDE_PROJECT_DIR)

## Cài cho máy khác

1. Copy folder này sang máy đích, không copy `.env` thật; tạo `.env` mới từ `.env.example` hoặc inject bằng secret manager.
2. Máy đích cần có sẵn: Python 3.10+ và Claude Code
3. Mở PowerShell trong folder, chạy: `powershell -ExecutionPolicy Bypass -File install.ps1`
4. Restart Claude Code → gõ `/mcp` kiểm tra `agent-harness ✓ connected`

`install.ps1` tự làm 4 bước: pip install → đăng ký MCP scope user → merge CLAUDE.md
+ hook vào `~/.claude/` (qua `merge_settings.py`, idempotent — chạy lại không tạo trùng)
→ smoke test. Lưu ý: mọi máy dùng chung 9Router resource nên chia sẻ chung rate limit
(100k tokens/phút, 100 requests/phút mỗi deployment).

# Web UI (tùy chọn):
python server.py   # → http://localhost:8000
```

## Còn cần làm

- [x] Verify credentials/deployments trên máy chủ sở hữu secret. Không chia sẻ log, screenshot, endpoint, username, local path hoặc trạng thái key ra ngoài.
- [ ] Live test 6 tool MCP end-to-end (mới ping từng model, chưa test full tool flow)
- [ ] Set `WORKSPACE_ROOT` trong `.env` trỏ vào repo làm việc thật
- [ ] Rotate API key nếu từng chia sẻ qua chat, screenshot, log hoặc máy không tin cậy
- [ ] Nice to have: lưu run history web UI ra file JSON; export findings ra `.md`
