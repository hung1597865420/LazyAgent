# Agent Harness — 10-Agent Coding Support Team

Hệ thống 10 AI agent chạy trên Azure AI Foundry, tích hợp vào Claude Code để hỗ trợ coding: review code tự động, tư vấn thiết kế, debug, và sinh phương án thay thế.

---

## Harness hoạt động như thế nào

### Kiến trúc tổng quan

```
Claude Code (bạn đang dùng)
    │
    ├── MCP Server (agent-harness) ←── tự động kết nối khi mở Claude Code
    │       │
    │       ├── panel_review  ──► [Reviewer + Tester + Security] chạy song song
    │       │                            └── Synthesizer tổng hợp findings
    │       │
    │       ├── consult       ──► Analyzer (grok reasoning) tư vấn thiết kế
    │       ├── suggest_fix   ──► Debugger phân tích lỗi + đề xuất patch
    │       ├── ask_codebase  ──► Manager (1M context) trả lời câu hỏi về code
    │       ├── alt_implementation ──► Code A + Code B sinh 2 approach song song
    │       └── quick_task    ──► Worker xử lý việc vặt nhanh
    │
    └── Web Dashboard (tùy chọn) ── python server.py → http://localhost:8000
```

### 10 Agent và vai trò

| Agent | Model | Layer | Vai trò |
|-------|-------|-------|---------|
| **Manager** | gpt-5.4-pro | Orchestration | Trả lời Q&A về codebase lớn (1M token context) |
| **Synthesizer** | gpt-5.4-pro-2 | Orchestration | Merge + dedupe findings từ review panel |
| **Analyzer** | grok-4-20-reasoning | Analysis | Tư vấn design, trade-offs, approach trước khi code |
| **Code A** | Kimi-K2.6 | Code | Sinh implementation approach 1 (80.2% SWE-bench) |
| **Code B** | gpt-5.4 | Code | Sinh implementation approach 2 (song song với Code A) |
| **Reviewer** | gpt-5.3-codex | Review | Bugs, code quality, anti-patterns |
| **Tester** | gpt-5.3-codex-2 | Review | Test gaps, edge cases, coverage |
| **Security** | gpt-5.3-codex-3 | Review | OWASP, vulns, auth flaws, injection |
| **Debugger** | gpt-5.4-2 | Fix | Root cause analysis + patch cụ thể |
| **Worker** | gpt-5.4-mini | Worker | Format, docstring, boilerplate, rename |

### Quy trình tự động khi code

Claude Code tự gọi harness theo quy tắc trong `~/.claude/CLAUDE.md` — bạn không cần làm gì thêm:

```
Bạn ra lệnh code
    │
    ├── Phần phức tạp? ──► consult(Analyzer) tư vấn trước
    │
    ├── Claude code xong
    │
    └── Trước khi báo hoàn thành ──► panel_review(Reviewer + Tester + Security)
                                          │
                                          ├── Có findings critical/high?
                                          │       └── Claude fix rồi mới báo xong
                                          │
                                          └── Approve → báo hoàn thành
```

### 8 MCP Tool có sẵn

| Tool | Khi nào dùng |
|------|-------------|
| `panel_review` | Sau khi code xong — 3 model review song song, trả findings có file/line/severity/fix |
| `consult` | Trước khi implement phần khó — hỏi design approach, trade-offs |
| `suggest_fix` | Debug bí sau 1-2 lần thử — phân tích error + đề xuất patch |
| `ask_codebase` | Hỏi về flow xuyên nhiều file trong codebase lớn |
| `alt_implementation` | So sánh 2 cách implement cho module độc lập |
| `quick_task` | Việc vặt: fixtures, mock data, boilerplate, docstring |
| `run_single_agent` | Gọi trực tiếp 1 agent cụ thể |
| `list_agents` | Xem thông tin 10 agent, model, specialty |

---

## Cài đặt

### Yêu cầu

- **Python 3.10+** — tải tại https://python.org
- **Claude Code** — tải tại https://claude.com/claude-code

### Cài đặt tự động (Windows)

```powershell
# 1. Giải nén folder, mở PowerShell trong folder đó
# 2. Chạy installer:
powershell -ExecutionPolicy Bypass -File install.ps1

# 3. Restart Claude Code, gõ /mcp kiểm tra:
#    agent-harness ✓ connected  ← là xong
```

Installer tự động thực hiện 4 bước:
1. `pip install` các Python dependencies
2. Đăng ký MCP server với Claude Code (scope user — có hiệu lực ở mọi project)
3. Tạo/merge `~/.claude/CLAUDE.md` (quy tắc tự động dùng harness)
4. Thêm hook nhắc `panel_review` vào `~/.claude/settings.json`
5. Chạy smoke test kiểm tra cấu hình

> **Idempotent:** Chạy lại installer nhiều lần không tạo trùng lặp.

### Cài đặt thủ công (macOS / Linux)

```bash
# 1. Cài dependencies
pip install -r requirements.txt

# 2. Đăng ký MCP
claude mcp add --scope user agent-harness -- python "/đường/dẫn/tới/mcp_server.py"

# 3. Merge CLAUDE.md và hook
python merge_settings.py

# 4. Restart Claude Code, kiểm tra /mcp
```

### Cấu hình (.env)

Tạo file `.env` cục bộ từ file mẫu `.env.example` và điền thông tin kết nối Azure OpenAI của bạn (chú ý KHÔNG commit file `.env` chứa API key lên git). Nếu cần đổi deployment name:

```env
# Azure AI Foundry endpoint
AZURE_OPENAI_ENDPOINT=https://your-resource.services.ai.azure.com/models
AZURE_OPENAI_API_KEY=your-key

# Đổi nếu deployment name trên Azure khác tên mặc định
MODEL_MANAGER=gpt-5.4-pro
MODEL_SYNTHESIZER=gpt-5.4-pro-2
MODEL_ANALYZER=grok-4-20-reasoning
MODEL_CODE_A=Kimi-K2.6
MODEL_CODE_B=gpt-5.4
MODEL_REVIEWER=gpt-5.3-codex
MODEL_TESTER=gpt-5.3-codex-2
MODEL_SECURITY=gpt-5.3-codex-3
MODEL_DEBUGGER=gpt-5.4-2
MODEL_WORKER=gpt-5.4-mini
```

---

## Sử dụng

### Chế độ tự động (mặc định)

Cứ ra lệnh code bình thường — harness tự chạy theo quy tắc trong `~/.claude/CLAUDE.md`:

```
"Viết API upload file cho dự án này"
"Fix bug lỗi encoding trong FormPage.tsx"
"Refactor cái module auth theo pattern Repository"
```

Claude sẽ tự `consult` trước phần phức tạp và `panel_review` trước khi báo xong. Bạn không cần nhắc gì thêm. Muốn bỏ qua review cho task nào thì nói: *"khỏi review"* hoặc *"nhanh thôi"*.

### Gọi tool thủ công

Trong Claude Code, bạn cũng có thể yêu cầu trực tiếp:

```
"dùng consult hỏi xem nên dùng Redis hay in-memory cache cho use case này"
"panel_review file src/api/upload.ts với focus vào security"
"suggest_fix cho cái lỗi này: [paste stack trace]"
"list_agents xem team có những con nào"
```

### Web Dashboard (tùy chọn)

Dùng để chạy thử pipeline thủ công và xem agent status:

```powershell
python server.py
# → mở http://localhost:8000
```

> Dashboard chỉ hiển thị các run được submit qua web UI, không hiển thị MCP runs từ Claude Code.

---

## Lưu ý

**Rate limit:** Cả team dùng chung 1 Azure resource. `panel_review` bắn 3 model song song — nếu team đông (5+ người) dùng đồng thời có thể bị throttle. Xin thêm quota tại Azure Portal nếu cần.

**Workspace:** `WORKSPACE_ROOT` trong `.env` để trống → harness tự bám theo project Claude Code đang mở (`CLAUDE_PROJECT_DIR`). Không cần đổi khi chuyển dự án.

**Khi harness lỗi:** Claude Code báo ngắn gọn và tiếp tục task bình thường, không bị block. Gõ `/mcp` để kiểm tra trạng thái kết nối.
